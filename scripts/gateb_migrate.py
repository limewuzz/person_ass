"""Explicit isolated-only migration tool. Never imported/executed by API or CI."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dbpg.repository import MigrationRunner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['apply', 'destroy-disposable-schema'])
    parser.add_argument('--authorized-isolated-gate-b', action='store_true')
    parser.add_argument('--password-file', required=True)
    args = parser.parse_args()
    if not args.authorized_isolated_gate_b or os.environ.get('MWCP_GATE_B_AUTHORIZED') != '1':
        parser.error('Separate Gate B authorization and explicit isolated acknowledgment required')
    import psycopg
    conn = None
    try:
        password = Path(args.password_file).read_text().strip()
        conn = psycopg.connect(host='mwcp-gateb-pg', port=5432, dbname='control_plane',
            user='mwcp_migrator', password=password, connect_timeout=5,
            application_name='mwcp-isolated-migrations')
        del password
        runner = MigrationRunner(conn, str(ROOT/'dbpg/migrations'))
        runner.ensure_version_table()
        paths = sorted((ROOT/'dbpg/migrations').glob('*.sql'))
        applied = runner.applied_with_checksums()
        expected = {p.stem: runner.file_checksum(p) for p in paths}
        if set(applied) - set(expected) or any(expected[k] != v for k, v in applied.items()):
            raise ValueError('Migration checksum/identity mismatch')
        conn.rollback()
        if args.action == 'apply':
            for path in paths:
                if path.stem not in applied: runner.apply(path.stem, path.name)
            with conn.cursor() as cur:
                cur.execute('REVOKE ALL ON schema_migrations FROM mwcp_app')
                cur.execute('GRANT SELECT ON schema_migrations TO mwcp_app')
            conn.commit()
        else:
            # Each down DDL and version deletion is one atomic transaction.
            for path in reversed(paths):
                if path.stem not in applied: continue
                with conn.cursor() as cur:
                    cur.execute('SELECT pg_advisory_xact_lock(%s)', (runner.ADVISORY_LOCK_KEY,))
                    for statement in runner._split_statements((ROOT/'dbpg/rollback'/path.name).read_text()):
                        cur.execute(statement)
                    cur.execute('DELETE FROM schema_migrations WHERE version=%s', (path.stem,))
                conn.commit()
        print('Isolated migration action completed; record live evidence separately.')
    except Exception:
        if conn is not None: conn.rollback()
        parser.exit(1, 'Isolated migration action failed; transaction rolled back.\n')
    finally:
        if conn is not None: conn.close()


if __name__ == '__main__': main()
