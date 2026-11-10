# PG v4 角色权限预期矩阵（静态设计；隔离环境演练前全部 NOT RUN）

| 账户 | SUPERUSER | CREATEDB | CREATEROLE | CONNECT db | SCHEMA public | 表 DML | 表 DDL | 序列 |
|---|---|---|---|---|---|---|---|---|
| mwcp_bootstrap | 是（镜像引导）* | 是* | 是* | ✓ | ✓ | ✓ | ✓ | ✓ |（* 首启末尾 ALTER ROLE NOLOGIN 收口） |
| mwcp_migrator | 否 | 否 | 否 | ✓ | USAGE+**CREATE** | ✓(自有对象) | ✓ | ✓ |
| mwcp_app | 否 | 否 | 否 | ✓ | USAGE | **SELECT/INSERT/UPDATE/DELETE** | ✗（CREATE/DROP/ALTER 均拒） | USAGE+SELECT |

默认权限链：migrator 建表时自动向 app 下发 DML（00-init-roles.sh ALTER DEFAULT PRIVILEGES）。
反例清单见 perm-negative-tests.sql（执行于授权隔离环境后回填实际错误码——当前 NOT RUN）。
readiness 定义（R4 A2 修正）：容器 healthcheck=pg_isready（进程级）；**应用 ready = mwcp_app
连接成功 + SELECT 1 + schema_migrations 版本匹配**（项目自带 MigrationRunner，非 Alembic），由 API /health/ready 的 database 依赖实现（P1-03）。
