"""Write to PostgreSQL. Each function is its own transaction on an autocommit connection."""

from typing import NamedTuple

import pandas as pd
import psycopg

from pipeline.transform import TransformResult

START_RUN = "INSERT INTO pipeline_runs (run_type, status) VALUES (%s, 'running') RETURNING run_id"

FINISH_RUN = """
UPDATE pipeline_runs
SET finished_at = now(), status = %s, rows_loaded = %s, rows_quarantined = %s,
    error = %s, warnings = %s
WHERE run_id = %s
"""

SCHEME_COLUMNS = [
    "scheme_code",
    "scheme_name",
    "plan_type",
    "option_type",
    "fund_house",
    "category",
    "isin_growth",
]

# The WHERE clause skips rows that haven't changed, so they aren't rewritten.
UPSERT_SCHEME = """
INSERT INTO schemes (scheme_code, scheme_name, plan_type, option_type, fund_house, category,
                     isin_growth)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (scheme_code) DO UPDATE SET
    scheme_name = EXCLUDED.scheme_name,
    plan_type   = EXCLUDED.plan_type,
    option_type = EXCLUDED.option_type,
    fund_house  = EXCLUDED.fund_house,
    category    = EXCLUDED.category,
    isin_growth = EXCLUDED.isin_growth
WHERE (schemes.scheme_name, schemes.plan_type, schemes.option_type, schemes.fund_house,
       schemes.category, schemes.isin_growth)
    IS DISTINCT FROM
      (EXCLUDED.scheme_name, EXCLUDED.plan_type, EXCLUDED.option_type, EXCLUDED.fund_house,
       EXCLUDED.category, EXCLUDED.isin_growth)
"""

# Replace the whole watchlist with the CSV's contents. The JOIN keeps only codes that exist
# in schemes (the foreign key would reject others); the coverage check reports those.
SYNC_WATCHLIST = """
INSERT INTO watchlist (scheme_code, category)
SELECT w.scheme_code, w.category
FROM unnest(%s::int[], %s::text[]) AS w (scheme_code, category)
JOIN schemes s ON s.scheme_code = w.scheme_code
"""

UPSERT_NAV = """
INSERT INTO nav_history (scheme_code, nav_date, nav)
VALUES (%s, %s, %s)
ON CONFLICT (scheme_code, nav_date) DO UPDATE SET nav = EXCLUDED.nav
WHERE nav_history.nav IS DISTINCT FROM EXCLUDED.nav
"""

# Backfill: the daily AMFI file is the official source, so never overwrite what's stored.
INSERT_NAV_IF_MISSING = """
INSERT INTO nav_history (scheme_code, nav_date, nav)
VALUES (%s, %s, %s)
ON CONFLICT (scheme_code, nav_date) DO NOTHING
"""

INSERT_QUARANTINE = "INSERT INTO quarantine (run_id, raw_line, reason) VALUES (%s, %s, %s)"


class InsertStats(NamedTuple):
    inserted: int  # new (scheme, date) rows
    already_stored: int  # rows we skipped because that date was already in nav_history
    mismatched: int  # of those, how many had a different NAV from the one stored


def _rows(df: pd.DataFrame, columns: list[str]) -> list[tuple]:
    """DataFrame -> list of tuples of plain Python values (int, str, Decimal, date, None)."""
    return list(df[columns].astype(object).itertuples(index=False, name=None))


def _quarantine_rows(run_id: int, result: TransformResult) -> list[tuple]:
    return [(run_id, *row) for row in _rows(result.quarantined, ["raw_line", "reason"])]


def start_run(conn: psycopg.Connection, run_type: str = "daily") -> int:
    with conn.transaction():
        return conn.execute(START_RUN, (run_type,)).fetchone()[0]


def finish_run(
    conn: psycopg.Connection,
    run_id: int,
    status: str,
    rows_loaded: int = 0,
    rows_quarantined: int = 0,
    error: str | None = None,
    warnings: str | None = None,
) -> None:
    with conn.transaction():
        conn.execute(FINISH_RUN, (status, rows_loaded, rows_quarantined, error, warnings, run_id))


def save_raw_lines(conn: psycopg.Connection, run_id: int, lines: list[str]) -> None:
    """Store every line exactly as received. COPY streams them in one go (fast for 18k lines)."""
    with conn.transaction(), conn.cursor() as cur:
        with cur.copy("COPY raw_nav (run_id, line_no, raw_line) FROM STDIN") as copy:
            for line_no, line in enumerate(lines, start=1):
                copy.write_row((run_id, line_no, line))


def load_day(conn: psycopg.Connection, run_id: int, result: TransformResult) -> None:
    """Upsert schemes, then NAVs, then record quarantined rows — all or nothing."""
    schemes = result.clean.drop_duplicates("scheme_code", keep="last")
    scheme_rows = _rows(schemes, SCHEME_COLUMNS)
    nav_rows = _rows(result.clean, ["scheme_code", "nav_date", "nav"])

    with conn.transaction(), conn.cursor() as cur:
        # schemes first: nav_history.scheme_code is a foreign key to schemes
        cur.executemany(UPSERT_SCHEME, scheme_rows)
        cur.executemany(UPSERT_NAV, nav_rows)
        cur.executemany(INSERT_QUARANTINE, _quarantine_rows(run_id, result))


def insert_missing_navs(
    conn: psycopg.Connection, run_id: int, result: TransformResult
) -> InsertStats:
    """Backfill: add NAVs for dates we don't have yet; leave stored ones alone — all or nothing.

    Schemes are not touched: the daily file owns their names and categories.
    """
    nav_rows = _rows(result.clean, ["scheme_code", "nav_date", "nav"])
    codes = sorted({row[0] for row in nav_rows})

    with conn.transaction(), conn.cursor() as cur:
        stored = {
            (code, day): nav
            for code, day, nav in cur.execute(
                "SELECT scheme_code, nav_date, nav FROM nav_history WHERE scheme_code = ANY(%s)",
                (codes,),
            )
        }
        new_rows = [row for row in nav_rows if (row[0], row[1]) not in stored]
        # Decimal comparison ignores trailing zeros: 1158.60900 == 1158.609
        mismatched = sum(
            1 for code, day, nav in nav_rows if (code, day) in stored and stored[code, day] != nav
        )
        cur.executemany(INSERT_NAV_IF_MISSING, new_rows)
        cur.executemany(INSERT_QUARANTINE, _quarantine_rows(run_id, result))

    return InsertStats(len(new_rows), len(nav_rows) - len(new_rows), mismatched)


def sync_watchlist(conn: psycopg.Connection, watchlist: dict[int, str]) -> None:
    """Make the watchlist table match data/watchlist.csv exactly."""
    with conn.transaction():
        conn.execute("DELETE FROM watchlist")
        conn.execute(SYNC_WATCHLIST, (list(watchlist), list(watchlist.values())))
