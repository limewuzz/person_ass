# V2 独立审查整改记录

本轮源自 2026-11-10 的独立审查（F1–F8）。最终测试计数、commit/tree 和报告以干净源码生成的交付 manifest 为准。PG/Docker/生产均未运行；以下“修复”指源码和本地验证，不能替代 Gate B。

| 原发现 | 修复与回归依据 |
|---|---|
| F1 前端不能编译 | 修正助手组件状态/query/mutation作用域，使用实际routing-policy路径、正确SDK参数和WebCrypto输入类型；恢复完整typecheck/lint/build；增加会话/同步/上传下载浏览器流程 |
| F2 PG API绕过仓储 | 实际路由服务统一绑定容器；新增有界、白名单JSON codec + PG检查点行锁/revisionCAS事务；提交后才响应，故障回滚；测试覆盖API写入、连接/状态重建、任务/审批/lease/finish、产物字节、会话和失败不确认；真实PG尚未实测 |
| F3 Outbox缺列及无退避 | 新增0005前向迁移，不改0001–0004；补claim_token/next_retry_at，claim检查退避时间；扩大SQL/DDL列检查；真实PG验证列入Gate B |
| F4 Docker缺依赖 | COPY全部backend/dbpg/contracts，正确根目录/PYTHONPATH、固定非rootUID、单独PG依赖锁；PG factory仅允许隔离目标，缺配置/版本不启动；镜像未构建/运行 |
| F5 CSRF不兼容 | 前端X-MW-CSRF与后端一致，兼容旧X-CSRF-Token；提供Secure CSRF Cookie，身份Cookie继续HttpOnly；Origin和常量时间token校验；测试正确头/错误token/外部Origin |
| F6 前端契约测试失败 | 保留原43操作测试；新增52个V2 Mock操作的明确模拟/不可用语义与schema校验，不用旧资源详情冒充新增响应；源码生成器现在真正由OpenAPI生成SDK、全部响应操作表和Mock schema，修复手工产物漂移 |
| F7 权限测试误判 | 每个DDL负向使用独立PL/pgSQL异常子事务，仅42501视为通过；意外成功/25P02失败；bootstrap预装pgcrypto，收回PUBLIC权限；真实角色验证仍需Gate B |
| F8 过时Gate B资产 | 新隔离compose、0001–0005对应逆向SQL、显式迁移CLI、按消费者UID的0600随机文件秘密、认证备份和篡改测试、独立pgbench工作负载；完整E1–E16转到GATE-B-V2-EXECUTION.md，旧GLM文档保留不改 |

其他整改：首次PG同步补INSERT ON CONFLICT；会话消息仓储并发幂等补冲突后回读；版本文件缺失不再静默通过；Web发布清单不再把旧ZIP当成已签名V2包；统一验收/打包计数读取活动契约锁；CI覆盖fix/V2分支和PG驱动依赖检查。

插件摘要登记仍不等于密码学签名验证；只保留本地元数据流程，未增加真实插件执行。生产可信签名、OIDC/session、TLS、真实探针/Worker和宿主隔离仍是明确阻断。现有22模板、个人工作坊页面、四种视口、可访问性/reduced-motion断言均保留，未用删除测试或降低断言换取通过。

## v2.0.1 接续整合

基线 `94beaa099d38c3dbc8bc5f9f061f80e10df0b97e` 已以等价提交吸收上述全部业务修复，git cherry 核验均为等价补丁。本轮不重复导入。保留其 CI 分支覆盖、schema_migrations用语、旧Gate B文档归档和79/95核查入口；原1.1.1核查脚本以原始字节存入docs/archive，保留检查明确验证该位置。修复前缀测试仅等待静态页面、尚未等待API/BFF启动的竞态；CI原始JUnit显示匿名请求在BFF启动前得到503而不是401，现在等待真实raw live200及BFF匿名401后再运行完整原断言。

CI另发现远端main由其他开发者新增CHANGELOG（a3a0495），旧guard强制远端等于最初658e3f9，导致新分支误报。现在以git merge-base --is-ancestor严格验证最初main历史仍被保留，并记录当前远端SHA；不重置main、不忽略历史丢失。
