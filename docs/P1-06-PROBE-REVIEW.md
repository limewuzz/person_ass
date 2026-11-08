# P1-06 只读探针审查材料（2026-11-08，本地 Mock 阶段）

> 代码：`backend/probes.py`；测试：`backend/tests/test_probes.py`（8 项，本地 ThreadingHTTPServer 作 Mock 目标）。
> 边界：**零生产目标**——目标清单仅存在于测试夹具；生产目标/常驻调度=未来独立审批（评审 R2 §5）。

## 1. 能力白名单

仅 `probe.http.get` / `probe.tcp.check`（READ 风险，capabilities 表 enabled=true）；非白名单能力（如 task.shell.exec）调用即 ValueError——`test_capability_whitelist_enforced` 实证。

## 2. 状态语义（显式区分，评审 §4 要求）

| 探测结果 | status | health（契约枚举） | 依据 |
|---|---|---|---|
| 2xx | healthy | healthy | — |
| 401/403 | auth_rejected | **unknown** | 目标在线但拒绝：证据不足，不判死不判活 |
| 5xx | degraded | degraded | — |
| 连接拒绝/不可达 | offline | offline | — |
| 超时 | timeout | **unknown** | 超时≠离线（评审 §4「明确离线、超时」） |

测试逐一断言（含 note 脱敏：只含状态码与耗时，无 URL 参数/凭据）。

## 3. provenance 三时刻（评审 §4 核心修正）

每次观测：`source=probe:<capability>`、`observed_at=探测完成时刻`、`received_at=写入 Registry 时刻`（含处理延迟，可注入假时钟）、`ttl_seconds`（默认 300，短 TTL 真实观测）。
- 快照数据：observed_at=审计证据时间（15:00+08），received_at=装载时刻——`test_observed_vs_received_distinct_for_snapshot` 断言两者可区分
- 探针数据：UNKNOWN→HEALTHY 迁移后 received_at≥observed_at——`test_healthy_probe_lives_not_fake`
- TTL 过期：假时钟 +31s → stale=true——`test_ttl_expiry_marks_stale`

## 4. Cherry 相关

Cherry 资产在 Registry 仅静态登记（frozen, external），**探针目标清单不包含、也不会包含任何 Cherry 端点**（probes.py 无生产目标；未来清单生成时 Cherry 域名列入硬排除表——已写入代码注释与本文档双锚定）。

## 5. 已知限制

1. 无调度器（按需单次执行；常驻探针循环=P2 后带审批引入）
2. HTTP 探针 `trust_env=False`（不走系统代理）——生产若需经 mihomo 中转属网络设计问题，另评审
3. tcp.check 未覆盖 TLS 握手层（P1-06 后续可加 probe.tls.handshake 能力，走同样白名单流程）
