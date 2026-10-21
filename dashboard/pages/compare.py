"""Compare: the watchlist funds in one category, side by side."""

import pandas as pd
import streamlit as st

import layout
import queries


def main() -> None:
    as_of = layout.page_header(
        "Compare funds", "Return and risk over the same 12 months for every fund."
    )
    if as_of is None:
        return

    metrics = queries.fund_metrics()
    categories = sorted(metrics["category"].unique(), key=layout.category_sort_key)
    category = st.radio("Category", categories, horizontal=True)

    rows = metrics[metrics["category"] == category].sort_values(
        "return_1y", ascending=False, na_position="last"
    )
    table = pd.DataFrame(
        {
            "Fund": rows["scheme_name"],
            "Fund house": rows["fund_house"],
            "1-yr return": rows["return_1y"] * 100,
            "Volatility": rows["volatility_1y"] * 100,
            "Max drawdown": rows["max_drawdown_1y"] * 100,
            "Latest NAV": rows["latest_nav"],
            "NAV date": rows["latest_date"],
        }
    )
    pct = st.column_config.NumberColumn
    st.dataframe(
        # Fund house is left off screen (every fund name starts with it) so the full fund
        # name fits without clipping; it is still in the CSV download.
        table.drop(columns="Fund house"),
        hide_index=True,
        width="stretch",
        column_config={
            "Fund": st.column_config.TextColumn(width=420),
            "1-yr return": pct(format="%.2f%%", help="Gain over the last 12 months."),
            "Volatility": pct(
                format="%.2f%%",
                help="How bumpy: standard deviation of daily returns, annualised (×√250).",
            ),
            "Max drawdown": pct(
                format="%.2f%%", help="Worst fall from a peak within the last 12 months."
            ),
            "Latest NAV": st.column_config.NumberColumn(format="₹%.4f"),
            "NAV date": st.column_config.DateColumn(format="DD MMM YYYY"),
        },
    )
    st.caption(
        "Click a column header to sort. All funds are Direct Plan – Growth. "
        "Funds with less than a year of history show blanks."
    )
    st.download_button(
        "Download CSV",
        table.to_csv(index=False).encode("utf-8"),
        file_name=f"fundpulse_{category}_{as_of:%Y-%m-%d}.csv",
        mime="text/csv",
        icon=":material/download:",
    )

    with st.expander("How are these calculated?"):
        st.markdown(
            "- **1-yr return** = latest NAV ÷ NAV on the last trading day on or before "
            "365 days earlier − 1.\n"
            "- **Volatility** = standard deviation of daily returns over that year × √250 "
            "(about 250 trading days a year).\n"
            "- **Max drawdown** = the biggest fall from a running high within that year.\n\n"
            "Each fund's year ends at its own latest NAV date."
        )


main()
