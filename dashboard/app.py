"""FundPulse dashboard.  Run from the project root:  streamlit run dashboard/app.py

This file only sets up navigation. Each page draws its own header (title, disclaimer,
"Data as of") via layout.page_header, so nothing depends on code after page.run().
"""

import streamlit as st

st.set_page_config(page_title="FundPulse", page_icon=":material/monitoring:", layout="wide")

page = st.navigation(
    [
        st.Page("pages/compare.py", title="Compare", icon=":material/table_chart:", default=True),
        st.Page("pages/fund_detail.py", title="Fund detail", icon=":material/show_chart:"),
        st.Page(
            "pages/pipeline_health.py", title="Pipeline health", icon=":material/monitor_heart:"
        ),
    ]
)
page.run()
