from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from app.components import (
    BG,
    BG2,
    BORDER,
    GREEN,
    RED,
    TEXT,
    TEXT_MUTED,
    empty_state,
    insight_box,
    metric_card,
    phase_badge,
    phase_explainer,
    plotly_defaults,
    signal_label,
)
from app.data_loader import db_has_data, get_all_categories_df, get_category_tools_df

BAR_COLORS = [
    "#22C55E",
    "#3B82F6",
    "#F59E0B",
    "#A855F7",
    "#F43F5E",
    "#14B8A6",
    "#EAB308",
    "#60A5FA",
    "#FB7185",
    "#34D399",
]


def _row_fill_for_signal(signal: str) -> str:
    if signal in {"Breakout", "Rising"}:
        return "rgba(34,197,94,0.10)"
    if signal == "Fading":
        return "rgba(239,68,68,0.10)"
    return "rgba(15,15,18,1.0)"


def render() -> None:
    if not db_has_data():
        st.title("Category View")
        empty_state()
        return

    categories_df = get_all_categories_df()
    if categories_df.empty:
        empty_state()
        return

    category_names = categories_df["category"].tolist()

    st.markdown("## Category Intelligence")
    st.markdown(
        "A category groups tools that solve the same problem. Seeing them side-by-side shows who is winning."
    )

    selected_category = st.selectbox("Choose a category", category_names)
    cat_row = categories_df[categories_df["category"] == selected_category].iloc[0]
    tools_df = get_category_tools_df(selected_category).sort_values("total_repos", ascending=False)

    total_repos = int(tools_df["total_repos"].sum())

    st.markdown(f"\n# {selected_category}")
    phase_badge(cat_row["market_phase"])
    st.markdown(
        f"<div style='margin-top:8px;color:{TEXT_MUTED};font-size:13px'>{phase_explainer(cat_row['market_phase'])} "
        "(what this phase means for decision-makers).</div>",
        unsafe_allow_html=True,
    )

    st.markdown("\n")
    c1, c2, c3 = st.columns(3)
    with c1:
        metric_card(
            "Tools tracked in this category",
            f"{int(cat_row['tool_count']):,}",
            "(distinct tools being compared in this problem area)",
        )
    with c2:
        metric_card(
            "Total repos across category",
            f"{total_repos:,}",
            "(sum of repositories that use at least one tracked tool here)",
        )
    with c3:
        metric_card(
            "Fragmentation index",
            str(cat_row["fragmentation_plain"]),
            "(plain-English concentration signal; higher fragmentation means less agreement)",
            color=GREEN,
        )

    insight_box(str(cat_row["insight_text"]), label="Category insight")

    st.markdown("### Where is the energy concentrating?")
    st.caption(
        "The bigger the bar, the more projects are using that tool "
        "(bar length equals repository count in this category)."
    )

    fig = go.Figure(
        go.Bar(
            x=tools_df["total_repos"],
            y=tools_df["display_name"],
            orientation="h",
            marker=dict(color=[BAR_COLORS[i % len(BAR_COLORS)] for i in range(len(tools_df))]),
            text=[f"{int(v):,}" for v in tools_df["total_repos"]],
            textposition="outside",
            hovertemplate="%{y}: %{x:,} repos (projects using this tool)<extra></extra>",
        )
    )
    fig.update_layout(
        **plotly_defaults(),
        height=420,
        xaxis_title="Total repos (projects using each tool)",
        yaxis_title="",
    )
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("### All tools in this category, compared")

    table_df = tools_df.copy()
    table_df["signal"] = table_df.apply(
        lambda r: signal_label(float(r["emergence_score"]), int(r["total_repos"]))[0], axis=1
    )
    table_df["desc_short"] = table_df["description"].apply(
        lambda s: s if len(str(s)) <= 60 else f"{str(s)[:57]}..."
    )
    table_df["active_pct"] = table_df.apply(
        lambda r: (float(r["active_repos"]) / max(1, float(r["total_repos"]))) * 100,
        axis=1,
    )

    fill_colors = [_row_fill_for_signal(sig) for sig in table_df["signal"]]

    table = go.Figure(
        data=[
            go.Table(
                header=dict(
                    values=[
                        "Tool",
                        "Used in",
                        "New (90d)",
                        "Still Active",
                        "Signal",
                        "What it is",
                    ],
                    fill_color="#18181B",
                    font=dict(color=TEXT, family="IBM Plex Mono, monospace", size=12),
                    line_color="rgba(255,255,255,0.12)",
                    align="left",
                ),
                cells=dict(
                    values=[
                        table_df["display_name"],
                        [f"{int(v):,} (repos using this tool)" for v in table_df["total_repos"]],
                        [f"{int(v):,} (new adopters in last 90 days)" for v in table_df["new_repos_90d"]],
                        [f"{v:.0f}% (share of using repos updated in last 30 days)" for v in table_df["active_pct"]],
                        [f"{v} (momentum classification)" for v in table_df["signal"]],
                        table_df["desc_short"],
                    ],
                    fill_color=[fill_colors] * 6,
                    font=dict(color=TEXT_MUTED, family="IBM Plex Mono, monospace", size=11),
                    line_color="rgba(255,255,255,0.08)",
                    align="left",
                    height=32,
                ),
            )
        ]
    )
    table.update_layout(
        **plotly_defaults(),
        margin=dict(l=0, r=0, t=0, b=0),
        height=max(260, 48 + 34 * len(table_df)),
    )
    st.plotly_chart(table, use_container_width=True)
