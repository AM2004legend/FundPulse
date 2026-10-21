"""Tests for the mfapi.in backfill. Network is faked; the cache lives in pytest's tmp_path."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fakes import FakeResponse, FakeSession

from pipeline.backfill import BackfillError, backfill, fetch_history, to_navall_lines
from pipeline.transform import parse_nav_lines

FIXTURE = Path(__file__).parent / "fixtures" / "mfapi_sample.json"
TODAY = date(2026, 10, 22)
SINCE = date(2023, 10, 22)  # 3 years before TODAY


@pytest.fixture
def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- adapter: mfapi JSON -> NAVAll-style lines -------------------------------------


def test_adapter_builds_navall_lines_oldest_first_within_cutoff(sample):
    lines = to_navall_lines(sample, since=SINCE)

    assert lines[1] == "Open Ended Schemes(Equity Scheme - Large Cap Fund)"
    assert lines[2] == "HDFC Mutual Fund"
    assert lines[3] == (
        "119018;INF179K01YV8;-;HDFC Large Cap Fund - Direct Plan - Growth Option;;;"
        "911.54600;23-Oct-2023"
    )
    dates = [line.split(";")[7] for line in lines[3:]]
    # 20-Oct-2023 is before the cutoff and 01-Jan-2013 far before it: both dropped
    assert dates == [
        "23-Oct-2023",
        "13-Oct-2026",
        "14-Oct-2026",
        "15-Oct-2026",
        "16-Oct-2026",
        "19-Oct-2026",
    ]


def test_adapter_output_goes_through_the_normal_parser(sample):
    result = parse_nav_lines(to_navall_lines(sample, since=SINCE))

    assert len(result.clean) == 5
    assert list(result.quarantined["reason"]) == ["nav is not a number: 'N.A.'"]
    first = result.clean.iloc[0]
    assert (first["nav_date"], first["nav"]) == (date(2023, 10, 23), Decimal("911.546"))


def test_adapter_passes_unparseable_dates_through_for_quarantine(sample):
    sample["data"] = [{"date": "2026/10/19", "nav": "10.5"}]
    result = parse_nav_lines(to_navall_lines(sample, since=SINCE))
    assert list(result.quarantined["reason"]) == ["date is not DD-Mon-YYYY: '2026/10/19'"]


# --- fetching + cache --------------------------------------------------------------------


def test_fetch_downloads_once_then_uses_the_cache(sample, tmp_path):
    body = json.dumps(sample).encode()
    data, from_cache = fetch_history(
        119018, session=FakeSession(FakeResponse(200, body)), cache_dir=tmp_path
    )
    assert (data, from_cache) == (sample, False)
    assert (tmp_path / "119018.json").exists()

    # FakeSession() with no outcomes fails the test if any request is made
    data, from_cache = fetch_history(119018, session=FakeSession(), cache_dir=tmp_path)
    assert (data, from_cache) == (sample, True)

    session = FakeSession(FakeResponse(200, body))
    fetch_history(119018, session=session, cache_dir=tmp_path, refresh=True)
    assert len(session.calls) == 1
    assert session.calls[0][0] == "https://api.mfapi.in/mf/119018"


def test_fetch_rejects_an_empty_answer_and_does_not_cache_it(tmp_path):
    empty = FakeResponse(200, b'{"meta": {}, "data": [], "status": "SUCCESS"}')
    with pytest.raises(BackfillError, match="no NAV history"):
        fetch_history(999999, session=FakeSession(empty), cache_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


# --- the whole backfill against the test database ------------------------------------------


def seed_scheme(conn, code):
    conn.execute("INSERT INTO schemes (scheme_code, scheme_name) VALUES (%s, %s)", (code, "x"))


def cache(tmp_path, sample):
    (tmp_path / f"{sample['meta']['scheme_code']}.json").write_text(json.dumps(sample))


def do_backfill(test_db_url, tmp_path, watchlist, session=None):
    return backfill(
        watchlist=watchlist,
        database_url=test_db_url,
        cache_dir=tmp_path,
        today=TODAY,
        session=session or FakeSession(),
        sleep=lambda seconds: None,
    )


def run_row(conn, run_id):
    return conn.execute(
        "SELECT run_type, status, rows_loaded, rows_quarantined, error, warnings "
        "FROM pipeline_runs WHERE run_id = %s",
        (run_id,),
    ).fetchone()


def nav_count(conn):
    return conn.execute("SELECT count(*) FROM nav_history").fetchone()[0]


def test_backfill_loads_history_and_a_rerun_inserts_nothing(conn, test_db_url, tmp_path, sample):
    seed_scheme(conn, 119018)
    cache(tmp_path, sample)

    first = do_backfill(test_db_url, tmp_path, {119018: "large-cap"})
    assert run_row(conn, first) == ("backfill", "success", 5, 1, None, None)
    assert nav_count(conn) == 5

    second = do_backfill(test_db_url, tmp_path, {119018: "large-cap"})
    assert run_row(conn, second)[2] == 0  # rows_loaded: nothing new
    assert nav_count(conn) == 5


def test_backfill_never_overwrites_a_stored_nav_and_reports_the_mismatch(
    conn, test_db_url, tmp_path, sample
):
    seed_scheme(conn, 119018)
    conn.execute("INSERT INTO nav_history VALUES (119018, '2026-10-16', '1172.5')")  # differs
    conn.execute("INSERT INTO nav_history VALUES (119018, '2026-10-19', '1158.609')")  # same
    cache(tmp_path, sample)

    run_id = do_backfill(test_db_url, tmp_path, {119018: "large-cap"})

    _, status, rows_loaded, _, _, warnings = run_row(conn, run_id)
    assert (status, rows_loaded) == ("success", 3)
    assert warnings == "119018: 1 date(s) differ from the stored NAV, kept the stored value"
    stored = conn.execute(
        "SELECT nav FROM nav_history WHERE scheme_code = 119018 AND nav_date = '2026-10-16'"
    ).fetchone()[0]
    assert stored == Decimal("1172.5")


def test_one_failing_fund_does_not_stop_the_others(conn, test_db_url, tmp_path, sample):
    seed_scheme(conn, 119018)
    cache(tmp_path, sample)

    with pytest.raises(BackfillError, match="999999"):
        do_backfill(test_db_url, tmp_path, {999999: "index", 119018: "large-cap"})

    (run_id,) = conn.execute("SELECT run_id FROM pipeline_runs").fetchone()
    _, status, rows_loaded, _, error, _ = run_row(conn, run_id)
    assert (status, rows_loaded) == ("failed", 5)
    assert error.startswith("999999: not in schemes yet")
    assert nav_count(conn) == 5
