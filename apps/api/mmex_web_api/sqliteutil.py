"""SQLite connection pragmas for NAS bind-mounts (same as recon app)."""

from __future__ import annotations


def configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA busy_timeout = 30000")
    cursor.execute("PRAGMA synchronous = FULL")
    cursor.execute("PRAGMA journal_mode = DELETE")
    cursor.close()
