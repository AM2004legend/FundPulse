"""Pipeline health: the recent runs of the daily load and the backfill."""

import pandas as pd
import streamlit as st

import layout
import queries

# Icon + label: status is never shown by colour alone.
STATUS = {"success": "✅ success", "failed": "❌ failed", "running": "⏳ running"}


def main() -> None:
    layout.page_header("Pipeline health", "The last 30 runs of the daily load and the backfill.")
    runs = queries.pipeline_runs()
    if runs.empty:
        st.info("No data yet: no pipeline runs have been recorded.")
        return

    daily_ok = runs[(runs["run_type"] == "daily") & (runs["status"] == "success")]
    last_ok = daily_ok.iloc[0] if not daily_ok.empty else None  # newest first
    left, middle, right = st.columns(3)
    left.metric(
        "Last successful daily run",
        f"{last_ok['started_at_ist']:%d %b, %H:%M} IST" if last_ok is not None else "never",
    )
    middle.metric("Failed runs (of these)", int((runs["status"] == "failed").sum()))
    right.metric("Rows in that run", f"{last_ok['rows_loaded']:,}" if last_ok is not None else "—")

    st.dataframe(
        pd.DataFrame(
            {
                "Run": runs["run_id"],
                "Type": runs["run_type"],
                "Status": runs["status"].map(STATUS),
                "Started (IST)": runs["started_at_ist"],
                "Duration (s)": runs["duration_seconds"],
                "Rows loaded": runs["rows_loaded"],
                "Quarantined": runs["rows_quarantined"],
                "Warnings": runs["warnings"].fillna("—"),
            }
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Started (IST)": st.column_config.DatetimeColumn(format="DD MMM YYYY, HH:mm"),
            "Duration (s)": st.column_config.NumberColumn(format="%.1f"),
            "Rows loaded": st.column_config.NumberColumn(format="localized"),
            "Quarantined": st.column_config.NumberColumn(format="localized"),
        },
    )

    failed = runs[runs["status"] == "failed"].set_index("run_id")
    if not failed.empty:
        st.subheader("Why did a run fail?")
        run_id = st.selectbox(
            "Failed run",
            failed.index.tolist(),
            format_func=lambda r: (
                f"Run {r} · {failed.loc[r, 'started_at_ist']:%d %b %Y, %H:%M} IST"
            ),
        )
        st.error(failed.loc[run_id, "error"] or "No error message was recorded.")


main()
