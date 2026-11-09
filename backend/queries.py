"""前端查询模块（本地 RC）：bootstrap / dashboard / history / 十个新只读域。

语义铁律：生产数据未接通 → source_meta 明示 MOCK/UNAVAILABLE + 证据时间/来源；
缺失值一律 null，绝不 fake healthy/fake 0/fake Connected（PRD §D）。
"""

from __future__ import annotations

from typing import Any

CONTRACT_VERSION = "1.1.1-local-integrated"


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _meta(kind, *, observed_at=None, ttl=None):
    mode = "UNAVAILABLE" if kind == "unavailable" else "MOCK"
    return {
        "data_mode": mode,
        "freshness": "UNKNOWN" if observed_at is None else "FRESH",
        "source_system": "mwcp-local-rc",
        "observed_at": observed_at,
        "received_at": _now(),
        "ttl_seconds": ttl,
        "as_of": _now(),
        "reason_code": "LOCAL_SYNTHETIC_ONLY" if mode == "MOCK" else "NOT_AUTHORIZED",
        "kind": "unavailable" if mode == "UNAVAILABLE" else "mock",
        "system": "mwcp-local-rc",
    }


def feature_state(status, min_phase, reason=None):
    return {
        "status": "MOCK_ONLY" if status == "enabled" else "DISABLED",
        "min_phase": "P1" if min_phase == "P1-03" else min_phase,
        "reason": reason,
    }


def ui_bootstrap(*, principal, features):
    return {
        "app_mode": "LOCAL_MOCK",
        "contract_version": CONTRACT_VERSION,
        "server_time": _now(),
        "identity": principal["identity"],
        "login": principal["login"],
        "features": features,
        "source_meta": _meta("mock"),
    }


def dashboard_summary(*, nodes_payload, task_counts, approval_counts, recent_events):
    counts = {
        k: task_counts.get(k, 0)
        for k in (
            "queued",
            "leased",
            "running",
            "succeeded",
            "failed",
            "canceled",
            "expired",
            "waiting_approval",
            "needs_reconciliation",
        )
    }
    counts["active"] = sum(
        counts[k]
        for k in (
            "queued",
            "leased",
            "running",
            "waiting_approval",
            "needs_reconciliation",
        )
    )
    counts["external"] = None
    return {
        "nodes": {"items": nodes_payload, "next_cursor": None},
        "task_counts": counts,
        "approval_counts": {
            k: approval_counts.get(k, 0)
            for k in ("pending", "approved", "rejected", "expired", "consumed")
        },
        "recent_events": recent_events,
        "source_meta": _meta("mock", observed_at=_now(), ttl=5),
    }


def display_record(
    rid,
    title,
    *,
    summary=None,
    enabled=False,
    route_ref=None,
    source_system=None,
    kind="mock",
):
    result = {
        "id": rid,
        "title": title,
        "enabled": False,
        "route_ref": route_ref,
        "source_meta": _meta(kind),
    }
    if summary is not None:
        result["summary"] = summary
    if source_system is not None:
        result["source_system"] = source_system
    return result


def display_record_list(items, next_cursor=None, kind="mock"):
    return {"items": items, "next_cursor": next_cursor, "source_meta": _meta(kind)}


# ── 十个新域的本地 RC 数据源（严格只读；有证据才 LIVE，否则 MOCK/UNAVAILABLE）──

WORKFLOWS = [
    display_record(
        "wf.daily-sweep",
        "每日助手 sweep（旧系统）",
        summary="Mac cron 9×/工作日；来源=审计 VERIFIED_AT_AUDIT，未接实时",
        enabled=False,
        route_ref="/tasks?filter=workflow:daily-sweep",
        source_system="daily-assistant",
        kind="mock",
    ),
    display_record(
        "wf.paper-push",
        "Rakazo paper_ 推送（旧系统）",
        summary="cron 15 1 * * * Asia/Shanghai；只读登记，不重复建调度",
        enabled=False,
        route_ref="/tasks?filter=workflow:paper-push",
        source_system="rakazo",
        kind="mock",
    ),
]

NETWORK_LINKS = [
    display_record(
        "link.mac-us-frp",
        "Mac→US frp over SSH 中继（7100）",
        summary="审计 VERIFIED：隧道健康依赖 UCloud 中继；未接实时探测",
        enabled=False,
        source_system="audit:2026-11-08",
        kind="mock",
    ),
    display_record(
        "link.ucloud-us-origin",
        "UCloud→US 回源（mofang）",
        summary="审计 VERIFIED + 已知间歇 502；未接实时探测",
        enabled=False,
        source_system="audit:2026-11-08",
        kind="mock",
    ),
    display_record(
        "link.us-tc",
        "US↔Tencent",
        summary="审计时点：单向可达（腾讯→US 200；US→腾讯 TLS 断）",
        enabled=False,
        source_system="audit:2026-11-08",
        kind="mock",
    ),
]

MODELS = [
    display_record(
        "model.deepseek-flash",
        "DeepSeek flash（经 Mac 8765 网关）",
        summary="主通道；来源=审计 VERIFIED_AT_AUDIT；额度/时延 UNKNOWN",
        enabled=False,
        source_system="daily-assistant",
        kind="mock",
    ),
    display_record(
        "model.kimi-k3",
        "Kimi k3（网关备通道）",
        summary="fallback；来源=审计 VERIFIED_AT_AUDIT",
        enabled=False,
        source_system="daily-assistant",
        kind="mock",
    ),
    display_record(
        "model.codex-cliproxy",
        "Codex 系列（US cliproxy）",
        summary="不经 Mac；gpt-6.x/5.6 系；来源=审计 VERIFIED_AT_AUDIT",
        enabled=False,
        source_system="cliproxy",
        kind="mock",
    ),
]

PROJECTS = [
    display_record(
        "proj.mw-control-plane",
        "mw-control-plane（本仓库）",
        summary="本地 RC；git HEAD 见 /ui/bootstrap.source_meta",
        enabled=True,
        source_system="git",
        kind="live",
    ),
    display_record(
        "proj.daily-assistant",
        "daily-assistant（冻结旧系统）",
        summary="只读登记；不修改",
        enabled=False,
        source_system="audit:2026-11-08",
        kind="mock",
    ),
    display_record(
        "proj.magicworkshop-server",
        "magicworkshop-server（冻结旧系统）",
        summary="只读登记；不修改",
        enabled=False,
        source_system="audit:2026-11-08",
        kind="mock",
    ),
]

COMPUTE_RUNS = [
    display_record(
        "compute.colab",
        "Google Colab",
        summary="账号权益 UNKNOWN（未验证）；无本地运行时",
        enabled=False,
        kind="unavailable",
    ),
    display_record(
        "compute.us-docker",
        "US Docker 容器组",
        summary="18 容器（审计 VERIFIED_AT_AUDIT）；未经实时查询",
        enabled=False,
        source_system="audit:2026-11-08",
        kind="mock",
    ),
]

KNOWLEDGE = [
    display_record(
        "kb.magicworkshop-audit",
        "全系统审计包 2026-11-08",
        summary="Drive 1pNUDglq…；28 文件脱敏交接",
        enabled=False,
        source_system="drive",
        kind="mock",
    ),
    display_record(
        "kb.notion-decisions",
        "Notion 架构决策记录",
        summary="由 GPT-6 维护；本 API 未接通 Notion",
        enabled=False,
        kind="unavailable",
    ),
]


def audit_history(engine, *, cursor, limit):
    with engine._lock:
        events = list(engine.audit_bus)
        ids = [e["id"] for e in events]
        start = ids.index(cursor) + 1 if cursor in ids else 0
        page = events[start : start + limit]
        next_cursor = page[-1]["id"] if page and start + limit < len(events) else None
        return {
            "items": page,
            "next_cursor": next_cursor,
            "source_meta": _meta("mock", observed_at=_now(), ttl=5),
        }


def observations_from_registry(store) -> list[dict]:
    """把 registry 中有探针证据的资源映射为 Observation 形状（无证据的跳过）。"""
    out = []
    for rec in store.resources.values():
        if rec.source.startswith("probe:"):
            out.append(
                {
                    "resource_id": rec.id,
                    "status": rec.base_health,
                    "observed_at": rec.observed_at,
                    "received_at": rec.received_at,
                    "ttl_seconds": rec.ttl_seconds,
                    "source": rec.source,
                    "stale": False,
                    "details_redacted": {},
                }
            )
    return out
