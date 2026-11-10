"""No real platform/network/Apple calls. Verify the relay's crash protocol."""

import importlib
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from mw_io import private_file, validate_origin, TransportError
from mw_outbox_dispatcher import Journal, process
import mw_outbox_dispatcher as relay
from mw_trigger import sign


def item():
    return {
        "id": "local-delivery",
        "mode": "SIMULATE",
        "target": "reminders",
        "input": "offline",
        "parameters": {},
        "generation": 1,
        "claim_token": "local-only-test-token",
    }


def test_journal_retries_only_response_after_ack_loss(tmp_path, monkeypatch):
    journal = Journal(tmp_path / "receipt.sqlite3")
    calls = []
    finish = []
    monkeypatch.setattr(
        relay,
        "execute",
        lambda i, c, w: (
            calls.append(i["id"])
            or {"sha256": "a" * 64, "uri": "mock://offline", "source_mode": "MOCK"}
        ),
    )

    def complete(did, body):
        finish.append(body)
        if len(finish) == 1:
            raise TransportError(503)
        return {"state": "SUCCEEDED"}

    with pytest.raises(TransportError):
        process(item(), journal, {}, complete)
    assert process(item(), journal, {}, complete)["state"] == "SUCCEEDED"
    assert calls == ["local-delivery"] and finish[0] == finish[1]
    process(item(), journal, {}, complete)
    assert len(calls) == 1 and finish[2] == finish[1]


def test_crash_before_recorded_receipt_never_reexecutes(tmp_path, monkeypatch):
    journal = Journal(tmp_path / "receipt.sqlite3")
    journal.put("local-delivery", "STARTED")
    monkeypatch.setattr(
        relay, "execute", lambda *args: pytest.fail("must reconcile, not execute")
    )
    out = []
    process(item(), journal, {}, lambda did, b: out.append(b))
    assert out[0]["outcome"] == "UNKNOWN"


def test_file_permissions_symlinks_origin_and_signed_header_binding(tmp_path):
    path = tmp_path / "secret"
    path.write_bytes(b"test-only-secret-value-longer-than-32bytes")
    path.chmod(0o600)
    assert private_file(path).startswith(b"test-only")
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        private_file(link)
    path.chmod(0o644)
    with pytest.raises(ValueError):
        private_file(path)
    assert validate_origin("http://127.0.0.1:8127") == "http://127.0.0.1:8127"
    for url in [
        "http://127.0.0.1:8765",
        "https://example.com",
        "https://user:secret@example.com",
        "http://169.254.169.254",
        "https://example.com/redirect",
    ]:
        with pytest.raises(ValueError):
            validate_origin(url)
    assert (
        sign(b"{}", b"test-key", "stable-key", 1, "stable-nonce")["X-MW-Signature"]
        != sign(b"{}", b"test-key", "other-key", 1, "stable-nonce")["X-MW-Signature"]
    )


def test_live_adapters_unconfigured_never_send_network(monkeypatch):
    import mw_connectors as adapters

    monkeypatch.setattr(
        adapters, "request_json", lambda *a, **k: pytest.fail("unexpected network")
    )
    for target in [
        "drive",
        "notion",
        "github",
        "reminders",
        "compute",
        "wechat",
        "implementation",
        "ai",
        "knowledge",
    ]:
        with pytest.raises(adapters.Unavailable):
            adapters.execute({**item(), "target": target, "mode": "LIVE"}, {}, True)
    assert adapters.execute(item(), {})["source_mode"] == "MOCK"


def test_real_loopback_mac_relay_cli_and_signed_trigger(tmp_path):
    """Owned isolated process, generated local credentials, SIMULATE only."""
    import json
    import os
    import socket
    import subprocess
    import time
    import secrets
    from auth import mint_token, ROLE_SCOPES
    from mw_io import request_json

    root = Path(__file__).parents[1]
    probe = socket.socket()
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    probe.bind(("127.0.0.1", 8137))
    probe.close()
    secret = secrets.token_hex(32)
    hmac_path = tmp_path / "hmac"
    hmac_path.write_text(secrets.token_hex(32))
    hmac_path.chmod(0o600)
    keys = tmp_path / "keys.json"
    keys.write_text(
        json.dumps(
            {
                "keys": {
                    "offline-test": {
                        "secret_file": str(hmac_path),
                        "owner_sub": "v3-offline-owner",
                        "channel": "wechat",
                        "recipes": ["wechat"],
                    }
                }
            }
        )
    )
    env = {
        **os.environ,
        "MWCP_AUTH_SECRETS": "dev-1:" + secret,
        "MWCP_WEBHOOK_KEYS_FILE": str(keys),
        "MWCP_PROBE_MODE": "test",
        "PYTHONPATH": str(root / "backend"),
    }
    env.pop("MWCP_AUTH_SECRETS_FILE", None)
    env.pop("MWCP_FANOUT_GRANTS_FILE", None)
    with (tmp_path / "api.log").open("w") as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8137",
                "--no-access-log",
                "--log-level",
                "warning",
            ],
            cwd=root,
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            origin = "http://127.0.0.1:8137"
            for _ in range(100):
                try:
                    request_json(origin + "/api/v1/health/live")
                    break
                except TransportError:
                    assert proc.poll() is None, "Isolated API startup failed"
                    time.sleep(0.05)
            else:
                pytest.fail("Isolated API readiness timeout")
            body = {
                "recipe_id": "wechat",
                "title": "signed local CLI",
                "input": "offline receipt only",
                "mode": "SIMULATE",
                "targets": ["reminder"],
                "origin": {"channel": "wechat"},
            }
            request = tmp_path / "intent.json"
            request.write_text(json.dumps(body))
            command = [
                sys.executable,
                str(root / "scripts/mw_trigger.py"),
                "--url",
                origin,
                "--request-file",
                str(request),
                "--key-id",
                "offline-test",
                "--key-file",
                str(hmac_path),
                "--idempotency-key",
                "v3-loopback-cli-123456",
            ]
            created = json.loads(subprocess.check_output(command, cwd=root, text=True))
            assert created["availability"] == "MOCK"
            assert (
                json.loads(subprocess.check_output(command, cwd=root, text=True))["id"]
                == created["id"]
            )
            token = tmp_path / "worker-jwt"
            token.write_text(
                mint_token(
                    secret,
                    sub="v3-cli-relay",
                    typ="worker",
                    role="worker",
                    scopes=["worker:heartbeat", "worker:claim"],
                )
            )
            token.chmod(0o600)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(root / "scripts/mw_outbox_dispatcher.py"),
                    "--url",
                    origin,
                    "--worker-id",
                    "v3-cli-relay",
                    "--node-id",
                    "v3-cli-node",
                    "--token-file",
                    str(token),
                    "--journal",
                    str(tmp_path / "journal.sqlite3"),
                    "--once",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            )
            assert json.loads(completed.stdout)["state"] == "SUCCEEDED"
            actor = mint_token(
                secret,
                sub="v3-offline-owner",
                typ="actor",
                role="admin",
                scopes=sorted(ROLE_SCOPES["admin"]),
            )
            final = request_json(
                origin + "/api/v1/fanouts/" + created["id"],
                headers={"Authorization": "Bearer " + actor},
            )
            assert (
                final["status"] == "SUCCEEDED"
                and final["deliveries"][0]["attempts"] == 1
            )
            assert final["deliveries"][0]["receipt"]["source_mode"] == "MOCK"
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
