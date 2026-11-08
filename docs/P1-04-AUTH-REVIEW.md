# P1-04 认证授权审查材料（2026-11-08）

> 范围：本地 Mock OIDC/JWT，未接任何生产账号；不含任何密钥（测试密钥为公开的本地常量）。
> 代码：`backend/auth.py`（校验器/Principal/吊销表/Mock 签发）、`backend/deps.py`、`backend/app.py`（AuthMiddleware）。
> 测试：`backend/tests/test_auth.py`（16 项）+ `test_health.py`（5 项，其中 3 项属认证边界）。

## 1. 身份模型

| 身份类型 | typ | role | scopes（白名单交集） | 说明 |
|---|---|---|---|---|
| Actor（人） | actor | viewer/operator/approver/admin | 按 ROLE_SCOPES 表 | 唯一可持有 admin:read 的类型 |
| Service | service | 同 actor 角色集 | 同上 | 预留（P2 审批流用） |
| Worker | worker | worker（强制，忽略 token 内 role 字段） | 仅 worker:heartbeat / worker:claim | **读不到 registry**（测试 `test_worker_cannot_read_registry_403` 实证） |

- Worker 身份独立：不接受 URL 参数授权（协议端点 `/workers/{id}/*` 的授权将来自 worker token 的 sub，P1-07 实现时校验 path id == token sub——已在 auth.py 注释锚定）。
- 令牌字段：iss/aud/sub/typ/role/scopes/jti/iat/nbf/exp（必填校验 `require` 列表）+ 可选 node_ids/kinds（对象级边界）。

## 2. 令牌校验规则（威胁 → 措施 → 测试）

| 威胁 | 措施 | 测试（结果 ✓ 33/33） |
|---|---|---|
| 无令牌/格式错 | Bearer 缺失 401；泛化错误不回显 token | test_missing_token_401 ✓ |
| alg=none / 算法混淆 | header.alg ∉ {HS256} 拒绝 + decode algorithms 白名单双保险 | test_alg_none_rejected_401 ✓ |
| 伪造签名 | kid→secret 表查表，未知 kid/错 secret 均拒 | test_bad_signature_401 / test_unknown_kid_401 ✓ |
| 错误 issuer/audience | 强制 iss/aud 校验 | test_wrong_issuer_401 / test_wrong_audience_401 ✓ |
| 过期 / 未生效 | exp 必填 + nbf 校验 | test_expired_token_401 / test_nbf_future_token_401 ✓ |
| 重放（吊销后） | jti 内存吊销表（P1-07 换 PG 持久化） | test_revoked_token_replay_401 ✓ |
| 越权动作（scope 缺失） | 端点强制 `_require_scope("registry:read")` | test_scope_missing_403 ✓ |
| IDOR（跨资源） | 对象级：node_ids/kinds 限定，列表过滤+详情 403 双执行 | test_node_scoped_token_idor_403 / test_kind_scoped_token_idor_403 ✓（列表不泄露越权对象） |
| 配置缺失 | MWCP_AUTH_SECRETS 空 → 中间件 503 fail closed（仅 health/live、health/ready 免认证） | 真实绑定实测：nodes→401/503 语义 ✓ |
| 日志泄密 | 错误泛化；测试断言 token/secret 不出现在任何日志记录 | test_token_never_logged ✓ |

## 3. 权限矩阵（当前实现）

| 端点 | 免认证 | registry:read | 对象级 |
|---|---|---|---|
| GET /health/live | ✅ | — | — |
| GET /health/ready | ✅（503 语义见 CHANGES C-1） | — | — |
| GET /nodes, /nodes/{id} | ❌ | 必须 | node_ids 边界 |
| GET /resources, /services | ❌ | 必须 | kinds+node_ids 双边界；kind 参数与 scope 冲突显式 403 |
| GET /agents, /agents/{id} | ❌ | 必须 | runtime_node_id 边界 |
| GET /capabilities | ❌ | 必须 | — |
| GET /me | ❌ | —（任何已认证） | 返回自身 scope 快照 |

## 4. 与旧系统的关系

- **零依赖**：不读 EXECUTOR_API_KEY/portal.conf/htpasswd；不碰 8765/portal/control-api。
- Mock issuer（`https://mock-issuer.mwcp.local`）与任何真实签发方无关联；接生产 OIDC 时替换 TokenValidator 构造参数即可（接口已按 iss/aud/kid 表抽象）。

## 5. 已知限制（如实申报）

1. HS256 对称签名（mock 阶段）；生产建议非对称（RS256/EdDSA）+ JWKS 端点——接口已预留 kid 表，换算法只动 ALLOWED_ALGS 与密钥来源。
2. 吊销表内存态：进程重启清空（P1-07 入库）。
3. 未实现 rate limit（评审未列为本轮必测；列入 P1-04 遗留）。
