# 待批准的最小修复提案（未应用、未声称已测试）

补丁 `01-header-idempotency-and-expiry.patch` 对准收到的原始 RC-01，修复：

- 从契约声明的 Idempotency-Key HTTP 头读取幂等键，缺失拒绝；
- 首次/重放统一返回202 TaskAccepted；
- local.simulate/local-ledger 的 MEDIUM/需审批策略由服务端强制；
- 审批 expires_at 输出实际到期时刻。

这是前两个关键阻断的最小可审 patch，尚未应用到 GLM 源码。它不解决其余 serializer、UUID、source_meta、Worker/审批消费、完整payload幂等绑定与 PG 问题，不等于完整后端修复。其余逐项见 docs/GLM-RC-INDEPENDENT-REVIEW.md。

PRD §3 将 backend/contracts 唯一 owner 交给 GLM，并明确 Codex 只读消费。当前已通过异步问题请求用户明确是否允许在隔离副本中修复实现；未获得回答之前不将该 patch 应用或运行。原始 ZIP 与后端 Python 源文件未修改。

批准后的验收要求：原109历史回归、156回归逐项辨认（新查询测试有与锁定契约相反的硬编码，须保留原证据并纠正断言）、全部43操作运行期schema+错误/UUID/状态码、完整UI审批Worker闭环、CSRF/session/SSE恢复、四屏宽与外部零请求。ready503不改变实际未就绪状态；契约缺503需GLM发兼容增量和新锁，不能造假200或私改契约。
