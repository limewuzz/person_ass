# P1-05 Resource Registry 审查材料（2026-11-08）

> 代码：`backend/registry.py`（schema/内存仓储/路由）；测试：`backend/tests/test_registry.py`（10 项）。
> 状态：**implemented locally + tested（内存仓储）**。按评审 §D：完成验收依赖隔离数据库（P1-03 暂缓中），故本轮**不标记为完整验收**。

## 1. 数据结构与 provenance

严格对齐契约 `contracts/openapi.yaml` 的 Node/Resource/Agent/Capability schema（required 字段逐一测试断言），并按评审 §D 增加 provenance 扩展字段：

| 字段 | 来源 | 说明 |
|---|---|---|
| source / source_system | `audit:magicworkshop-audit-2026-11-08` | 审计基线，非实时 |
| observed_at | 2026-11-08T15:00:00+08:00 | 证据时点（VERIFIED_AT_AUDIT） |
| received_at | 同上 | 平台入库时间（当前=审计时间） |
| ttl_seconds | 86400 | 基线有效期 24h，过期即 stale=true |

## 2. 状态生命周期与 UNKNOWN/STALE 传播

```
无探针证据 ──────────────> health = unknown（禁止 healthy/degraded 伪造）
     │
有观测（未来探针写入）──> health = 上报值
     │
now - observed_at > ttl ─> stale = true（契约 bool 字段；评审的 STALE 态映射于此，
                           health 保持最后观测值不篡改）
```

- 衰减规则可注入假时钟：`test_stale_decay_after_ttl` 用「审计时点+24h10s」验证 stale 翻转，`test_no_probe_evidence_means_unknown` 验证全部种子 unknown。
- LIVE 态（真实探针、observed_at=now、短 ttl）将在 P1-06 实现；届时 RegistryStore 换 PG 实现（接口不变）。

## 3. 种子数据（审计基线，全部只读登记）

- 4 节点：us-server(PRIMARY) / mac-mini(STANDBY_GATEWAY) / ucloud-vps(RELAY) / tencent-cloud(EXISTING_BUSINESS)
- 13 服务资源（portal/frpc/daily-assistant/quota-relay/code-server/dsh/caddy/frps/nginx/frps-assistant/cliproxy/rakazo/cherry-web——cherry 冻结态只登记）
- 6 agents（rakazo 三 bot + 8765 网关 + kimi cli + dsh）
- 4 capabilities（2 READ 探针 + 1 READ 适配器 + task.shell.exec HIGH 且 enabled=false——遵守 SQL 的 critical_disabled 约束，测试断言）

**资产 ID ≠ 写权限**：Registry 全部只读；无任何指向旧系统 API 的执行通道；Cherry 仅登记不可调用。

## 4. 契约测试清单（10/10 ✓）

形状×4（node/resource/agent/capability required 字段+枚举值域）、services 别名=kind 过滤、UNKNOWN 传播、STALE 衰减（假时钟）、游标分页（两页不相交）、kind/node 过滤、404、HIGH/CRITICAL 禁用约束。

## 5. 端口 3100 归属调查（评审 §A-5 关闭）

实测（2026-11-08 19:05 北京，只读）：
- 宿主监听：`127.0.0.1:3100` ← docker-proxy PID 2775106
- `docker inspect rakazo-api-1`：镜像 `ghcr.io/elie222/rakazo/app:edge`，PortBindings=`map[3100/tcp:[{127.0.0.1 3100}]]`，网络 rakazo_app+rakazo_data，**StartedAt=2026-10-22T07:27:18Z**
- 容器内 `GET /health` → `{"ok":true}`
- compose 定义明文：`"127.0.0.1:${RAKAZO_API_PORT:-3100}:3100"`

**结论：3100 = rakazo-api-1 的固定回环发布端口，自 10-22 存在（非新出现，是审计枚举遗漏）。** 已按「不猜产品」原则用三源证据（inspect/compose/health 探测）关闭。Registry 将登记为 `svc.us.rakazo-api`（kind=service, node=us-server, health=unknown, source=audit+p0-verify）。

## 6. 已知限制

1. 内存仓储：重启即回种子态（by design，P1-03 落库）。
2. 无写路径（P1 阶段 Registry 纯只读——符合评审「不允许自由 shell/调用」）。
3. capabilities 的 args_schema 为示意性类型标注，冻结契约时换 JSON Schema 2020-12 引用。
