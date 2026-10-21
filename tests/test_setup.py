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


def test_nav_is_numeric_16_8():
    # Some AMFI NAVs have 8 decimal places; NUMERIC(16,8) stores them exactly.
    with get_connection() as conn:
        row = conn.execute(
            "SELECT data_type, numeric_precision, numeric_scale FROM information_schema.columns "
            "WHERE table_name = 'nav_history' AND column_name = 'nav'"
        ).fetchone()

    assert row == ("numeric", 16, 8)
