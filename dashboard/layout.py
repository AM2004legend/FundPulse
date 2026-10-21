"""Pieces every page shares: the page header with the data date, and the disclaimer."""

from datetime import date

import streamlit as st

import queries

DISCLAIMER = "For learning only. Not investment advice. Past returns don't predict future returns."
CATEGORY_ORDER = ["large-cap", "flexi-cap", "mid-cap", "index", "debt"]


def page_header(title: str, intro: str) -> date | None:
    """Title, disclaimer and "Data as of <date>". Returns that date, or None if no data.

    Every page calls this first, so the disclaimer is on every page however it's opened.
    """
    st.title(title)
    st.caption(DISCLAIMER)
    as_of = queries.data_as_of()
    if as_of is None:
        st.info(
            "No data yet. Load it with `python -m pipeline.run` and "
            "`python -m pipeline.backfill`, then reload this page."
        )
    else:
        st.caption(f"Data as of {as_of:%d %b %Y} · {intro}")
    return as_of


def category_sort_key(category: str) -> int:
    return CATEGORY_ORDER.index(category) if category in CATEGORY_ORDER else len(CATEGORY_ORDER)
