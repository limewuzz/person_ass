#!/bin/bash
# PG v4.1 角色初始化（R5-D1/D3 修复：先建角色后授权；密码只经 stdin，绝不进 argv/环境展开）
# 由官方镜像 docker-entrypoint-initdb.d 在首次空卷初始化时执行一次（bootstrap 超级用户）。
set -euo pipefail
: "${POSTGRES_USER:=mwcp_bootstrap}" "${POSTGRES_DB:=control_plane}"
APP_PW="$(cat /run/secrets/mwcp_pg_app_password)"
MIG_PW="$(cat /run/secrets/mwcp_pg_migrator_password)"
trap 'unset APP_PW MIG_PW' EXIT

sql_escape() { printf '%s' "$1" | sed "s/'/''/g"; }

# 密码经 heredoc → psql stdin（进程参数/日志/环境展开文本中均不出现明文）
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
-- Bootstrap installs trusted extension before losing login. Migrator need not
-- receive database CREATE just to run 0001's CREATE EXTENSION IF NOT EXISTS.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE control_plane FROM PUBLIC;
-- ── 第 1 步（R5-D1）：先完整创建两个角色 ──
CREATE ROLE mwcp_migrator LOGIN PASSWORD '$(sql_escape "$MIG_PW")'
  NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE mwcp_app LOGIN PASSWORD '$(sql_escape "$APP_PW")'
  NOSUPERUSER NOCREATEDB NOCREATEROLE;

-- ── 第 2 步：基础授权 ──
GRANT CONNECT ON DATABASE control_plane TO mwcp_migrator, mwcp_app;
GRANT USAGE ON SCHEMA public TO mwcp_app;
GRANT USAGE, CREATE ON SCHEMA public TO mwcp_migrator;

-- ── 第 3 步：默认权限（此时 mwcp_app 已存在，语句合法）──
ALTER DEFAULT PRIVILEGES FOR ROLE mwcp_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO mwcp_app;
ALTER DEFAULT PRIVILEGES FOR ROLE mwcp_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO mwcp_app;

-- ── 第 4 步：bootstrap 立即降权 ──
ALTER ROLE mwcp_bootstrap NOLOGIN;
EOSQL
echo "[00-init-roles] roles ready (mwcp_migrator DDL / mwcp_app DML / bootstrap NOLOGIN)"
