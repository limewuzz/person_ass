# 给 GLM 的完整执行 Prompt — MagicWorkshop Backend R11→Local RC（一次性交付）

**你是 MagicWorkshop 后端唯一负责 Agent。用户已经要求一次性完成整个非 Cherry 后端的本地 Release Candidate，而不是每轮只修两三个单测。你必须在当前已授权的 Mac 本地代码/Mock 范围内持续推进直至本地 DoD 满足；无需就普通本地实现反复征求用户许可。禁止越过生产权限边界。**

## 一、第一步：获取并验证唯一 PRD/契约

1. 到 Google Drive「MagicWorkshop｜统一资源池与多入口控制 / 待完成」目录读取本次交接文件（链接从交接索引中获取）：
   - `MAGICWORKSHOP-FULL-PRD-v1.0-LOCAL.md`（通读全部 11 节，以本轮最新版为主）
   - `MAGICWORKSHOP-OPENAPI-1.1-LOCAL-BASELINE.yaml`（**31+10=41 路径 / 33+10=43 操作**；源契约全部保留）
   - `PROMPT-GLM-BACKEND-FULL-RC.md`（本文件）
   - `PROMPT-CODEX-FRONTEND-FULL-RC.md`（阅读以了解接口、职责和前端期望，但**不要修改 Codex 主仓库**）
2. 取 R10 原始 `R10-01-SOURCE-SNAPSHOT.zip`、`R10-02-TEST-RESULTS.zip` 和 R11 负向证据 `MagicWorkshop-R10-GPT6-R11-REGISTRY-CONSISTENCY-NEGATIVE-EVIDENCE.zip`。现场 repo `~/develop/mw-control-plane`（实际路径为准），先做 `git status --short`、`git rev-parse HEAD`，核对基线 GLM 报告 `7fa9f307c3633aa557d2e7eecf0bd2902cef269c`。若不一致，先安全审计差异，不覆盖未提交代码、不抹掉他人修改。
3. 计算所有参考文件 SHA-256；列出 `BASELINE-FACTS.md`：GLM 当前本地可验证事实、Drive 历史、仍未测内容分开。**禁止**把已知 109 项回归当成整个后端完成。先跑旧套件；先在 R10 HEAD 上复现 R11-C1/C2 两项 `2 failed`，留 JUnit、日志、退出码，然后开始修复。

## 二、不可越界的硬边界

- Cherry Studio 彻底冻结：不读/写/探测/调用它的代码、数据库、配置、模型、账号、会话、鉴权文件、网络和部署。只能新 UI 保留静态外链。**不能以审计或跑测试为理由读取 Cherry。**
- 既有 Rakazo、paper_ cron、Mac 8765、EventKit/Reminders、美国旧 PG、腾讯云/UCloud/Caddy/nginx/frp、所有当前运行的业务和端口一律不触碰，不能替换、重启、扫描或新增生产调用。凭据 A 仍 OPEN，**不轮换、不读取/打印真实值**。
- **不启动或部署 PostgreSQL/任何隔离 Docker PG 容器、不创建新生产服务/网络/卷、不改防火墙反代、不跑真实探针或外部 API、不进行生产 OAuth、Colab/Drive/Notion 实际业务调用**。用户当前授权只有 Mac 本地代码、静态验证、完全合成的 Mock、loopback-only 新 API 进程和测试（前端集成）。
- 单用户轻量部署目标常驻 1.5GiB、初期约 2GiB 容量预算；不添加 Redis/Prometheus/Loki/Kubernetes；重型 Worker 不部署在美国主控。**容量预算是设计目标，未实测，不是性能承诺。**
- 所有代码和仓库 README/迁移计划留 repo；Drive 只用于脱敏交付证据，Notion 用于决策和状态，不保存秘密值或重复代码。

## 三、契约优先：由你唯一拥有 OpenAPI，和 Codex 解耦并锁定

以 v0.4 的 `contracts/openapi.yaml` 的 **31 条路径 / 33 操作**为保护基线，合并本交接 `1.1` 的 **10 条新只读路径**（bootstrap、dashboard/summary、events/history、task attempts、workflows、network/links、models、projects、compute/runs、knowledge）。目标 41/43；`Resource` 兼容新增可选 generation/lifecycle_state。不得 silently rename path 参数 `{id}`、response envelope、operationId 或安全 scope。

立即完成：

1. 对现有 FastAPI 实际路由与 1.1 OpenAPI 做 AST/runtime route diff；每项标记 `IMPLEMENTED`, `MOCK_ONLY`, `NOT_IMPLEMENTED` 与 x-phase，不把路由存在当成完整业务实现。
2. 补足 Query 参数、异常 status、鉴权/IDOR scope matrix、分页 cursor、时效/来源、SSE 语义、示例响应和 OpenAPI 规范校验。现有 `/api/v1/events` 是 SSE；新 `/api/v1/events/history` 为 JSON；详情 `/services/:id` 使用已有 `/api/v1/resources/{id}`，无需创造重复服务详情 API。
3. 生成 `contracts/CONTRACT-LOCK.json`：`version`, `sha256`, `paths=41`, `operations=43`, `openapi_file`, `backend_head`, `status`, `generated_at`；`contracts/examples/` 和脱敏 `contracts/mock-fixtures/`；给 Codex 提供单一不可歧义的 YAML SHA-256。与 Codex 共享时用 Drive 私有「待完成」新文件，不改对方代码仓库。
4. 若设计更改有真正必要，发 `CONTRACT-CHANGE-REQUEST.md`（旧/新 diff、影响的 UI、迁移策略、兼容性测试），先以非破坏性可选字段扩展，不单方面修改锁定契约。**实现已冻结契约优先于增加未经要求的新接口。**

## 四、一次性实现完整后端（不是再一轮补丁）

### A. R11 Registry/Probe 状态一致性结构性修复（优先）

- `RegistryStore.resources` 的权威字段不能再由业务写者直接修改。提供 `RegistryService` 的受控 `register / transfer_owner / move_node / change_kind / disable / delete / recreate / observe` 变更接口，并测试旧调用者兼容迁移。读者获取快照，不把内部可变对象返回给任意调用方。
- 设计**单调不可重用 `resource_generation`**（含删除/重建与进程重启的未来持久化映射）与 `target_version`，一个统一锁序/事务模型覆盖资源权威写入、批准目标 update/disable 和探针结果提交；不在锁内 DNS/HTTP。验证 owner A→B→A 不变值的 ABA、删除+重建后旧观测失效、并发迁移、双 update、disable-vs-finish。
- 本地新 API 中的资源管理写操作默认 feature-gated，仅由测试/本地模拟用；不对生产资源施加任何写。遗留 `ResourceRec.owner_system=...` 直写测试迁移到受控 API，不能靠暴露无锁 dict 让新协议失效。
- Probe SSRF allowlist 默认生产空集，目标批准精确绑定 URL 六元组与 kind/node/owner/generation；默认 client 不能绕过 `production` 模式；不能让 whitelisted DNS 解析进私网、禁止重定向，**DNS rebinding TOCTOU 未根除时不批准真实探针**。审计 path/query 默认不输出原文；敏感错误 fail-closed。
- 真实 `observed_at`/`received_at` 由实际代码时钟获取，不用人为 `+0.1`；TTL 与 UNKNOWN/STALE/DEGRADED/OFFLINE 语义一致。

### B. Identity/Auth、权限与策略

- 保留所有 R4–R10 已修权限。Mock JWT 严格 `typ∈{actor,service,worker}`，未知类型 401；Service/Worker 无 admin scope；`iss/aud/exp/nbf/iat/jti/kid` 验证并 fail-closed；Worker id 与 subject 强绑定；每一详情路由 IDOR/跨角色矩阵覆盖。
- 生产 OIDC、持久化 JTI 黑名单、生产会话+BFF 仅准备隔离设计与适配器（feature disabled），不得伪装为已接通。核心安全限制要在服务端 policy 里硬编码，而非依赖 UI 禁用。

### C. WorkItem、Tasks、Approvals、Worker Gateway、Audit

- 一次性写全本地 Task Engine：work item 关联、task 状态机非法跳转拒绝、同 actor/scope/idempotency-key/payload-hash 幂等、100 并发重复请求仅建一条，冲突409。Task events + attempts + trace_id 可检索。
- Worker 心跳/claim/started/finish 的单独令牌/范围、lease token hash、lease expiry、generation CAS、迟到结果拒绝、worker 掉线、幂等 retry vs non-idempotent reconciliation；全部用本地模拟 Worker，不执行真实 shell/模型/脚本或旧系统动作。
- Approvals：策略（READ LOW/MEDIUM/HIGH）、request payload hash、过期、一次性消费、拒绝/取消、二次确认与审计。只有纯本地 MOCK 能执行模拟批准/拒绝；HIGH 以及任何旧服务写一律不可调用。
- Transactional outbox / inbox dedup 设计，以及 mock repository 下可观察到的最终一致语义。真正 PG transactional CAS、提交/锁、唯一索引与迁移 SQL 写代码和测试计划，但运行 `NOT RUN`。

### D. 前端所需查询模块全部实现

- `GET /api/v1/ui/bootstrap`（FeatureState、登录身份、app_mode、contract_version、source_meta）;
- `GET /api/v1/dashboard/summary`（节点/任务/审批/近期事件摘要，未知值=null）；
- `GET /api/v1/events/history` JSON 列表（SSE `/events` 原语义保留）；
- `GET /api/v1/tasks/{id}/attempts`（对象权限）；
- `GET /api/v1/workflows`, `/network/links`, `/models`, `/projects`, `/compute/runs`, `/knowledge`（严格只读查询，只有有证据才能 LIVE，否则 MOCK/UNAVAILABLE，`DisplayRecordList`）；
- v0.4 其余接口（nodes/resources/services/agents/capabilities/work-items/tasks/approvals/observations/audit/artifacts/integrations/workers 等）按 x-phase 完成对应本地业务/安全语义，**不是只返回漂亮种子页面的伪实现**。
- 生产数据未接通：返回有来源、时间、TTL 的 `source_meta`，缺失值 null，不能 fake healthy、fake 0、fake GPU/Connected。

### E. PostgreSQL/P1-03 代码完整但运行 Gate 未批准

- 以 PG v5 静态方案为起点完成 migrations/Alembic、ORM/repository/UoW、roles/DDL least privilege、资源单调 generation、approval/version/outbox 的唯一约束、transactional conditional `UPDATE ... WHERE generation=? RETURNING ...` 设计与 rollback/restore SOP。
- 代码 lint、SQL 语法/权限矩阵静态断言、纯内存模型契约测试可运行；**不能启动隔离 Docker/PG 或连接任何真实库，不可能证明 PG 锁/权限/备份恢复实际通过**，四态明确 `PG_RUNTIME NOT RUN`。未来需用户批准的 Gate：空卷首启、app 角色非 DDL、迁移回滚、加密备份/恢复、pgbench、OOM、loopback/TLS、非回环拒绝。
- 宿主启动配置不把 secret 写 Compose env/argv/inspect，Dockerfile 上线前需锁定真实 digest，不凭空编造 hash。保留真实密码轮换安全事件待批。

## 五、工程质量和安全测试一次性做到位

- 保留 R10 原 **109/109**，R11 两项新负向要先在 R10 失败、修复后通过；每个模块配单元/路由契约/IDOR/feature gating/transaction model/状态机/真正并发/属性测试，测试独立不依赖执行顺序或共享全局 store。
- 对 `resources` 受控更新、owner ABA、node/kind 修改、delete/recreate、授权失效、write vs disable、worker lease expiry、idempotency collision、审批 payload 篡改、日志泄漏、SSE resume、错误格式、cursor、观测 freshness、外网拒绝做负向覆盖。
- 禁止“为满足计数而降低断言”。发现旧测试对真实设计有冲突，应记录证据、前后版本，保持语义，不通过改测试蒙混。
- 只启动 `127.0.0.1` loopback 本地 API + Mock，记录运行端口，避免占用已有 3100/8765/8123 生产端口（如目标端口已占用择其它空闲开发端口）；禁止开放 `0.0.0.0` 和联生产代理。
- 资源预算：单用户无高并发，目标常驻 1.5GiB/预留 2GiB、CPU 小峰值；压测本地 mock 任务（小并发，防 OOM），报告 RSS/CPU/存储增长/GC 观察，不编造美国机实时资源。

## 六、交付流程与不可拖延的终点

本轮完整执行流程（不要让 GPT-6 在每个小补丁后反复下发 R12/R13）：

1. `BASELINE`：读取 PRD/Contract/R10/R11，验证 clean HEAD 和旧回归，复现 2 failed。
2. `CONTRACT LOCK`：41/43 OAS 3.1 + examples + generation schemas + route diff + frozen SHA，供 Codex 使用。
3. `ALL MODULES IMPLEMENTED`：A–E 全部本地代码/Mock 闭环，完善迁移静态方案；不越界生产。
4. `TEST & REPAIR`：完整测试运行 2 次不同收集顺序、所有修复与并发矩阵、Mock 健康源真值；**不要提前停止在“几项修好”**。
5. `INTEGRATION`：配合 Codex 联调新 loopback API、冻结 types，提交契约 E2E / UI 所需响应 examples；任何契约冲突主动给出 RFC/兼容 diff。
6. `RELEASE-CANDIDATE EVIDENCE`：同一个 Git HEAD、clean，所有测试与 Contract SHA 一致，上传 Drive「待完成」完整 `RC-00~RC-07` 对应后端材料；从 Drive 回读校验大小 SHA。保持 Drive 私有，不覆盖 R10/R11 历史。
7. `FINAL HANDOFF`：明确说明已实现、本地测试、未在生产部署、等待授权 Gate；不把 PG、OIDC、网络、Colab 标记为 tested。给出 Codex 集成入口和统一启动命令，不要使用“全部已上线”。

**完成标准**：代码可独立重建、全量 41/43 契约和后端实现状态逐项对应、可在纯 Mock 新控制平面走通任务/审批/Worker 状态链、旧 109 项不退化、R11 两项修复通过、未来真实 PG/网络从未被暗中触发、完整 Evidence-First 交付。

用户要求你**一次性做到本地 Release Candidate**。该做的本地代码、测试和文档直接做完；真正需要新授权的生产行为标记 `NOT APPROVED/NOT RUN` 并继续做其它合法部分，不要擅自跨 Gate，也不要用一句“等待审批”替代所有本地研发。
