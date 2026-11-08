#!/bin/bash
# PG v4 可执行角色初始化（R4 A2：v3 的 .sql 缺密码设置步骤）
# 由官方镜像 docker-entrypoint-initdb.d 在首次空卷初始化时执行一次（bootstrap 超级用户）。
# 密码只从 /run/secrets 文件读入 psql 变量，不进参数表/日志/渲染 Compose。
set -euo pipefail
: "${POSTGRES_USER:=mwcp_bootstrap}" "${POSTGRES_DB:=control_plane}"
APP_PW="$(cat /run/secrets/mwcp_pg_app_password)"
MIG_PW="$(cat /run/secrets/mwcp_pg_migrator_password)"
trap 'unset APP_PW MIG_PW' EXIT
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v mig_pw="$MIG_PW" -v app_pw="$APP_PW" <<'EOSQL'
-- 迁移账户：DDL（Alembic 专用；public schema 建对象权 + 默认权限下发 DML 给 app）
CREATE ROLE mwcp_migrator LOGIN PASSWORD :'mig_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE control_plane TO mwcp_migrator;
GRANT USAGE, CREATE ON SCHEMA public TO mwcp_migrator;
ALTER DEFAULT PRIVILEGES FOR ROLE mwcp_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mwcp_app;
ALTER DEFAULT PRIVILEGES FOR ROLE mwcp_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO mwcp_app;

-- 应用运行账户：仅 DML（连接级；表级由上面默认权限在迁移建表时自动下发）
CREATE ROLE mwcp_app LOGIN PASSWORD :'app_pw'
  NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE control_plane TO mwcp_app;
GRANT USAGE ON SCHEMA public TO mwcp_app;

-- bootstrap 立即降权（首启即收口，不等部署 SOP 末步）
ALTER ROLE mwcp_bootstrap NOLOGIN;
EOSQL
echo "[00-init-roles] roles ready (mwcp_migrator DDL / mwcp_app DML / bootstrap NOLOGIN)"
