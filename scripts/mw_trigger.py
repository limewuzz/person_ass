"""Signed single-input trigger. Secrets are read from a private file, never argv."""

import argparse
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from mw_io import private_file, request_bytes, validate_origin


def sign(raw, key, idem, timestamp=None, nonce=None):
    ts = str(int(time.time()) if timestamp is None else timestamp)
    nonce = nonce or secrets.token_urlsafe(18)
    value = f"{ts}\n{nonce}\n{idem}\n{hashlib.sha256(raw).hexdigest()}".encode()
    return {
        "X-MW-Timestamp": ts,
        "X-MW-Nonce": nonce,
        "Idempotency-Key": idem,
        "X-MW-Signature": hmac.new(key, value, hashlib.sha256).hexdigest(),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--allow-remote", action="store_true")
    p.add_argument("--request-file", required=True)
    p.add_argument("--key-id", required=True)
    p.add_argument("--key-file", required=True)
    p.add_argument(
        "--idempotency-key",
        required=True,
        help="Persist and reuse this identifier after a timeout",
    )
    args = p.parse_args()
    origin = validate_origin(args.url, args.allow_remote)
    raw = Path(args.request_file).read_bytes()
    if len(raw) > 65536:
        p.error("Request exceeds 64 KiB")
    json.loads(raw)
    key = private_file(args.key_file, 4096)
    if len(key) < 32:
        p.error("HMAC secret must contain at least 32 bytes")
    headers = {**sign(raw, key, args.idempotency_key), "X-MW-Key-Id": args.key_id}
    result = request_bytes(origin + "/api/v1/webhooks/trigger", raw, headers, "POST")
    print(
        json.dumps(
            {
                k: result[k]
                for k in ("id", "work_item_id", "trace_id", "status", "availability")
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
