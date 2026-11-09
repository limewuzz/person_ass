# Frontend gates

- 本地前端与纯合成 Mock：本次授权范围，代码及测试见证据包。
- 原GLM锁已归档；兼容修订1.1.1由独立修复分支维护，两端同SHA。原35项中的24项失败已修复；当前通过判定只见最终机器报告。
- 实际 PG / Docker / 备份恢复 / SQL 隔离权限：NOT RUN，后端负责且需另行授权。
- 真实 TLS / OIDC / BFF 会话 / CSRF：NOT RUN。本地演示HttpOnly session/CSRF已测；不保存生产令牌。
- 生产探针、DNS pinning/SSRF、全局限流、/docs：GLM 后端 Gate，前端不通过旧服务探测补证。
- 凭据 A 事件 OPEN；本任务未读取或轮换凭据。
- 美国 1.5 GiB 目标、初期约 2 GiB 预留为设计目标；本次仅报告前端静态包大小，未验证美国机 SLA。
- Cherry Studio、Rakazo、8765、旧 DB、Caddy/nginx/frp/cron、腾讯与 UCloud 原业务零访问/零修改。浏览器网络测试只允许 loopback。
- 生产写操作默认禁用；本地按钮不代表服务端授权。真实策略、Worker token 与 IDOR 验收必须使用 GLM 测试证明。
- 生产部署、网络变更与身份接入：DEPLOYED=NO / APPROVED=NO。

回退：停止新 Vite 进程，删除隔离前端目录即可；没有改动既有服务、端口或数据库。交付保留源码、锁文件和原始历史页。
