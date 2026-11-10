"""Explicit PostgreSQL ASGI factory; never migrates or silently falls back.

Only run after separate Gate B authorization. Connection credentials are read
from files and remain out of argv/environment/logs. No automatic remote target.
"""
import os
from pathlib import Path


def create_app():
    import psycopg
    from service_container import swap_to_postgres
    if os.environ.get('MWCP_GATE_B_AUTHORIZED') != '1':
        raise RuntimeError('Separate isolated Gate B authorization required')
    if os.environ.get('MWCP_REPOSITORY') != 'postgres':
        raise RuntimeError('Explicit MWCP_REPOSITORY=postgres required')
    if os.environ.get('MWCP_DB_HOST') != 'mwcp-gateb-pg':
        raise RuntimeError('Only the isolated Gate B database host is permitted')
    path = Path(os.environ.get('MWCP_PG_APP_PASSWORD_FILE', '/run/secrets/mwcp_pg_app_password'))
    password = path.read_text().strip()
    if len(password) < 32:
        raise RuntimeError('Invalid application secret file')
    conn = None
    try:
        conn = psycopg.connect(host='mwcp-gateb-pg', port=5432,
                              user='mwcp_app', dbname='control_plane', password=password,
                              connect_timeout=5, application_name='mwcp-gateb-api')
        import app as api
        swap_to_postgres(conn)
        api.app.add_event_handler('shutdown', conn.close)
        return api.app
    except Exception:
        if conn is not None:
            conn.close()
        raise RuntimeError('PostgreSQL startup failed; inspect sanitized Gate B diagnostics') from None
    finally:
        del password
