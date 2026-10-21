"""Write to PostgreSQL. Each function is its own transaction on an autocommit connection."""

import pandas as pd
import psycopg

from pipeline.transform import TransformResult

START_RUN = "INSERT INTO pipeline_runs (status) VALUES ('running') RETURNING run_id"

FINISH_RUN = """
UPDATE pipeline_runs
SET finished_at = now(), status = %s, rows_loaded = %s, rows_quarantined = %s, error = %s
WHERE run_id = %s
"""

# is_watchlist is deliberately not in the SET list: a reload must never reset it.
# The WHERE clause skips rows that haven't changed, so they aren't rewritten.
UPSERT_SCHEME = """
INSERT INTO schemes (scheme_code, scheme_name, fund_house, category, isin_growth)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (scheme_code) DO UPDATE SET
    scheme_name = EXCLUDED.scheme_name,
    fund_house  = EXCLUDED.fund_house,
    category    = EXCLUDED.category,
    isin_growth = EXCLUDED.isin_growth
WHERE (schemes.scheme_name, schemes.fund_house, schemes.category, schemes.isin_growth)
    IS DISTINCT FROM
      (EXCLUDED.scheme_name, EXCLUDED.fund_house, EXCLUDED.category, EXCLUDED.isin_growth)
"""

UPSERT_NAV = """
INSERT INTO nav_history (scheme_code, nav_date, nav)
VALUES (%s, %s, %s)
ON CONFLICT (scheme_code, nav_date) DO UPDATE SET nav = EXCLUDED.nav
WHERE nav_history.nav IS DISTINCT FROM EXCLUDED.nav
"""

INSERT_QUARANTINE = "INSERT INTO quarantine (run_id, raw_line, reason) VALUES (%s, %s, %s)"


def _rows(df: pd.DataFrame, columns: list[str]) -> list[tuple]:
    """DataFrame -> list of tuples of plain Python values (int, str, Decimal, date, None)."""
    return list(df[columns].astype(object).itertuples(index=False, name=None))


def start_run(conn: psycopg.Connection) -> int:
    with conn.transaction():
        return conn.execute(START_RUN).fetchone()[0]


def finish_run(
    conn: psycopg.Connection,
    run_id: int,
    status: str,
    rows_loaded: int = 0,
    rows_quarantined: int = 0,
    error: str | None = None,
) -> None:
    with conn.transaction():
        conn.execute(FINISH_RUN, (status, rows_loaded, rows_quarantined, error, run_id))


def save_raw_lines(conn: psycopg.Connection, run_id: int, lines: list[str]) -> None:
    """Store every line exactly as received. COPY streams them in one go (fast for 18k lines)."""
    with conn.transaction(), conn.cursor() as cur:
        with cur.copy("COPY raw_nav (run_id, line_no, raw_line) FROM STDIN") as copy:
            for line_no, line in enumerate(lines, start=1):
                copy.write_row((run_id, line_no, line))


def load_day(conn: psycopg.Connection, run_id: int, result: TransformResult) -> None:
    """Upsert schemes, then NAVs, then record quarantined rows — all or nothing."""
    schemes = result.clean.drop_duplicates("scheme_code", keep="last")
    scheme_rows = _rows(
        schemes, ["scheme_code", "scheme_name", "fund_house", "category", "isin_growth"]
    )
    nav_rows = _rows(result.clean, ["scheme_code", "nav_date", "nav"])
    quarantine_rows = [(run_id, *row) for row in _rows(result.quarantined, ["raw_line", "reason"])]

    with conn.transaction(), conn.cursor() as cur:
        # schemes first: nav_history.scheme_code is a foreign key to schemes
        cur.executemany(UPSERT_SCHEME, scheme_rows)
        cur.executemany(UPSERT_NAV, nav_rows)
        cur.executemany(INSERT_QUARANTINE, quarantine_rows)
