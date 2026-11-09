import os
import sys
from pathlib import Path

# 测试专用 Mock 密钥（非生产凭据；仓库允许，因为它只用于本地测试签发）
os.environ.pop("MWCP_AUTH_SECRETS_FILE", None)
os.environ["MWCP_AUTH_SECRETS"] = "dev-1:test-secret-only-for-local-tests"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
