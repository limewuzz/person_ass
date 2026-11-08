# R4-04 · PG v4 提案（未部署）

**状态：PROPOSAL v4 / NOT DEPLOYED / 静态与本地单测为限**。v4 = v3 拓扑不变，修复 R4-A2 逐项真实阻断。
文件：`deploy/postgres/compose-v4.yml.proposal`、`init/00-init-roles.sh`（可执行）、`perm-matrix.md`、`perm-negative-tests.sql`、`backend/Dockerfile.api`、`build/entrypoint.sh`。

## 1. A2 阻断项逐条修复对照

| R4-A2 指出 | v4 修复 | 证据文件 |
|---|---|---|
| init-roles.sql 无可执行密码设置；PASSWORD_FILE 只管 bootstrap | 改 **.sh 初始化**：`cat /run/secrets/*` → psql `:变量` 注入 CREATE ROLE PASSWORD；密码不进参数表/日志（trap unset） | init/00-init-roles.sh |
| migrator 建对象权限/所有权/默认权限不明 | 显式：`GRANT USAGE,CREATE ON SCHEMA public` + `ALTER DEFAULT PRIVILEGES`（建表自动向 app 下发 DML）；所有权=migrator | init/00-init-roles.sh + perm-matrix.md |
| app 能否 DML 而不能 DDL 未证 | 预期矩阵 + 反例 SQL（CREATE TABLE/DROP TABLE/CREATE ROLE 应全部 denied）——**静态 NOT RUN，待授权隔离环境回填实际错误码** | perm-matrix.md + perm-negative-tests.sql |
| pg_isready 冒充认证证明 | healthcheck 改回 bootstrap 用户并注释「仅进程存活」；**应用 ready 定义 = mwcp_app SELECT 1 + alembic_version 核对**（P1-03 实现，/health/ready 的 database 依赖） | compose-v4 + perm-matrix.md |
| 回环可达性不能由 YAML 推断 | 保留为部署 Gate 第 5 步（目标 Docker 版本实测，含非回环拒绝验证）；PROPOSAL 不宣称已验 | §6 Gate |
| 备份顺序/globals 保护/密钥解封/down -v | 沿用 v3 §4 SOP（globals 先行→建库→pg_restore --exit-on-error→抽测→故障注入）；globals 备份同级加密；解封口令独立于加密密钥；`down -v` 红标为数据销毁、单独审批 | PROPOSAL.md v3 §4（仍有效） |
| 连接数/资源/OOM | max_connections=20、shm 256m、640m 限额 + **pgbench 只在批准隔离环境**（未压测，无数据，不宣称） | compose-v4 + §6 |
| mock HS256 ≠ 生产 OIDC | README/代码/文档统一「Mock JWT 验证」标注；生产 OIDC=独立验收（不变） | — |

## 2. 密钥管理（v4 强化）

- 4 个 secret 文件（bootstrap/migrator/app 口令 + JWT kid 表）只存在于部署机 `deploy/postgres/secrets/`（600, root, .gitignore 排除）。
- **bootstrap 首启即 NOLOGIN**（不等 SOP 末步）；灾难恢复路径=宿主 root `docker exec` + 单用户模式（记录于 Gate）。
- entrypoint.sh：口令从 /run/secrets 读入 → Python URL 转义拼 DSN → 临时 env 文件（600）source 后立即删除；uvicorn 明文访问日志关闭（走结构化脱敏审计）。
- 静态校验：`docker compose -f compose-v4.yml.proposal -p mwcp config --quiet`；起容器后 `docker inspect` 双容器 Env 断言无口令/DSN。

## 3. 已知未决（如实）

1. perm-negative-tests：**NOT RUN**（无授权隔离环境）；回填前权限结论仅为「静态设计」。
2. pgbench：**未执行**；资源参数（640m/20conn/2M work_mem）未经压测证实。
3. 回环发布可达性：目标 Docker 版本未实测。
4. Alembic：迁移脚本未写（P1-03）；001_control_plane.sql 转译待做。
5. mwcp-edge（API 出网探针网）：不存在；未来独立审批。
