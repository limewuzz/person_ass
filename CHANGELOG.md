# Changelog

本文件记录 MagicWorkshop 各版本分支的关键变更。格式遵循 Keep a Changelog；版本号与 GitHub 分支一一对应。

## [v2.0.1] - 2026-11-10

修复 V2 Gate B 独立审查列出的全部部署阻断项（DEPLOYMENT_BLOCKED → 可进入 Gate B 候选）。分支：`v2.0.1`（基于 `debug/v2.0.0-gate-b`）。

### Fixed
- PostgreSQL 模式下 API 业务读写不再静默走内存：`postgres_pending` fail-closed，未连真实 PG 时启动即拒绝；新增 `durable_state.py` / `pg_runtime.py` 与中间件绑定（`backend/app.py`）。
- Outbox 仓储引用的两列在迁移中不存在：新增 `dbpg/migrations/0005_runtime_persistence.sql`，补齐 `outbox.claim_token`、`outbox.next_retry_at` 及重试索引。
- `backend/Dockerfile.api` 漏装 API 启动所需模块：改为整包拷贝 `backend/ dbpg/ contracts/ scripts/`，并安装 `requirements-postgres.lock`。
- 前后端 CSRF 请求头不一致导致会话写操作 403：后端同时接受 `X-MW-CSRF` 与 `X-CSRF-Token`，改用 `hmac.compare_digest` 并校验 Origin（`backend/app.py`）。
- 包内 Gate B 方案停留在旧迁移范围：新增 `docs/GATE-B-V2-EXECUTION.md`（0001→0005 全量迁移、逐条校验），旧 `GATE-B-EXECUTION-PLAN.md` 归档至 `docs/archive/`；`deploy/postgres/perm-negative-tests.sql` 重写，`perm-matrix.md` 的 readiness 口径改为 `schema_migrations`（项目自带 MigrationRunner，非 Alembic）。
- `docs/r4_contract_check.py` 断言对齐 V2 契约锁定值 79 paths / 95 operations（原为 RC 1.1 的 41/43）。
- CI（`.github/workflows/unified-local-rc.yml`）覆盖 `v2.0.0` / `v2.0.1` / `debug/**` 分支。

### 验证
- 后端 + dbpg 离线 + BFF 回环：254 passed（正/反序）。
- 前端：tsc、eslint、34 个 vitest 单测、生产构建、契约 SHA 校验全部通过。
- PG 真实运行与生产部署仍为 NOT_RUN / DEPLOYMENT_BLOCKED，须经用户单独授权 Gate B。

## [v2.0.0] - 2026-11-10

V2 全栈统一交接快照。分支：`v2.0.0`（提交 `1c3fc76`，Git Tree `24ac3b87b5b4f2c51ea4e859f5d349fc4e1ea2e3`，与 Google Drive 交接包一致）。

### Added
- 七条同步工作流全模块实现：平台核心、AI 基础设施、Agent 系统、算力资源/Worker 中心、多端客户端同步、数据集成、契约总控与交接验签。
- 统一契约 `contracts/openapi.yaml` 2.0.0-unified-v2：79 paths / 95 operations（完整保留 1.1.1 的 41/43），SHA-256 `d94462c4…3f52504f`。
- 本地复现：后端 + PG 离线正/反序 228 passed ×2、BFF 回环 18 passed、前端单测 22 passed；契约路由覆盖 0 missing / 0 unexpected。
- 状态标注：DEPLOYED=NO / PG_RUNTIME=NOT_RUN / APPROVED=LOCAL_ONLY。

## [v1.1.1] - 2026-11-09（Local RC，分支 `integration/local-rc-1.1.1`）

- 契约 1.1 冻结 41 paths / 43 operations；R4–R11 独立审查轮次（注册表一致性、权限负向、探针、密钥轮换等）全部闭环。
- Phase A 数据库核心整改：DI 容器（fail-closed PG 开关）、迁移原子性（advisory lock + 校验和）、Registry ABA 防护、Outbox 领取/确认/退避/死信（at-least-once）。
- 本地 156+ 项测试全绿，契约不变。

## [v0.1_personal] - 2026-11-10（分支 `v0.1_personal`）

- 个人助手初始版本：HTTPS 会话前端构建与部署预检、本地验收与 GLM 交接材料。

## 说明

- 生产部署、真实 PostgreSQL 运行、真实节点探针/生产 OIDC/TLS 等仍是独立 Gate，未经用户单独授权不得执行；详见 `docs/GATE-B-V2-EXECUTION.md` 与 `docs/GLM-DEPLOYMENT-HANDOFF.md`。
- 详细审查记录见各版本分支下的 `docs/`（R4–R10、RC-REPRO、RC-JOINT 系列）。
