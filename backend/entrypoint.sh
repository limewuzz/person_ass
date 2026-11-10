#!/bin/sh
# mwcp-api 入口（R5-D4 修复：secret 只走文件；无临时明文文件；变量正确 export）
set -eu
SECRETS_DIR="${MWCP_SECRETS_DIR:-/run/secrets}"
fail() { echo "[entrypoint] $1" >&2; exit 1; }
for f in mwcp_pg_app_password mwcp_auth_secrets; do
  [ -f "$SECRETS_DIR/$f" ] || fail "missing secret $f"
done
# 只传文件路径；DSN 由应用进程内自行拼装（app 启动时读文件，不落任何明文中间文件）
export MWCP_SECRETS_DIR
export MWCP_AUTH_SECRETS_FILE="$SECRETS_DIR/mwcp_auth_secrets"
export MWCP_PG_APP_PASSWORD_FILE="$SECRETS_DIR/mwcp_pg_app_password"
if [ "${MWCP_REPOSITORY:-memory}" = "postgres" ]; then
  set -- pg_runtime:create_app --factory
else
  set -- app:app
fi
exec python -m uvicorn "$@" \
  --host "${MWCP_LISTEN_HOST:-0.0.0.0}" --port "${MWCP_LISTEN_PORT:-8123}" \
  --no-access-log  # 访问日志走结构化脱敏审计
