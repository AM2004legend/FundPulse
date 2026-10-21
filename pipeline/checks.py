"""Data-quality checks, run after each daily load.

A failed "fail" check marks the run failed (exit code 1) but keeps the loaded data:
loads are upserts that never delete, so a suspicious file can't destroy history.
The checks are there to alert a human. "warn" checks are recorded but never fail a run.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import psycopg

from pipeline.transform import TransformResult

IST = timezone(timedelta(hours=5, minutes=30))  # India has no daylight saving: fixed offset
VOLUME_MIN_PERCENT = 90
MAX_AGE_DAYS = 4
BIG_MOVE = Decimal("0.20")

# For each fund: its newest NAV and the NAV on its previous available date (LAG), so a
# move over a weekend or holiday still counts as one step.
BIG_MOVES_SQL = """
WITH ranked AS (
    SELECT scheme_code, nav_date, nav,
           LAG(nav) OVER (PARTITION BY scheme_code ORDER BY nav_date) AS prev_nav,
           ROW_NUMBER() OVER (PARTITION BY scheme_code ORDER BY nav_date DESC) AS newest_first
    FROM nav_history
    WHERE scheme_code = ANY(%s)
)
SELECT scheme_code, nav_date, nav / prev_nav - 1 AS change
FROM ranked
WHERE newest_first = 1 AND prev_nav IS NOT NULL AND abs(nav / prev_nav - 1) > %s
ORDER BY scheme_code
"""


@dataclass(frozen=True)
class CheckResult:
    name: str
    severity: str  # "fail" or "warn"
    passed: bool
    message: str


def today_in_india() -> date:
    return datetime.now(IST).date()


def _newest_date(result: TransformResult) -> date | None:
    return None if result.clean.empty else result.clean["nav_date"].max()


def check_volume(conn: psycopg.Connection, run_id: int, rows_now: int) -> CheckResult:
    """Fail if this run has under 90% of the rows of the last successful daily run.

    Backfill runs load a different amount of data, so they are not a valid baseline.
    """
    row = conn.execute(
        "SELECT rows_loaded FROM pipeline_runs "
        "WHERE run_type = 'daily' AND status = 'success' AND run_id < %s "
        "ORDER BY run_id DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    if row is None:
        return CheckResult("volume", "fail", True, f"{rows_now} rows; no previous successful run")

    previous = row[0]
    # Integer maths: 0.9 * 100 is 90.00000000000001 in floating point.
    passed = rows_now * 100 >= previous * VOLUME_MIN_PERCENT
    message = f"{rows_now} rows vs {previous} last time (minimum {VOLUME_MIN_PERCENT}%)"
    return CheckResult("volume", "fail", passed, message)


def check_watchlist_coverage(result: TransformResult, watchlist: dict[int, str]) -> CheckResult:
    """Fail if any watchlist fund has no NAV for the file's newest date."""
    newest = _newest_date(result)
    clean = result.clean
    have = set(clean.loc[clean["nav_date"] == newest, "scheme_code"]) if newest else set()
    missing = sorted(set(watchlist) - have)

    if missing:
        listed = ", ".join(map(str, missing))
        message = f"{len(missing)} of {len(watchlist)} have no NAV for {newest}: {listed}"
    else:
        message = f"all {len(watchlist)} watchlist funds have a NAV for {newest}"
    return CheckResult("watchlist_coverage", "fail", not missing, message)


def check_freshness(result: TransformResult, today: date) -> CheckResult:
    """Fail if the newest NAV date in the file is more than 4 days old (AMFI file not updated)."""
    newest = _newest_date(result)
    if newest is None:
        return CheckResult("freshness", "fail", False, "no valid NAV rows in the file")

    age = (today - newest).days
    message = f"newest NAV date {newest} is {age} days old (limit {MAX_AGE_DAYS})"
    return CheckResult("freshness", "fail", age <= MAX_AGE_DAYS, message)


def check_big_moves(conn: psycopg.Connection, scheme_codes: list[int]) -> CheckResult:
    """Warn if a watchlist fund's newest NAV moved more than 20% from its previous NAV."""
    rows = conn.execute(BIG_MOVES_SQL, (scheme_codes, BIG_MOVE)).fetchall()
    if not rows:
        return CheckResult("big_move", "warn", True, f"no watchlist fund moved over {BIG_MOVE:.0%}")

    moves = ", ".join(f"{code} {change:+.1%} on {day}" for code, day, change in rows)
    return CheckResult("big_move", "warn", False, f"moved over {BIG_MOVE:.0%}: {moves}")


def run_checks(
    conn: psycopg.Connection,
    run_id: int,
    result: TransformResult,
    watchlist: dict[int, str],
    today: date,
) -> list[CheckResult]:
    return [
        check_volume(conn, run_id, len(result.clean)),
        check_watchlist_coverage(result, watchlist),
        check_freshness(result, today),
        check_big_moves(conn, list(watchlist)),
    ]
