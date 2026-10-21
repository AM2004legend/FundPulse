"""Tests for load.py against the test database."""

from decimal import Decimal

import psycopg
import pytest

from pipeline import load
from pipeline.transform import parse_nav_lines


@pytest.fixture
def result(fixture_lines):
    return parse_nav_lines(fixture_lines)


def counts(conn) -> dict[str, int]:
    tables = ["schemes", "nav_history", "quarantine"]
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


def load_new_run(conn, result):
    load.load_day(conn, load.start_run(conn), result)


def test_loading_the_same_day_twice_changes_nothing(conn, result):
    load_new_run(conn, result)
    first = counts(conn)
    load_new_run(conn, result)
    second = counts(conn)

    assert first["schemes"] == second["schemes"] == 15
    assert first["nav_history"] == second["nav_history"] == 15
    # quarantine is a per-run log, so each run adds its own 3 rows
    assert (first["quarantine"], second["quarantine"]) == (3, 6)


def test_changed_nav_is_updated_in_place(conn, result):
    load_new_run(conn, result)
    corrected = result._replace(clean=result.clean.copy())
    corrected.clean.loc[corrected.clean["scheme_code"] == 135762, "nav"] = Decimal("30.5")
    load_new_run(conn, corrected)

    nav = conn.execute("SELECT nav FROM nav_history WHERE scheme_code = 135762").fetchone()[0]
    assert nav == Decimal("30.5")
    assert counts(conn)["nav_history"] == 15


def test_eight_decimal_nav_is_stored_exactly(conn, result):
    load_new_run(conn, result)
    nav = conn.execute("SELECT nav FROM nav_history WHERE scheme_code = 108844").fetchone()[0]
    assert nav == Decimal("14.86269632")


def test_missing_values_are_stored_as_null_not_nan(conn, fixture_lines):
    # No fund house heading and an invalid ISIN: both must reach the database as NULL.
    header = fixture_lines[0]
    lines = [header, "Open Ended Schemes(Equity Scheme - Large Cap Fund)"]
    lines.append("100001;Redeemed;-;Fund A;;;10.5;21-Oct-2026")
    load_new_run(conn, parse_nav_lines(lines))

    row = conn.execute("SELECT fund_house, isin_growth FROM schemes WHERE scheme_code = 100001")
    assert row.fetchone() == (None, None)


def test_load_is_all_or_nothing(conn, result):
    # Sneak a NAV past the transform that the database's CHECK (nav > 0) rejects.
    # It is the very last row, so everything before it must be rolled back too.
    broken = result._replace(clean=result.clean.copy())
    broken.clean.loc[broken.clean.index[-1], "nav"] = Decimal("0")

    with pytest.raises(psycopg.errors.CheckViolation):
        load_new_run(conn, broken)

    assert counts(conn) == {"schemes": 0, "nav_history": 0, "quarantine": 0}


def watchlist_rows(conn):
    return conn.execute("SELECT scheme_code, category FROM watchlist ORDER BY 1").fetchall()


def test_sync_watchlist_replaces_contents_and_skips_unknown_codes(conn, result):
    load_new_run(conn, result)

    load.sync_watchlist(conn, {120465: "large-cap", 999999: "index"})
    assert watchlist_rows(conn) == [(120465, "large-cap")]  # 999999 isn't a known scheme

    load.sync_watchlist(conn, {135762: "debt"})
    assert watchlist_rows(conn) == [(135762, "debt")]  # the CSV is the source of truth


def test_reload_keeps_watchlist(conn, result):
    load_new_run(conn, result)
    load.sync_watchlist(conn, {120465: "large-cap"})
    load_new_run(conn, result)
    assert watchlist_rows(conn) == [(120465, "large-cap")]


def test_plan_and_option_are_stored(conn, result):
    load_new_run(conn, result)
    row = conn.execute(
        "SELECT scheme_name, plan_type, option_type FROM schemes WHERE scheme_code = 120465"
    ).fetchone()
    assert row == ("Axis Large Cap Fund", "Direct Plan", "Growth Option")


def test_raw_lines_are_saved_exactly(conn, fixture_lines):
    run_id = load.start_run(conn)
    load.save_raw_lines(conn, run_id, fixture_lines)

    rows = conn.execute(
        "SELECT line_no, raw_line FROM raw_nav WHERE run_id = %s ORDER BY line_no", (run_id,)
    ).fetchall()
    assert [r[1] for r in rows] == fixture_lines
    assert rows[1] == (2, " ")  # the single-space "blank" line survives
