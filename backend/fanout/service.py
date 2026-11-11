"""One WorkItem, one aggregate approval, independent at-least-once deliveries.
State is serialized by the engine lock and checkpointed by DurableRequests.
"""

import copy, hashlib, hmac, json, secrets, time, uuid, os, re
from pathlib import Path
from functools import wraps
from auth import Principal
from contract_wire import actor_uuid
from registry import RegistryService, ResourceRec
from taskengine import TaskEngineError, TaskAttemptRec, _now_iso

RECIPES = json.loads(Path(__file__).with_name("recipes.json").read_text())


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def fail(code, status=409):
    raise TaskEngineError(code, code, status)


def synchronized(fn):
    @wraps(fn)
    def run(self, *args, **kwargs):
        with self.engine._lock:
            return fn(self, *args, **kwargs)

    return run


class FanoutService:
    def __init__(self, engine, store, approvals, sync, clock=time.time):
        self.engine, self.store, self.approvals, self.sync, self.clock = (
            engine,
            store,
            approvals,
            sync,
            clock,
        )
        self.plans = {}
        self.deliveries = {}
        self.idempotency = {}
        self.nonces = {}
        self.revision = 0
        self._dirty = set()
        self.streams = {}
        allowed = {
            "ai",
            "drive",
            "notion",
            "reminders",
            "compute",
            "github",
            "implementation",
            "wechat",
            "knowledge",
        }
        for recipe in RECIPES.values():
            seen = set()
            for step, target, risk, deps in recipe["steps"]:
                if (
                    step in seen
                    or target not in allowed
                    or risk not in {"LOW", "MEDIUM"}
                    or not set(deps) <= seen
                    or (
                        target in {"compute", "github", "implementation"}
                        and risk != "MEDIUM"
                    )
                ):
                    raise RuntimeError("Invalid recipe or risk downgrade")
                seen.add(step)

    def recipes(self):
        return {
            "items": [
                {
                    "id": k,
                    "name": v["name"],
                    "version": 1,
                    "steps": [
                        {"id": s, "target": t, "risk": r, "depends_on": d}
                        for s, t, r, d in v["steps"]
                    ],
                }
                for k, v in RECIPES.items()
            ]
        }

    def _event(self, p, action):
        self.revision += 1
        p["revision"] = self.revision
        self._dirty.update(p["delivery_ids"])
        self.engine.audit(
            p["owner_sub"],
            action,
            p["id"],
            f"work_item={p['work_item_id']} revision={p['revision']}",
            p["trace_id"],
        )
        self.sync.get_sync_state(owner_sub=p["owner_sub"])
        state = self.sync.sync_states[p["owner_sub"]]
        state.revision += 1
        state.cursor = f"sync-cursor-{state.revision}"
        state.updated_at = _now_iso()

    @synchronized
    def require(self, pid, principal):
        p = self.plans.get(pid)
        if not p:
            fail("not_found", 404)
        if not principal.may_access_kind("service") or not principal.may_access_node(
            None
        ):
            fail("fanout_forbidden", 403)
        if principal.role != "admin" and p["owner_sub"] != principal.sub:
            fail("fanout_forbidden", 403)
        return p

    def create(self, body, principal, key, work_item_id=None, run_grant=False):
        with self.engine._lock, self.store._target_lock:
            if not principal.may_access_kind(
                "service"
            ) or not principal.may_access_node(None):
                fail("fanout_forbidden", 403)
            rid = body["recipe_id"]
            recipe = RECIPES.get(rid)
            if not recipe:
                fail("unknown_recipe", 400)
            wanted = set(body["targets"])
            available = {s for s, _, _, _ in recipe["steps"]}
            if not wanted or not wanted <= available:
                fail("invalid_targets", 400)
            steps = {s: (t, r, deps) for s, t, r, deps in recipe["steps"]}
            for _ in range(len(steps)):
                wanted.update(d for s in tuple(wanted) for d in steps[s][2])
            if body["mode"] not in {"SIMULATE", "LIVE"}:
                fail("invalid_mode", 400)
            if body["origin"]["channel"] not in {
                "web",
                "android",
                "macos",
                "windows",
                "wechat",
                "rakazo",
                "github",
                "shortcuts",
                "colab",
                "manual",
            }:
                fail("invalid_origin", 400)
            # Never attach a frozen service or gateway as a destination, even via URL text.
            if any(
                x in json.dumps(body.get("parameters", {})).lower()
                for x in ["cherry", "8765", "rakazo://"]
            ):
                fail("frozen_destination", 403)
            fp = digest({"body": body, "work_item_id": work_item_id})
            idx = (principal.sub, key)
            old = self.idempotency.get(idx)
            if old:
                if old[0] != fp:
                    fail("idempotency_conflict")
                return self.view(old[1], principal), True
            if len(self.plans) >= 1000 or len(self.deliveries) + len(wanted) > 10000:
                fail("fanout_capacity", 503)
            params = body.get("parameters", {})
            if rid == "checkpoint" and body["mode"] == "LIVE":
                if not run_grant:
                    fail("run_scoped_webhook_required", 403)
                run = self.worker_hub.compute_runs.get(params.get("run_id"))
                if not run or run.source_kind != "live":
                    fail("live_compute_run_unavailable", 503)
                if (
                    not re.fullmatch(
                        r"[0-9a-f]{64}", params.get("checkpoint_sha256", "")
                    )
                    or not params.get("checkpoint_uri", "").startswith("https://")
                    or "step" not in params
                    or "byte_size" not in params
                ):
                    fail("checkpoint_metadata_required", 400)
                if any(c["step"] == params["step"] for c in run.checkpoints):
                    fail("checkpoint_step_conflict")
            pid = str(uuid.uuid4())
            trace = str(uuid.uuid4())
            if work_item_id:
                wi = self.engine.work_items.get(work_item_id)
                if not wi or (
                    principal.role != "admin" and wi.created_by != actor_uuid(principal)
                ):
                    fail("work_item_forbidden", 403)
            else:
                wi = self.engine.create_work_item(
                    title=body["title"],
                    kind="paper" if rid == "paper" else "task",
                    created_by=actor_uuid(principal),
                    instructions=body["input"],
                    source_system=body["origin"]["channel"],
                    trace_id=trace,
                )
            if "fanout-control-plane" not in self.store.resources:
                RegistryService(self.store).register(
                    ResourceRec(
                        "fanout-control-plane",
                        "service",
                        "mwcp",
                        "Fan-out control plane",
                        None,
                    )
                )
            gated = any(steps[s][1] == "MEDIUM" for s in wanted)
            root, _ = self.engine.create_task(
                principal_id=principal.sub,
                capability="fanout.orchestrate",
                capability_version=1,
                resource_id="fanout-control-plane",
                idempotency_key="fanout-root-" + pid,
                arguments={"plan_hash": fp},
                origin_channel=(
                    body["origin"]["channel"]
                    if body["origin"]["channel"]
                    in {"web", "android", "cli", "rakazo", "system", "other"}
                    else "other"
                ),
                origin_external_ref="v3-origin:" + body["origin"]["channel"],
                work_item_id=wi.id,
                requires_approval=gated,
                risk="MEDIUM" if gated else "LOW",
                dry_run=body["mode"] == "SIMULATE",
                trace_id=trace,
            )
            self.engine.admitted_generations[root.id] = self.store.resources[
                "fanout-control-plane"
            ].generation
            p = {
                "id": pid,
                "work_item_id": wi.id,
                "task_id": root.id,
                "owner_sub": principal.sub,
                "trace_id": trace,
                "recipe_id": rid,
                "recipe_version": 1,
                "title": body["title"],
                "input": body["input"],
                "parameters": copy.deepcopy(body.get("parameters", {})),
                "origin": copy.deepcopy(body["origin"]),
                "mode": body["mode"],
                "plan_hash": fp,
                "approval_id": None,
                "revision": 0,
                "created_at": _now_iso(),
                "delivery_ids": [],
            }
            if gated:
                p["approval_id"] = self.approvals.create_for_task(
                    root, risk="MEDIUM"
                ).id
            for step in steps:
                if step not in wanted:
                    continue
                target, risk, deps = steps[step]
                did = str(uuid.uuid4())
                child, _ = self.engine.create_task(
                    principal_id=principal.sub,
                    capability="fanout." + target,
                    capability_version=1,
                    resource_id="fanout-control-plane",
                    idempotency_key="fanout-child-" + did,
                    arguments={"plan_id": pid, "step_id": step, "plan_hash": fp},
                    origin_channel=(
                        body["origin"]["channel"]
                        if body["origin"]["channel"]
                        in {"web", "android", "cli", "rakazo", "system", "other"}
                        else "other"
                    ),
                    origin_external_ref="v3-origin:" + body["origin"]["channel"],
                    work_item_id=wi.id,
                    requires_approval=risk == "MEDIUM",
                    risk=risk,
                    dry_run=p["mode"] == "SIMULATE",
                    trace_id=trace,
                )
                d = {
                    "id": did,
                    "plan_id": pid,
                    "task_id": child.id,
                    "step_id": step,
                    "target": target,
                    "risk": risk,
                    "depends_on": deps,
                    "state": "WAITING_APPROVAL" if risk == "MEDIUM" else "QUEUED",
                    "attempts": 0,
                    "generation": 0,
                    "next_retry_at": 0.0,
                    "lease_expires_at": 0.0,
                    "worker_id": None,
                    "claim_hash": None,
                    "receipt": None,
                    "result_hash": None,
                    "last_error": None,
                }
                self.deliveries[did] = d
                p["delivery_ids"].append(did)
            if rid == "checkpoint" and body["mode"] == "LIVE":
                aid = str(uuid.uuid4())
                self.engine.artifacts[aid] = {
                    "id": aid,
                    "task_id": root.id,
                    "storage_system": "EXTERNAL_CHECKPOINT_REFERENCE",
                    "uri": params["checkpoint_uri"],
                    "sha256": params["checkpoint_sha256"],
                    "byte_size": params["byte_size"],
                }
                run.checkpoints.append(
                    {
                        "step": params["step"],
                        "artifact_id": aid,
                        "artifact_sha256": params["checkpoint_sha256"],
                        "recorded_at": _now_iso(),
                    }
                )
                run.last_checkpoint_artifact_id = aid
                run.state = "CHECKPOINTED"
                # The signed run reports a digest; bytes are not fetched or independently verified.
            wi.status = "in_progress"
            self.plans[pid] = p
            self.idempotency[idx] = (fp, pid)
            self._event(p, "fanout.created")
            return self.view(pid, principal), False

    def refresh(self):
        with self.engine._lock:
            self.approvals.sweep()
            for p in self.plans.values():
                approval = self.approvals.approvals.get(p["approval_id"])
                root = self.engine.tasks[p["task_id"]]
                if approval and approval.state == "approved":
                    self.engine.verify_integrity(root)
                    if approval.payload_hash != root.request_hash:
                        fail("approval_payload_tampered")
                    approval.state = "consumed"
                    approval.consumed_at = _now_iso()
                    for did in p["delivery_ids"]:
                        d = self.deliveries[did]
                        if d["state"] == "WAITING_APPROVAL":
                            d["state"] = "QUEUED"
                            self.engine.transition(
                                d["task_id"], "QUEUED", actor="batch-approval"
                            )
                    self._event(p, "fanout.approved")
                if approval and approval.state in {"expired", "rejected", "canceled"}:
                    for did in p["delivery_ids"]:
                        d = self.deliveries[did]
                        if d["state"] == "WAITING_APPROVAL":
                            d["state"] = (
                                "CANCELED" if approval.state != "expired" else "EXPIRED"
                            )
                            self.engine.transition(
                                d["task_id"], d["state"], actor="batch-approval"
                            )
                            self._event(p, "fanout.gate_closed")
                for did in p["delivery_ids"]:
                    d = self.deliveries[did]
                    if (
                        d["state"] == "RUNNING"
                        and self.clock() >= d["lease_expires_at"]
                    ):
                        d["state"] = "NEEDS_RECONCILIATION"
                        d["last_error"] = "lease_expired_unknown_outcome"
                        self.engine.transition(
                            d["task_id"], "NEEDS_RECONCILIATION", actor="lease-recovery"
                        )
                        self._event(p, "fanout.lease_expired")

            for p in self.plans.values():
                by_step = {
                    self.deliveries[k]["step_id"]: self.deliveries[k]
                    for k in p["delivery_ids"]
                }
                for d in by_step.values():
                    if d["state"] == "QUEUED" and any(
                        by_step[k]["state"] in {"FAILED", "CANCELED", "EXPIRED"}
                        for k in d["depends_on"]
                    ):
                        d["state"] = "CANCELED"
                        d["last_error"] = "dependency_failed"
                        self.engine.transition(
                            d["task_id"], "CANCELED", actor="dependency-policy"
                        )
                        self._event(p, "fanout.dependency_failed")
                ds = [self.deliveries[x] for x in p["delivery_ids"]]
                root = self.engine.tasks[p["task_id"]]
                terminal = all(
                    d["state"] in {"SUCCEEDED", "FAILED", "CANCELED", "EXPIRED"}
                    for d in ds
                )
                if terminal and root.state == "QUEUED":
                    self.engine.transition(
                        root.id, "LEASED", actor="fanout-convergence"
                    )
                    self.engine.transition(
                        root.id, "RUNNING", actor="fanout-convergence"
                    )
                    self.engine.transition(
                        root.id,
                        (
                            "SUCCEEDED"
                            if all(d["state"] == "SUCCEEDED" for d in ds)
                            else "FAILED"
                        ),
                        actor="fanout-convergence",
                    )
                    self.engine.work_items[p["work_item_id"]].status = (
                        "done" if root.state == "SUCCEEDED" else "blocked"
                    )
                    self._event(p, "fanout.converged")
                if terminal:
                    wi = self.engine.work_items[p["work_item_id"]]
                    desired = (
                        "done"
                        if all(d["state"] == "SUCCEEDED" for d in ds)
                        else "blocked"
                    )
                    if wi.status != desired:
                        wi.status = desired
                        self._event(p, "fanout.work_item_closed")

    @synchronized
    def view(self, pid, principal):
        p = self.require(pid, principal)
        ds = [self.deliveries[k] for k in p["delivery_ids"]]
        states = {d["state"] for d in ds}
        status = (
            "WAITING_APPROVAL"
            if "WAITING_APPROVAL" in states
            else (
                "NEEDS_RECONCILIATION"
                if "NEEDS_RECONCILIATION" in states
                else (
                    "SUCCEEDED"
                    if states == {"SUCCEEDED"}
                    else (
                        "PARTIAL"
                        if "SUCCEEDED" in states
                        else (
                            "FAILED"
                            if states <= {"FAILED", "CANCELED", "EXPIRED"}
                            else "RUNNING" if "RUNNING" in states else "QUEUED"
                        )
                    )
                )
            )
        )
        result = copy.deepcopy(p)
        result["status"] = status
        result["deliveries"] = [
            {k: v for k, v in d.items() if k not in {"claim_hash", "result_hash"}}
            for d in ds
        ]
        a = self.approvals.approvals.get(p["approval_id"])
        result["approval"] = self.approvals.approval_out(a) if a else None
        result["availability"] = (
            "MOCK"
            if p["mode"] == "SIMULATE"
            else (
                "LIVE"
                if all(self.live_granted(p, d["target"]) for d in ds)
                else "UNAVAILABLE"
            )
        )
        return result

    def decide(self, pid, principal, decision):
        with self.engine._lock:
            p = self.require(pid, principal)
            if not principal.has_scope("approvals:decide"):
                fail("forbidden", 403)
            if not p["approval_id"]:
                fail("no_batch_approval")
            self.approvals.decide(
                p["approval_id"], decision=decision, actor=principal.sub
            )
            self.refresh()
            return self.view(pid, principal)

    def verify_admission(self, p, d):
        root = self.engine.tasks[p["task_id"]]
        self.engine.verify_integrity(root)
        self.engine.verify_integrity(self.engine.tasks[d["task_id"]])
        resource = self.store.resources.get(root.resource_id)
        if (
            not resource
            or resource.lifecycle_state != "ACTIVE"
            or resource.generation != self.engine.admitted_generations.get(root.id)
        ):
            fail("fanout_resource_changed")

    def claim(self, worker_id, capabilities, limit=1, mode="SIMULATE", plan_id=None):
        with self.engine._lock, self.store._target_lock:
            self.refresh()
            out = []
            for d in self.deliveries.values():
                if len(out) >= min(limit, 10):
                    break
                if (
                    d["state"] != "QUEUED"
                    or d["next_retry_at"] > self.clock()
                    or ("fanout." + d["target"]) not in capabilities
                ):
                    continue
                p = self.plans[d["plan_id"]]
                if p["mode"] != mode or (plan_id and p["id"] != plan_id):
                    continue
                if mode == "LIVE" and not self.live_granted(p, d["target"], worker_id):
                    continue
                by_step = {
                    self.deliveries[x]["step_id"]: self.deliveries[x]
                    for x in p["delivery_ids"]
                }
                if any(by_step[s]["state"] != "SUCCEEDED" for s in d["depends_on"]):
                    continue
                self.verify_admission(p, d)
                token = secrets.token_urlsafe(32)
                d.update(
                    state="RUNNING",
                    worker_id=worker_id,
                    claim_hash=hashlib.sha256(token.encode()).hexdigest(),
                    lease_expires_at=self.clock() + 60,
                    generation=d["generation"] + 1,
                    attempts=d["attempts"] + 1,
                )
                t = self.engine.tasks[d["task_id"]]
                self.engine.transition(t.id, "LEASED", actor=worker_id)
                t.generation = d["generation"]
                self.engine.transition(t.id, "RUNNING", actor=worker_id)
                self.engine.attempts.setdefault(t.id, []).append(
                    TaskAttemptRec(
                        str(uuid.uuid4()),
                        t.id,
                        worker_id,
                        d["generation"],
                        started_at=_now_iso(),
                        state="RUNNING",
                    )
                )
                item = copy.deepcopy(d)
                item.pop("claim_hash")
                item.update(
                    claim_token=token,
                    idempotency_key=d["id"],
                    mode=p["mode"],
                    input=p["input"],
                    parameters=p["parameters"],
                    trace_id=p["trace_id"],
                    work_item_id=p["work_item_id"],
                )
                out.append(item)
                self._event(p, "fanout.claimed")
            return out

    def finish(self, did, worker_id, body):
        with self.engine._lock, self.store._target_lock:
            self.refresh()
            d = self.deliveries.get(did)
            if not d:
                fail("not_found", 404)
            token_hash = hashlib.sha256(body["claim_token"].encode()).hexdigest()
            fp = digest(body)
            if (
                d["worker_id"] != worker_id
                or not hmac.compare_digest(d["claim_hash"] or "", token_hash)
                or d["generation"] != body["generation"]
            ):
                fail("lease_conflict")
            if d["result_hash"] == fp:
                return {"delivery_id": did, "state": d["state"], "replayed": True}
            if d["state"] != "RUNNING" or self.clock() >= d["lease_expires_at"]:
                fail("late_result")
            self.verify_admission(self.plans[d["plan_id"]], d)
            outcome = body["outcome"]
            receipt = body.get("receipt")
            if outcome == "SUCCEEDED":
                if not receipt or not re.fullmatch(
                    r"[0-9a-f]{64}", receipt.get("sha256", "")
                ):
                    fail("receipt_required", 400)
                try:
                    int(receipt["sha256"], 16)
                except ValueError:
                    fail("invalid_sha256", 400)
                if not re.match(
                    r"^(mock|https|file|reminders|x-apple-reminderkit)://",
                    receipt.get("uri", ""),
                ):
                    fail("invalid_receipt_uri", 400)
                if receipt.get("source_mode") != (
                    "MOCK" if self.plans[d["plan_id"]]["mode"] == "SIMULATE" else "LIVE"
                ):
                    fail("receipt_mode_mismatch", 400)
                d["state"] = "SUCCEEDED"
                d["receipt"] = copy.deepcopy(receipt)
                self.engine.transition(d["task_id"], "SUCCEEDED", actor=worker_id)
                aid = str(uuid.uuid4())
                self.engine.artifacts[aid] = {
                    "id": aid,
                    "task_id": d["task_id"],
                    "storage_system": d["target"],
                    "uri": receipt["uri"],
                    "sha256": receipt["sha256"],
                    "byte_size": receipt.get("byte_size"),
                }
            else:
                self.engine.transition(
                    d["task_id"], "NEEDS_RECONCILIATION", actor=worker_id
                )
                d["last_error"] = body.get("error_code", "execution_unknown")
                if outcome == "RETRYABLE" and d["attempts"] < 5:
                    d["state"] = "QUEUED"
                    d["next_retry_at"] = self.clock() + min(300, 2 ** d["attempts"])
                    self.engine.transition(d["task_id"], "QUEUED", actor="retry-policy")
                else:
                    d["state"] = "NEEDS_RECONCILIATION"
            d["result_hash"] = fp
            attempt = self.engine.attempts[d["task_id"]][-1]
            attempt.finished_at = _now_iso()
            attempt.outcome = "SUCCEEDED" if outcome == "SUCCEEDED" else "FAILED"
            attempt.state = "SUCCEEDED" if outcome == "SUCCEEDED" else "FAILED"
            self._event(self.plans[d["plan_id"]], "fanout." + d["state"].lower())
            self.refresh()
            return {"delivery_id": did, "state": d["state"], "replayed": False}

    def reconcile(self, pid, did, principal, body):
        with self.engine._lock:
            p = self.require(pid, principal)
            d = self.deliveries.get(did)
            if not d or d["plan_id"] != pid:
                fail("not_found", 404)
            if not principal.has_scope("approvals:decide"):
                fail("forbidden", 403)
            if (
                d["state"] != "NEEDS_RECONCILIATION"
                or d["generation"] != body["expected_generation"]
            ):
                fail("reconciliation_conflict")
            if not 10 <= len(body.get("reason", "")) <= 500:
                fail("reconciliation_reason_required", 400)
            # Explicitly assert no external effect before retry; successful siblings stay closed.
            if body["resolution"] == "RETRY_CONFIRMED_NOT_EXECUTED":
                d.update(
                    state="QUEUED",
                    next_retry_at=self.clock(),
                    claim_hash=None,
                    result_hash=None,
                )
                self.engine.transition(d["task_id"], "QUEUED", actor=principal.sub)
            elif body["resolution"] == "ACCEPT_RECEIPT":
                receipt = body.get("receipt") or {}
                if (
                    not re.fullmatch(r"[0-9a-f]{64}", receipt.get("sha256", ""))
                    or not re.match(
                        r"^(mock|https|file|reminders|x-apple-reminderkit)://",
                        receipt.get("uri", ""),
                    )
                    or receipt.get("source_mode")
                    != ("MOCK" if p["mode"] == "SIMULATE" else "LIVE")
                ):
                    fail("invalid_reconciliation_receipt", 400)
                d["state"] = "SUCCEEDED"
                d["receipt"] = copy.deepcopy(receipt)
                self.engine.transition(d["task_id"], "SUCCEEDED", actor=principal.sub)
                aid = str(uuid.uuid4())
                self.engine.artifacts[aid] = {
                    "id": aid,
                    "task_id": d["task_id"],
                    "storage_system": d["target"],
                    "uri": receipt["uri"],
                    "sha256": receipt["sha256"],
                    "byte_size": receipt.get("byte_size"),
                }
            elif body["resolution"] == "FAIL":
                d["state"] = "FAILED"
                self.engine.transition(d["task_id"], "FAILED", actor=principal.sub)
            else:
                fail("invalid_resolution", 400)
            self._event(p, "fanout.reconciled")
            self.refresh()
            return self.view(pid, principal)

    def live_granted(self, p, target, worker_id=None):
        try:
            config = json.loads(Path(os.environ["MWCP_FANOUT_GRANTS_FILE"]).read_text())
            return any(
                g.get("enabled") is True
                and g.get("target") == target
                and g.get("owner_sub") == p["owner_sub"]
                and p["recipe_id"] in g.get("recipes", [])
                and (worker_id is None or worker_id in g.get("worker_ids", []))
                for g in config["grants"]
            )
        except (KeyError, ValueError, OSError, TypeError, AttributeError):
            return False

    def project_sql(self, cur):
        """Projection and checkpoint commit share the SAME PostgreSQL transaction.
        Never claim these rows with the legacy generic Outbox repository.
        """
        for did in self._dirty:
            d = self.deliveries.get(did)
            if not d or d["state"] == "WAITING_APPROVAL":
                continue
            p = self.plans[d["plan_id"]]
            cur.execute(
                """INSERT INTO outbox(aggregate,aggregate_id,kind,payload,delivery_id,delivery_state,claim_token,claimed_at,claim_expires_at,attempt_count,next_retry_at,dispatched_at,last_error)
     VALUES ('fanout',%s,'fanout.delivery',%s::jsonb,%s,%s,%s,to_timestamp(NULLIF(%s,0)),to_timestamp(NULLIF(%s,0)),%s,to_timestamp(NULLIF(%s,0)),CASE WHEN %s='SUCCEEDED' THEN now() ELSE NULL END,%s)
     ON CONFLICT(delivery_id) DO UPDATE SET delivery_state=EXCLUDED.delivery_state,claim_token=EXCLUDED.claim_token,claimed_at=EXCLUDED.claimed_at,claim_expires_at=EXCLUDED.claim_expires_at,attempt_count=EXCLUDED.attempt_count,next_retry_at=EXCLUDED.next_retry_at,dispatched_at=COALESCE(outbox.dispatched_at,EXCLUDED.dispatched_at),last_error=EXCLUDED.last_error""",
                (
                    did,
                    json.dumps(
                        {
                            "plan_id": p["id"],
                            "work_item_id": p["work_item_id"],
                            "trace_id": p["trace_id"],
                            "step_id": d["step_id"],
                        }
                    ),
                    did,
                    d["state"],
                    d["claim_hash"],
                    max(0, d["lease_expires_at"] - 60),
                    d["lease_expires_at"],
                    d["attempts"],
                    d["next_retry_at"],
                    d["state"],
                    d["last_error"],
                ),
            )
