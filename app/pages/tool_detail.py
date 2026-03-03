from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.components import (
    BG2,
    BLUE,
    BORDER,
    GREEN,
    TEXT,
    TEXT_MUTED,
    empty_state,
    insight_box,
    metric_card,
    plotly_defaults,
)
from app.data_loader import db_has_data, get_all_tools_df, get_tool_detail


def generate_tool_insight(tool_data: dict) -> str:
    name = tool_data["display_name"]
    total = tool_data["total_repos"]
    new_90d = tool_data["new_repos_90d"]
    active = tool_data["active_repos"]
    emergence = tool_data["emergence_score"]

    adoption_pct = (new_90d / max(1, total)) * 100
    activity_pct = (active / max(1, total)) * 100

    if emergence > 40:
        momentum = (
            f"{name} is in breakout growth - {new_90d:,} new projects adopted it in the last 90 days alone, "
            f"which is {adoption_pct:.0f}% of its total base (share of current users that are recent adopters)."
        )
    elif emergence > 15:
        momentum = (
            f"{name} is growing steadily. {new_90d:,} new projects have adopted it in the last 90 days "
            "(recent adoption momentum)."
        )
    elif emergence < 5 and total > 500:
        momentum = (
            f"{name} is widely used ({total:,} repos) but not gaining new adopters quickly. "
            "It is established infrastructure - reliable, but the growth phase may be over."
        )
    else:
        momentum = f"{name} has a stable user base of {total:,} repos (projects currently using it)."

    if activity_pct > 70:
        health = (
            "The tool's user base is highly active - most projects using it are still being updated regularly "
            "(high maintenance activity in the last 30 days)."
        )
    elif activity_pct > 40:
        health = "Most projects using it are still actively maintained (updated within the last 30 days)."
    else:
        health = (
            f"Worth noting: only {activity_pct:.0f}% of repos using it were updated in the last 30 days "
            "(maintenance activity signal). This could mean stable projects, or reduced engagement."
        )

    return f"{momentum} {health}"


def _format_option(row) -> str:
    return f"{row['display_name']} ({row['ecosystem']} · {row['category']}) - {int(row['total_repos']):,} repos"


def _build_version_chart(version_spread: list[dict]) -> go.Figure:
    labels = [row["version_normalized"] for row in version_spread]
    values = [int(row["cnt"]) for row in version_spread]
    colors = [GREEN] + ["#4B5563", "#52525B", "#3F3F46", "#374151", "#27272A"]
    colors = colors[: len(values)]

    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(color=colors),
            text=[f"{v:,} repos" for v in values],
            textposition="outside",
            hovertemplate="%{y}: %{x:,} repos (projects on this version)<extra></extra>",
        )
    )
    fig.update_layout(**plotly_defaults(), height=320, xaxis_title="Repos (projects on this version)")
    fig.update_yaxes(autorange="reversed")
    return fig


def _format_star(stars: int) -> str:
    if stars >= 1_000_000:
        return f"{stars / 1_000_000:.1f}M"
    if stars >= 1_000:
        return f"{stars / 1_000:.1f}K"
    return f"{stars}"


def render() -> None:
    if not db_has_data():
        st.title("Tool Deep Dive")
        empty_state()
        return

    tools_df = get_all_tools_df()
    if tools_df.empty:
        empty_state()
        return

    tools_df = tools_df.sort_values("total_repos", ascending=False).reset_index(drop=True)
    option_labels = [_format_option(row) for _, row in tools_df.iterrows()]
    label_to_name = dict(zip(option_labels, tools_df["canonical_name"]))

    st.markdown("## Tool Deep Dive")
    st.markdown(
        "Select any tool to see where it is being used, how fast it is growing, "
        "and what it means in plain English."
    )

    selected_label = st.selectbox("Choose a tool to explore", option_labels)
    canonical_name = label_to_name[selected_label]
    tool = get_tool_detail(canonical_name)
    if not tool:
        st.warning("No tool data found for this selection.")
        return

    st.markdown(f"\n# {tool['display_name']}")
    st.markdown(tool["description"])

    badges = [
        f"<span style='padding:4px 10px;border:1px solid {BORDER};border-radius:999px;color:{TEXT_MUTED};font-size:11px'>{tool['ecosystem']} (ecosystem where this package is used)</span>",
        f"<span style='padding:4px 10px;border:1px solid {BORDER};border-radius:999px;color:{TEXT_MUTED};font-size:11px'>{tool['category']} (problem this tool solves)</span>",
    ]
    if tool.get("github_repo"):
        badges.append(
            f"<a href='https://github.com/{tool['github_repo']}' target='_blank' "
            "style='padding:4px 10px;border:1px solid rgba(59,130,246,0.4);border-radius:999px;color:#93C5FD;font-size:11px;text-decoration:none'>"
            "GitHub repo (source project page)</a>"
        )

    st.markdown(
        "<div style='display:flex;gap:8px;flex-wrap:wrap'>" + "".join(badges) + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("\n")
    col1, col2, col3 = st.columns(3)
    with col1:
        metric_card(
            "Projects using it",
            f"{int(tool['total_repos']):,}",
            "(public repos with 500+ stars that list this dependency)",
        )
    with col2:
        metric_card(
            "New adopters (90 days)",
            f"{int(tool['new_repos_90d']):,}",
            "(repos that started using it recently)",
            color=BLUE,
        )
    with col3:
        active_pct = (float(tool["active_repos"]) / max(1, float(tool["total_repos"]))) * 100
        metric_card(
            "Still actively used",
            f"{int(tool['active_repos']):,}",
            f"({active_pct:.0f}% of using repos were updated in the last 30 days)",
            color=GREEN,
        )

    insight_box(generate_tool_insight(tool), label="What this means")

    left, right = st.columns(2)
    with left:
        st.markdown("### Which version are people running?")
        st.caption(
            "If most users are on the latest version, the tool is usually well-maintained and trusted "
            "for upgrades (version distribution signal)."
        )

        version_spread = tool.get("version_spread", [])
        if version_spread:
            fig = _build_version_chart(version_spread)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Version data not available for this tool.")

    with right:
        st.markdown("### Notable projects using this tool")
        st.caption(
            "High-star repositories are usually well-maintained projects "
            "(quality signal from community attention)."
        )

        top_repos = tool.get("top_repos", [])
        if not top_repos:
            st.info("No notable repositories found yet.")
        else:
            for repo in top_repos:
                st.markdown(
                    f"""
                <div style="background:{BG2};border:1px solid {BORDER};border-radius:10px;padding:10px 12px;margin-bottom:8px;
                            display:flex;justify-content:space-between;align-items:center">
                    <span style="font-family:'IBM Plex Mono',monospace;color:{TEXT};font-size:12px">{repo['repo_full_name']}</span>
                    <span style="font-family:'IBM Plex Mono',monospace;color:{TEXT_MUTED};font-size:12px">★ {_format_star(int(repo['stars']))}
                    <span style='color:{TEXT_MUTED}'>(GitHub stars)</span></span>
                </div>
                """,
                    unsafe_allow_html=True,
                )

    history = tool.get("history", [])
    if len(history) > 1:
        hist_df = pd.DataFrame(history)
        st.markdown("### Adoption over time")
        st.caption("Each point is a daily snapshot of how many repos are using this tool (daily adoption count).")

        line = go.Figure(
            go.Scatter(
                x=hist_df["snapshot_date"],
                y=hist_df["total_repos"],
                mode="lines+markers",
                line=dict(color=GREEN, width=2),
                marker=dict(size=6, color=GREEN),
                hovertemplate="%{x}: %{y:,} repos (projects using this tool)<extra></extra>",
            )
        )
        line.update_layout(
            **plotly_defaults(),
            xaxis_title="Snapshot date (day this measurement was recorded)",
            yaxis_title="Total repos (projects using this tool)",
            height=360,
        )
        st.plotly_chart(line, use_container_width=True)
