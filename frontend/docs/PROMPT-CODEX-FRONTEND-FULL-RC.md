# 给 Codex 的完整执行 Prompt — MagicWorkshop Frontend 全站本地 RC（一次性交付）

**你是 MagicWorkshop 前端唯一负责 Agent。用户要求你把全部非 Cherry 的前端一次性做成可运行、可测试、可展示的单用户控制台，而不是只做几张静态截图。** 开发范围是你自己的前端仓库和新 API 的本地 Mock/loopback；不触碰旧业务或生产主控。你的后端对应 Agent 是 GLM；后端契约由 GLM 独占管理，二者以锁定的同一份 OpenAPI SHA 协作。

## 一、先读交接与确定工作区

1. 从 Google Drive「MagicWorkshop｜统一资源池与多入口控制 / 待完成」完整读取：
   - `MAGICWORKSHOP-FULL-PRD-v1.0-LOCAL.md`（特别是 0、3、5、6、7、8、9、10 节）
   - `MAGICWORKSHOP-OPENAPI-1.1-LOCAL-BASELINE.yaml`（设计基线：旧 31 路径 33 操作 + 10 新只读路径 = 41/43）
   - `PROMPT-CODEX-FRONTEND-FULL-RC.md`（本文件）
   - `PROMPT-GLM-BACKEND-FULL-RC.md`（仅了解 GLM 负责的后端合约与交付边界，**不要修改 GLM 后端源码**）
   - 原 v0.4 压缩包 `MagicWorkshop-GLM-待完成-v0.4.zip` 的 `docs/09-FRONTEND-ROUTES.md`、`docs/10-*`、`frontend-reference/`、`MANIFEST.sha256`。
2. 对前端 repo 建立安全隔离（优先本地 `~/develop/mw-console`；有现成 repo 则使用现成位置，先 `git status`）。若 v0.4 的 V2 Spectra Motion 已在某个前端 repo，优先继承而非重新设计。V1/Prism 历史资源逐字节归档，不修改它们。
3. 生成 `BASELINE-FRONTEND.md`：现有页面/组件/依赖/缺失的接口、设计哈希和运行方式；明确设计参考不是生产已接通的页面。

## 二、硬边界：你在前端也没有生产操作权限

- Cherry Studio **完全冻结**，不读取/探测/调用其 API、源代码、数据库、配置、会话、帐号、模型、鉴权文件；仅能在新站提供已有静态外部链接，**不 iframe、代理、自动预览或预取 Cherry**。
- 禁止浏览器直接访问 Rakazo、Mac 8765、腾讯、UCloud、美国现有数据库、模型网关、Agent PTY、Notion/Drive/Colab 实际 API。前端只能请求**新本地 GLM API** 或本地 MSW Mock；不能通过用户凭据“测一下真实线上”绕权。
- 不部署到生产服务器、不改 DNS、端口、Caddy、nginx、鉴权和现有业务；不新建生产任务或真实探针。没有批准真实 PG/Docker、凭据轮换或生产 Worker 执行。P2 危险按钮在生产状态默认禁用；任何模拟动作明确显示 `LOCAL MOCK`。
- 单用户设计，不引入多租户 UI、复杂 SaaS 计费、高频实时流或重型前端依赖；后端目标约 1.5GiB/预留约 2GiB，前端尽量静态构建、缓存节流。

## 三、契约协作：不得从页面猜字段，先锁定 SDK

- **接口设计唯一源**：`MAGICWORKSHOP-OPENAPI-1.1-LOCAL-BASELINE.yaml` 是候选，本轮 GLM 最终发布 `contracts/CONTRACT-LOCK.json + openapi.yaml + examples + fixtures`。首先校验 41/43，不删除旧接口；正式集成前必须把 GLM `openapi_sha256` 与你生成 TypeScript client 的 `contract_sha256` 精确对齐，不一致 CI FAIL。
- 按 OpenAPI 生成 TS 类型/API client，禁 `any`、禁散落的 `fetch('/...')`/自己起别名字段。单一 client 封装 baseURL、timeout、AbortController、trace_id、cursor、401/403/404/409/503 处理；SSE/Last-Event-ID 与新 `/events/history` JSON 分离。FeatureState 只显示权限，权限仍由后端确认。
- **GLM 维护 API/后端目录，你只能读/消费**。如遇接口缺字段、OAS 3.1 结构错误、类型不一致：输出 `CONTRACT-CHANGE-REQUEST.md`，列页面、operationId、现契约、希望修订、兼容性影响及最小 patch；允许先用相同 schema 的 MSW fixtures 实现 UI，不能让 Mock 字段成为事实标准。
- 本地启动集成只允许 127.0.0.1 新 API。浏览器 SSE 需安全认证机制，不在 URL query 带 bearer。优先同源 session/BFF 设计，mock session 只能用于本地演示，明确演示身份，不存生产 token 于 localStorage。
- 新增接口必须用好：`/ui/bootstrap`, `/dashboard/summary`, `/events/history`, `/tasks/{id}/attempts`, `/workflows`, `/network/links`, `/models`, `/projects`, `/compute/runs`, `/knowledge`。服务详情 UI `/services/:id` 从 `GET /resources/{id}` 取得（kind=service）；不要创造 `/api/v1/services/{id}` 的假客户端。

## 四、一次性实现 22 种页面/模板，不遗漏 P2/P3

**路由总计 22 种**：V2 Motion 根 `/`，V1 历史 `/versions/v1.0`，Prism 历史 `/versions/v2.0-prism`，15 功能路由与 4 动态详情模板。根据 v0.4 `docs/09-FRONTEND-ROUTES.md` 将以下完整实装（非 Cherry）：

| 优先 | 页面 / 路由 | 核心体验 & API |
|---|---|---|
| P1 | `/dashboard` 总控制台 | nodes/summary/tasks/recent events；四节点健康与来源、时间、TTL、告警；未知显示 UNKNOWN |
| P1 | `/tasks` 任务工作台 | tasks/work-items；筛选、分页、详情跳转、Mock 创建/取消、本地模拟任务状态 |
| P1 | `/approvals` 审批 | approvals/audit；风险、审批人、参数摘要、到期、审计；本地 Mock 操作，实际执行锁定 |
| P1 | `/nodes` 节点 | US 主控/Mac 备用/UCloud/腾讯四角色；状态真值、最近见到时间、断线 stale |
| P1 | `/services` 服务 | resources?kind=service；按 owner/node/health 筛选、详情，Cherry 只有静态外链 |
| P1 | `/observability` 观测 | observations/audit/events/history/SSE；过滤、时间、脱敏、重连状态与 fallback polling |
| P1 | `/agents` Agent | agents/capabilities；Identity、Skill、Worker 与模型明确区分、不可用调用禁用 |
| P2 | `/workflows` 工作流 | 旧 cron/routine 只读目录与时区，不添加触发旧任务按钮 |
| P2 | `/network` 网络 | 有证据的链路/端口示意；缺证据 UNKNOWN，绝不从地图画线推断可达 |
| P2 | `/models` 模型网关 | Mac 8765 与 US cliproxy 分离展示，所有指标来源标识清楚，不能改路由 |
| P2 | `/projects` 代码项目 | projects/artifacts；仓库、测试摘要、工作项关联，禁在线 shell |
| P2 | `/integrations` 集成 | integrations/bootstrap；授权状态、权限缺失、feature gates，未授权不模拟 Connected |
| P3 | `/compute` 计算 | compute/runs；实验与 checkpoint 索引 UI，Colab 未授权显示 UNAVAILABLE |
| P3 | `/artifacts` 产物 | artifacts / detail；URI/sha256/来源任务、权限，不能假装真实私有 Drive 已下载 |
| P3 | `/knowledge` 知识 | knowledge/work-items；Notion 决策只读 UI，未授权显示 unavailable，不自动写 Notion |
| Detail | `/tasks/:id` | Overview/Attempts/Events/Approvals/Artifacts，SSE跟随、过期与对账 |
| Detail | `/nodes/:id` | Health/Services/Network/History/Risk，只读和 stale |
| Detail | `/services/:id` | Runtime/Dependencies/Logs/Owner/Changes，调用 resources/{id} 并校验 kind |
| Detail | `/agents/:id` | Identity/Capabilities/Runtime/Tasks/Source，必须依据真实 source 系统 |

**每个页面必须可点击导航、真正渲染且有功能交互**：排序、筛选、分页、详情、切换时间范围、错误反馈、loading/empty/unknown/stale/unauthorized/offline；P2/P3 的外部数据源未授权时可以使用**严格标明的 MOCK 数据和可操作的本地演示**，但不能画假数据当 LIVE。代码中不能有“看着像实现，实际没有 route”的幽灵页。

## 五、设计系统与体验要求（继承，不重新发明）

- 使用 v0.4 `frontend-reference/` 的 **V2 Spectra Motion 深色霓虹设计**，保持 lime/cyan/purple/blue/pink/amber 强调色、网格与架构动效；把设计转成统一 tokens（CSS vars）和可复用组件，不把 HTML 字符串硬编码当业务页面。
- 原历史 `V1.0` 与 `Prism` 不可修改；原文件 SHA 保持，若托管位置变化须对打包前后资源校验并在 README 写清为什么。
- 组件必须交付：Shell/Sidebar/Topbar、HealthBadge（文字+图标）、ProvenanceTooltip（source+observed/received/ttl）、FeatureGate、RiskApprovalPanel、ListTable、FilterToolbar、CursorPagination、TaskTimeline、EntityDetailTabs、GraphCanvas、ConnectionBanner、Error/Loading/Empty/Offline/PermissionState、ConfirmationDialog 和 toast。
- 断点桌面 1600/1280、平板 768、手机 390；夜间深色美学保持。完整键盘导航、ARIA、focus-visible、对比度、reduce motion；页面不可在 background tab 高频刷新，虚拟列表/节流视情况做。
- 不能“所有节点都绿色”；首次看数据为 UNKNOWN/UNAVAILABLE；将 `DataSourceMeta.data_mode`（LIVE/MOCK/UNAVAILABLE）与 `freshness`（FRESH/STALE/UNKNOWN）**分开展示**。未测 count=null → `—/暂无可靠统计`，不自动 0。敏感信息不得出现在图表 tooltip、analytics、错误文本或 screenshot。

## 六、真正可操作的本地 Demo 主流程（必须 E2E）

在后端纯 Mock 中依次：

1. 进入 Dashboard，看到身份、节点状态、来源时间及 MOCK 标签。
2. Tasks 发起一条**只作用于新平台本地任务账本**的模拟任务；前端生成 Idempotency-Key（只为新任务生成，失败重试保留键），展示 task_id、trace_id、状态时间线。
3. Policy 判定需要批准→进入 Approvals，看清 risk、scope、动作、目标、到期；仅在 `LOCAL_MOCK` 的 feature flag 允许时演示批准。
4. 模拟 Worker claim→leased→running→succeeded 或 fails→reconcile；任务详情的 Attempts/Events/Artifacts tab 随后更新。
5. 模拟 Mac 断线 / US 新 API 不可用：UI 显示 OFFLINE/STALE，缓存只读，不自动变成第二写主控；网络恢复后事件/游标补齐。
6. 模拟 401、403、404、409、503：合理错误/无权显示，不漏出 object id 的敏感信息，不误标成功。
7. 手动验证所有 22 模板；P2/P3 页面未获真实授权时保持 MOCK/UNAVAILABLE，不触发旧 API 或新增远程能力。

必要 Mock fixtures 只能来源于 GLM 共享 schema，不要用 UI 自造字段。`/events` SSE 与 `/events/history` JSON 实现不同客户端；SSE 降级轮询需节流与 backoff。

## 七、技术选型和文件组织（可等价实现但要说明）

- 推荐 React + TypeScript + Vite + Router + TanStack Query + CSS variables/轻组件库（按现有仓库技术栈优先，不必重构）；MSW mock fixtures；Vitest/Testing Library 单测；Playwright E2E + 截图。选择复杂图形/动画库时优先轻量，避免 WebGL 常驻造成额外资源开销。
- 模块化目录：`src/app/`, `src/layout/`, `src/components/`, `src/features/{dashboard,tasks,...}`, `src/api/generated/`, `src/api/client.ts`, `src/mocks/`, `src/styles/tokens.css`, `e2e/`, `tests/`。核心契约驱动 hooks 要可替换 Mock 与新本地 API。
- CI 要执行：`typecheck`, `lint`, `unit`, `contract-sha-check`, `build`, `e2e`；不把 E2E 红的页面直接标完成。E2E 服务器全绑定 `127.0.0.1`。

## 八、交付验收：一次性完整做到本地 RC

- 所有 22 模板可访问，15 功能页每页至少 1 主要交互；4 详情页正确读取目标实体，无权/404/stale 有分支；完整本地模拟任务链可 E2E 走通。
- 自动化覆盖 1600/1280/768/390 + reduced-motion，报告渲染 screenshot 和布局回归；空/加载/错/过期/断线/拒权/Mock 标签，不能靠颜色 alone。
- OpenAPI `41 paths / 43 operations` 一致，`CONTRACT-LOCK.json` 的 SHA 与 SDK 的生成输入一致；单测可从 fixtures 验证每个 path、字段和成功/失败例子。
- `V2 Motion` 主视图继承且不卡顿，V1/Prism 哈希保留；不出现“登录真实 API”“调用旧服务”等越界能力。
- 实际来源状态 `LIVE` 仅在 GLM 新本地 API 且确有有效观测证据时展示；old/mock source 不提升为 LIVE。
- 完成后同一 clean HEAD 生成 `RC-04-FRONTEND-SOURCE.zip`（白名单脱敏源码）、`RC-05-FRONTEND-E2E.zip`（测试日志、截图、类型检查、构建结果）、前后端 `RC-06-INTEGRATION.zip` 的前端部分、`RC-FRONTEND-MANIFEST.sha256`。上传原私有 Drive「待完成」并**下载回读 SHA-256/bytes**；不覆盖历史。
- 最终提交：所有页面状态表（implemented/tested/deployed/approved），每项所依赖 API / contract SHA / Mock/真实来源标识；若 GLM 后端接口还没 ready，先利用**相同 contract** 的 MSW 做完页面，不要因此停工，也不要宣称联调已完成。

**用户授权的是“一次性做完本地前端及联调”，不是允许接入现有生产业务。** 你可以在允许的本地代码范围内自测、自修复并持续完成全站，不需要用户逐页确认；若遇真正越界需审批的动作，就跳过该外部操作并给 Gate 清单，继续完成其它部分。
