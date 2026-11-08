#!/bin/sh
# mwcp-api 入口（R4 A2/BLOCK-01：口令只从 /run/secrets 文件进程内拼装，不进环境变量/日志）
set -eu
SECRETS_DIR="${MWCP_SECRETS_DIR:-/run/secrets}"

fail() { echo "[entrypoint] $1" >&2; exit 1; }
[ -f "$SECRETS_DIR/mwcp_pg_app_password" ] || fail "missing secret mwcp_pg_app_password"
[ -f "$SECRETS_DIR/mwcp_auth_secrets" ] || fail "missing secret mwcp_auth_secrets"

# DB DSN：URL 转义口令（特殊字符安全），只写进程内变量（不 export 到子 shell 日志）
python3 - <<'PY' > /tmp/.mwcp_env
import os, urllib.parse, pathlib
secrets = pathlib.Path(os.environ.get("MWCP_SECRETS_DIR", "/run/secrets"))
pw = (secrets / "mwcp_pg_app_password").read_text().strip()
user = urllib.parse.quote("mwcp_app", safe="")
pw_q = urllib.parse.quote(pw, safe="")
dsn = f"postgresql://{user}:{pw_q}@mwcp-db:5432/control_plane"
auth = (secrets / "mwcp_auth_secrets").read_text().strip()
# 输出为 env 文件（600），由本脚本 source 后立即删除
print(f"MWCP_DB_DSN='{dsn}'")
print("MWCP_AUTH_SECRETS='<redacted-from-env>'")
print(f"MWCP_AUTH_SECRETS_FILE='{secrets}/mwcp_auth_secrets'")
PY
chmod 600 /tmp/.mwcp_env
. /tmp/.mwcp_env
rm -f /tmp/.mwcp_env

# 应用侧由 MWCP_AUTH_SECRETS_FILE 再读 JWT kid 表（auth.load_secrets_from_env 改造点见 R4-04 §6）
exec python -m uvicorn app:app \
  --host "${MWCP_LISTEN_HOST:-0.0.0.0}" --port "${MWCP_LISTEN_PORT:-8123}" \
  --no-access-log  # 访问日志走结构化审计（含脱敏），不用 uvicorn 明文行
