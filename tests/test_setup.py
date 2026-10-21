"""Phase 1 smoke test: config, db.py, Docker Postgres and schema.sql all work together."""

from pipeline.db import get_connection

EXPECTED_TABLES = {"pipeline_runs", "raw_nav", "schemes", "nav_history", "quarantine"}


def test_schema_tables_exist():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()

    found = {row[0] for row in rows}
    assert EXPECTED_TABLES <= found, f"missing tables: {EXPECTED_TABLES - found}"
