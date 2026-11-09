# MagicWorkshop 完整产品与工程 PRD v1.0 — Backend × Frontend 一次性本地交付

> 日期：2026-11-09（规划版本）。状态：**用户授权制定完整开发计划与两 Agent 本地开发交接，不构成上线/生产操作授权**。工程基线 R10 `7fa9f307c3633aa557d2e7eecf0bd2902cef269c`（由 GLM 报告，GPT-6 仅独立校验白名单源码、109/109 Mock 测试）。
>
> 本 PRD 是用户要求的**一次性交付完整计划**：不再循环“一轮只修 2–3 个补丁”；GLM 一次性完成后端、契约、迁移与本地 Mock 闭环；Codex 一次性完成全部非 Cherry 页面、设计系统与契约联调；所有不允许的生产操作保持封锁。所有交付状态必须分为 `IMPLEMENTED / TESTED / DEPLOYED / APPROVED`。

## 0. 明确授权、约束与事实层级

- **产品**：私人单用户 MagicWorkshop 控制平面；不是 SaaS、多租户、高并发或代替所有已有服务的重写项目。
- **主从拓扑**：美国 6vCPU/约 11GiB RAM 服务器拟作唯一可写主控；Mac mini M2/8GiB 拟作只读备用入口 + 本地 Worker；UCloud 继续原中继；腾讯云保留原服务，不建立第二控制平面。**该拓扑为设计和未来实施目标，非已经部署的事实**。
- **已接受容量决策**：美国新主控常驻目标 **约 1.5GiB RAM**、初期容量预留 **约 2GiB**；无高并发；不要默认增加 Redis / Prometheus / Loki / Kubernetes。性能峰值、数据库内存及机器现存业务占用需要实测，2GiB 不是未经压测的 SLA；重型 LLM、浏览器和视频任务放独立 Worker/计算节点。
- **最高优先级冻结**：Cherry Studio：不读、不探测、不调用、不修改代码、数据库、配置、账户、会话、模型设置、同步、鉴权文件、部署与网络；仅可保留既有静态外链。**不接触旧 Rakazo / 8765 / nginx / Caddy / frp / 定时任务 / 美国现有 DB / 腾讯云既有业务，不复用其口令或业务表。** 禁止因开发需要触发任何旧服务行为。
- **未经批准不能做**：生产 Postgres 或隔离 Docker/PG 容器启动、任何真实探针或面向真实节点的访问、生产凭据 A 轮换、端口/防火墙/反代改动、新增公网服务、旧系统 API 调用、Mac/美国生产任务执行、第三方 OAuth 接入、外部 Colab 操作、生产部署。允许：本地静态设计、代码编辑、只使用合成数据的 Mock HTTP、单测/契约/安全扫描、无真实秘密的 CI、本地纯进程模拟器、上传脱敏证据到现有私有 Drive「待完成」。涉及上述禁区另行获得用户明示授权，不能把“做完项目”视作默许。
- **凭据事件**：凭据 A 事件 OPEN；历史 Git 清理不是轮换。制定独立可审方案即可，不能擅自轮换；不在任何交付物出现秘密值。
- **严禁伪装真实状态**：`UNKNOWN` 不等于 `HEALTHY`；`STALE` 不等于 `OFFLINE`；未连通不能显示“在线”。所有可视化指标必须有来源、观察时间、接收时间、TTL 与数据模式。前端不能把 HTTP 200 自动视为数据真实。

## 1. 目标、用户故事与非目标

**北极星目标**：单个用户在同一界面查看美国主控、Mac、UCloud、腾讯等已知节点、服务、Agent、工作项、任务、审批、事件、研究产物和集成；能在**纯本地 Mock 模式**走通“发起工作项→策略判断→审批→排队→Worker 领取→执行模拟→事件/结果→对账”，将来逐项授权接入真实只读数据或执行功能。前端不直接连接旧业务或秘密服务；所有外部能力通过新后端授权 Adapter。

必须具备：

1. 一个一致的身份、可见性和只读展示模型；区别模型供应商、Agent、Worker、资源、能力。
2. 一个可靠的任务状态机和审计账本模型；独立本地 Mock Worker 可以验证失败、超时、重试、过期、撤销与幂等。
3. 15 个非 Cherry 功能页面、4 个动态详情模板、V2 Motion 架构首页、V1/Prism 原版归档，合计 **22 种页面/模板**。
4. 单一、可机器验证的前后端契约与 TypeScript 类型生成；统一 Mock 响应库；页面/接口/Schema/权限/来源映射清楚。
5. 一次性提交完整的本地实现与证据；不是把真实接口缺失的页面伪装完成。不可用功能提供明确 `DISABLED` 状态和原因。

**非目标**：多租户、GPU 模型推理、常驻浏览器沙箱、大数据仓库、高频 TSDB、完整 Prometheus/Loki、在网页执行任意 Shell、读取 Cherry 业务状态、兼容所有旧库表、自动在美国上线、自动决定 AI Tool 的生产权限。

## 2. 当前可信基线 / 需要重用的文件

- 设计包 v0.4：`MagicWorkshop-GLM-待完成-v0.4.zip`，包含 16 专题、初始 SQL、OpenAPI 3.1、26 验收例、15 页面与 4 详情模板、V2 Motion/V1/Prism 参考。Drive：https://drive.google.com/file/d/1LDv2VdadODjUguw4W0wvvdmru21HXBYT/view
- R10 源码证据与回归：`R10-01-SOURCE-SNAPSHOT.zip`（Drive：https://drive.google.com/file/d/1D-pCD-HjBVBdbgx656ZVv42YL7uzLyhm/view）；`R10-02-TEST-RESULTS.zip`（https://drive.google.com/file/d/1YOlcsg-GBT3nkQcD4TGGgCGs6tNWzzxb/view）；GPT-6 独立运行 **109 passed**。
- R11 结构缺口：Registry 公开可变对象可被无锁写者修改；缺少单调 resource generation 导致 owner A→B→A（ABA）错误接受旧结果。离线复现包：https://drive.google.com/file/d/1v8UgQ0BeCXi8m3r4gbGT2VtjzSX5-90J/view
- PostgreSQL v5：静态提案，**没有运行期验证，不可部署**。后端需要完成 PG DDL/migration/permissions/backup SOP 的**代码及静态审核**，运行期 Gate 标 `NOT RUN`。
- 本交接提供 `MAGICWORKSHOP-OPENAPI-1.1-LOCAL-BASELINE.yaml`：以 v0.4 原 **31 路径 / 33 操作**为不可删基础，新增 **10 个前端所需只读路径**，合并 **41 路径 / 43 操作**；**设计契约候选**，不是已完成的后端功能，也不是生产 API 发布。

## 3. Agent 分工、仓库与冲突防护

| 责任 | GLM 后端（唯一 owner） | Codex 前端（唯一 owner） |
|---|---|---|
| 仓库 | 现有 Mac `~/develop/mw-control-plane`（以现场实际路径为准）；`backend/`, `deploy/`, `contracts/`, `database/`, `tests/` | 单独仓库/工作树 `~/develop/mw-console`（如不存在，在个人本地开发目录新建，不触碰生产）；`src/`, `public/`, `tests/`, `e2e/` |
| OpenAPI | 维护并冻结 `contracts/openapi.yaml` v1.1；Schema、response example、mock fixtures、兼容性 lint | 只能消费已冻结 YAML，生成类型/SDK/Mock adapters；发现契约问题提交 diff request，不私改共享契约 |
| 数据 | Registry/Task/Approval/Worker/Policy/Audit/Artifact 的服务端权威状态 | React Query/SDK 页面状态及少量 UI 缓存；绝不自行决定资源真实健康或通过前端做审批鉴权 |
| 部署 | 本地代码、纯进程 Mock、PG 静态方案（容器运行 NOT RUN） | 本地 Vite dev/build、静态预览和浏览器 E2E；禁止接真实生产旧系统 |
| 交接 | `CONTRACT-FREEZE` 的版本号、operationIds、YAML SHA-256、生成 fixtures/types | 同一 YAML SHA-256 的 client、UI screenshot/E2E、接口兼容报告 |
| 文档 | 后端代码/README/迁移计划留仓库；审核证据存 Drive | 前端代码/README/UI 方案留仓库；审核证据存 Drive |

**集成协议**：GLM 在开始阶段提供候选 v1.1 的 review diff、补全所有响应 schema/examples，产出 `CONTRACT-LOCK.json`（`version`, `sha256`, `paths`, `operations`, `source_commit`, `locked_at`, `change_log`）。Codex 以此生成 SDK，**不得由两 Agent 分别猜 API**。若 Codex 先行开发可用同版 YAML 的 Mock Service Worker/fixtures，但每个屏幕显示 `MOCK`。契约修改采用 `CHANGE-REQUEST.md` + 兼容性差异 + 两边更新同 SHA 的方式，默认只新增可选字段/接口，不破坏旧 v0.4 的 31/33。若必须破坏，走新 API 版本而不是 silent rename。每个 Agent 不改对方仓库的主要源码。

## 4. 系统架构（轻量模块化单体）

```text
V2 Spectra Motion UI (Codex, 15 functions + 4 detail + 3 archive/home)
          │ typed generated API SDK / SSE or fallback polling
          v
FastAPI modular monolith (GLM; one API process for single-user)
  Identity/Auth | Resource & Capability Registry | Probe Policy | WorkItem/Task/Lease
  Approval/Policy | Worker Gateway | Audit/Events | Artifact/Integration Catalog
          │ storage boundary (IRepository/UoW; NOT old database)
          v
Independent Control DB (planned PostgreSQL; deployment NOT APPROVED)
          │ future: approved Worker pulls, no unsolicited inbound to Mac
          v
Local Mock Worker and mock adapters only in this development batch

NO DIRECT BROWSER → Cherry / legacy / production node / agent PTY
NO DOUBLE WRITER: US single control writer; Mac fallback is cache/read-only
```

Production-oriented code may use dependency-injected repository pattern for PostgreSQL and pure in-memory simulator for local tests. **Do not launch PG or Docker**. Do not claim SQLite tests fully substitute PG transaction, isolation or permission tests. Maintain meaningful smoke checks and SQL static lint; mark PG integration `NOT RUN` until explicit authorization.

### 4.1 Identity and policy

- Human Actor, Service identity and Worker identity disjoint. Unknown `typ` rejected. Service/Worker never gain `admin:read` from self-declared scopes. `iss/aud/exp/nbf/iat/jti/kid` validated; local Mock JWT only, independent future OIDC path disabled.
- Role/Scope server side, every detail endpoint tests IDOR and per-resource permissions; Worker URL id must match token `sub`; worker token cannot call user admin endpoints. Fail-closed with `503 auth_misconfigured` when auth infrastructure invalid, but `/health/live` may remain 200.
- High-risk actions disabled; medium require policy/approval and new user permission for production; ordinary task creation in local Mock should never call production adapters. No arbitrary URLs/shell arguments from UI.
- Future browser auth: prefer same-origin BFF session with HttpOnly, Secure, SameSite cookie and CSRF controls; no long-lived JWT in `localStorage`. Local design uses seeded mock login only with unmistakable badge.

### 4.2 Registry and probe state machine — R11 完整修复，不再碎片补丁

- `ResourceRec` 必须不可被任意业务代码原地赋值权威字段；资源 `owner_system`, `kind`, `node_id`, lifecycle 的修改统一走 `RegistryService.register/update_owner/move/reclassify/deactivate/delete/recreate`。
- 每个资源有不可重用的 `generation`；**delete/recreate 也不得回到旧 generation**，可使用全局 monotonic sequence 或不可重用 epoch（注意进程重启/跨进程持久化）。锁协议保护资源写入与 ApprovedTarget 更新、禁用、探针最终健康提交；统一锁序，禁止在锁内 DNS/HTTP/network。
- 批准目标绑定 `resource_id`, generation, kind, node, owner, capability, version, scheme/host/port/path/query 的完整精确端点。调用方仅传 `target_id`；永不把“资源存在”当“目标已批准”。
- 生产 allowlist 保持空；每次 URL 先进行 scheme、domain/IP、端口、DNS 逐地址过滤；reject 私网/回环/metadata；禁止重定向；**DNS rebinding TOCTOU 目前未根除**，未实现连接到已验证 IP 的安全绑定/证书 Host 保留前不可启用生产扫描。
- 执行时快照 generation+target.version；探针 HTTP Mock 完成后，在一个原子提交中重检 resource generation、owner/kind/node、target enabled/version，再写 `base_health + observation provenance`。**A→B→A**、删除重建、撤销/迁移与旧结果并发不得写入健康。
- 观测 `observed_at` 是真实发生时刻、`received_at` 是真实接收/提交时刻，不得把模拟的 `clock()+0.1` 作为真实 provenance。超时→unknown；认证拒绝→unknown+auth_rejected；5xx→degraded；连接拒绝→offline（有证据）；TTL过期→stale。
- 普通审计/异常不输出原始 path/query；已有 `#p:sha12/#q:sha12` 为低强度摘要，低熵值可猜测。生产敏感场景优先不记录或使用带密钥的不可枚举关联标识。只记录最小化字段与 trace_id。
- 未来 PG 必须使用带 resource generation + approved version 的条件事务更新和同事务审计/outbox；单机 Python 锁不算跨进程线性化。

### 4.3 WorkItem / Task / Worker 可靠链（仅本地 Mock 执行）

- 工作项 WorkItem 与一次 Task 分离。Task 状态：`DRAFT→VALIDATING→WAITING_APPROVAL`（可选）`→QUEUED→LEASED→RUNNING→SUCCEEDED`，失败/结束 `FAILED/CANCELED/EXPIRED/NEEDS_RECONCILIATION`；拒绝非法跳转。所有状态变更有 audit/task_event 与 trace_id。
- `POST /api/v1/tasks` 要求 `Idempotency-Key`，用户、范围、请求 hash 形成唯一组合；相同键+相同 hash 返回同一逻辑 task，键相同 payload 不同为 409。模拟并发 100 次也只产生一个逻辑 task。
- Worker 只用单独 token 轮询 `claim`，租约 CAS、`generation`、`lease_token_hash` 校验；旧 lease/旧 generation 的 finish 不能覆盖新结果。Worker 断线、重试、非幂等结果不确定必须进入 `NEEDS_RECONCILIATION`，不盲目重试。
- 审批与执行参数绑定（resource/capability/args hash），一次性批准、过期和版本变更失效；无授权默认拒绝。UI 审批在 **LOCAL_MOCK** 才能真实改变本地模拟账本，生产开关默认禁用。
- 审计/事件/消息采用事务 outbox + 消费去重设计；本地纯进程实现，并提供 PG 事务 SQL/迁移草案及等价性测试设计，但不得假称 PG 恢复已测。

### 4.4 目录、集成与产物

- Agents、Models、Projects、Network Links、Workflows、Integrations、Compute Runs、Knowledge 使用统一只读目录抽象，有 source meta；不从旧业务直接批量抓取数据。
- Artifact Registry 只存 URI、sha256、大小、mime、来源任务与权限可见性；真正 Drive、Notion、Colab 操作未授权时只支持 `UNAVAILABLE`/`MOCK` 本地 seed，不使用伪“CONNECTED”。
- Cherry Studio 只在新 UI 存一条**静态外部链接**，不可列为可探测 Target、可调用 Capability 或连接器。

## 5. API 契约 v1.1：前后端唯一接口基线

**交付的机器可读文件**：`MAGICWORKSHOP-OPENAPI-1.1-LOCAL-BASELINE.yaml`，OpenAPI 3.1；保留既有 31 路径 33 操作，增加 10 个只读查询路径，共 41 路径、43 操作。v0.4 existing schema 被延续，`Resource` 加入**可选** `generation/lifecycle_state` 字段以不破坏旧响应。GLM 在 CONTRACT-LOCK Gate 内对 URI、状态码、响应字段进行最终 lint/实现核对；Codex 不能自行修改 YAML 的语义。

### 5.1 新增 10 条接口（除既有 31 路径外）

| Method & Path | 阶段 | Response schema | 前端使用 | 数据真实性要求 |
|---|---|---|---|---|
| `GET /api/v1/ui/bootstrap` | P1 | `UIBootstrap` | 顶栏身份、feature flags、环境状态 | 明示 LOCAL_MOCK/STAGING/PRODUCTION；功能可用性由服务端判定 |
| `GET /api/v1/dashboard/summary` | P1 | `DashboardSummary` | 总控 KPIs、节点概况、审批数量 | 不可测计数为 `null`，不得默认为 0 |
| `GET /api/v1/events/history` | P1 | `AuditHistoryList` | 观测/最近事件 JSON 列表 | SSE `/events` 之外单独 JSON 历史，游标分页 |
| `GET /api/v1/tasks/{id}/attempts` | P2 | `TaskAttemptList` | 任务详情 Attempts | 对象级授权；租约/身份敏感字段不返回 |
| `GET /api/v1/workflows` | P2 | `DisplayRecordList` | Workflows | 原 cron 只读信息；不能触发 |
| `GET /api/v1/network/links` | P2 | `DisplayRecordList` | Network | 未测链路 UNKNOWN；不可推断可达 |
| `GET /api/v1/models` | P2 | `DisplayRecordList` | Models | 只读模型网关目录，无路由或密钥 |
| `GET /api/v1/projects` | P2 | `DisplayRecordList` | Projects | 只读项目索引，不执行 git/shell |
| `GET /api/v1/compute/runs` | P3 | `DisplayRecordList` | Compute | Colab 未授权→UNAVAILABLE，非真实 GPU 指标 |
| `GET /api/v1/knowledge` | P3 | `DisplayRecordList` | Knowledge | Notion 未授权→UNAVAILABLE，避免伪检索结果 |

**不新增 `/api/v1/services/{id}`**：服务列表沿用 `GET /api/v1/services`，服务详情页 `/services/:id` **调用已有** `GET /api/v1/resources/{id}` 并校验 `kind=service`；不为 UI 别名增加重复 API。任务详情 GET `/tasks/{id}`、events `/tasks/{id}/events`，审批详情 `/approvals/{id}` 等都已在旧 31 中，不能重新造不兼容端点。

### 5.2 通用 Schema / 时间与错误

- `DataSourceMeta`: `data_mode: LIVE|MOCK|UNAVAILABLE`, `freshness: FRESH|STALE|UNKNOWN`, `source_system`, `observed_at|null`, `received_at|null`, `ttl_seconds|null`, `reason_code|null`, `as_of`。两个维度正交，`data_mode=MOCK` 的健康状态不能冒充 LIVE。
- `FeatureState`: `AVAILABLE|MOCK_ONLY|DISABLED|NOT_IMPLEMENTED`, `reason`, `min_phase`；页面按钮必须由返回状态 + 权限控制，不依赖 UI 伪判断。
- `Resource` 扩展可选 `generation >=1`、`lifecycle_state`。所有时间使用带偏移 ISO8601 RFC3339，浏览器按当前时区格式化；后端原始字段不丢失。
- 列表 `items` + `next_cursor`; 新目录统一含 `source_meta`。分页 `limit` 1–100 / opaque cursor；未知总数不返回假 total。
- 错误结构保留既有 `{error:{code,message,details_redacted?},trace_id}`；HTTP `401` 未认证、`403` 无权、`404` 隐藏对象或不存在、`409` CAS/幂等冲突、`422` 参数无效、`503`依赖不可用。具体错误码包括 `UNAUTHENTICATED`, `FORBIDDEN`, `IDEMPOTENCY_CONFLICT`, `LEASE_EXPIRED`, `DEPENDENCY_UNAVAILABLE`, `SOURCE_STALE`, `TARGET_NOT_APPROVED`, `AUTH_MISCONFIGURED`, `NEEDS_RECONCILIATION`。必须返回可安全显示消息、不回显完整 URL 或用户秘密； `Retry-After` 仅在有意义时返回。
- SSE `GET /api/v1/events` 是 `text/event-stream`、具事件 id 和 resume cursor；**不要**把它误当 JSON 列表；浏览器 SSE 在同源 cookie/BFF 或明确支持授权的 `fetch` 流中使用，不能把 Bearer 放 URL 参数。
- Contract-freeze 之后 `operationId` 稳定、TS 生成构建不允许 unchecked `any`；增加统一请求 trace ID、请求超时、AbortController、retry 仅限可重试 GET，敏感 POST 不自动重复。

### 5.3 页面 → API 映射（15 功能页）

| 页面 | 路由 | 主要 API | 阶段 / 本地交付行为 |
|---|---|---|---|
| 总控 Dashboard | `/dashboard` | bootstrap, dashboard/summary, nodes, tasks, events/history | P1：真实/Mock/Unavailable 标注，所有卡带观测时刻 |
| Tasks | `/tasks` | tasks, work-items, tasks/{id}, task events | P1 列表 / P2 本地 Mock 创建、取消和状态机 |
| Approvals | `/approvals` | approvals, audit, approvals/{id}, approve/reject | P1 只读 / P2 仅本地模拟审批，生产无权 |
| Nodes | `/nodes` | nodes, nodes/{id}, resources | P1：四节点角色、不可用/过期正确显示 |
| Services | `/services` | services, resources?kind=service, resources/{id} | P1：只读，不触碰旧服务；Cherry 只能静态外链 |
| Observability | `/observability` | observations, audit, events/history, events (SSE) | P1：事件时间线、来源、ttl、断线退化轮询 |
| Agents | `/agents` | agents, agents/{id}, capabilities | P1：Agent 与模型分离、权限降级 |
| Workflows | `/workflows` | workflows | P2 只读目录；旧 cron 不可触发 |
| Network | `/network` | network/links, nodes | P2 已知链路图，未实测为 UNKNOWN |
| Models | `/models` | models, capabilities | P2 显示独立 8765/US 通道，无路由写操作 |
| Projects | `/projects` | projects, artifacts | P2 仓库索引，无 shell |
| Integrations | `/integrations` | integrations, bootstrap | P2 状态/权限，禁用第三方生产授权按钮 |
| Compute | `/compute` | compute/runs, artifacts | P3 离线 UI + mock/catalog；未授权 Colab=UNAVAILABLE |
| Artifacts | `/artifacts` | artifacts, artifacts/{id} | P3 路径/校验/来源，无下载真实私有文件的假链接 |
| Knowledge | `/knowledge` | knowledge, work-items | P3 离线目录+来源链接，非直接 Notion 写入 |

四详情模板：`/tasks/:id` → tasks/{id} + events + attempts + approvals/artifacts references；`/nodes/:id` → nodes/{id} + resources；`/services/:id` → resources/{id}（kind=service）+ observations/audit；`/agents/:id` → agents/{id} + capabilities/task refs。详情禁止跨资源 IDOR；不存在显示 Not found，不默默回列表首项。

## 6. 前端 UX、设计、可访问性、真实状态

- **视觉来源**：v0.4 `frontend-reference/` 的 V2.0 **Spectra Motion**（炫彩深色、lime/cyan/purple/blue/pink/amber）作为默认设计系统；`/` 是架构首页，历史 `/versions/v1.0`、`/versions/v2.0-prism` 原样归档，必须 hash 比对，不得直接覆盖历史 HTML。
- 组件库：Shell/Sidebar/Topbar/Search/HealthBadge/ProvenanceTooltip/FeatureGate/ApprovalRiskCard/FilterBar/Pagination/Table/Timeline/EntityDetail/EmptyState/ErrorState/Skeleton/ConnectionBanner/OfflineCacheBadge/ConfirmModal。高危按钮默认禁用且有说明。
- `/dashboard`, `/tasks`, `/approvals`, `/nodes`, `/services`, `/observability`, `/agents` P1 全可浏览；其余 8 页也**必须具有真实可交互 UI**（筛选、排序、详情、连接/状态提示），但未获授权的数据不能伪造；通过带 `MOCK ONLY` 的种子演示交互，真实模式空态 `UNAVAILABLE`。
- 任务/审批在开发环境支持本地模拟状态流；不对外网调用旧 API。失联展示 Banner，缓存可读但明确 `STALE`，Mac 不自动升级为第二写主控。
- 响应式验收 1600 / 1280 / 768 / 390 px；WCAG 基础键盘可操作、aria-label、焦点、对比度、状态非颜色单独表达；`prefers-reduced-motion` 禁用粒子、悬停动画。隐藏标签页/不在 viewport 时停止动画与高频刷新。
- 前端从服务端 `UIBootstrap.features` 决定是否显示“生产审批/执行”；所有写操作仍必须后端独立授权。不得在 API 失败时显示模拟健康点来填充 UI。

## 7. 一次性完整交付范围及内部顺序（不拆成交互轮次）

**交付目标是一次完整本地 Release Candidate**，允许 Agent 自己在授权的本地代码范围内做多次提交、自测和修复，但不能把未测内容算 DONE；不要每修一个 bug 就等待新提示。

### M0：契约冻结和基线（GLM 主导、Codex 并行组件架构）

- 从 R10 源码完整对照 v0.4 和本 v1.1，生成 `OPENAPI-DIFF.md`；31/33 旧接口保留、10 新只读 API 定义细化；补回缺失标准响应/错误、Schema examples、鉴权 scope matrix。运行 OAS lint、JSON Schema 2020-12、route coverage diff。产出 `CONTRACT-LOCK.json` 和可公开给 Codex 的合成 fixtures。Codex 生成 SDK 和 Mock layer；两方核对同一 SHA。
- 先运行 R11 两项负向，在 R10 复现失败。保留 R10 109 测试的统计与先前证据。

### M1：GLM 后端完整本地实现

- 解决 Registry 单调 generation + 统一写 API/锁/ABA/delete-recreate，恢复/禁用/结果提交同锁；测试通过后扩展其他模块，不反复打补丁。
- 完整实现 Identity、Registry、Capability、Policy、WorkItem、Task 状态机、Approval、Worker 协议、Audit/Event/SSE、Observation、Artifact/Catalog、UI bootstrap+summary；P1/P2 只读和允许的**本地模拟写闭环**。
- 仓库内补 PostgreSQL ORM/migrations/schema 权限脚本、reconcile/outbox 设计及预期 SQL 反例；**不允许运行 PG/Docker/外部真网**，报告 `PG_RUNTIME_NOT_RUN`。使用 pure mocked repository/unit-of-work 跑任务交易与并发模拟。
- HTTP MockTransport-only probe + SSRF 防护、数据可信度；真实目标 allowlist 空集；独立 CI 检查代码中无生产域名/秘密/外网测试依赖。

### M2：Codex 前端全部 22 模板完成

- 全 15 功能页 + 4 详情 + 根架构首页 + V1/Prism 历史路由可导航；首页和历史资源哈希保护；响应式/无障碍、筛选分页、错误/离线/过期、时间线、模拟数据与未连接状态。
- 统一 TS SDK 由 contract 生成；MSW / fixture 模式与 Live API 模式可切换，但所谓 Live 只能指新本地 GLM API，不可连接生产/旧系统；操作按钮由 `FeatureState` 控制。
- 前端 E2E 覆盖主要流程、视觉截图、契约模拟兼容；在 Mock Task Engine 上走通本地模拟审批/Worker/结果，全部组件不是纯静态占位。

### M3：共同联调、Release Candidate 交付（仍不部署）

- 用 GLM **本地新 API 进程** + Codex 本地 dev server 联调。只绑定 loopback，禁止真实探针、未授权接口对外与自动旧业务调用；对同源 BFF、安全 header、CORS 和 SSE 做 Mock 验证。
- `contract SHA` 一致性、SDK 生成漂移检测、全路由可达、负向/并发/键盘/低内存测试、实测内存峰值；若高于目标预算先优化并记录 tradeoff，不宣称 SLA。
- 发布本地 RC 标签（例如 `rc-local-1`），包含可启动**非数据库真实依赖**的演示与测试命令；如果某场景需要 PG/真实 OAuth 或网络才能验证，明确列为 `NOT RUN` 而不是绕过许可。

## 8. 必须交付的可复核证据（Drive「待完成」）

- `RC-00-REVIEW-INDEX.md`：GLM/Codex 两仓库、HEAD、版本、SHA、主张→证据、implemented/tested/deployed/approved 四态、未决 Gate。
- `RC-01-CONTRACT.zip`：最终 OpenAPI 3.1、JSON Schemas、examples、类型生成锁、API diff、server route coverage、mock fixtures；不得包含 secrets。
- `RC-02-BACKEND-SOURCE.zip`：干净 HEAD 白名单源码（无 `.git`、`.env`、`STATE.md`、生产日志/数据库），测试及迁移计划。
- `RC-03-BACKEND-TESTS.zip`：pytest JUnit/collect-only/环境/exit codes/负向原始失败和修复后证明/线程屏障与 ABA 测试日志。
- `RC-04-FRONTEND-SOURCE.zip`：干净 HEAD 白名单源码、锁定依赖、生成 SDK；保留设计版本哈希。
- `RC-05-FRONTEND-E2E.zip`：playwright 日志/JUnit、1600/1280/768/390 截图、视觉差异摘要、无障碍/性能/断线测试。
- `RC-06-INTEGRATION.zip`：loopback-only HTTP 交换、10 新路由与旧 31 路由差异报告、业务主流程端到端 trace、特性开关截图。
- `RC-07-SECURITY-AND-GATES.md`：密钥 A OPEN、SSRF/DNS TOCTOU、全局限流/PG 未跑、`/docs`、正式 OIDC、旧系统冻结、部署准入清单与回滚。
- `RC-MANIFEST.sha256`：每个上传物的 SHA-256 与 bytes，**逐件下载回读**；Drive 私有且不改变共享权限。

**必要测试矩阵**：R10 109 旧测零退化；R11 2 条旧失败转通过；资源 ABA、无锁写入者、删除/重建、审批和资源 owner 转移、授权撤销竞态、跨 Worker 过期回报、100×幂等并发、状态机非法跳转、Mock 验证器 fail-closed、404/403 IDOR、SSRF redirect/private/DNS、SSE 恢复、分页/游标、时间真值/TTL、来源显示、前端 22 模板、响应式 4 尺寸、UI Mock 标签、旧 HTML 哈希与 Cherry 零调用。

## 9. Definition of Done（验收）

**本地交付成功**须全部满足：

1. GLM 完整后端本地代码与 Codex 完整前端本地代码、各自 clean HEAD，交付源码/测试可独立复现；二者**同一 OpenAPI SHA**，JSON/TS/client/fixtures 一致。所有 41 路径在契约中，旧 31 路径不无意删除；新 P2/P3 路由若尚不具真实数据来源须能返回可用的**诚实状态**，不能宣称外网已经接通。
2. 22 种页面/模板全部存在并有真实导航、空/错/无权/过期/离线与移动端处理；7 个 P1 页面与本地新 API 完成联调，其余具有合成 Mock 或 UNAVAILABLE 明示；非 Cherry 无幽灵链接。
3. 本地 Mock 完整任务/审批/Worker 可靠状态链可复现，原本 109 项回归仍通过，新增真正并发/失效状态测试及前后端 E2E 通过；无源代码秘密，测试只打本地/Mock。
4. 新旧服务/生产/Cherry**零更改**；所有高风险生产能力默认禁用，生产探针 allowlist 为空；测试中的权限不得依赖前端禁用按钮。
5. **任何 PG/Docker/真实 TLS/OIDC/网络/备份恢复未验证内容明确 `NOT RUN`**，用户需另行审批“隔离环境实测 → 生产部署”Gate；项目不能用没有实际验证的运行期能力宣称 production-ready。
6. 证据包完整、Drive 回读一致、Notion 仅记决策/链接；无重复创建记忆、无凭据泄露。

## 10. 独立审批 Gate 和产能约束

- Gate A = **本地 RC 代码验收**：用户当前允许，目标一次性完成；可以本地 Mock/loopback、构建/运行本地前后端。
- Gate B = **隔离 PostgreSQL/Compose 运行演练**：未来单独授权才能启动容器、创建 DB、连接真实 PG。验收空卷首启、least privilege、迁移与数据恢复、内存/OOM、非回环拒绝、备份加密与实测 RPO/RTO；不涉及旧库。
- Gate C = **有限只读生产目标接入**：未来逐个命名范围、目标 IP/域名、请求方法/频率、凭据授权、网络安全与探针 DNS pinning；Cherry 永久排除。
- Gate D = **正式 OIDC / Mac Worker / P2 生产执行**：单独批准身份与最小权限、审批、灰度和回滚；先只读能力；任何写旧业务功能另行逐项授权。
- Gate E = **生产主控部署**：另行批准新容器、端口、反代、TLS、备份、切流和恢复；在此之前不得声称已上线。

**单用户资源约束**：设计目标常驻约 1.5GiB、初期峰值容量约 2GiB；CPU 日常低占用，避免重型遥测栈和额外队列进程。成本预算不代替 PG/CPU/内存真实压测；以 `MemAvailable` 和原业务峰值决定是否可以部署。容量不足时优先降低刷新频率、任务并发、worker 数、日志采样，绝不挤占原业务 OOM 保护。

## 11. 文件权威与参考（时间/性质）

| 来源 | 地位 |
|---|---|
| 当前用户明确授权及 Cherry 冻结、单用户 1.5–2GiB | 最高约束 |
| R10 代码和 R11 独立负向 | 已验证本地源码和测试、尚未部署 |
| v0.4 OpenAPI 31/33、DB草案、UI 页面规格 | 被本 PRD 兼容继承的设计基线 |
| 本交接 OpenAPI v1.1 41/43 | 双 Agent **候选冻结基线**，需 GLM 最终契约 lint/route diff 后签章 |
| 旧环境审计/部署研究 | 有采样时间的历史资料，不能作为今天的真实运行值 |
| 本 PRD 中 Mock/Local UI/PG 事务建议 | 新设计要求，尚未等于已实现 |

**冲突处理**：用户当前范围与不可触碰边界优先；老设计与新版 v1.1 兼容优先；若必须 breaking API、触碰生产或新授权，记录 issue/ADR 并停止那项越权操作，不停止其它已授权的本地开发。
