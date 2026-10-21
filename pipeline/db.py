"""The one place that opens database connections."""

import psycopg

from pipeline.config import get_database_url


def get_connection(url: str | None = None, autocommit: bool = False) -> psycopg.Connection:
    """Open a new connection (to DATABASE_URL unless another url is given).

    Use it as `with get_connection() as conn:` — on leaving the block psycopg
    commits if there was no error, rolls back if there was, and closes the connection.
    With autocommit=True, nothing is grouped unless you open `with conn.transaction():`.
    """
    return psycopg.connect(url or get_database_url(), autocommit=autocommit, connect_timeout=10)


if __name__ == "__main__":
    # Quick check: python -m pipeline.db
    with get_connection() as conn:
        version = conn.execute("SHOW server_version").fetchone()[0]
        print(f"Connected. PostgreSQL {version}")
