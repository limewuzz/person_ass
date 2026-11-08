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

import os
import socket
import time
from dataclasses import dataclass, field

import httpx

from registry import RESOURCE_KINDS, RegistryStore, _iso

PROBE_CAPABILITIES = {"probe.http.get", "probe.tcp.check"}  # 白名单（须与 capabilities 表 enabled 一致）

import ipaddress
import urllib.parse

# ---- SSRF 防护（R4 §B）----
# 云元数据/链路本地/唯一本地等一律拒绝；回环仅测试模式显式放行；
# 生产模式要求 hostname 命中显式注册白名单（当前为空 → 任何目标都会被拒）。
BLOCKED_LITERAL_HOSTS = {
    "metadata.google.internal", "metadata.goog",
    "169.254.169.254", "fd00:ec2::254",      # AWS/GCP 元数据
    "100.100.100.100",                        # 阿里云元数据
}
PRODUCTION_ALLOWED_HOSTS: set[str] = set()   # 生产白名单：空 = 禁止一切生产目标

# 执行模式由服务端环境决定（MWCP_PROBE_MODE=production|test），调用方不可传参覆盖（R5-P1）。
# 每次调用即时读取（避免测试间 import 顺序污染）；production：主机必须在白名单；
# test：仅供本地测试进程（loopback 需逐目标 allow_loopback）。
def current_probe_mode() -> str:
    m = os.environ.get("MWCP_PROBE_MODE", "production").strip().lower()
    if m not in ("production", "test"):
        raise RuntimeError(f"MWCP_PROBE_MODE must be production|test, got {m!r}")
    return m

MAX_CONCURRENCY = 16        # 全局并发硬上限
MAX_BATCH_SIZE = 64         # 单批目标总数硬上限
ALLOWED_PORT_RANGE = (1, 65535)


class ProbeTargetRejected(ValueError):
    """目标未通过 SSRF 校验。"""


def validate_probe_target(target: ProbeTarget, *, allow_loopback: bool = False,
                          production_mode: bool = False) -> None:
    """显式校验：scheme/主机/解析后 IP 三层检查（DNS 预解析缓解重绑定，残余风险见 R4-07）。"""
    if target.capability == "probe.tcp.check":
        host, port = target.host, target.port
        if not host or not port:
            raise ProbeTargetRejected("tcp target needs host+port")
    elif target.capability == "probe.http.get":
        if not target.url:
            raise ProbeTargetRejected("http target needs url")
        p = urllib.parse.urlsplit(target.url)
        if p.scheme not in ("http", "https"):
            raise ProbeTargetRejected(f"scheme {p.scheme!r} not allowed")
        if p.username or p.password:
            raise ProbeTargetRejected("credentials in URL not allowed")
        host = p.hostname
        if not host:
            raise ProbeTargetRejected("no hostname")
    else:
        raise ProbeTargetRejected(f"capability {target.capability} not in whitelist")
    host_l = host.lower().strip(".")
    if target.capability == "probe.tcp.check":
        if not (ALLOWED_PORT_RANGE[0] <= int(target.port) <= ALLOWED_PORT_RANGE[1]):
            raise ProbeTargetRejected("port out of allowed range")
    if production_mode:
        if host_l not in PRODUCTION_ALLOWED_HOSTS:
            raise ProbeTargetRejected("host not in production whitelist (empty by design)")
        # 白名单域名也不得解析进私网/元数据（防重绑定的白名单侧加固）
    elif current_probe_mode() == "production" and not production_mode:
        # 默认入口语义：未显式指定 production_mode 的调用按当前服务端模式判定
        if host_l not in PRODUCTION_ALLOWED_HOSTS:
            raise ProbeTargetRejected("production mode: host not in whitelist")
    if host_l in BLOCKED_LITERAL_HOSTS:
        raise ProbeTargetRejected("cloud metadata endpoint blocked")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ProbeTargetRejected(f"dns resolve failed: {e}") from e
    seen: set[str] = set()
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        seen.add(str(ip))
        if ip.is_loopback:
            # R6-P2：白名单/生产模式绝不豁免回环；仅测试模式显式 allow_loopback 放行
            if production_mode or not allow_loopback:
                raise ProbeTargetRejected(f"non-public address blocked: {ip}")
        elif ip.is_link_local or ip.is_private or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            # R6-P2：私网/链路本地/保留/组播无条件拒绝——白名单只决定"能否探测该资产"，
            # 绝不自动授权其解析到非全局地址
            raise ProbeTargetRejected(f"non-public address blocked: {ip}")





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


@dataclass(frozen=True)
class ApprovedProbeTarget:
    """R6-P1：获准探针目标的不可变绑定（登记=授权；资源存在≠目标授权）。

    canonical endpoint 在登记时固化；执行时逐字段比对，任何替换（URL/端口/能力）即拒绝。
    """
    target_id: str
    resource_id: str
    capability: str
    scheme: str | None
    host: str
    port: int | None
    path: str | None
    query: str | None = None
    kind: str = "service"
    node_id: str | None = None
    owner: str = "local-test"
    approved_at: str = ""
    version: int = 1
    enabled: bool = True


def _canonical_endpoint(target: ProbeTarget) -> tuple:
    """归一化 (capability, scheme, host, port, path, query)；比较用。

    R7-P1：完整 URL 语义——**query 原样逐字符参与绑定**（不做参数重排/解码归一，
    防止 ?probe=passive ↔ ?command=unexpected 这类语义偷换）。
    """
    if target.capability == "probe.http.get":
        p = urllib.parse.urlsplit(target.url)
        port = p.port or (443 if p.scheme == "https" else 80)
        return ("probe.http.get", p.scheme.lower(), p.hostname.lower().strip("."), port,
                p.path or "/", p.query or "")
    return ("probe.tcp.check", None, target.host.lower().strip("."), int(target.port), None, None)


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
    "redirect": "unknown",  # 3xx：目标要求重定向，未跟随，证据不足
    "offline": "offline",
    "timeout": "unknown",          # 超时 ≠ 离线：证据不足按 unknown
    "auth_rejected": "unknown",    # 401/403：目标在线但拒绝（不判死）
    "degraded": "degraded",
}


def http_probe(target: ProbeTarget, client: httpx.Client | None = None) -> ProbeObservation:
    assert target.capability == "probe.http.get" and target.url
    own = client is None
    client = client or httpx.Client(verify=True, trust_env=False, follow_redirects=False)  # 不走系统代理；禁止跟随重定向
    t0 = time.time()
    note = ""
    try:
        r = client.get(target.url, timeout=target.timeout_seconds)
        elapsed = time.time() - t0
        if r.status_code < 300:
            status = "healthy"
        elif r.status_code < 400:
            status, note = "redirect", f"http {r.status_code} redirect not followed"  # SSRF：不跟随
            r.close()
        elif r.status_code in (401, 403):
            status = "auth_rejected"
        else:
            status = "degraded"
        if not note:
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


def register_target(store: RegistryStore, target: ProbeTarget, *, allow_loopback: bool = False,
                     owner: str = "local-test") -> ApprovedProbeTarget:
    """显式登记探针目标（唯一授权入口）。登记=资源存在性+SSRF 校验+固化 canonical endpoint。

    R6-P1：登记结果写入 store.approved_probe_targets（独立于 resources 字典）；
    run_probe 只接受"与获准 endpoint 逐字段一致"的目标。
    """
    _authoritative_guard(store, target)  # R8-P1：登记即核对权威记录
    validate_probe_target(target, allow_loopback=allow_loopback,
                          production_mode=(current_probe_mode() == "production"))
    cap, scheme, host, port, path, query = _canonical_endpoint(target)
    if not hasattr(store, "approved_probe_targets"):
        store.approved_probe_targets = {}
    with store._target_lock:  # R8-P2：登记原子提交（并发重登记只认一个结果）
        existing = store.approved_probe_targets.get(target.resource_id)
        if existing is not None:
            # R7-P3：完全相同绑定=幂等；任何差异必须走 update_target 版本化变更
            same = (_canonical_endpoint(_target_from_approved(existing)) ==
                    _canonical_endpoint(target)
                    and existing.kind == target.kind and existing.node_id == target.node_id)
            if not same:
                raise ProbeTargetRejected(
                    f"target for {target.resource_id} already approved "
                    f"(v{existing.version}); changing an approved target requires "
                    f"update_target with expected_version (authorization change)")
            return existing
        approved = ApprovedProbeTarget(
            target_id=f"{target.resource_id}:{cap}", resource_id=target.resource_id,
            capability=cap, scheme=scheme, host=host, port=port, path=path, query=query,
            kind=target.kind, node_id=target.node_id,
            owner=owner, approved_at=_iso(time.time()))
        store.approved_probe_targets[target.resource_id] = approved
        _audit_target_change(store, approved, 0, 1, "register", owner)
        return approved


def update_target(store: RegistryStore, target: ProbeTarget, *, expected_version: int,
                  allow_loopback: bool = False, owner: str = "local-test") -> ApprovedProbeTarget:
    """R7-P3：显式版本化变更已批准目标（乐观锁 + 审计记录）。"""
    if not hasattr(store, "approved_probe_targets"):
        store.approved_probe_targets = {}
    _authoritative_guard(store, target)  # R8-P1
    # 预检（快路径，无锁）：存在性 + 版本
    existing = store.approved_probe_targets.get(target.resource_id)
    if existing is None:
        raise ProbeTargetRejected(f"no approved target for {target.resource_id}; use register_target")
    if existing.version != expected_version:
        raise ProbeTargetRejected(
            f"version conflict: approved target at v{existing.version}, "
            f"expected_version={expected_version} (concurrent modification?)")
    # SSRF/白名单校验（锁外：可被并发交错穿透——真正的 CAS 在提交段）
    validate_probe_target(target, allow_loopback=allow_loopback,
                          production_mode=(current_probe_mode() == "production"))
    cap, scheme, host, port, path, query = _canonical_endpoint(target)
    with store._target_lock:  # R8-P2：原子 CAS——锁内重读版本，唯一写者胜出
        current = store.approved_probe_targets.get(target.resource_id)
        if current is None:
            raise ProbeTargetRejected(f"no approved target for {target.resource_id}")
        if current.version != expected_version:
            raise ProbeTargetRejected(
                f"version conflict: approved target at v{current.version}, "
                f"expected_version={expected_version} (concurrent modification?)")
        new = ApprovedProbeTarget(
            target_id=current.target_id, resource_id=target.resource_id,
            capability=cap, scheme=scheme, host=host, port=port, path=path, query=query,
            kind=target.kind, node_id=target.node_id,
            owner=owner, approved_at=current.approved_at,
            version=current.version + 1, enabled=current.enabled)
        store.approved_probe_targets[target.resource_id] = new
        _audit_target_change(store, new, current.version, new.version, "update", owner)
        return new


def disable_target(store: RegistryStore, resource_id: str, *, expected_version: int | None = None,
                   owner: str = "local-test") -> None:
    """禁用已批准目标（执行即拒）；R8-P2：与 update 同样的原子 CAS 语义。

    expected_version=None 兼容旧行为（读当前版本直接禁用，锁内提交）。
    """
    import dataclasses
    approved_map = getattr(store, "approved_probe_targets", {})
    with store._target_lock:
        existing = approved_map.get(resource_id)
        if existing is None:
            raise ProbeTargetRejected(f"no approved target for {resource_id}")
        if expected_version is not None and existing.version != expected_version:
            raise ProbeTargetRejected(
                f"version conflict: approved target at v{existing.version}, "
                f"expected_version={expected_version} (concurrent modification?)")
        disabled = dataclasses.replace(existing, enabled=False, version=existing.version + 1)
        approved_map[resource_id] = disabled
        _audit_target_change(store, disabled, existing.version, disabled.version, "disable", owner)


def _audit_target_change(store, approved: "ApprovedProbeTarget", from_v: int, to_v: int,
                         action: str, owner: str) -> None:
    """R7-P3：所有授权变更留痕（无秘密值；P1-03 后转持久表）。"""
    if not hasattr(store, "target_change_log"):
        store.target_change_log = []
    store.target_change_log.append({
        "target_id": approved.target_id, "action": action,
        "from_version": from_v, "to_version": to_v,
        "endpoint": f"{approved.scheme or 'tcp'}://{approved.host}:{approved.port}{approved.path or ''}",
        "query_fingerprint": _sha12(approved.query) if approved.query else None,  # R8-P3：不落原始 query
        "kind": approved.kind, "node_id": approved.node_id,
        "owner": owner, "changed_at": _iso(time.time()),
    })


def _target_from_approved(a: ApprovedProbeTarget) -> ProbeTarget:
    """从获准记录重建 ProbeTarget（服务端查找路径用；不信任调用方 URL）。"""
    if a.capability == "probe.http.get":
        netloc = f"{a.host}:{a.port}"
        url = urllib.parse.urlunsplit((a.scheme, netloc, a.path or "/", a.query or "", ""))
        return ProbeTarget(resource_id=a.resource_id, kind=a.kind, node_id=a.node_id,
                           capability="probe.http.get", url=url)
    return ProbeTarget(resource_id=a.resource_id, kind=a.kind, node_id=a.node_id,
                       capability="probe.tcp.check", host=a.host, port=a.port)


def run_probe_by_id(store: RegistryStore, resource_id: str, *, clock=time.time,
                    client: httpx.Client | None = None,
                    allow_loopback: bool = False) -> ProbeObservation:
    """R7 推荐执行入口：按 resource_id 取**服务端获准配置**构造目标，
    调用方不传 URL/port（不可偷换）；再走 run_probe 的完整校验链。"""
    approved_map = getattr(store, "approved_probe_targets", {})
    approved = approved_map.get(resource_id)
    if approved is None:
        raise ProbeTargetRejected(f"target not registered for resource {resource_id}")
    target = _target_from_approved(approved)
    return run_probe(target, store, clock=clock, client=client,
                     allow_loopback=allow_loopback)


def _sha12(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _fmt_endpoint(ep: tuple) -> str:
    """端点格式化（脱敏）：query 只显示指纹，不出现原始键值。"""
    cap, scheme, host, port, path, query = ep
    q = f"?#sha256:{_sha12(query)}" if query else ""
    proto = scheme or "tcp"
    return f"{cap} {proto}://{host}:{port}{path or '/'}{q}"


def _authoritative_guard(store: RegistryStore, target: ProbeTarget) -> None:
    """R8-P1：登记/更新/执行时核对权威资源记录——kind/node 不符即拒（防错误归属）。"""
    rec = store.resources.get(target.resource_id)
    if rec is None:
        raise ProbeTargetRejected(f"resource {target.resource_id} not registered in store")
    if target.kind != rec.kind or target.node_id != rec.node_id:
        raise ProbeTargetRejected(
            f"target kind/node mismatch with authoritative resource record: "
            f"target=({target.kind},{target.node_id}) resource=({rec.kind},{rec.node_id})")


def _require_approved_target(store: RegistryStore, target: ProbeTarget) -> None:
    """执行前校验：目标必须已登记，且 canonical endpoint 逐字段一致（防偷换）。"""
    approved_map = getattr(store, "approved_probe_targets", {})
    approved = approved_map.get(target.resource_id)
    if approved is None:
        raise ProbeTargetRejected(f"target not registered for resource {target.resource_id} "
                                  f"(resource existence is NOT probe authorization)")
    if not approved.enabled:
        raise ProbeTargetRejected(f"approved target disabled: {approved.target_id}")
    got = _canonical_endpoint(target)
    want = _canonical_endpoint(_target_from_approved(approved))
    if got != want:
        # R8-P3：异常消息只含脱敏端点（query 以指纹表示）
        raise ProbeTargetRejected(
            f"target mismatch with approved endpoint: got {_fmt_endpoint(got)} "
            f"want {_fmt_endpoint(want)}")
    # R7-P2：kind/node 同样绑定——健康证据不得错误归属到其他类别/节点
    if target.kind != approved.kind or target.node_id != approved.node_id:
        raise ProbeTargetRejected(
            f"kind/node mismatch with approved target: got "
            f"({target.kind},{target.node_id}) want ({approved.kind},{approved.node_id})")
    # R8-P1（执行侧）：获准后权威资源记录若迁移/改类，执行即拒
    _authoritative_guard(store, target)


def run_probe(target: ProbeTarget, store: RegistryStore, clock=time.time,
              client: httpx.Client | None = None, *, allow_loopback: bool = False) -> ProbeObservation:
    """执行白名单探针并写回 Registry（observed_at≠received_at：写入含处理耗时）。

    R5-P1：模式由模块 PROBE_MODE 决定（不可调用方覆盖）；目标必须先 register_target；
    未登记资源一律拒绝且绝不自动创建；测试 loopback 豁免需逐目标显式声明。
    """
    if target.capability not in PROBE_CAPABILITIES:
        raise ValueError(f"capability {target.capability} not in probe whitelist")
    if target.kind not in RESOURCE_KINDS:
        raise ValueError(f"bad kind {target.kind}")
    if target.resource_id not in store.resources:
        raise ProbeTargetRejected(f"resource {target.resource_id} not registered (refuse auto-create)")
    _require_approved_target(store, target)  # R6-P1：登记绑定校验
    validate_probe_target(target, allow_loopback=allow_loopback,
                          production_mode=(current_probe_mode() == "production"))
    obs = http_probe(target, client) if target.capability == "probe.http.get" else tcp_probe(target)
    obs.observed_at = _iso(clock())            # 探测完成时刻
    obs.received_at = _iso(clock() + 0.1)      # 写入时刻（演示 100ms 处理延迟，可注入）
    rec = store.resources[target.resource_id]  # R5：只更新已登记资源，绝不自动创建
    rec.base_health = obs.health
    rec.observed_at = obs.observed_at
    rec.received_at = obs.received_at
    rec.ttl_seconds = obs.ttl_seconds
    rec.source = obs.source
    return obs


def run_batch(targets: list[ProbeTarget], store: RegistryStore, *, max_concurrency: int = 4,
              allow_loopback: bool = False, clock=time.time) -> list:
    """并发执行（有界线程池）；任一目标校验失败抛错且不执行该目标。

    R5：总数 ≤ MAX_BATCH_SIZE；并发钳制到 [1, MAX_CONCURRENCY]。
    """
    import concurrent.futures as cf
    if len(targets) > MAX_BATCH_SIZE:
        raise ProbeTargetRejected(f"batch too large: {len(targets)} > {MAX_BATCH_SIZE}")
    max_concurrency = max(1, min(int(max_concurrency), MAX_CONCURRENCY))
    for t in targets:
        if t.resource_id not in store.resources:
            raise ProbeTargetRejected(f"resource {t.resource_id} not registered")
        _require_approved_target(store, t)  # R6-P1
        validate_probe_target(t, allow_loopback=allow_loopback,
                              production_mode=(current_probe_mode() == "production"))
    results: list = []
    with cf.ThreadPoolExecutor(max_workers=max_concurrency) as ex:
        futs = {ex.submit(run_probe, t, store, clock, None, allow_loopback=allow_loopback): t for t in targets}
        for f in cf.as_completed(futs):
            results.append(f.result())
    return results
