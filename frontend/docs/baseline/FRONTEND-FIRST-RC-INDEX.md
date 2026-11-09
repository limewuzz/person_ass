> 本文件记录首轮 ea71dfc 交付。后续已收到 GLM 最终锁；当前状态与新增失败见 GLM-RC-INDEPENDENT-REVIEW.md，原缺锁描述为历史状态。

# MagicWorkshop frontend evidence index

交付性质：前端 LOCAL MOCK RC。全部 22 种模板已实现；四尺寸路由/交互、任务成功/失败/对账/取消、错误/权限/过期/离线、基本 WCAG 自动化见 RC-05。并非联合前后端 RC 验收通过。

统一候选 SHA：`18b42a97b3f975fcbe9a0326a1374d56fa547268e6fdefd18dc9cb529e8f7a25`，41/43；没有 GLM 最终锁。目录 source_meta/data_mode 与 freshness 独立；缺失来源显示 MOCK/UNKNOWN/UNAVAILABLE。清单逐页见 PAGE-STATUS.md。

| 交付 | 内容 | 复核 |
|---|---|---|
| RC-04-FRONTEND-SOURCE.zip | 干净 Git HEAD 白名单源码、锁依赖、原版历史 HTML、生成 SDK、测试与文档 | git archive；source-head.txt；npm ci |
| RC-05-FRONTEND-E2E.zip | 最终同 HEAD 的 typecheck/lint/unit/build/SHA/E2E 日志、JUnit、截图和浏览器报告 | release-run.json 记录 HEAD/exit codes；scripts/verify-release.mjs 可复现 |
| RC-06-INTEGRATION-FRONTEND.zip | 前端集成入口、候选契约与生成锁、变更请求、合成 HTTP 路径状态交换 | 明示 MSW_SYNTHETIC_NOT_GLM_INTEGRATION，不是 GLM 实际接口证据 |
| RC-FRONTEND-MANIFEST.sha256 / RC-FRONTEND-FILE-SIZES.csv | 三个 ZIP 校验与字节 | Drive 逐件下载回读 |

单元测试验证未改候选 JSON Schema 的目录/列表/详情/错误 fixture，POST 账本语义、Worker 浏览器角色拒绝、幂等100次与非法跳转。真实后端 Worker 认证、PG 原子事务、R10/R11 后端测试未在前端重复执行，不冒称通过。

E2E 是合成数据；MSW 进程内 ledger 在整页重载时重置。全站截图覆盖 1600/1280/768/390；有 overflow 断言、基本 WCAG 扫描和 reduced-motion 检查，没有设计像素基准与跨浏览器认证。测试执行环境为本次 Linux Chromium，不冒称用户 Mac/手机实机通过。

静态构建体积见 check.log，不等于美国主控 RAM 验证。未运行真实 PG、Docker、TLS、OIDC、生产探针或部署。外部 Gate 见 RC-07-SECURITY-AND-GATES.md。CI 工作流已准备，远端 CI NOT RUN。
