# GLM RC 独立联调审查

源码 ZIP SHA-256 350c36e8dc405ec886615fc1c64100420495236927a6d92db1c593ac807f015a；声明提交 f13d6e52ce3b7e021ed982225a41caad2ae2571e。最终 YAML 与前端 SDK SHA 一致，均为 18b42a97b3f975fcbe9a0326a1374d56fa547268e6fdefd18dc9cb529e8f7a25。

原后端156项回归独立复跑通过；追加按锁定 schema/format 校验35项，11通过、24失败。不是生产故障或外部探测；全用本地 ASGI 与合成数据。

| 操作/检查 | 实际状态 | 契约问题 |
|---|---|---|
| get /api/v1/health/live | 200 | /:required |
| get /api/v1/health/ready | 503 | /status:declared_status |
| get /api/v1/me | 200 | /:required |
| get /api/v1/resources | 200 | /items/0/generation:minimum, /items/0/lifecycle_state:enum, /items/1/generation:minimum, /items/1/lifecycle_state:enum, /items/2/generation:minimum, /items/2/lifecycle_state:enum, /items/3/generation:minimum, /items/3/lifecycle_state:enum, /items/4/generation:minimum, /items/4/lifecycle_state:enum, /items/5/generation:minimum, /items/5/lifecycle_state:enum, /items/6/generation:minimum, /items/6/lifecycle_state:enum, /items/7/generation:minimum, /items/7/lifecycle_state:enum, /items/8/generation: |
| get /api/v1/services | 200 | /items/0/generation:minimum, /items/0/lifecycle_state:enum, /items/1/generation:minimum, /items/1/lifecycle_state:enum, /items/2/generation:minimum, /items/2/lifecycle_state:enum, /items/3/generation:minimum, /items/3/lifecycle_state:enum, /items/4/generation:minimum, /items/4/lifecycle_state:enum, /items/5/generation:minimum, /items/5/lifecycle_state:enum, /items/6/generation:minimum, /items/6/lifecycle_state:enum, /items/7/generation:minimum, /items/7/lifecycle_state:enum, /items/8/generation: |
| get /api/v1/integrations | 200 | /items/0/status:enum, /items/1/status:enum |
| get /api/v1/ui/bootstrap | 200 | /app_mode:enum, /features/cherry_links/status:enum, /features/approvals/status:enum, /features/real_probes/status:enum, /features/tasks/status:enum, /features/workers/status:enum, /features/production_db/status:enum, /features/production_db/min_phase:enum, /source_meta:required, /:required |
| get /api/v1/dashboard/summary | 200 | /nodes:type, /source_meta:required |
| get /api/v1/events/history | 200 | /source_meta:required |
| get /api/v1/workflows | 200 | /items/0/source_meta:required, /items/1/source_meta:required, /source_meta:required |
| get /api/v1/network/links | 200 | /items/0/source_meta:required, /items/1/source_meta:required, /items/2/source_meta:required, /source_meta:required |
| get /api/v1/models | 200 | /items/0/source_meta:required, /items/1/source_meta:required, /items/2/source_meta:required, /source_meta:required |
| get /api/v1/projects | 200 | /items/0/source_meta:required, /items/1/source_meta:required, /items/2/source_meta:required, /source_meta:required |
| get /api/v1/compute/runs | 200 | /items/0/source_system:type, /items/0/source_meta:required, /items/1/source_meta:required, /source_meta:required |
| get /api/v1/knowledge | 200 | /items/0/source_meta:required, /items/1/source_system:type, /items/1/source_meta:required, /source_meta:required |
| get /api/v1/resources/{id} | 200 | /generation:minimum, /lifecycle_state:enum |
| post /api/v1/work-items | 200 | /status:declared_status |
| post /api/v1/tasks | 201 | /status:declared_status |
| post /api/v1/tasks | 201 | /status:declared_status |
| CHECK header_idempotency_replay | FAIL | 同一 Idempotency-Key 头、相同 payload 创建两个 task |
| get /api/v1/tasks/{id} | 200 | /id:format, /work_item_id:anyOf |
| get /api/v1/tasks/{id}/events | 200 | /items/0/id:format, /items/0/task_id:format |
| get /api/v1/tasks/{id}/attempts | 200 | /:required |
| post /api/v1/tasks/{id}/cancel | 200 | /status:declared_status |

## 阻断项

1. tasks POST 忽略契约 Idempotency-Key header，改读未定义 body.idempotency_key；相同请求重复创建。首次201/重放200不符合202 TaskAccepted。
2. bootstrap app_mode/local-rc、login、FeatureState enabled/disabled、source_meta.kind 均非锁定字段/枚举；dashboard.nodes 是数组，锁定为 NodeList。
3. UUID字段带 wi-/tk-/ap-/te-前缀；attempt缺 state/source_meta/next_cursor，approval state小写。
4. approval expires_at_iso写创建时刻而非expires_at时间，UI按真值会立即显示过期；不得前端延长掩盖。
5. Worker claim忽略能力过滤；缺 task_id/lease_until；非幂等任务超时统一重排需复核。审批consume未接gateway，artifacts永远空。
6. 错误体缺trace_id或被HTTPException包在detail；服务optional generation=0、lifecycle小写违反契约。
7. /health/ready 503真实且应保留，但锁定YAML未定义503；需由GLM以变更流程补契约，不得伪装就绪。

## 前端已继续完成

导入最终锁与原fixtures，不修改YAML；补同源loopback BFF（HttpOnly本地演示session、CSRF、服务端ephemeral bearer）；浏览器不保存或接触JWT；SSE支持audit命名事件与Last-Event-ID代理。BFF检查响应schema，发现漂移返回503/upstream_contract_mismatch，不做字段别名或假数据填充。原GLM包与backend源码未改。

## 所需后端修订（PRD §3 owner=GLM）

先修真实实现到冻结契约：修改serializer/status/header读取与server-owned local.simulate policy；维护内部兼容不得把旧测改绿掩盖。补入JSON Schema运行期正反例与header幂等测试、完整审批/Worker/结果测试。ready503需GLM追加兼容response并重新发布锁，双方重生成SDK。

本审查与前端BFF不等于联合RC已通过；在这些问题修复前不能宣称前后端联调完成。
