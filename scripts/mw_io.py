"""Small stdlib-only transport shared by the opt-in V3 clients."""

import json
import os
import stat
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class TransportError(Exception):
    def __init__(self, status=0):
        self.status = status
        super().__init__(
            f"HTTP transport failed ({status}); response and credentials withheld"
        )


def private_file(path, limit=65536):
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_size > limit
        ):
            raise ValueError(
                "Credential file must be a bounded regular file with mode 0600"
            )
        return os.read(fd, limit + 1).strip()
    finally:
        os.close(fd)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_origin(url, allow_remote=False):
    p = urllib.parse.urlsplit(url)
    if p.username or p.password or p.query or p.fragment or p.path not in ("", "/"):
        raise ValueError(
            "Supply a control-plane origin without credentials, path, query or fragment"
        )
    if p.hostname in {"127.0.0.1", "localhost", "::1"}:
        if p.scheme != "http" or p.port not in {8127, 8137, 8147}:
            raise ValueError(
                "Only new isolated loopback ports 8127/8137/8147 are allowed"
            )
    elif not allow_remote or p.scheme != "https" or p.port not in (None, 443):
        raise ValueError(
            "Remote control-plane access requires --allow-remote and an HTTPS origin"
        )
    return url.rstrip("/")


def request_json(url, body=None, headers=None, method=None, timeout=10):
    data = (
        None
        if body is None
        else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    )
    return request_bytes(url, data, headers, method, timeout)


def request_bytes(url, data=None, headers=None, method=None, timeout=10):
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(
            req, timeout=timeout
        ) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise TransportError()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise TransportError(e.code) from None
    except (OSError, ValueError):
        raise TransportError() from None
