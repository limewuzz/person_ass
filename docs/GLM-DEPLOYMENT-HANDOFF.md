# MagicWorkshop V3 → GLM 部署工程交接

**DEPLOYMENT_BLOCKED · DEPLOYED=NO · PG_RUNTIME=NOT_RUN · EXTERNAL_CONNECTORS=NOT_VERIFIED**

仓库 https://github.com/limewuzz/person_ass ，目标分支 `v3.0`，开发分支 `feature/v3.0-fanout`。以合并后回读的 commit/tree 及交付包 `RELEASE-IDENTITY.json` 为最终源码身份。源自已合并 V2.0.1 `c17b64b4cfb3650405600a48fb0a509976ac7807`。不修改 main/v2 分支，不重写历史。原 GLM 文档及 V1/Prism 资源由 `scripts/check_baseline.py` 和 `frontend/scripts/check-design.mjs` 核验。

活动契约只在 `contracts/openapi.yaml`；版本 **3.0.0-fanout-local，89 paths /106 operations**。SHA 以 `contracts/CONTRACT-LOCK.json` 为准。V2 的完整 79/95 契约按原始 SHA d94462c44cd7c331470fc79731da29a7539d78f770b52288fce590ae3f52504f 保存在 `contracts/snapshots/v2.0.1/`，用于兼容回归，不是第二份活动契约。V3 新增 11 操作，并对两个旧入口加入显式可选的配方分支，旧调用体与响应保持兼容。SDK 由根契约生成。

## 拓扑与依赖

```text
浏览器 → 127.0.0.1:5174 静态/Vite → 127.0.0.1:8128 同源 BFF → 127.0.0.1:8127 API
                                                   ↓
                                     单 WorkItem / 合并审批 / Fanout
                                                   ↓
                           PG checkpoint + outbox 投影（同事务候选；未跑真实 PG）
                                                   ↓
                                     Mac relay（独立 worker 身份）
```

`frontend/` React/Vite、SDK、MSW、BFF 与浏览器测试；`backend/fanout/` 四配方、门禁、HMAC、租约与 SSE；`backend/durable_state.py` 有界 codec/事务/CAS；`contracts/` 契约；`dbpg/` 0001–0006 与回滚；`deploy/postgres/` 隔离 Gate B 配置；`scripts/mw_*.py` Mac relay/签名工具/可选适配器；`tests/`、`backend/tests/`、`frontend/` 保存分层验证；`docs/` 保留历史交接与当前 V3 手册。

Python 3.12、Node 24、Chromium；Linux/macOS 开发。Python/Node 锁依赖不新增第三方包。Apple Reminders 适配器仅 macOS，需要用户另行授予系统自动化权限。Gate B 后续另需 Docker Compose v2、PostgreSQL 16 客户端、pgbench、OpenSSL。无 Redis、Prometheus、Loki 或 Kubernetes。

## 构建与本地操作

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock
npm ci --prefix frontend
(cd frontend && npx playwright install chromium)
node scripts/mw.mjs contract
node scripts/mw.mjs start
node scripts/mw.mjs stop
node scripts/mw.mjs test
node scripts/mw.mjs build
node scripts/mw.mjs package
```

start/stop 使用 pid、启动时间和 nonce 识别本次进程；端口占用即拒绝，不终止既有服务。默认只绑定回环。直接 API/BFF 组合的受控启动入口为 `node frontend/scripts/start-integration.mjs`（从 frontend 目录执行 `node scripts/start-integration.mjs ../backend`）；该入口生成本地合成身份和模拟 Worker。前端生产静态候选由 `frontend/dist/` 提供；同一入口支持 `--static`。生产不得照搬本地 JWT/登录身份；正式静态服务由 GLM 配合新 BFF/API 独立配置。

健康：`/api/v1/health/live` 进程存活；`/api/v1/health/ready` 依赖不满足应返回 503，不能强制改绿。本地日志在 `.runtime/`，完整测试在 `frontend/evidence/release/`，浏览器回执与截图在 `frontend/evidence/workspace/`。日志禁止输出 JWT、HMAC、Cookie 或外部 token。

## 身份与环境模板

见 `deploy/v3/environment.example` 和 `deploy/v3/*.example.json`，均只有占位符。Webhook 配置路径 `MWCP_WEBHOOK_KEYS_FILE`；目的端授权 `MWCP_FANOUT_GRANTS_FILE`。凭据内容通过 0600 文件读取，配置文件/本地 SQLite journal 均不得提交；生产应使用 `/run/secrets`。各 HMAC key 绑定 owner/channel/recipes，checkpoint 还必须绑定 run_ids 和 24 小时内 expires_at。普通浏览器不获得 Worker 或签名密钥。

## PostgreSQL 与迁移/回滚阻断

当前 API 使用 `runtime_state` JSON checkpoint 作为领域权威，`dbpg/repository.py` 的规范化仓储不是第二个 API 权威。0006 将 codec 上限从1扩至2，增加 outbox.delivery_id 唯一键与 delivery_state。Fanout checkpoint 与 outbox 投影在一个连接事务中提交；单元测试使用可注入失败的假数据库验证回滚，**不代表真实 PostgreSQL 已接通或事务/约束已验收**。

未来 Gate B 仅在独立一次性数据库按 0001→0006 执行，使用 migrator/app/备份角色分离；app 不得 DDL/超级用户/读其他业务库。先备份 codec1 的 V2 全量数据，再升级 V3。codec2 不能被 V2 读取；0006 down 会在存在 codec2 行时明确拒绝。回退需停写并恢复升级前经过恢复验证的 V2 备份，或仅在可销毁实验库完整销毁重建；不得静默丢弃 fanout 数据、删 checkpoint 来骗过 down。

候选启动/升级 SOP：冻结新控制平面写入→备份与 SHA 验证→在隔离副本迁移→检查权限/事务/CAS/断电恢复→构建静态前端→配置生产身份/TLS/秘密文件→先只读健康检查→少量预授权目的端→核验所有回执与内存峰值。失败先停止新服务，保留证据，再按验证过的备份恢复流程回退；禁止操作旧业务进程、数据库或反代。

## Mac relay 与连接器

阅读 [V3-FANOUT.md](V3-FANOUT.md)。默认 SIMULATE，无真实平台写入。LIVE 需要用户授权、服务器端 owner/recipe/target/worker grant、命令行显式外部写开关及对应私有配置。Notion 页面、Drive 意图 JSON 归档、GitHub Issue、Mac 指定现有提醒事项列表有候选适配器，均未在真实平台试写；不承诺其生产可用性。Drive 适配器只归档提交的意图 JSON，不声称复制未读取的 PDF 或权重；回执 SHA 是描述符摘要，checkpoint 文件 SHA 是受限调用方上报，未独立下载验证。

AI 摘要、知识检索、微信发送、Colab 自动启动和代码执行尚无真实执行适配器，明确 UNAVAILABLE/对账，不会返回伪成功。可接收微信/Rakazo/Shortcuts 的 HMAC 入站标准包，但未部署机器人或修改这些平台。Cherry Studio 只允许静态外链或用户手动粘贴总结，不 iframe、代理、预取；8765 完全冻结。

## GLM 接手 Gate 清单

| Gate | 本轮状态 | GLM 后续证据 |
|---|---|---|
| 本地编排/审批/重试/租约/SSE | 以交付 JUnit/CI 为准 | 在干净源码重新运行统一 test |
| PG0001–0006与codec2运行 | NOT_RUN / BLOCKED | 迁移、角色反例、事务故障、outbox唯一约束、跨进程CAS |
| 持久化/重启/备份恢复 | 假数据库回归，真实运行未验收 | 崩溃注入、恢复前后哈希与回执不重放 |
| 真实连接器 | 未启用/未验证 | 独立测试账号、最小授权、重放与未知结果对账 |
| 生产身份/TLS/Worker与探针 | BLOCKED | OIDC/JTI持久化、TLS、受限能力与网络白名单 |
| 容量与旧业务隔离 | 未测 | 6核约11GiB主机上新控制平面1.5GiB目标/初留2GiB，测CPU/内存/磁盘峰值 |

后续 Gate B 和美国机部署必须获得用户单独授权。预算是规划目标；不放置模型推理、重型 Worker 或浏览器任务于美国主控。Cherry、Rakazo、8765、其他云业务、旧数据库、生产反代、定时任务、凭据轮换均未触碰。
