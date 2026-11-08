"""P1-05 Resource Registry（内存仓储 + 契约形状，不伪装真实持久数据）。

对应评审 §D：
- Node/Resource/Agent/Capability 与 provenance（source_system/observed_at/received_at/ttl_seconds）。
- 无探针证据 → health=unknown；观测过期 → stale=true（契约用 bool stale，STALE 状态映射说明见
  P1-05-REGISTRY-REVIEW.md）。
- 种子数据来自 2026-11-08 审计基线（source=audit:magicworkshop-audit-2026-11-08），
  全部只读登记；资产 ID ≠ 对旧系统的任何写权限。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException, Query

from deps import get_principal

from auth import Principal

# ---- 契约枚举（contracts/openapi.yaml Node/Resource/Agent/Capability）----
NODE_ROLES = {"PRIMARY", "STANDBY_GATEWAY", "RELAY", "EXISTING_BUSINESS", "WORKER"}
HEALTH = {"healthy", "degraded", "offline", "unknown"}
RESOURCE_KINDS = {"node", "service", "agent", "model", "project", "integration", "artifact", "workflow"}
AGENT_STATUS = {"available", "degraded", "offline", "unknown"}
RISKS = {"READ", "LOW", "MEDIUM", "HIGH", "CRITICAL"}

AUDIT_SOURCE = "audit:magicworkshop-audit-2026-11-08"
AUDIT_OBSERVED_AT = "2026-11-08T15:00:00+08:00"  # 审计证据时点（非实时探针）


@dataclass
class NodeRec:
    id: str
    name: str
    role: str
    source: str = AUDIT_SOURCE
    observed_at: str | None = AUDIT_OBSERVED_AT
    received_at: str | None = None
    ttl_seconds: int | None = 86400  # 审计基线 24h 内视为未过期
    base_health: str = "unknown"  # 无探针 → unknown


@dataclass
class ResourceRec:
    id: str
    kind: str
    owner_system: str
    display_name: str
    node_id: str | None
    source: str = AUDIT_SOURCE
    observed_at: str | None = AUDIT_OBSERVED_AT
    received_at: str | None = None
    ttl_seconds: int | None = 86400
    base_health: str = "unknown"


@dataclass
class AgentRec:
    id: str
    display_name: str
    owner_system: str
    runtime_node_id: str | None
    capabilities: list[str] = field(default_factory=list)
    status: str = "unknown"  # 无探针
    observed_at: str | None = AUDIT_OBSERVED_AT
    received_at: str | None = None
    ttl_seconds: int | None = 86400
    source: str = AUDIT_SOURCE


@dataclass
class CapabilityRec:
    name: str
    version: int
    risk: str
    read_only: bool = True
    enabled: bool = False  # SQL 约束：HIGH/CRITICAL 不得 enabled
    requires_approval: bool = True
    args_schema: dict = field(default_factory=dict)


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(ts))


def _is_stale(rec, now_iso: str) -> bool:
    if rec.ttl_seconds is None or rec.observed_at is None:
        return False  # 无 TTL 定义 = 依赖来源声明（audit 基线恒标 stale 由 received_at 决定）
    import datetime as dt
    obs = dt.datetime.fromisoformat(rec.observed_at)
    cur = dt.datetime.fromisoformat(now_iso)
    return (cur - obs).total_seconds() > rec.ttl_seconds


class RegistryStore:
    """内存仓储（测试替身）。P1-03 落地后替换为 PG 实现，接口不变。"""

    def __init__(self, clock=time.time) -> None:
        self.clock = clock
        self.nodes: dict[str, NodeRec] = {}
        self.resources: dict[str, ResourceRec] = {}
        self.agents: dict[str, AgentRec] = {}
        self.capabilities: dict[tuple[str, int], CapabilityRec] = {}

    def _now_iso(self) -> str:
        return _iso(self.clock())

    # ---- 序列化（契约形状 + provenance 扩展字段）----
    def node_out(self, r: NodeRec) -> dict:
        return {
            "id": r.id, "name": r.name, "role": r.role,
            "health": r.base_health, "stale": _is_stale(r, self._now_iso()),
            "observed_at": r.observed_at, "last_seen_at": None,
            "source": r.source,
            # provenance 扩展（评审 §D 要求）
            "source_system": r.source, "received_at": r.received_at,
            "ttl_seconds": r.ttl_seconds,
        }

    def resource_out(self, r: ResourceRec) -> dict:
        return {
            "id": r.id, "kind": r.kind, "node_id": r.node_id,
            "owner_system": r.owner_system, "display_name": r.display_name,
            "health": r.base_health, "stale": _is_stale(r, self._now_iso()),
            "observed_at": r.observed_at, "source": r.source,
            "source_system": r.source, "received_at": r.received_at,
            "ttl_seconds": r.ttl_seconds,
        }

    def agent_out(self, r: AgentRec) -> dict:
        return {
            "id": r.id, "display_name": r.display_name,
            "owner_system": r.owner_system, "runtime_node_id": r.runtime_node_id,
            "status": r.status, "capabilities": r.capabilities,
            "observed_at": r.observed_at,
            "stale": _is_stale(r, self._now_iso()),
            "source_system": r.source, "received_at": r.received_at,
            "ttl_seconds": r.ttl_seconds,
        }

    @staticmethod
    def capability_out(r: CapabilityRec) -> dict:
        return {
            "name": r.name, "version": r.version, "risk": r.risk,
            "read_only": r.read_only, "enabled": r.enabled,
            "requires_approval": r.requires_approval, "args_schema": r.args_schema,
        }


def seed_audit_baseline(store: RegistryStore) -> None:
    """审计基线（VERIFIED_AT_AUDIT；health=unknown，等待真实探针）。

    评审 R2 §4：observed_at=原始证据时间（审计时点），received_at=实际摄取时间
    （本进程装载快照的时刻）——两者必须可区分，不得填同一值营造实时性。
    """
    ingest_at = _iso(store.clock())
    for n in [
        NodeRec("us-server", "US server (mofang)", "PRIMARY", received_at=ingest_at),
        NodeRec("mac-mini", "Mac mini (home)", "STANDBY_GATEWAY", received_at=ingest_at),
        NodeRec("ucloud-vps", "UCloud VPS", "RELAY", received_at=ingest_at),
        NodeRec("tencent-cloud", "Tencent Cloud", "EXISTING_BUSINESS", received_at=ingest_at),
    ]:
        store.nodes[n.id] = n
    svcs = [
        ("svc.mwcp.portal", "portal", "magicworkshop-server", "门户/终端/Kimi/screen", "mac-mini"),
        ("svc.mwcp.frpc-main", "service", "magicworkshop-server", "frpc 主隧道×5", "mac-mini"),
        ("svc.mwcp.daily-assistant", "service", "daily-assistant", "执行器+8765 AI 网关", "mac-mini"),
        ("svc.mwcp.quota-relay", "service", "quota-relay", "额度中转 8799", "mac-mini"),
        ("svc.mwcp.code-server", "service", "magicworkshop-server", "code-server 8080", "mac-mini"),
        ("svc.mwcp.dsh", "service", "magicworkshop-server", "dsh 3080", "mac-mini"),
        ("svc.ucloud.caddy", "service", "caddy", "公网入口 7 站点", "ucloud-vps"),
        ("svc.ucloud.frps", "service", "frp", "主 frps 7000", "ucloud-vps"),
        ("svc.us.nginx", "service", "nginx", "魔坊全站入口", "us-server"),
        ("svc.us.frps-assistant", "service", "frp", "助手 frps 7100", "us-server"),
        ("svc.us.cliproxy", "service", "cliproxy", "Codex OAuth→OpenAI 兼容 8317", "us-server"),
        ("svc.us.rakazo", "service", "rakazo", "AI 队友平台 5 容器", "us-server"),
        ("svc.tc.cherry-web", "service", "cherry-web", "Cherry 无头版 7180（冻结）", "tencent-cloud"),
    ]
    for sid, kind, owner, disp, node in svcs:
        store.resources[sid] = ResourceRec(sid, kind, owner, disp, node, received_at=ingest_at)
    for a in [
        AgentRec("agent.rakazo.chief", "Rakazo Chief", "rakazo", "us-server", ["daily-assistant:tasks"]),
        AgentRec("agent.rakazo.paper", "Rakazo paper_", "rakazo", "us-server", ["web_search"]),
        AgentRec("agent.rakazo.fupan", "Rakazo 复盘官", "rakazo", "us-server", ["search_history"]),
        AgentRec("agent.mac.ai-gateway", "Mac 8765 AI 网关", "daily-assistant", "mac-mini", []),
        AgentRec("agent.mac.kimi-cli", "Kimi Code CLI", "kimi", "mac-mini", []),
        AgentRec("agent.mac.dsh", "dsh harness", "dsh", "mac-mini", []),
    ]:
        a.received_at = ingest_at
        store.agents[a.id] = a
    for c in [
        CapabilityRec("probe.http.get", 1, "READ", True, True, False,
                      {"url": "string", "timeout_seconds": "int"}),
        CapabilityRec("probe.tcp.check", 1, "READ", True, True, False,
                      {"host": "string", "port": "int"}),
        CapabilityRec("adapter.legacy.status", 1, "READ", True, False, False, {}),
        CapabilityRec("task.shell.exec", 1, "HIGH", False, False, True, {}),
    ]:
        store.capabilities[(c.name, c.version)] = c


def _paginate(items: list[dict], cursor: str | None, limit: int) -> dict:
    """稳定游标分页：cursor=上一页最后 id。"""
    if cursor:
        ids = [i["id"] for i in items]
        if cursor in ids:
            items = items[ids.index(cursor) + 1:]
        else:
            items = []
    page = items[:limit]
    next_cursor = page[-1]["id"] if page and len(items) > limit else None
    return {"items": page, "next_cursor": next_cursor, "page_meta": {"limit": limit}}


def _require_scope(principal: Principal, scope: str) -> None:
    if not principal.has_scope(scope):
        raise HTTPException(status_code=403,
                            detail={"error": "forbidden", "reason": f"missing scope {scope}"})


def _object_guard(principal: Principal, *, kind: str | None = None, node_id: str | None = None) -> None:
    """对象级权限（IDOR）：token 限定的 kinds/node_ids 之外一律 403。"""
    if kind is not None and not principal.may_access_kind(kind):
        raise HTTPException(status_code=403, detail={"error": "forbidden", "reason": "kind out of token scope"})
    if node_id is not None and not principal.may_access_node(node_id):
        raise HTTPException(status_code=403, detail={"error": "forbidden", "reason": "node out of token scope"})


def build_registry_router(store: RegistryStore):
    router = APIRouter()

    @router.get("/api/v1/nodes")
    def list_nodes(cursor: str | None = Query(None, max_length=300), limit: int = Query(50, le=200),
                   principal: Principal = Depends(get_principal)):
        _require_scope(principal, "registry:read")
        items = [store.node_out(n) for n in store.nodes.values()
                 if principal.may_access_node(n.id)]
        return _paginate(sorted(items, key=lambda x: x["id"]), cursor, limit)

    @router.get("/api/v1/nodes/{node_id}")
    def get_node(node_id: str, principal: Principal = Depends(get_principal)):
        _require_scope(principal, "registry:read")
        _object_guard(principal, node_id=node_id)
        rec = store.nodes.get(node_id)
        if not rec:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        return store.node_out(rec)

    @router.get("/api/v1/resources")
    def list_resources(kind: str | None = None, node_id: str | None = None,
                       cursor: str | None = Query(None, max_length=300), limit: int = Query(50, le=200),
                       principal: Principal = Depends(get_principal)):
        _require_scope(principal, "registry:read")
        if kind is not None and not principal.may_access_kind(kind):
            raise HTTPException(status_code=403,
                                detail={"error": "forbidden", "reason": "kind out of token scope"})
        items = []
        for r in store.resources.values():
            if kind and r.kind != kind:
                continue
            if node_id and r.node_id != node_id:
                continue
            if not principal.may_access_kind(r.kind) or not principal.may_access_node(r.node_id):
                continue
            items.append(store.resource_out(r))
        return _paginate(sorted(items, key=lambda x: x["id"]), cursor, limit)

    @router.get("/api/v1/services")
    def list_services(cursor: str | None = Query(None, max_length=300), limit: int = Query(50, le=200),
                      principal: Principal = Depends(get_principal)):
        _require_scope(principal, "registry:read")
        return list_resources("service", None, cursor, limit, principal)

    @router.get("/api/v1/resources/{resource_id}")
    def get_resource(resource_id: str, principal: Principal = Depends(get_principal)):
        _require_scope(principal, "registry:read")
        rec = store.resources.get(resource_id)
        if not rec:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        _object_guard(principal, kind=rec.kind, node_id=rec.node_id)
        return store.resource_out(rec)

    @router.get("/api/v1/agents")
    def list_agents(cursor: str | None = Query(None, max_length=300), limit: int = Query(50, le=200),
                    principal: Principal = Depends(get_principal)):
        _require_scope(principal, "registry:read")
        items = [store.agent_out(a) for a in store.agents.values()
                 if principal.may_access_node(a.runtime_node_id)]
        return _paginate(sorted(items, key=lambda x: x["id"]), cursor, limit)

    @router.get("/api/v1/agents/{agent_id}")
    def get_agent(agent_id: str, principal: Principal = Depends(get_principal)):
        rec = store.agents.get(agent_id)
        if not rec:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        _object_guard(principal, node_id=rec.runtime_node_id)
        return store.agent_out(rec)

    @router.get("/api/v1/capabilities")
    def list_capabilities(principal: Principal = Depends(get_principal)):
        _require_scope(principal, "registry:read")
        return {"items": [store.capability_out(c) for c in store.capabilities.values()]}

    return router


def build_me_router(validator_holder: dict):
    router = APIRouter()

    @router.get("/api/v1/me")
    def me(principal: Principal = Depends(get_principal)):
        return {
            "principal": {
                "sub": principal.sub, "type": principal.typ, "role": principal.role,
                "scopes": sorted(principal.scopes),
                "node_scope": sorted(principal.node_ids) if principal.node_ids is not None else None,
                "kind_scope": sorted(principal.kinds) if principal.kinds is not None else None,
            },
            "issuer": validator_holder["validator"].issuer,
        }

    return router
