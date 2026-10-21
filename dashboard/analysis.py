"""Calculations on a chosen date range. Pure pandas: no database and no Streamlit, so they
can be unit-tested directly. Input: a DataFrame with scheme_code, nav_date, nav (floats)."""

import pandas as pd


def _sorted(navs: pd.DataFrame) -> pd.DataFrame:
    return navs.sort_values(["scheme_code", "nav_date"]).reset_index(drop=True)


def rebase(navs: pd.DataFrame) -> pd.DataFrame:
    """Add `value`: each fund's NAV scaled so its first NAV in the range is 100.

    Two funds with NAVs of 1,150 and 66 can then share one axis: both lines show what
    ₹100 invested at the start of the range would have become.
    """
    out = _sorted(navs)
    first = out.groupby("scheme_code")["nav"].transform("first")
    out["value"] = out["nav"] / first * 100
    return out


def drawdown(navs: pd.DataFrame) -> pd.DataFrame:
    """Add `running_peak` and `drawdown`, with the peak starting fresh at the range start."""
    out = _sorted(navs)
    out["running_peak"] = out.groupby("scheme_code")["nav"].cummax()
    out["drawdown"] = out["nav"] / out["running_peak"] - 1
    return out


def period_stats(navs: pd.DataFrame) -> pd.DataFrame:
    """One row per scheme_code: start/end date, return over the range, worst drawdown in it."""
    by_fund = drawdown(navs).groupby("scheme_code")
    return pd.DataFrame(
        {
            "start_date": by_fund["nav_date"].first(),
            "end_date": by_fund["nav_date"].last(),
            "period_return": by_fund["nav"].last() / by_fund["nav"].first() - 1,
            "max_drawdown": by_fund["drawdown"].min(),
        }
    )
