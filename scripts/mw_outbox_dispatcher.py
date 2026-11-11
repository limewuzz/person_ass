"""Mac relay: bounded polling, durable local receipts, no execution on unknown recovery.
Default SIMULATE. LIVE additionally requires --enable-external-writes, server worker
allowlists, connector configuration and scoped private-file credentials.
"""

from datetime import datetime, timezone
import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote
from mw_io import private_file, request_json, validate_origin, TransportError
from mw_connectors import execute, Unavailable, UnknownOutcome


class Journal:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        if path.stat().st_mode & 0o077:
            raise ValueError("Journal must be private (0600)")
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS effects(id TEXT PRIMARY KEY, state TEXT, body TEXT)"
        )
        self.db.commit()

    def get(self, key):
        row = self.db.execute(
            "SELECT state, body FROM effects WHERE id=?", (key,)
        ).fetchone()
        return (row[0], json.loads(row[1]) if row[1] else None) if row else None

    def put(self, key, state, body=None):
        self.db.execute(
            "INSERT INTO effects VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,body=excluded.body",
            (key, state, json.dumps(body) if body else None),
        )
        self.db.commit()


def process(item, journal, config, complete, writes=False):
    old = journal.get(item["id"])
    base = {"claim_token": item["claim_token"], "generation": item["generation"]}
    if (
        old
        and old[0] in {"RESULT", "ACKED"}
        and old[1]["generation"] == item["generation"]
    ):
        body = old[1]  # Exact response retry; never repeat the provider write.
    elif old and old[0] in {"STARTED", "RESULT", "ACKED"}:
        body = {
            **base,
            "outcome": "UNKNOWN",
            "error_code": "journal_requires_reconciliation",
        }
    else:
        journal.put(
            item["id"], "STARTED"
        )  # Commit before any possible external side effect.
        try:
            body = {
                **base,
                "outcome": "SUCCEEDED",
                "receipt": execute(item, config, writes),
            }
        except Unavailable:
            body = {**base, "outcome": "UNKNOWN", "error_code": "connector_unavailable"}
        except UnknownOutcome:
            body = {
                **base,
                "outcome": "UNKNOWN",
                "error_code": "external_result_unknown",
            }
        except TransportError:
            # Only read-only adapter preflight raises TransportError: no write was sent.
            body = {
                **base,
                "outcome": "RETRYABLE",
                "error_code": "read_preflight_unavailable",
            }
        except Exception:
            body = {
                **base,
                "outcome": "UNKNOWN",
                "error_code": "adapter_result_unknown",
            }
        journal.put(item["id"], "RESULT", body)
    result = complete(item["id"], body)
    # A retryable failure has no side effect; permit the next generation after server backoff.
    journal.put(
        item["id"], "SAFE_RETRY" if body["outcome"] == "RETRYABLE" else "ACKED", body
    )
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("url", "worker-id", "node-id", "token-file"):
        p.add_argument("--" + key, required=True)
    p.add_argument("--allow-remote", action="store_true")
    p.add_argument("--mode", choices=["SIMULATE", "LIVE"], default="SIMULATE")
    p.add_argument("--enable-external-writes", action="store_true")
    p.add_argument("--connectors-file")
    p.add_argument("--journal", default=".runtime/mac-outbox.sqlite3")
    p.add_argument("--once", action="store_true")
    args = p.parse_args()
    origin = validate_origin(args.url, args.allow_remote)
    if args.mode == "LIVE" and not args.enable_external_writes:
        p.error("LIVE requires explicit --enable-external-writes and server grants")
    config = (
        json.loads(private_file(args.connectors_file).decode())
        if args.connectors_file
        else {}
    )
    journal = Journal(args.journal)
    prefix = "/api/v1/workers/" + quote(args.worker_id, safe="")
    targets = (
        list(config)
        if args.mode == "LIVE"
        else [
            "ai",
            "drive",
            "notion",
            "reminders",
            "compute",
            "github",
            "implementation",
            "wechat",
            "knowledge",
        ]
    )

    def call(path, body):
        token = private_file(args.token_file, 16384).decode()
        return request_json(
            origin + prefix + path, body, {"Authorization": "Bearer " + token}, "POST"
        )

    while True:
        try:
            call(
                "/heartbeat",
                {
                    "node_id": args.node_id,
                    "available_capabilities": ["fanout." + x for x in targets],
                    "version": "3.0-relay",
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            items = call("/outbox/claim", {"mode": args.mode, "limit": 1})["items"]
            for item in items:
                # Retry ACK from the committed journal within the lease; never repeat the effect.
                for attempt in range(3):
                    try:
                        result = process(
                            item,
                            journal,
                            config,
                            lambda did, body: call("/outbox/" + did + "/finish", body),
                            args.enable_external_writes,
                        )
                        print(
                            json.dumps(
                                {"delivery_id": item["id"], "state": result["state"]}
                            )
                        )
                        break
                    except TransportError as error:
                        if (
                            error.status in {401, 403, 409}
                            or time.time() + 3 >= item["lease_expires_at"]
                        ):
                            break
                        time.sleep(1)
        except TransportError as error:
            print(
                json.dumps(
                    {"status": "control_plane_unavailable", "http_status": error.status}
                )
            )
        if args.once:
            break
        time.sleep(5)


if __name__ == "__main__":
    main()
