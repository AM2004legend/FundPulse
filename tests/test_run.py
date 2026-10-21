"""End-to-end tests of one pipeline run, with the download replaced by the fixture."""

from datetime import date

import pytest

from pipeline import run as run_module
from pipeline.extract import DownloadError
from pipeline.run import QualityCheckError, run

TODAY = date(2026, 10, 22)  # the fixture's newest NAV date is 21-Oct-2026
WATCHLIST = {120465: "large-cap", 135762: "debt"}


def run_row(conn, run_id):
    return conn.execute(
        "SELECT status, rows_loaded, rows_quarantined, error, warnings, finished_at IS NOT NULL "
        "FROM pipeline_runs WHERE run_id = %s",
        (run_id,),
    ).fetchone()


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def run_fixture(test_db_url, lines, watchlist=WATCHLIST):
    return run(fetch=lambda: lines, database_url=test_db_url, watchlist=watchlist, today=TODAY)


def test_successful_run_is_logged(conn, test_db_url, fixture_lines):
    run_id = run_fixture(test_db_url, fixture_lines)

    assert run_row(conn, run_id) == ("success", 15, 3, None, None, True)
    assert count(conn, "raw_nav") == len(fixture_lines) == 46
    assert count(conn, "nav_history") == 15
    assert count(conn, "watchlist") == 2


def test_failed_check_marks_run_failed_but_keeps_the_data(conn, test_db_url, fixture_lines):
    with pytest.raises(QualityCheckError, match="999999"):
        run_fixture(test_db_url, fixture_lines, watchlist={**WATCHLIST, 999999: "index"})

    (run_id,) = conn.execute("SELECT run_id FROM pipeline_runs").fetchone()
    status, rows_loaded, _, error, _, finished = run_row(conn, run_id)
    assert (status, rows_loaded, finished) == ("failed", 15, True)
    assert error.startswith("watchlist_coverage:")
    assert count(conn, "nav_history") == 15  # loads are upserts: safe to keep


def test_failed_download_is_logged_and_loads_nothing(conn, test_db_url):
    def broken_fetch():
        raise DownloadError("AMFI is down")

    with pytest.raises(DownloadError):
        run(fetch=broken_fetch, database_url=test_db_url, watchlist=WATCHLIST, today=TODAY)

    (run_id,) = conn.execute("SELECT run_id FROM pipeline_runs").fetchone()
    status, rows_loaded, _, error, _, finished = run_row(conn, run_id)
    assert (status, rows_loaded, finished) == ("failed", 0, True)
    assert error == "DownloadError: AMFI is down"
    assert count(conn, "nav_history") == 0


def test_failed_load_keeps_raw_lines_but_no_clean_data(
    conn, test_db_url, fixture_lines, monkeypatch
):
    def broken_load(*args):
        raise RuntimeError("disk full")

    monkeypatch.setattr(run_module, "load_day", broken_load)
    with pytest.raises(RuntimeError):
        run_fixture(test_db_url, fixture_lines)

    assert conn.execute("SELECT status FROM pipeline_runs").fetchone() == ("failed",)
    assert count(conn, "raw_nav") == 46  # saved in its own transaction, before the load
    assert count(conn, "nav_history") == 0
