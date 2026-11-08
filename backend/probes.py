"""P1-06 只读探针（本地 Mock/快照阶段——无生产目标、无后台常驻）。

对应评审 R2 §0/§5：
- 仅执行能力白名单中的 READ 探针（probe.http.get / probe.tcp.check，enabled=true）。
- 每次观测产出完整 provenance：source（probe:<name>）、observed_at（探测完成时刻）、
  received_at（写入 Registry 的时刻，含处理延迟，可与 observed_at 区分）、ttl_seconds。
- 状态语义显式区分：healthy / offline（连接拒绝）/ timeout（超时，unknown）/ auth_rejected
  （401/403，unknown+note）/ degraded（5xx）；过期未复测 → stale。
- 本模块不含任何生产目标；生产目标清单属未来独立审批（评审 §5「不得新增长期生产监听」）。
"""
from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field

import httpx

from registry import RESOURCE_KINDS, RegistryStore, _iso

PROBE_CAPABILITIES = {"probe.http.get", "probe.tcp.check"}  # 白名单（须与 capabilities 表 enabled 一致）


@dataclass
class ProbeTarget:
    resource_id: str
    kind: str = "service"
    node_id: str | None = None
    capability: str = "probe.http.get"
    url: str | None = None          # http 探针
    host: str | None = None         # tcp 探针
    port: int | None = None
    timeout_seconds: float = 3.0
    ttl_seconds: int = 300          # 短 TTL：真实观测


@dataclass
class ProbeObservation:
    resource_id: str
    status: str          # healthy|offline|timeout|auth_rejected|degraded
    health: str          # healthy|offline|unknown|degraded（契约枚举）
    note: str = ""       # 脱敏说明（不含 URL 凭据等）
    observed_at: str = ""
    received_at: str = ""
    ttl_seconds: int = 300
    source: str = ""


HEALTH_MAP = {
    "healthy": "healthy",
    "offline": "offline",
    "timeout": "unknown",          # 超时 ≠ 离线：证据不足按 unknown
    "auth_rejected": "unknown",    # 401/403：目标在线但拒绝（不判死）
    "degraded": "degraded",
}


def http_probe(target: ProbeTarget, client: httpx.Client | None = None) -> ProbeObservation:
    assert target.capability == "probe.http.get" and target.url
    own = client is None
    client = client or httpx.Client(verify=True, trust_env=False)  # 本地 mock 阶段不走系统代理
    t0 = time.time()
    try:
        r = client.get(target.url, timeout=target.timeout_seconds)
        elapsed = time.time() - t0
        if r.status_code < 300:
            status = "healthy"
        elif r.status_code in (401, 403):
            status = "auth_rejected"
        else:
            status = "degraded"
        note = f"http {r.status_code} in {elapsed:.2f}s"
    except httpx.TimeoutException:
        status, note = "timeout", f"timeout after {target.timeout_seconds}s"
    except httpx.ConnectError:
        status, note = "offline", "connection refused/unreachable"
    except Exception as e:  # 其余网络栈错误一律 offline，不暴露细节
        status, note = "offline", type(e).__name__
    finally:
        if own:
            client.close()
    return ProbeObservation(
        resource_id=target.resource_id, status=status, health=HEALTH_MAP[status], note=note,
        ttl_seconds=target.ttl_seconds, source="probe:http.get",
    )


def tcp_probe(target: ProbeTarget) -> ProbeObservation:
    assert target.capability == "probe.tcp.check" and target.host and target.port
    t0 = time.time()
    try:
        with socket.create_connection((target.host, target.port), timeout=target.timeout_seconds):
            status, note = "healthy", f"tcp open in {time.time()-t0:.2f}s"
    except socket.timeout:
        status, note = "timeout", f"timeout after {target.timeout_seconds}s"
    except OSError:
        status, note = "offline", "connection refused/unreachable"
    return ProbeObservation(
        resource_id=target.resource_id, status=status, health=HEALTH_MAP[status], note=note,
        ttl_seconds=target.ttl_seconds, source="probe:tcp.check",
    )


def run_probe(target: ProbeTarget, store: RegistryStore, clock=time.time,
              client: httpx.Client | None = None) -> ProbeObservation:
    """执行白名单探针并写回 Registry（observed_at≠received_at：写入含处理耗时）。"""
    if target.capability not in PROBE_CAPABILITIES:
        raise ValueError(f"capability {target.capability} not in probe whitelist")
    if target.kind not in RESOURCE_KINDS:
        raise ValueError(f"bad kind {target.kind}")
    obs = http_probe(target, client) if target.capability == "probe.http.get" else tcp_probe(target)
    obs.observed_at = _iso(clock())            # 探测完成时刻
    obs.received_at = _iso(clock() + 0.1)      # 写入时刻（演示 100ms 处理延迟，可注入）
    rec = store.resources.get(target.resource_id)
    if rec is None:
        from registry import ResourceRec
        rec = ResourceRec(id=target.resource_id, kind=target.kind, owner_system="probe",
                          display_name=target.resource_id, node_id=target.node_id)
        store.resources[target.resource_id] = rec
    rec.base_health = obs.health
    rec.observed_at = obs.observed_at
    rec.received_at = obs.received_at
    rec.ttl_seconds = obs.ttl_seconds
    rec.source = obs.source
    return obs
