"""Tests for the data-quality checks."""

from datetime import date

import pytest

from pipeline import checks, load
from pipeline.config import WATCHLIST_CATEGORIES, read_watchlist
from pipeline.transform import parse_nav_lines

NEWEST_IN_FIXTURE = date(2026, 10, 21)


@pytest.fixture
def result(fixture_lines):
    return parse_nav_lines(fixture_lines)


# --- freshness -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("today", "passed"),
    [
        (date(2026, 10, 21), True),  # same day
        (date(2026, 10, 25), True),  # 4 days old: still OK
        (date(2026, 10, 26), False),  # 5 days old: stale
    ],
)
def test_freshness(result, today, passed):
    r = checks.check_freshness(result, today=today)
    assert (r.severity, r.passed) == ("fail", passed)
    assert "2026-10-21" in r.message


def test_freshness_fails_when_nothing_is_clean(result):
    empty = result._replace(clean=result.clean.iloc[0:0])
    assert not checks.check_freshness(empty, today=NEWEST_IN_FIXTURE).passed


# --- watchlist coverage ----------------------------------------------------------


def test_coverage_passes_when_every_watchlist_fund_has_the_newest_nav(result):
    r = checks.check_watchlist_coverage(result, {120465: "large-cap", 135762: "debt"})
    assert (r.severity, r.passed) == ("fail", True)


def test_coverage_fails_and_names_the_missing_funds(result):
    # 118553 is in the file but dated 2023; 999999 is not in the file at all.
    r = checks.check_watchlist_coverage(result, {120465: "x", 118553: "x", 999999: "x"})
    assert not r.passed
    assert "118553" in r.message and "999999" in r.message and "120465" not in r.message


# --- volume ------------------------------------------------------------------------


def test_volume_is_skipped_on_the_first_run(conn):
    r = checks.check_volume(conn, load.start_run(conn), rows_now=15)
    assert r.passed
    assert "no previous successful run" in r.message


def test_volume_compares_with_the_last_successful_run(conn):
    earlier = load.start_run(conn)
    load.finish_run(conn, earlier, "success", rows_loaded=100)
    failed = load.start_run(conn)
    load.finish_run(conn, failed, "failed", rows_loaded=5)  # failed runs are ignored
    now = load.start_run(conn)

    assert checks.check_volume(conn, now, rows_now=90).passed  # exactly 90%
    assert not checks.check_volume(conn, now, rows_now=89).passed


# --- big moves -----------------------------------------------------------------------


def seed_navs(conn, navs: dict[int, list[tuple[str, str]]]):
    for code, series in navs.items():
        conn.execute(
            "INSERT INTO schemes (scheme_code, scheme_name) VALUES (%s, %s)", (code, f"Fund {code}")
        )
        for day, nav in series:
            conn.execute("INSERT INTO nav_history VALUES (%s, %s, %s)", (code, day, nav))


def test_big_move_warns_only_for_watchlist_funds_above_20_percent(conn):
    seed_navs(
        conn,
        {
            100001: [("2026-10-16", "10"), ("2026-10-19", "12.5")],  # +25% (over a weekend)
            100002: [("2026-10-16", "10"), ("2026-10-19", "11")],  # +10%
            100003: [("2026-10-16", "10"), ("2026-10-19", "20")],  # +100%, not on the watchlist
            100004: [("2026-10-16", "10"), ("2026-10-19", "7.9")],  # -21%
            100005: [("2026-10-19", "10")],  # only one NAV: nothing to compare
        },
    )
    r = checks.check_big_moves(conn, [100001, 100002, 100004, 100005])

    assert (r.severity, r.passed) == ("warn", False)
    assert "100001" in r.message and "100004" in r.message
    assert "100002" not in r.message and "100003" not in r.message


def test_big_move_passes_with_no_history(conn):
    assert checks.check_big_moves(conn, [100001]).passed


# --- the watchlist file itself -------------------------------------------------------


def test_watchlist_csv_is_valid():
    watchlist = read_watchlist()  # raises on duplicate codes or unknown categories
    assert 25 <= len(watchlist) <= 35
    assert set(watchlist.values()) == set(WATCHLIST_CATEGORIES)
