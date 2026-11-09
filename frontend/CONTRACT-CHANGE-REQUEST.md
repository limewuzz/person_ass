# Contract issues resolved in isolated local integration

用户已明确授权修复独立后端副本。原GLM包不变；原契约归档。当前两仓库共享1.1.1、41/43、SHA e4194aa3d00dd1dca300010d7dc85e94b3d9da0a07a25c3fc977b092677cd1fa。

| 原问题 | 当前处理 |
|---|---|
| Task头部幂等键被忽略，重放不一致 | 读取Idempotency-Key，完整请求指纹与actor绑定；首次/重放同202 TaskAccepted；100 HTTP并发只建一条/一审批 |
| bootstrap/NodeList/source_meta/枚举/UUID不合契约 | 实现原承诺字段与格式；实际43操作响应逐项按共享schema校验 |
| 审批到期写成创建时刻、参数上下文缺失 | 真实expires_at；兼容追加请求者、scope、目标/代数、脱敏参数；过期/篡改/取消失效 |
| Worker过滤、审批消费与产物链缺口 | 广告/请求能力交集、JWT身份/范围、原子审批消费、lease/generation CAS；真实内存产物digest，不假装Drive下载 |
| 最终revision读取之后的Registry竞态 | 公开字段不可写；所有受控写与观察提交共享锁；owner变更清旧观测；generation覆盖ABA与删除重建 |
| readiness真实503未声明 | 兼容追加503/Error和ReadinessStatus；保持not_ready/PG not_connected，不改成假200 |
| 浏览器JWT/SSE鉴权不完整 | 同源HttpOnly演示session+CSRF；JWT仅服务端；audit命名事件及Last-Event-ID；无MSW成功兜底 |

当前仍缺真实来源的dependencies/logs/runtime等不编造字段或新API，页面明确UNKNOWN。真实外部集成、PG运行、生产身份与部署不是本次授权内容。历史最小补丁和失败证据在integration/baseline、docs/baseline；它们已被完整修复分支取代，勿应用到当前源码。
