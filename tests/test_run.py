"""End-to-end tests of one pipeline run, with the download replaced by the fixture."""

import pytest

from pipeline import run as run_module
from pipeline.extract import DownloadError
from pipeline.run import run


def run_row(conn, run_id):
    return conn.execute(
        "SELECT status, rows_loaded, rows_quarantined, error, finished_at IS NOT NULL "
        "FROM pipeline_runs WHERE run_id = %s",
        (run_id,),
    ).fetchone()


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_successful_run_is_logged(conn, test_db_url, fixture_lines):
    run_id = run(fetch=lambda: fixture_lines, database_url=test_db_url)

    assert run_row(conn, run_id) == ("success", 15, 3, None, True)
    assert count(conn, "raw_nav") == len(fixture_lines) == 46
    assert count(conn, "nav_history") == 15


def test_failed_download_is_logged_and_loads_nothing(conn, test_db_url):
    def broken_fetch():
        raise DownloadError("AMFI is down")

    with pytest.raises(DownloadError):
        run(fetch=broken_fetch, database_url=test_db_url)

    (run_id,) = conn.execute("SELECT run_id FROM pipeline_runs").fetchone()
    status, rows_loaded, _, error, finished = run_row(conn, run_id)
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
        run(fetch=lambda: fixture_lines, database_url=test_db_url)

    assert conn.execute("SELECT status FROM pipeline_runs").fetchone() == ("failed",)
    assert count(conn, "raw_nav") == 46  # saved in its own transaction, before the load
    assert count(conn, "nav_history") == 0
