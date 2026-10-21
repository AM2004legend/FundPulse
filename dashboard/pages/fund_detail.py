"""Fund detail: NAV history and drawdown for one fund, or two funds on the same chart."""

from datetime import timedelta

import pandas as pd
import streamlit as st

import analysis
import charts
import layout
import queries


def main() -> None:
    as_of = layout.page_header("Fund detail", "NAV history and drawdown for the period you pick.")
    if as_of is None:
        return

    metrics = queries.fund_metrics()
    names = dict(zip(metrics["scheme_code"], metrics["scheme_name"], strict=True))
    categories = dict(zip(metrics["scheme_code"], metrics["category"], strict=True))
    codes = sorted(names, key=lambda c: (layout.category_sort_key(categories[c]), names[c]))

    def label(code):
        return "—" if code is None else f"{names[code]} · {categories[code]}"

    pick_fund, pick_other, pick_dates = st.columns(3)
    fund = pick_fund.selectbox("Fund", codes, format_func=label, key="fund")
    other = pick_other.selectbox(
        "Compare with (optional)",
        [None, *[c for c in codes if c != fund]],
        format_func=label,
        key="other_fund",
    )
    first, last = queries.nav_range(fund)
    picked = pick_dates.date_input(
        "Date range",
        value=(max(first, last - timedelta(days=365)), last),
        min_value=first,
        max_value=last,
        format="DD/MM/YYYY",
        key="date_range",
    )
    if len(picked) != 2:
        st.info("Pick an end date for the range.")
        return
    start, end = picked

    selected = (fund,) if other is None else (fund, other)
    navs = queries.navs(selected, start, end)
    if navs.empty:
        st.info("No NAVs in this date range.")
        return
    navs["fund"] = navs["scheme_code"].map(names)
    chart_names = [names[code] for code in selected]  # picked first = colour slot 1

    # One row per fund: name, then its two numbers (short labels, so nothing is truncated).
    stats = analysis.period_stats(navs)
    for code in selected:
        name_col, return_col, drawdown_col = st.columns([2, 1, 1], vertical_alignment="center")
        name_col.markdown(f"**{names[code]}**")
        return_col.metric("Return", f"{stats.loc[code, 'period_return']:+.2%}")
        drawdown_col.metric("Max drawdown", f"{stats.loc[code, 'max_drawdown']:.2%}")

    if other is None:
        st.subheader("NAV")
        nav_chart = charts.line_chart(navs, "nav", "NAV (₹)", ",.2f", chart_names)
    else:
        st.subheader("Growth of ₹100")
        st.caption(
            "Both funds start at 100 on the first day of the range, so they share one scale."
        )
        nav_chart = charts.line_chart(
            analysis.rebase(navs), "value", "Value of ₹100", ",.1f", chart_names
        )
    st.altair_chart(nav_chart, width="stretch", theme="streamlit")

    st.subheader("Drawdown")
    st.caption("How far below its highest NAV *within this range* the fund was on each day.")
    drawdowns = analysis.drawdown(navs)
    dd_chart = charts.line_chart(drawdowns, "drawdown", "Below peak", ".0%", chart_names, area=True)
    st.altair_chart(dd_chart, width="stretch", theme="streamlit")

    with st.expander("Show data"):
        st.dataframe(
            pd.DataFrame(
                {
                    "Date": drawdowns["nav_date"],
                    "Fund": drawdowns["fund"],
                    "NAV": drawdowns["nav"],
                    "Drawdown": drawdowns["drawdown"] * 100,
                }
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "Date": st.column_config.DateColumn(format="DD MMM YYYY"),
                "NAV": st.column_config.NumberColumn(format="₹%.4f"),
                "Drawdown": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )


main()
