# 页面状态与依赖

全部 API 为 /api/v1 前缀；全部新页面本次只验收合成 Mock。旧字段无统一 provenance 时明确 UNKNOWN；不推断 LIVE。统一候选 SHA：e4194aa3d00dd1dca300010d7dc85e94b3d9da0a07a25c3fc977b092677cd1fa。

| 页面 | 路由 | API | 主要交互 | IMPLEMENTED | TESTED | DEPLOYED | APPROVED |
|---|---|---|---|---|---|---|---|
| 首页 | `/` | dashboard/summary, ui/bootstrap | 场景/暂停/速度/缩放 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 总控 | `/dashboard` | dashboard/summary | 刷新与详情导航 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 任务 | `/tasks` | tasks, work-items | 创建/筛选/分页/取消 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 审批 | `/approvals` | approvals, tasks, audit | 二次确认/批准/拒绝 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 节点 | `/nodes` | nodes | 搜索/筛选/详情 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 服务 | `/services` | resources | kind=service 本地筛选/详情 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 观测 | `/observability` | events/history, events SSE | 时间范围/降级轮询 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| Agent | `/agents` | agents, capabilities | 筛选/详情 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 工作流 | `/workflows` | workflows | 只读排序/详情 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 网络 | `/network` | network/links | 场景/只读详情 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 模型 | `/models` | models | 分通道目录/筛选 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 项目 | `/projects` | projects | 搜索/详情 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 集成 | `/integrations` | integrations, ui/bootstrap | 授权目录/筛选 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 计算 | `/compute` | compute/runs | UNAVAILABLE 详情 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 产物 | `/artifacts` | artifacts | URI/sha 只读详情 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 知识 | `/knowledge` | knowledge | UNAVAILABLE 详情 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 任务详情 | `/tasks/:id` | tasks/{id}, tasks/{id}/events, tasks/{id}/attempts, approvals, artifacts | 五 tabs/时间线/取消 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 节点详情 | `/nodes/:id` | nodes/{id}, resources, network/links, events/history | 五 tabs | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| 服务详情 | `/services/:id` | resources/{id}, observations, audit | kind 校验/五 tabs | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| Agent 详情 | `/agents/:id` | agents/{id}, capabilities | 五 tabs | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| V1 历史 | `/versions/v1.0` | 无新 API | 原页自有交互/字节保留 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |
| Prism 历史 | `/versions/v2.0-prism` | 无新 API | 原页自有交互/字节保留 | YES | MOCK + actual loopback E2E, 4 sizes | NO | LOCAL ONLY |

最终锁和本地新API已联调；真实外部身份/来源、缺少来源的关联字段、PG 和生产部署均未验收。缺字段的详情 tab 明示 UNKNOWN；不是已实现真实运行期数据。测试截图不是像素设计基准。
