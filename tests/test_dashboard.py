"""Dashboard tests: pure calculations, plus every page run headlessly against the test DB."""

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard"
sys.path.insert(0, str(DASHBOARD))  # how `streamlit run dashboard/app.py` sees its modules

import analysis  # noqa: E402
import charts  # noqa: E402

DISCLAIMER = "For learning only. Not investment advice. Past returns don't predict future returns."


# --- pure calculations (no database, no Streamlit) --------------------------------------


def navs(rows):
    return pd.DataFrame(rows, columns=["scheme_code", "nav_date", "nav"])


SERIES = navs(
    [
        (1, date(2026, 1, 5), 100.0),
        (1, date(2026, 1, 6), 110.0),
        (1, date(2026, 1, 7), 99.0),
        (1, date(2026, 1, 9), 121.0),
        (2, date(2026, 1, 6), 50.0),
        (2, date(2026, 1, 8), 55.0),
    ]
)


def test_rebase_starts_every_fund_at_100():
    out = analysis.rebase(SERIES)
    assert out[out.scheme_code == 1]["value"].tolist() == pytest.approx([100, 110, 99, 121])
    assert out[out.scheme_code == 2]["value"].tolist() == pytest.approx([100, 110])


def test_drawdown_is_measured_from_the_peak_within_the_range():
    out = analysis.drawdown(SERIES)
    assert out[out.scheme_code == 1]["drawdown"].tolist() == pytest.approx([0, 0, -0.1, 0])

    # Starting the range at the 99 NAV: that is the first peak, so no drawdown is shown,
    # even though the all-time drawdown on that day was -10%.
    later = SERIES[SERIES.nav_date >= date(2026, 1, 7)]
    out = analysis.drawdown(later)
    assert out[out.scheme_code == 1]["drawdown"].tolist() == pytest.approx([0, 0])


def test_period_stats():
    stats = analysis.period_stats(SERIES)
    assert stats.loc[1, "period_return"] == pytest.approx(0.21)  # 121 / 100 - 1
    assert stats.loc[1, "max_drawdown"] == pytest.approx(-0.1)
    assert stats.loc[2, "period_return"] == pytest.approx(0.1)
    assert stats.loc[2, "max_drawdown"] == pytest.approx(0)


def test_chart_colour_follows_the_picked_order_not_the_data_order():
    df = SERIES.assign(fund=SERIES["scheme_code"].map({1: "Zeta Fund", 2: "Alpha Fund"}))
    spec = charts.line_chart(df, "nav", "NAV", ",.2f", ["Zeta Fund", "Alpha Fund"]).to_dict()

    line = next(layer for layer in spec["layer"] if layer["mark"]["type"] == "line")
    scale = line["encoding"]["color"]["scale"]
    assert scale["domain"] == ["Zeta Fund", "Alpha Fund"]
    assert scale["range"][0] == "#2a78d6"  # the first-picked fund is always slot-1 blue


# --- the app, end to end ---------------------------------------------------------------------

FUNDS = [
    # code, name, fund house, watchlist category, first NAV, daily step
    (900001, "Alpha Large Cap Fund", "Alpha Mutual Fund", "large-cap", 100.0, 0.05),
    (900002, "Beta Large Cap Fund", "Beta Mutual Fund", "large-cap", 50.0, 0.01),
    (900003, "Gamma Nifty 50 Index Fund", "Gamma Mutual Fund", "index", 20.0, 0.02),
]
LATEST = date(2026, 10, 21)


def seed(conn):
    days = [LATEST - timedelta(days=n) for n in range(450)]
    weekdays = sorted(d for d in days if d.weekday() < 5)
    with conn.cursor() as cur:
        for code, name, house, category, start, step in FUNDS:
            cur.execute(
                "INSERT INTO schemes (scheme_code, scheme_name, plan_type, option_type, "
                "fund_house) VALUES (%s, %s, 'Direct Plan', 'Growth', %s)",
                (code, name, house),
            )
            cur.execute("INSERT INTO watchlist VALUES (%s, %s)", (code, category))
            cur.executemany(
                "INSERT INTO nav_history VALUES (%s, %s, %s)",
                [(code, d, round(start + i * step, 4)) for i, d in enumerate(weekdays)],
            )
        cur.execute(
            "INSERT INTO pipeline_runs (run_type, status, finished_at, rows_loaded) "
            "VALUES ('backfill', 'success', now(), 900), ('daily', 'success', now(), 14000)"
        )
        cur.execute(
            "INSERT INTO pipeline_runs (run_type, status, finished_at, error) "
            "VALUES ('daily', 'failed', now(), 'DownloadError: AMFI is down')"
        )


@pytest.fixture
def app(conn, test_db_url, monkeypatch):
    """Returns a function that builds the app pointed at the (empty) test database."""
    monkeypatch.setenv("DATABASE_URL", test_db_url)
    st.cache_data.clear()  # cached query results from an earlier test must not leak in
    return lambda: AppTest.from_file(str(DASHBOARD / "app.py"), default_timeout=30)


def open_page(app, page=None):
    at = app()
    if page:
        at.switch_page(page)
    at.run()
    assert not at.exception, at.exception
    return at


def texts(at):
    return " ".join(e.value for e in [*at.caption, *at.markdown, *at.info, *at.error])


@pytest.mark.parametrize("page", [None, "pages/fund_detail.py", "pages/pipeline_health.py"])
def test_every_page_shows_the_data_date_and_disclaimer(app, conn, page):
    seed(conn)
    at = open_page(app, page)
    assert "Data as of 21 Oct 2026" in texts(at)
    assert DISCLAIMER in texts(at)


def test_compare_lists_the_funds_of_the_chosen_category(app, conn):
    seed(conn)
    at = open_page(app)

    table = at.dataframe[0].value
    assert table["Fund"].tolist() == ["Alpha Large Cap Fund", "Beta Large Cap Fund"]  # best first
    assert table["1-yr return"].notna().all() and table["Max drawdown"].notna().all()

    at.radio[0].set_value("index").run()
    assert at.dataframe[0].value["Fund"].tolist() == ["Gamma Nifty 50 Index Fund"]
    assert any(button.proto.label == "Download CSV" for button in at.get("download_button"))


def chart_elements(at):
    return at.get("vega_lite_chart")  # AppTest has no typed wrapper for Altair charts


def test_fund_detail_draws_nav_and_drawdown_charts_for_one_or_two_funds(app, conn):
    seed(conn)
    at = open_page(app, "pages/fund_detail.py")
    assert len(chart_elements(at)) == 2
    assert len(at.metric) == 2  # return + max drawdown for one fund

    at.selectbox(key="other_fund").set_value(900002).run()
    assert not at.exception
    assert len(chart_elements(at)) == 2
    assert len(at.metric) == 4  # two funds
    assert [s.value for s in at.subheader][0] == "Growth of ₹100"  # rebased, one shared axis


def test_range_starts_at_the_last_nav_on_or_before_the_start_date(app, conn):
    # Same rule as v_fund_metrics' 1-year base, so Fund detail and Compare agree.
    import queries

    seed(conn)
    saturday = date(2026, 10, 17)
    rows = queries.navs((900001,), saturday, LATEST)
    assert rows["nav_date"].iloc[0] == date(2026, 10, 16)  # the Friday before
    assert rows["nav_date"].iloc[-1] == LATEST


def test_fund_detail_default_return_matches_compare(app, conn):
    seed(conn)
    compare = open_page(app).dataframe[0].value.set_index("Fund")
    detail = open_page(app, "pages/fund_detail.py")  # default: first large-cap fund, last year
    assert detail.metric[0].value == f"{compare.loc['Alpha Large Cap Fund', '1-yr return']:+.2f}%"


def test_pipeline_health_shows_recent_runs_and_the_failed_runs_error(app, conn):
    seed(conn)
    at = open_page(app, "pages/pipeline_health.py")
    assert len(at.dataframe[0].value) == 3
    assert "DownloadError: AMFI is down" in texts(at)


def test_empty_database_shows_a_message_instead_of_crashing(app):
    for page in [None, "pages/fund_detail.py", "pages/pipeline_health.py"]:
        at = open_page(app, page)
        assert "No data yet" in texts(at)
