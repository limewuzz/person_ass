"""Pure-Python RFC 7519 JWT (HS256 / none) compatible with PyJWT 2.x API."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Iterable


class PyJWTError(Exception):
    pass


class DecodeError(PyJWTError):
    pass


class InvalidTokenError(PyJWTError):
    pass


class InvalidSignatureError(DecodeError):
    pass


class ExpiredSignatureError(InvalidTokenError):
    pass


class ImmatureSignatureError(InvalidTokenError):
    pass


class InvalidIssuerError(InvalidTokenError):
    pass


class InvalidAudienceError(InvalidTokenError):
    pass


class InvalidAlgorithmError(InvalidTokenError):
    pass


class MissingRequiredClaimError(InvalidTokenError):
    pass


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    rem = len(s) % 4
    if rem:
        s += "=" * (4 - rem)
    try:
        return base64.urlsafe_b64decode(s.encode("ascii"))
    except Exception as e:
        raise DecodeError("Invalid base64url encoding") from e


def get_unverified_header(jwt_token: str) -> dict[str, Any]:
    if not isinstance(jwt_token, str) or jwt_token.count(".") != 2:
        raise DecodeError("Not enough segments")
    header_b64, _, _ = jwt_token.split(".")
    try:
        hdr = json.loads(_b64url_decode(header_b64).decode("utf-8"))
    except Exception as e:
        raise DecodeError("Invalid header JSON") from e
    if not isinstance(hdr, dict):
        raise DecodeError("Header must be a JSON object")
    return hdr


def encode(
    payload: dict[str, Any],
    key: str | bytes,
    algorithm: str = "HS256",
    headers: dict[str, Any] | None = None,
) -> str:
    hdr: dict[str, Any] = {"typ": "JWT", "alg": algorithm}
    if headers:
        hdr.update(headers)
    hdr["alg"] = algorithm
    header_seg = _b64url_encode(
        json.dumps(hdr, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    payload_seg = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{header_seg}.{payload_seg}".encode("ascii")
    if algorithm == "none":
        sig_seg = ""
    elif algorithm == "HS256":
        key_bytes = key.encode("utf-8") if isinstance(key, str) else bytes(key)
        sig = hmac.new(key_bytes, signing_input, hashlib.sha256).digest()
        sig_seg = _b64url_encode(sig)
    else:
        raise InvalidAlgorithmError(f"Unsupported algorithm: {algorithm}")
    return f"{header_seg}.{payload_seg}.{sig_seg}"


def decode(
    jwt_token: str,
    key: str | bytes = "",
    algorithms: Iterable[str] | None = None,
    issuer: str | None = None,
    audience: str | None = None,
    options: dict[str, Any] | None = None,
    leeway: float = 0.0,
) -> dict[str, Any]:
    if not isinstance(jwt_token, str) or jwt_token.count(".") != 2:
        raise DecodeError("Invalid token format")
    header_seg, payload_seg, sig_seg = jwt_token.split(".")
    header = get_unverified_header(jwt_token)
    alg = header.get("alg")
    allowed = set(algorithms or [])
    if not allowed or alg not in allowed:
        raise InvalidAlgorithmError(f"Algorithm {alg!r} not allowed")
    if alg == "HS256":
        key_bytes = key.encode("utf-8") if isinstance(key, str) else bytes(key)
        signing_input = f"{header_seg}.{payload_seg}".encode("ascii")
        expected_sig = hmac.new(key_bytes, signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(sig_seg)
        if not hmac.compare_digest(expected_sig, actual_sig):
            raise InvalidSignatureError("Signature verification failed")
    elif alg == "none":
        if sig_seg != "":
            raise InvalidSignatureError("alg=none must have empty signature")
    else:
        raise InvalidAlgorithmError(f"Unsupported algorithm: {alg}")

    try:
        claims = json.loads(_b64url_decode(payload_seg).decode("utf-8"))
    except Exception as e:
        raise DecodeError("Invalid payload JSON") from e
    if not isinstance(claims, dict):
        raise DecodeError("Payload must be a JSON object")

    opts = options or {}
    required = opts.get("require", [])
    for req_claim in required:
        if req_claim not in claims:
            raise MissingRequiredClaimError(f"Missing required claim: {req_claim}")

    now = time.time()
    if "exp" in claims:
        try:
            exp_val = float(claims["exp"])
        except Exception as e:
            raise DecodeError("exp must be numeric") from e
        if now >= exp_val + leeway:
            raise ExpiredSignatureError("Signature has expired")

    if "nbf" in claims:
        try:
            nbf_val = float(claims["nbf"])
        except Exception as e:
            raise DecodeError("nbf must be numeric") from e
        if now + leeway < nbf_val:
            raise ImmatureSignatureError("The token is not yet valid (nbf)")

    if issuer is not None and claims.get("iss") != issuer:
        raise InvalidIssuerError("Invalid issuer")

    if audience is not None:
        aud_claim = claims.get("aud")
        if isinstance(aud_claim, list):
            if audience not in aud_claim:
                raise InvalidAudienceError("Invalid audience")
        elif aud_claim != audience:
            raise InvalidAudienceError("Invalid audience")

    return claims
