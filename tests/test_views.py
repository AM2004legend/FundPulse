"""Tests for sql/views.sql on tiny hand-made NAV series whose answers can be worked out by hand."""

from datetime import date
from decimal import Decimal


def seed(conn, code, navs, watchlist_category=None):
    conn.execute(
        "INSERT INTO schemes (scheme_code, scheme_name) VALUES (%s, %s)", (code, f"Fund {code}")
    )
    for day, nav in navs:
        conn.execute("INSERT INTO nav_history VALUES (%s, %s, %s)", (code, day, nav))
    if watchlist_category:
        conn.execute("INSERT INTO watchlist VALUES (%s, %s)", (code, watchlist_category))


def r8(x):
    """Round to 8 decimal places so database and hand-computed Decimals compare cleanly."""
    return None if x is None else round(x, 8)


def d(text):
    return date.fromisoformat(text)


# Mon, Tue, Wed, (Thu is a holiday), Fri, Mon
FUND_A = [
    ("2026-01-05", "100"),
    ("2026-01-06", "110"),
    ("2026-01-07", "99"),
    ("2026-01-09", "121"),
    ("2026-01-12", "121"),
]
# Dates interleave with FUND_A's
FUND_B = [("2026-01-06", "50"), ("2026-01-08", "55")]


# --- v_daily_returns -----------------------------------------------------------------


def daily_returns(conn, code):
    rows = conn.execute(
        "SELECT nav_date, prev_nav_date, daily_return FROM v_daily_returns "
        "WHERE scheme_code = %s ORDER BY nav_date",
        (code,),
    ).fetchall()
    return [(day, prev, r8(ret)) for day, prev, ret in rows]


def test_daily_return_uses_the_previous_available_date(conn):
    seed(conn, 1, FUND_A)

    assert daily_returns(conn, 1) == [
        (d("2026-01-05"), None, None),  # first NAV: nothing to compare with
        (d("2026-01-06"), d("2026-01-05"), Decimal("0.1")),  # 110 / 100 - 1
        (d("2026-01-07"), d("2026-01-06"), Decimal("-0.1")),  # 99 / 110 - 1
        (d("2026-01-09"), d("2026-01-07"), r8(Decimal(121) / 99 - 1)),  # skips the holiday
        (d("2026-01-12"), d("2026-01-09"), Decimal("0")),  # over the weekend: one step
    ]


def test_partition_by_keeps_funds_separate(conn):
    # Without PARTITION BY scheme_code, LAG would look at the previous row of *any* fund:
    # fund 2's first NAV would get a "return" against fund 1's NAV.
    seed(conn, 1, FUND_A)
    seed(conn, 2, FUND_B)

    assert daily_returns(conn, 2) == [
        (d("2026-01-06"), None, None),
        (d("2026-01-08"), d("2026-01-06"), Decimal("0.1")),  # 55 / 50 - 1
    ]
    assert daily_returns(conn, 1)[2] == (d("2026-01-07"), d("2026-01-06"), Decimal("-0.1"))


# --- v_drawdown -----------------------------------------------------------------------


def test_drawdown_measures_the_fall_from_the_running_peak(conn):
    seed(conn, 1, FUND_A)
    rows = conn.execute(
        "SELECT running_peak, drawdown FROM v_drawdown WHERE scheme_code = 1 ORDER BY nav_date"
    ).fetchall()

    assert [(peak, r8(dd)) for peak, dd in rows] == [
        (Decimal(100), Decimal(0)),
        (Decimal(110), Decimal(0)),  # new peak
        (Decimal(110), Decimal("-0.1")),  # 99 / 110 - 1
        (Decimal(121), Decimal(0)),  # new peak
        (Decimal(121), Decimal(0)),
    ]


# --- v_fund_metrics ---------------------------------------------------------------------

# Returns are exactly 0, +1%, -1%, +1%, -1%:  mean 0, sample variance 4 * 0.01² / 4 = 0.0001
FUND_VOL = [
    ("2025-10-01", "100"),  # the 1-year base (last NAV on or before 2025-10-21)
    ("2026-10-15", "100"),
    ("2026-10-16", "101"),
    ("2026-10-19", "99.99"),
    ("2026-10-20", "100.9899"),
    ("2026-10-21", "99.980001"),  # 100.9899 * 0.99
]
# 2025-10-21 has no NAV: the base must be 2025-10-20, not 2025-10-22 or 2025-10-17
FUND_BASE = [
    ("2025-10-17", "90"),
    ("2025-10-20", "100"),
    ("2025-10-22", "105"),
    ("2026-10-21", "120"),
]
# Lags behind the others: its window must start from ITS latest date (2026-10-19)
FUND_LAGGING = [("2025-10-16", "40"), ("2025-10-20", "50"), ("2026-10-19", "60")]
FUND_YOUNG = [("2026-06-01", "10"), ("2026-10-21", "11")]  # less than a year of history


def metrics(conn):
    rows = conn.execute(
        "SELECT scheme_code, category, latest_date, nav_1y_ago_date, return_1y, volatility_1y, "
        "max_drawdown_1y, n_returns FROM v_fund_metrics"
    ).fetchall()
    return {
        code: (cat, latest, base, r8(ret), r8(vol), r8(mdd), n)
        for code, cat, latest, base, ret, vol, mdd, n in rows
    }


def test_volatility_and_drawdown_match_hand_calculation(conn):
    seed(conn, 4, FUND_VOL, "index")

    expected_vol = Decimal("0.01") * Decimal(250).sqrt()  # sqrt(0.0001) * sqrt(250)
    worst = Decimal("99.980001") / Decimal("101") - 1  # lowest NAV vs the peak of 101
    assert metrics(conn)[4] == (
        "index",
        d("2026-10-21"),
        d("2025-10-01"),
        r8(Decimal("99.980001") / 100 - 1),
        r8(expected_vol),
        r8(worst),
        5,
    )


def test_one_year_return_uses_last_available_date_on_or_before_target(conn):
    seed(conn, 3, FUND_BASE, "large-cap")
    # base 2025-10-20 (100) -> 120: +20%. Window 100, 105, 120 never falls: drawdown 0.
    assert metrics(conn)[3][2:4] == (d("2025-10-20"), Decimal("0.2"))
    assert metrics(conn)[3][5:] == (Decimal(0), 2)


def test_each_fund_uses_its_own_latest_date(conn):
    seed(conn, 3, FUND_BASE, "large-cap")
    seed(conn, 6, FUND_LAGGING, "mid-cap")
    # Own target 2025-10-19 -> base 2025-10-16 (40) -> 60: +50%.
    # (Using the newest date overall, 2026-10-21, would wrongly pick 50 and give +20%.)
    assert metrics(conn)[6][1:4] == (d("2026-10-19"), d("2025-10-16"), Decimal("0.5"))


def test_fund_with_less_than_a_year_gets_no_metrics(conn):
    seed(conn, 5, FUND_YOUNG, "debt")
    assert metrics(conn)[5] == ("debt", d("2026-10-21"), None, None, None, None, None)


def test_only_watchlist_funds_appear(conn):
    seed(conn, 1, FUND_A)  # not on the watchlist
    seed(conn, 3, FUND_BASE, "large-cap")
    assert set(metrics(conn)) == {3}
