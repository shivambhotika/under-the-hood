from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="Under The Hood",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=DM+Sans:wght@300;400;500;600&display=swap');

.stApp { background: #09090B; }
[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }
.stDeployButton { display: none; }

h1,h2,h3 {
    font-family: 'DM Sans', sans-serif !important;
    color: #E4E4E7 !important;
    letter-spacing: -0.02em !important;
}
p, li, .stMarkdown { color: #E4E4E7; }

[data-testid="stSidebar"] {
    background: #0F0F12 !important;
    border-right: 1px solid rgba(255,255,255,0.07);
}
[data-testid="stSidebar"] * { color: #E4E4E7; }

.stSelectbox > div > div {
    background: #0F0F12;
    border-color: rgba(255,255,255,0.1);
    color: #E4E4E7;
}
[data-testid="stDataFrame"] {
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 10px;
}
</style>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown(
        """
    <div style="padding:16px 0 24px;border-bottom:1px solid rgba(255,255,255,0.07);margin-bottom:20px">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:16px;font-weight:600;color:#E4E4E7">
            🔧 Under The Hood
        </div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#71717A;margin-top:4px">
            OSS Tool Intelligence
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    page = st.radio(
        "Navigate",
        ["🏠 What's Happening Now", "🔍 Tool Deep Dive", "📦 Category View", "📖 How to Read This"],
        label_visibility="collapsed",
    )

    st.markdown(
        """
    <div style="margin-top:auto;padding-top:40px;font-family:'IBM Plex Mono',monospace;
                font-size:10px;color:#3F3F46">
        Data: GitHub API<br>
        Updated: Daily<br>
        Repos tracked: 500+ stars only
    </div>
    """,
        unsafe_allow_html=True,
    )

if page == "🏠 What's Happening Now":
    from app.pages.home import render

    render()
elif page == "🔍 Tool Deep Dive":
    from app.pages.tool_detail import render

    render()
elif page == "📦 Category View":
    from app.pages.category_view import render

    render()
elif page == "📖 How to Read This":
    from app.pages.learn import render

    render()
