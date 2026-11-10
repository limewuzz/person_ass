"""Generate fresh per-consumer file secrets; no values on stdout/argv/env.

Run only on the separately authorized disposable host as root so bind-mounted
0600 files have the actual container consumer UIDs (Compose file uid is ignored).
"""
import argparse
import os
from pathlib import Path
import secrets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', default='/run/mwcp-gateb/secrets')
    parser.add_argument('--authorized-isolated-gate-b', action='store_true')
    args = parser.parse_args()
    if not args.authorized_isolated_gate_b or os.environ.get('MWCP_GATE_B_AUTHORIZED') != '1':
        parser.error('Separate Gate B authorization required')
    if os.geteuid() != 0: parser.error('Root required to assign consumer ownership')
    root = Path(args.directory)
    if not root.is_absolute() or root.exists(): parser.error('Use a fresh absolute secrets directory')
    root.mkdir(parents=True, mode=0o700)
    for name in ('db','api','backup'): (root/name).mkdir(mode=0o700)
    app_password = secrets.token_hex(32)
    values = {
        'db/mwcp_pg_bootstrap_password': (secrets.token_hex(32), 999),
        'db/mwcp_pg_migrator_password': (secrets.token_hex(32), 999),
        'db/mwcp_pg_app_password': (app_password, 999),
        'api/mwcp_pg_app_password': (app_password, 10001),
        'api/mwcp_auth_secrets': ('gateb-1:'+secrets.token_hex(32), 10001),
        'backup/encryption': (secrets.token_hex(32), 0),
        'backup/mac': (secrets.token_hex(32), 0),
        'backup/pgpass': ('mwcp-gateb-pg:5432:control_plane:mwcp_app:'+app_password, 0),
    }
    for name, (value, uid) in values.items():
        path = root/name
        fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream: stream.write(value+'\n')
        os.chown(path, uid, uid)
    print('Private Gate B files created with consumer ownership; no secret values emitted.')


if __name__ == '__main__': main()
