from __future__ import annotations

import streamlit as st

# Color system
BG = "#09090B"
BG2 = "#0F0F12"
BG3 = "#141417"
TEXT = "#E4E4E7"
TEXT_MUTED = "#71717A"
GREEN = "#22C55E"
AMBER = "#F59E0B"
RED = "#EF4444"
BLUE = "#3B82F6"
PURPLE = "#A855F7"
BORDER = "rgba(255,255,255,0.07)"

ECO_COLORS = {"npm": AMBER, "pypi": BLUE, "cargo": RED, "go": GREEN}
PHASE_COLORS = {
    "Mature": TEXT_MUTED,
    "Consolidating": PURPLE,
    "Early / Competing": BLUE,
    "Fragmenting": AMBER,
    "In Transition": AMBER,
}


def plotly_defaults() -> dict:
    return dict(
        paper_bgcolor=BG,
        plot_bgcolor=BG2,
        font=dict(family="IBM Plex Mono, monospace", color=TEXT_MUTED, size=11),
        margin=dict(l=0, r=0, t=30, b=0),
        showlegend=False,
    )


def signal_label(emergence_score: float, total_repos: int) -> tuple[str, str, str]:
    """Plain English signal label for non-technical readers."""
    if total_repos > 15000:
        return ("Dominant", PURPLE, "Used by almost everyone in this category")
    if emergence_score > 40:
        return ("Breakout", GREEN, "Growing extremely fast from a small base")
    if emergence_score > 20:
        return ("Rising", GREEN, "Growing faster than average")
    if emergence_score < 5 and total_repos > 1000:
        return ("Fading", RED, "Still widely used, but losing ground")
    if emergence_score < 3:
        return ("Stable", AMBER, "Established tool, not growing or shrinking much")
    return ("Active", AMBER, "Healthy and in use")


def phase_explainer(phase: str) -> str:
    """One sentence explaining what a market phase means to a non-technical reader."""
    return {
        "Mature": "Like Microsoft Word in word processors - one tool won and most people use it.",
        "Consolidating": "Like smartphones before iPhone vs Android settled - a winner is becoming clear.",
        "Early / Competing": "Like the early days of social media - many players, no one has won yet.",
        "Fragmenting": "Lots of tools exist but developers cannot agree on any of them.",
        "In Transition": "Something is changing. Yesterday's winner might not be tomorrow's.",
    }.get(phase, "")


def metric_card(label: str, value: str, sublabel: str = "", color: str = TEXT) -> None:
    """Render a single metric in a dark card using st.markdown."""
    st.markdown(
        f"""
    <div style="background:{BG2};border:1px solid {BORDER};border-radius:10px;padding:20px 24px;">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;text-transform:uppercase;
                    letter-spacing:0.08em;color:{TEXT_MUTED};margin-bottom:8px">{label}</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:28px;font-weight:600;
                    letter-spacing:-0.03em;color:{color}">{value}</div>
        <div style="font-size:12px;color:{TEXT_MUTED};margin-top:4px">{sublabel}</div>
    </div>
    """,
        unsafe_allow_html=True,
    )


def insight_box(text: str, label: str = "Insight") -> None:
    st.markdown(
        f"""
    <div style="background:{BG2};border:1px solid {BORDER};border-left:3px solid {GREEN};
                border-radius:0 10px 10px 0;padding:20px 24px;margin:16px 0">
        <div style="font-family:'IBM Plex Mono',monospace;font-size:10px;text-transform:uppercase;
                    letter-spacing:0.08em;color:{GREEN};margin-bottom:10px">{label}</div>
        <div style="font-size:14px;color:{TEXT};line-height:1.7">{text}</div>
        <div style="margin-top:10px;font-family:'IBM Plex Mono',monospace;font-size:10px;
                    color:{TEXT_MUTED}">Auto-generated from adoption data - not editorial opinion</div>
    </div>
    """,
        unsafe_allow_html=True,
    )


def phase_badge(phase: str) -> None:
    color = PHASE_COLORS.get(phase, TEXT_MUTED)
    st.markdown(
        f"""
    <div style="display:inline-block;padding:6px 14px;border-radius:100px;
                background:{color}22;border:1px solid {color}44;
                font-family:'IBM Plex Mono',monospace;font-size:11px;
                font-weight:500;color:{color}">{phase}</div>
    """,
        unsafe_allow_html=True,
    )


def empty_state() -> None:
    """Show when DB has no data yet."""
    st.markdown(
        f"""
    <div style="text-align:center;padding:80px 40px;background:{BG2};
                border:1px solid {BORDER};border-radius:12px;margin:40px 0">
        <div style="font-size:40px;margin-bottom:16px">🔧</div>
        <div style="font-size:20px;font-weight:600;color:{TEXT};margin-bottom:8px">
            No data yet
        </div>
        <div style="font-size:14px;color:{TEXT_MUTED};max-width:460px;margin:0 auto;line-height:1.6">
            Run the data pipeline first to collect adoption data from GitHub.
        </div>
        <div style="margin-top:24px;background:{BG3};border-radius:8px;padding:16px;
                    font-family:'IBM Plex Mono',monospace;font-size:13px;color:{TEXT_MUTED};
                    text-align:left;max-width:320px;margin:24px auto 0">
            python scripts/run_all.py
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )


def format_k(value: int | float) -> str:
    value = float(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{int(value):,}"
