"""The one place that opens database connections."""

import psycopg

from pipeline.config import get_database_url


def get_connection() -> psycopg.Connection:
    """Open a new connection.

    Use it as `with get_connection() as conn:` — on leaving the block psycopg
    commits if there was no error, rolls back if there was, and closes the connection.
    """
    return psycopg.connect(get_database_url(), connect_timeout=10)


if __name__ == "__main__":
    # Quick check: python -m pipeline.db
    with get_connection() as conn:
        version = conn.execute("SHOW server_version").fetchone()[0]
        print(f"Connected. PostgreSQL {version}")
