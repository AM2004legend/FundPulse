"""Database access for the dashboard: read-only, views only, cached for 10 minutes.

The dashboard doesn't import the pipeline package. Its only contract with the pipeline is
the views in sql/views.sql, so it can be deployed on its own (Streamlit Community Cloud).
"""

import os
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg
import streamlit as st
from dotenv import load_dotenv

# Local development reads .env. On Streamlit Cloud, DATABASE_URL comes from the app's Secrets
# (Streamlit exposes top-level secrets as environment variables).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CACHE_SECONDS = 600


def _read(sql: str, params: tuple | dict = ()) -> pd.DataFrame:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (.env locally, Secrets on Streamlit Cloud).")
    # A short-lived connection per (cached) query: no stale connections to a hosted database.
    with psycopg.connect(url, connect_timeout=10) as conn:
        conn.read_only = True  # the dashboard can never change data, even by mistake
        cur = conn.execute(sql, params)
        return pd.DataFrame(cur.fetchall(), columns=[col.name for col in cur.description])


def _floats(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """NUMERIC arrives as Decimal (exact). Charts and formatting want floats; display only."""
    for col in columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    return df


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def data_as_of() -> date | None:
    """Newest NAV date across the watchlist, or None when nothing has been loaded."""
    value = _read("SELECT max(latest_date) AS as_of FROM v_fund_metrics")["as_of"].iloc[0]
    return None if pd.isna(value) else value


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def fund_metrics() -> pd.DataFrame:
    df = _read("SELECT * FROM v_fund_metrics")
    return _floats(
        df, ["latest_nav", "nav_1y_ago", "return_1y", "volatility_1y", "max_drawdown_1y"]
    )


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def nav_range(scheme_code: int) -> tuple[date, date]:
    row = _read(
        "SELECT min(nav_date) AS first, max(nav_date) AS last FROM v_drawdown "
        "WHERE scheme_code = %s",
        (scheme_code,),
    ).iloc[0]
    return row["first"], row["last"]


# Each fund's range starts at its last NAV on or before `start` - the same rule the views use
# for the 1-year base - so a range that starts on a weekend or holiday still has a start
# value, and Fund detail's default "last year" return matches the Compare page.
NAVS_SQL = """
SELECT d.scheme_code, d.nav_date, d.nav
FROM unnest(%(codes)s::int[]) AS f (scheme_code)
CROSS JOIN LATERAL (
    SELECT coalesce(max(nav_date), %(start)s::date) AS first_date
    FROM v_drawdown
    WHERE scheme_code = f.scheme_code AND nav_date <= %(start)s::date
) s
JOIN v_drawdown d
  ON d.scheme_code = f.scheme_code
 AND d.nav_date BETWEEN s.first_date AND %(end)s::date
ORDER BY d.scheme_code, d.nav_date
"""


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def navs(scheme_codes: tuple[int, ...], start: date, end: date) -> pd.DataFrame:
    df = _read(NAVS_SQL, {"codes": list(scheme_codes), "start": start, "end": end})
    return _floats(df, ["nav"])


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def pipeline_runs(limit: int = 30) -> pd.DataFrame:
    df = _read("SELECT * FROM v_pipeline_runs ORDER BY run_id DESC LIMIT %s", (limit,))
    return _floats(df, ["duration_seconds"])
