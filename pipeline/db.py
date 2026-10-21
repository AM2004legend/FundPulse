"""The one place that opens database connections.

python -m pipeline.db          check the connection
python -m pipeline.db --init   apply sql/schema.sql then sql/views.sql (safe to re-run)
"""

import argparse

import psycopg

from pipeline.config import PROJECT_ROOT, get_database_url

SQL_FILES = [PROJECT_ROOT / "sql" / "schema.sql", PROJECT_ROOT / "sql" / "views.sql"]


def get_connection(url: str | None = None, autocommit: bool = False) -> psycopg.Connection:
    """Open a new connection (to DATABASE_URL unless another url is given).

    Use it as `with get_connection() as conn:` — on leaving the block psycopg
    commits if there was no error, rolls back if there was, and closes the connection.
    With autocommit=True, nothing is grouped unless you open `with conn.transaction():`.
    """
    return psycopg.connect(url or get_database_url(), autocommit=autocommit, connect_timeout=10)


def apply_sql_files(conn: psycopg.Connection) -> None:
    """Create missing tables and (re)create the views, in one transaction."""
    with conn.transaction():
        for path in SQL_FILES:
            conn.execute(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check or initialise the database.")
    parser.add_argument("--init", action="store_true", help="apply schema.sql and views.sql")
    args = parser.parse_args()

    with get_connection(autocommit=True) as conn:
        version = conn.execute("SHOW server_version").fetchone()[0]
        print(f"Connected. PostgreSQL {version}")
        if args.init:
            apply_sql_files(conn)
            print("Applied: " + ", ".join(p.name for p in SQL_FILES))
