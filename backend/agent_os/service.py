"""Agent OS Service (Workflow 3): Agent Studio, Conversations + SSE, Multi-Agent Supervisor, and Plugin Security."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
import threading
import uuid
from typing import Any

import queries as Q
from contract_wire import actor_uuid
from registry import AgentRec, AUDIT_OBSERVED_AT
from taskengine import TaskEngineError, json_stable

HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
FORBIDDEN_PLUGIN_SCOPE_PREFIXES = ("admin:", "worker:", "shell:", "root:")


@dataclass
class ConversationRec:
    id: str
    title: str
    owner_sub: str
    agent_id: str | None
    work_item_id: str | None
    created_at: str
    updated_at: str


@dataclass
class MessageRec:
    id: str
    conversation_id: str
    sequence: int
    role: str
    content: str
    spawned_task_id: str | None = None
    approval_id: str | None = None
    created_at: str = ""
    request_hash: str = ""


@dataclass
class PluginRec:
    id: str
    name: str
    version: str
    previous_version: str | None
    signature_sha256: str
    requested_scopes: list[str]
    enabled: bool
    source_repo: str
    updated_at: str
    previous_signature_sha256: str | None = None


class AgentOSService:
    """Manages Agent Studio, owner-scoped Conversations, Supervisor plans, and signed Plugins (V2-EXT-006)."""

    def __init__(self, *, store, engine, approvals) -> None:
        self._lock = threading.RLock()
        self.store = store
        self.engine = engine
        self.approvals = approvals
        self.agent_metadata: dict[str, dict[str, Any]] = {}
        self.conversations: dict[str, ConversationRec] = {}
        self.messages: dict[str, list[MessageRec]] = {}
        self._msg_idem: dict[tuple[str, str, str], tuple[str, str]] = {}  # (sub, conv_id, idem_key) -> (msg_id, hash)
        self.plugins: dict[str, PluginRec] = {}
        self._seed_baseline_plugins()

    def _seed_baseline_plugins(self) -> None:
        now = Q._now()
        p = PluginRec(
            id="plugin.paper-digest",
            name="Rakazo Paper Digest Formatter",
            version="1.0.0",
            previous_version=None,
            signature_sha256="a" * 64,
            requested_scopes=["registry:read", "tasks:read"],
            enabled=False,
            source_repo="https://github.com/limewuzz/person_ass",
            updated_at=now,
        )
        self.plugins[p.id] = p

    # ── Agent Studio ──

    def upsert_agent(self, body: dict, *, actor: str) -> dict:
        aid = body["id"]
        if "cherry" in aid.lower() or "cherry" in body["owner_system"].lower():
            raise PermissionError("cherry_frozen_boundary")
        caps = list(body.get("capabilities") or [])
        with self._lock, self.store._target_lock:
            for c in caps:
                if not any((k == c or (isinstance(k, tuple) and k[0] == c)) for k in self.store.capabilities):
                    raise ValueError(f"unknown_capability:{c}")
            rec = AgentRec(
                id=aid,
                display_name=body["display_name"],
                owner_system=body["owner_system"],
                runtime_node_id=body.get("runtime_node_id"),
                capabilities=caps,
                status="unknown",
                observed_at=AUDIT_OBSERVED_AT,
                received_at=None,
                ttl_seconds=86400,
                source="v2-agent-studio",
            )
            self.store.agents[aid] = rec
            self.agent_metadata[aid] = {
                "default_model_id": body.get("default_model_id"),
                "system_prompt": body.get("system_prompt"),
            }
            self.engine.audit(actor, "agent_os.agent.upsert", aid, f"caps={len(caps)}")
            return self.store.agent_out(rec)

    def patch_agent(self, aid: str, body: dict, *, actor: str) -> dict:
        with self._lock, self.store._target_lock:
            rec = self.store.agents.get(aid)
            if rec is None:
                raise KeyError(aid)
            if "cherry" in rec.owner_system.lower():
                raise PermissionError("cherry_frozen_boundary")
            if body.get("display_name") is not None:
                rec.display_name = body["display_name"]
            if body.get("capabilities") is not None:
                caps = list(body["capabilities"])
                for c in caps:
                    if not any((k == c or (isinstance(k, tuple) and k[0] == c)) for k in self.store.capabilities):
                        raise ValueError(f"unknown_capability:{c}")
                rec.capabilities = caps
            meta = self.agent_metadata.setdefault(aid, {})
            if "default_model_id" in body:
                meta["default_model_id"] = body["default_model_id"]
            if "system_prompt" in body:
                meta["system_prompt"] = body["system_prompt"]
            self.engine.audit(actor, "agent_os.agent.patch", aid, "updated")
            return self.store.agent_out(rec)

    # ── Conversations & Streaming (WORKSPACE-CONTRACT-REQUEST.md) ──

    def create_conversation(self, body: dict, *, principal) -> dict:
        with self._lock:
            agent_id = body.get("agent_id")
            if agent_id and agent_id not in self.store.agents:
                raise KeyError(agent_id)
            wi_id = body.get("work_item_id")
            if wi_id:
                wi = self.engine.work_items.get(wi_id)
                if wi is None:
                    raise KeyError(wi_id)
                if principal.role != "admin" and wi.created_by != actor_uuid(principal):
                    raise PermissionError("work_item_forbidden")
            now = Q._now()
            cid = str(uuid.uuid4())
            rec = ConversationRec(
                id=cid,
                title=body["title"],
                owner_sub=principal.sub,
                agent_id=agent_id,
                work_item_id=wi_id,
                created_at=now,
                updated_at=now,
            )
            self.conversations[cid] = rec
            self.messages[cid] = []
            self.engine.audit(principal.sub, "agent_os.conversation.create", cid, "ok")
            return self.conversation_out(rec)

    def require_conversation(self, cid: str, principal) -> ConversationRec:
        rec = self.conversations.get(cid)
        if rec is None:
            raise KeyError(cid)
        if principal.role != "admin" and rec.owner_sub != principal.sub:
            raise PermissionError("conversation_forbidden")
        return rec

    def list_conversations(self, principal) -> list[dict]:
        with self._lock:
            return [
                self.conversation_out(c)
                for c in self.conversations.values()
                if principal.role == "admin" or c.owner_sub == principal.sub
            ]

    def append_message(
        self, cid: str, body: dict, *, idempotency_key: str, principal
    ) -> dict:
        if not (12 <= len(idempotency_key) <= 256):
            raise ValueError("bad_idempotency_key")
        with self._lock, self.engine._lock, self.store._target_lock:
            conv = self.require_conversation(cid, principal)
            payload_hash = hashlib.sha256(json_stable(body).encode("utf-8")).hexdigest()
            idem_tuple = (principal.sub, cid, idempotency_key)
            if idem_tuple in self._msg_idem:
                existing_msg_id, prev_hash = self._msg_idem[idem_tuple]
                if prev_hash != payload_hash:
                    raise FileExistsError("idempotency_conflict")
                existing_msg = next(
                    m for m in self.messages[cid] if m.id == existing_msg_id
                )
                return self.message_out(existing_msg, replayed=True)

            spawn_cap = body.get("spawn_capability")
            spawn_res = body.get("spawn_resource_id") or "local-ledger"
            spawned_task_id = None
            approval_id = None
            if spawn_cap:
                if spawn_cap != "local.simulate" or spawn_res != "local-ledger":
                    raise PermissionError("local_simulation_only")
                resource = self.store.resources.get(spawn_res)
                if resource is None or resource.lifecycle_state != "ACTIVE":
                    raise PermissionError("resource_forbidden")
                task, _ = self.engine.create_task(
                    principal_id=principal.sub,
                    capability=spawn_cap,
                    capability_version=1,
                    resource_id=spawn_res,
                    idempotency_key=f"conv-msg-{idempotency_key}",
                    arguments={"outcome": "SUCCEEDED"},
                    origin_channel="web",
                    work_item_id=conv.work_item_id,
                    requires_approval=True,
                    risk="MEDIUM",
                    dry_run=True,
                )
                self.engine.admitted_generations[task.id] = resource.generation
                apr = self.approvals.create_for_task(task, risk="MEDIUM")
                spawned_task_id = task.id
                approval_id = apr.id

            seq = len(self.messages[cid]) + 1
            now = Q._now()
            msg = MessageRec(
                id=str(uuid.uuid4()),
                conversation_id=cid,
                sequence=seq,
                role=body.get("role", "user"),
                content=body["content"],
                spawned_task_id=spawned_task_id,
                approval_id=approval_id,
                created_at=now,
                request_hash=payload_hash,
            )
            self.messages[cid].append(msg)
            conv.updated_at = now
            self._msg_idem[idem_tuple] = (msg.id, payload_hash)
            self.engine.audit(principal.sub, "agent_os.message.append", msg.id, f"conv={cid}")
            return self.message_out(msg, replayed=False)

    def list_messages(self, cid: str, principal) -> list[dict]:
        with self._lock:
            self.require_conversation(cid, principal)
            return [self.message_out(m, replayed=False) for m in self.messages.get(cid, [])]

    def stream_conversation_sse(self, cid: str, *, last_event_id: str | None, principal) -> str:
        with self._lock:
            self.require_conversation(cid, principal)
            msgs = list(self.messages.get(cid, []))
        ids = [m.id for m in msgs]
        start = ids.index(last_event_id) + 1 if last_event_id in ids else 0
        chunks: list[str] = []
        for m in msgs[start:]:
            payload = self.message_out(m, replayed=False)
            chunks.append(
                f"id: {m.id}\nevent: conversation.message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            )
        chunks.append("retry: 15000\n: conversation stream snapshot complete\n\n")
        return "".join(chunks)

    def conversation_out(self, rec: ConversationRec) -> dict:
        return {
            "id": rec.id,
            "title": rec.title,
            "owner_sub": rec.owner_sub,
            "agent_id": rec.agent_id,
            "work_item_id": rec.work_item_id,
            "message_count": len(self.messages.get(rec.id, [])),
            "created_at": rec.created_at,
            "updated_at": rec.updated_at,
        }

    def message_out(self, m: MessageRec, *, replayed: bool) -> dict:
        return {
            "id": m.id,
            "conversation_id": m.conversation_id,
            "sequence": m.sequence,
            "role": m.role,
            "content": m.content,
            "spawned_task_id": m.spawned_task_id,
            "approval_id": m.approval_id,
            "created_at": m.created_at,
            "replayed": replayed,
        }

    # ── Supervisor Multi-Agent Orchestration ──

    def create_supervisor_plan(self, body: dict, *, principal) -> dict:
        if body.get("dry_run") is not True:
            raise ValueError("dry_run_required")
        goal = body["goal"]
        preferred = list(body.get("preferred_agents") or ["agent.rakazo.chief", "agent.daily.executor"])
        with self._lock, self.engine._lock, self.store._target_lock:
            for aid in preferred:
                if aid not in self.store.agents:
                    raise KeyError(aid)
            wi = self.engine.create_work_item(
                title=goal[:200],
                kind="task",
                created_by=actor_uuid(principal),
                source_system="supervisor",
            )
            steps = []
            created_task_ids = []
            for idx, aid in enumerate(preferred, 1):
                steps.append(
                    {
                        "step_index": idx,
                        "agent_id": aid,
                        "capability": "local.simulate",
                        "resource_id": "local-ledger",
                        "risk": "MEDIUM",
                    }
                )
                if body.get("execute_immediately"):
                    resource = self.store.resources["local-ledger"]
                    t, _ = self.engine.create_task(
                        principal_id=principal.sub,
                        capability="local.simulate",
                        capability_version=1,
                        resource_id="local-ledger",
                        idempotency_key=f"sup-{wi.id[:16]}-step-{idx}",
                        arguments={"outcome": "SUCCEEDED"},
                        origin_channel="web",
                        work_item_id=wi.id,
                        requires_approval=True,
                        risk="MEDIUM",
                        dry_run=True,
                    )
                    self.engine.admitted_generations[t.id] = resource.generation
                    self.approvals.create_for_task(t, risk="MEDIUM")
                    created_task_ids.append(t.id)
            plan_id = str(uuid.uuid4())
            self.engine.audit(principal.sub, "agent_os.supervisor.plan", plan_id, f"steps={len(steps)}")
            return {
                "plan_id": plan_id,
                "work_item_id": wi.id,
                "steps": steps,
                "created_task_ids": created_task_ids,
                "requires_approval": True,
            }

    # ── Plugin Security Lifecycle (V2-EXT-006) ──

    def register_plugin(self, body: dict, *, actor: str) -> dict:
        pid = body["id"]
        sig = body["signature_sha256"]
        if not HEX64_RE.fullmatch(sig):
            raise ValueError("invalid_signature_sha256")
        scopes = list(body["requested_scopes"])
        for s in scopes:
            if s.startswith(FORBIDDEN_PLUGIN_SCOPE_PREFIXES):
                raise PermissionError(f"plugin_scope_forbidden:{s}")
        if "cherry" in pid.lower() or "cherry" in body["source_repo"].lower():
            raise PermissionError("cherry_frozen_boundary")
        with self._lock:
            existing = self.plugins.get(pid)
            prev_ver = existing.version if existing else None
            prev_sig = existing.signature_sha256 if existing else None
            rec = PluginRec(
                id=pid,
                name=body["name"],
                version=body["version"],
                previous_version=prev_ver,
                signature_sha256=sig.lower(),
                requested_scopes=scopes,
                enabled=False,
                source_repo=body["source_repo"],
                updated_at=Q._now(),
                previous_signature_sha256=prev_sig,
            )
            self.plugins[pid] = rec
            self.engine.audit(actor, "agent_os.plugin.register", pid, f"v={rec.version}")
            return self.plugin_out(rec)

    def set_plugin_enabled(self, pid: str, enabled: bool, *, actor: str) -> dict:
        with self._lock:
            rec = self.plugins.get(pid)
            if rec is None:
                raise KeyError(pid)
            rec.enabled = enabled
            rec.updated_at = Q._now()
            action = "agent_os.plugin.enable" if enabled else "agent_os.plugin.disable"
            self.engine.audit(actor, action, pid, f"v={rec.version}")
            return self.plugin_out(rec)

    def rollback_plugin(self, pid: str, *, actor: str) -> dict:
        with self._lock:
            rec = self.plugins.get(pid)
            if rec is None:
                raise KeyError(pid)
            if not rec.previous_version:
                raise ValueError("no_previous_version_to_rollback")
            old_v = rec.version
            rec.version = rec.previous_version
            rec.previous_version = None
            if rec.previous_signature_sha256:
                rec.signature_sha256 = rec.previous_signature_sha256
            rec.updated_at = Q._now()
            self.engine.audit(actor, "agent_os.plugin.rollback", pid, f"{old_v}->{rec.version}")
            return self.plugin_out(rec)

    def plugin_out(self, rec: PluginRec) -> dict:
        return {
            "id": rec.id,
            "name": rec.name,
            "version": rec.version,
            "previous_version": rec.previous_version,
            "signature_sha256": rec.signature_sha256,
            "requested_scopes": list(rec.requested_scopes),
            "enabled": rec.enabled,
            "source_repo": rec.source_repo,
            "updated_at": rec.updated_at,
        }
