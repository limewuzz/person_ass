# MagicWorkshop V2 → GLM 部署工程交接

状态：本地源码整改与验收；**DEPLOYMENT_BLOCKED / DEPLOYED=NO / PG_RUNTIME=NOT_RUN**。不授权生产变更。

## 版本与交付身份

仓库：https://github.com/limewuzz/person_ass 。修复分支：`fix/v2-gate-b-readiness`，PR 目标：`v0.1_personal`；不修改 main，不强推。最终 commit/tree、契约 SHA、测试结果在交付包的 `RELEASE-IDENTITY.json`、`MANIFEST.json` 与 `integrated-release.json` 中由干净 Git HEAD 自动生成。

源自已验证 Drive V2 包（230 文件，tree `24ac3b87b5b4f2c51ea4e859f5d349fc4e1ea2e3`），导入提交 `1c3fc76` 的父提交是正式已合并 `ae654d4`。V2 原交接宣称 ccd867c2ee40，本轮只独立证明原包 tree，不伪造远端不存在的原提交历史。旧 GLM 16 份历史文档字节、全部原路径及 V1/Prism 历史资源由检查脚本保留。

活动契约：`contracts/openapi.yaml`，2.0.0-unified-v2，**79 paths / 95 operations**，SHA `d94462c44cd7c331470fc79731da29a7539d78f770b52288fce590ae3f52504f`。本轮不改其字节。1.1.1 原 41/43 操作和 schema 属性兼容保留；历史 contracts/baseline 不作为当前契约。

## 目录与拓扑

```text
frontend/                 React/Vite 页面、SDK、MSW、BFF及浏览器测试
backend/                  FastAPI、Registry/Task/Approval/Worker、七个 V2 工作流
  durable_state.py        有界 JSON codec、PG 请求事务/行锁/CAS/失败恢复
  pg_runtime.py           隔离 Gate B 专用 PG ASGI factory
contracts/                唯一 OpenAPI、锁、schema、历史证据
 dbpg/migrations/         0001–0005 前向迁移（真实 PG 尚未执行）
 dbpg/rollback/           对应逆向 SQL，仅可销毁的实验 DB
 dbpg/repository.py       规范化仓储接口；非当前 API runtime 的第二权威
 deploy/postgres/         新 Gate B compose、初始化与权限脚本；旧 proposal 保留
scripts/                  统一命令、秘密扫描、打包、备份加密及显式 Gate B 工具
docs/                     历史记录、当前修复说明、部署手册
```

本地开发：浏览器→127.0.0.1:5174 静态/Vite→127.0.0.1:8128 同源 BFF→127.0.0.1:8127 FastAPI。合成 Worker 仅处理新本地账本的 local.simulate，不调用真实 Worker。纯 MSW 演示端口5173。端口已占用即停止新启动，不杀旧进程。

Gate B：internal 网络内独立 PG + API，PG无宿主端口，API只发布127.0.0.1:8129；约定角色 mwcp_migrator/mwcp_app，库 control_plane。见 [V2 Gate B 执行手册](GATE-B-V2-EXECUTION.md)。生产反向代理/TLS/真实身份不在本轮操作范围。

## 运行依赖与统一命令

Python3.12；Node24；Linux/macOS 开发；浏览器测试需 Chromium。`backend/requirements.lock` 为本地锁；隔离 PG 镜像用 `backend/requirements-postgres.lock`（psycopg3.3.8）。备份工具另需 OpenSSL；授权 Gate B 需 Docker Compose v2、PG16客户端、pgbench。无 Redis/Loki/Prometheus/Kubernetes。

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

完整 test 要求干净 Git，包含正反序后端、PG离线、BFF、类型/lint/Vitest/build、Mock/回环浏览器、/app前缀及HTTPS session候选测试。报告仅证明相应本地范围，不能代替PG运行或生产证据。

前端优先静态产物，常驻API/BFF按实际身份方案选择。HTTPS现有cookie站点候选构建：

```sh
MW_PUBLIC_ORIGIN=https://REPLACE_WITH_APPROVED_HOST node scripts/mw.mjs build-session
```

默认只读；未经服务端验证不得设 MW_SESSION_WRITES=enabled。前端session写使用X-MW-CSRF（新后端兼容旧X-CSRF-Token），从可读CSRF Cookie取值；身份Cookie仍HttpOnly/Secure/SameSite Strict；服务端核对Origin。不能把本地临时身份升级成OIDC。

## PG、迁移、恢复与备份

[当前 Gate B 手册](GATE-B-V2-EXECUTION.md) 为唯一当前操作方案，覆盖0001–0005、逆序销毁、角色权限、E1–E16和新脚本。当前 API 持久权威为有64MiB上限、codec=1的PG runtime_state检查点。API请求按行锁和revisionCAS串行、事务提交后才响应；Provider密钥、JWT签名密钥、浏览器session不进入检查点，重启session失效。规范化表仓储不得与检查点混作两套权威。

`schema_migrations`版本及checksum必须完全匹配，否则PG API拒绝启动；应用不自动迁移。0005新增Outbox缺列和运行态检查点，不改写旧迁移。应用角色无DDL/建角色/建库权限，版本表只读；bootstrap预装pgcrypto后NOLOGIN。秘密按实际消费者UID以0600文件注入，不能通过chmod644解决读取问题。

备份采用pg_dump一致快照及独立AES-256-CBC/PBKDF2+HMAC认证封装；验签后解密，拒绝覆盖，篡改不产生恢复输出。角色重建、全新卷恢复、重启恢复、密钥保管/异机留存都必须真实验证，源码ZIP不是数据库备份。

## 健康、日志与环境变量

`/api/v1/health/live`200表示进程可用；`/api/v1/health/ready`在生产依赖未满足时503，包含实际database/probes/auth/workers状态。不能以PG的pg_isready替代API readiness，更不能为过关硬改200。

本地日志`.runtime/local.log`，进程身份`.runtime/local.json`；报告`frontend/evidence/release/`等，均被Git/Vite watch排除。生产应使用有界脱敏结构日志及轮转，不打印认证头、Cookie、密码、key或完整DSN。

占位环境模板：`deploy/local.env.example`、`deploy/gateb.env.example`。只填写路径/端口/身份模式，秘密内容不进.env或仓库。HTTPS外部Origin须精确配置MWCP_PUBLIC_ORIGIN；隔离PG通过MWCP_DB_HOST=mwcp-gateb-pg及文件秘密配置。不要复用聊天中暴露的凭据。

## 候选启动、升级、回滚

1. 先冻结源码commit/tree和构建manifest，在新的版本目录/镜像构建、验签及测试；不覆盖当前业务目录。
2. Gate B获批后在新网络/卷迁移，API匿名拒绝和真实持久化/恢复/权限/备份/资源全通过后记录结果。
3. 生产另获批准后，由GLM确定真实身份、TLS、BFF/静态服务及宿主隔离，验证健康后才切流；本轮无切流命令。
4. 升级前做可恢复备份，确认schema前后兼容；部署新版本并保留旧不可变产物。失败停止切换并恢复先前版本，不能把旧代码直接指向不兼容schema。
5. 数据回滚必须按已验证恢复方案；破坏性down仅供可销毁实验数据库，不是生产回滚。清理只针对核对过身份的mwcp-gateb资源，不执行docker prune或模糊匹配kill/rm。

## GLM接手验收与生产阻断

核对manifest→重建SDK/前端→完整本地test→查看V2整改记录→另获授权→逐项执行E1–E16并回传原始脱敏证据。每项记录时间、commit、目标身份、退出码、schema/CAS断言、内存/CPU/磁盘峰值和未执行项。

仍阻断生产：真实PG/API事务与CAS及故障恢复、备份恢复、生产session/OIDC/TLS、可信插件签名和真实Worker/探针策略、美国宿主容量与旧业务隔离。6核/11GiB机器、新主控1.5GiB目标/初期2GiB预留均是规划，不是实测结论。模型推理和重型执行不放主控。

Cherry Studio只保留静态外链；不iframe/代理/预取；Rakazo/8765/生产DB/反代/定时任务、美国旧业务、腾讯/UCloud现有业务、真实Worker/探针和凭据轮换本轮均未操作。
