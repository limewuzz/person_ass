"""P1-04 认证授权（本地 Mock OIDC/JWT，不接生产账号）。

设计要点（对应评审 §C）：
- JWT 仅接受 allowlist 算法（HS256）；校验 iss/aud/signature/exp/nbf/jti；拒绝 alg=none。
- kid 轮换：多密钥表（kid -> secret），header 必须带 kid。
- 认证配置缺失 → fail closed（除 /health/live 外全部 503）。
- Actor / Service / Worker 三类身份分离；Worker 只有受限 scopes，不得凭 URL 参数授权。
- jti 吊销表（内存，P1 演示级）；重放已吊销 token → 401。
- 对象级授权：principal 可携带 node_ids / kinds 限定，资源查询强制检查（IDOR 防护）。
- 不引入旧 EXECUTOR_API_KEY；密钥只来自环境变量 MWCP_AUTH_SECRET(S)。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import jwt

MOCK_ISSUER = "https://mock-issuer.mwcp.local"
AUDIENCE = "mwcp-api"
ALLOWED_ALGS = {"HS256"}

ACTOR_ROLES = {"viewer", "operator", "approver", "admin"}
ROLE_SCOPES: dict[str, set[str]] = {
    "viewer": {"health:read", "registry:read"},
    "operator": {"health:read", "registry:read", "probes:read"},
    "approver": {"health:read", "registry:read", "approvals:read"},
    "admin": {"health:read", "registry:read", "probes:read", "approvals:read", "admin:read"},
    "worker": {"worker:heartbeat", "worker:claim"},  # Worker 独立范围，无 registry 读
}


class AuthConfigError(Exception):
    """认证配置缺失/非法 —— fail closed 用。"""


@dataclass
class Principal:
    sub: str
    typ: str  # actor | service | worker
    role: str
    scopes: set[str] = field(default_factory=set)
    node_ids: set[str] | None = None  # None=不限制（对象级 IDOR 边界）
    kinds: set[str] | None = None
    jti: str = ""

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def may_access_node(self, node_id: str | None) -> bool:
        return self.node_ids is None or node_id in self.node_ids

    def may_access_kind(self, kind: str) -> bool:
        return self.kinds is None or kind in self.kinds


class RevocationStore:
    """jti 吊销表（内存演示级；P1-07 起 Worker 走数据库持久化）。"""

    def __init__(self) -> None:
        self._revoked: set[str] = set()

    def revoke(self, jti: str) -> None:
        self._revoked.add(jti)

    def is_revoked(self, jti: str) -> bool:
        return jti in self._revoked


class TokenValidator:
    def __init__(self, secrets_by_kid: dict[str, str], issuer: str = MOCK_ISSUER,
                 audience: str = AUDIENCE, clock: Callable[[], float] = time.time) -> None:
        if not secrets_by_kid:
            raise AuthConfigError("MWCP_AUTH_SECRETS empty — fail closed")
        self._secrets = secrets_by_kid
        self.issuer = issuer
        self.audience = audience
        self.clock = clock
        self.revocations = RevocationStore()

    def decode(self, token: str) -> Principal:
        # 拒绝 alg=none：jwt.decode 的 algorithms 参数本身就是 allowlist；
        # 再显式校验 header，防未来误放开。
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise _unauthorized("malformed token") from e
        if header.get("alg") not in ALLOWED_ALGS:
            raise _unauthorized("disallowed alg")
        kid = header.get("kid")
        secret = self._secrets.get(kid or "")
        if secret is None:
            raise _unauthorized("unknown kid")
        try:
            claims = jwt.decode(
                token, secret, algorithms=["HS256"],
                issuer=self.issuer, audience=self.audience,
                options={"require": ["exp", "iss", "aud", "sub", "typ", "jti"]},
            )
        except jwt.ExpiredSignatureError as e:
            raise _unauthorized("token expired") from e
        except jwt.InvalidIssuerError as e:
            raise _unauthorized("bad issuer") from e
        except jwt.InvalidAudienceError as e:
            raise _unauthorized("bad audience") from e
        except jwt.ImmatureSignatureError as e:
            raise _unauthorized("token not yet valid (nbf)") from e
        except jwt.PyJWTError as e:
            raise _unauthorized("invalid token") from e
        if self.revocations.is_revoked(claims["jti"]):
            raise _unauthorized("token revoked")
        typ = claims["typ"]
        role = claims.get("role", "")
        if typ == "worker":
            role = "worker"  # worker 身份不接受其他 role 字段
        elif typ in ("actor", "service") and role not in ACTOR_ROLES:
            raise _unauthorized("bad role")
        return Principal(
            sub=claims["sub"], typ=typ, role=role,
            scopes=set(claims.get("scopes", [])) & ROLE_SCOPES.get(role, set()),
            node_ids=set(claims["node_ids"]) if claims.get("node_ids") is not None else None,
            kinds=set(claims["kinds"]) if claims.get("kinds") is not None else None,
            jti=claims["jti"],
        )


def _unauthorized(msg: str) -> Exception:
    from fastapi import HTTPException
    # 统一泛化错误信息：不回显 token 内容
    return HTTPException(status_code=401, detail={"error": "unauthorized", "reason": msg})


def load_secrets_from_env() -> dict[str, str]:
    """MWCP_AUTH_SECRETS='kid1:secret1,kid2:secret2'（仅部署环境注入，不入库）。"""
    raw = os.environ.get("MWCP_AUTH_SECRETS", "")
    out: dict[str, str] = {}
    for pair in raw.split(","):
        if ":" in pair:
            k, v = pair.split(":", 1)
            k, v = k.strip(), v.strip()
            if k and v:
                out[k] = v
    return out


def mint_token(secret: str, *, sub: str, typ: str, role: str, scopes: list[str],
               kid: str = "dev-1", issuer: str = MOCK_ISSUER, aud: str = AUDIENCE,
               ttl_seconds: int = 600, jti: str = "test-jti", now: float | None = None,
               nbf_offset: int = 0, node_ids: list[str] | None = None,
               kinds: list[str] | None = None) -> str:
    """仅测试/本地开发用的 Mock issuer 签发函数。"""
    t = time.time() if now is None else now
    payload: dict[str, Any] = {
        "iss": issuer, "aud": aud, "sub": sub, "typ": typ, "role": role,
        "scopes": scopes, "jti": jti, "iat": int(t), "nbf": int(t) + nbf_offset,
        "exp": int(t) + ttl_seconds,
    }
    if node_ids is not None:
        payload["node_ids"] = node_ids
    if kinds is not None:
        payload["kinds"] = kinds
    return jwt.encode(payload, secret, algorithm="HS256", headers={"kid": kid})
