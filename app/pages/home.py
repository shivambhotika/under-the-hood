from __future__ import annotations

import streamlit as st

from app.components import (
    AMBER,
    BG2,
    BORDER,
    GREEN,
    TEXT,
    TEXT_MUTED,
    empty_state,
    metric_card,
    signal_label,
)
from app.data_loader import (
    db_has_data,
    get_all_categories_df,
    get_category_tools_df,
    get_summary_stats,
    get_top_movers,
)


def _phase_short_label(phase: str) -> str:
    if phase == "Mature":
        return "One tool has won"
    if phase == "Consolidating":
        return "A winner is emerging"
    return "Still competing"


def render() -> None:
    if not db_has_data():
        st.title("Under The Hood")
        empty_state()
        return

    stats = get_summary_stats()

    st.markdown("## What the open source world is actually building.")
    st.markdown(
        f"Tracking **{stats['total_tools']:,} tools** across **{stats['total_repos']:,} repositories** "
        "(public projects with 500+ GitHub stars). Updated daily. No hype."
    )

    st.markdown("\n")
    col1, col2, col3 = st.columns(3)
    with col1:
        metric_card(
            "Total repos scanned",
            f"{stats['total_repos']:,}",
            "(repositories where these tools appear in dependency files)",
        )
    with col2:
        metric_card(
            "Tools tracked",
            f"{stats['total_tools']:,}",
            "(distinct developer tools in this intelligence universe)",
        )
    with col3:
        mover = stats.get("biggest_mover") or {}
        mover_name = mover.get("display_name", "N/A")
        metric_card(
            "Today's most interesting signal",
            f"{mover_name} ↑ fastest growing",
            "(tool with the highest emergence score today, meaning fastest relative growth)",
            color=GREEN,
        )

    st.markdown("\n### What's worth paying attention to right now")
    st.markdown(
        "These are the tools with the most momentum "
        "(growing fast relative to their current size, not just already being big)."
    )

    movers = get_top_movers(6)
    if movers.empty:
        st.info("No mover data yet (run the pipeline to compute emergence signals).")
    else:
        cols = st.columns(3)
        for idx, row in movers.iterrows():
            label, color, explainer = signal_label(float(row["emergence_score"]), int(row["total_repos"]))
            signal_text = {
                "Breakout": "🚀 Breakout",
                "Rising": "↑ Rising",
                "Fading": "↓ Fading",
                "Stable": "→ Stable",
                "Active": "→ Active",
                "Dominant": "👑 Dominant",
            }.get(label, label)
            activity_pct = (float(row["active_repos"]) / max(1, float(row["total_repos"]))) * 100
            with cols[idx % 3]:
                st.markdown(
                    f"""
                <div style="background:{BG2};border:1px solid {BORDER};border-radius:12px;padding:16px;min-height:250px;margin-bottom:14px">
                    <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:10px">
                        <span style="padding:4px 8px;border-radius:100px;background:rgba(245,158,11,0.15);
                                     border:1px solid rgba(245,158,11,0.35);font-size:10px;color:{AMBER};font-family:'IBM Plex Mono',monospace">
                            {row['category']}
                        </span>
                        <span style="padding:4px 8px;border-radius:100px;background:{color}22;
                                     border:1px solid {color}55;font-size:10px;color:{color};font-family:'IBM Plex Mono',monospace">
                            {signal_text}
                        </span>
                    </div>
                    <div style="font-family:'DM Sans',sans-serif;font-size:24px;color:{TEXT};font-weight:600;line-height:1.2">{row['display_name']}</div>
                    <div style="font-size:12px;color:{TEXT_MUTED};line-height:1.6;margin-top:6px">{row['description']}</div>
                    <div style="height:1px;background:{BORDER};margin:12px 0"></div>
                    <div style="font-size:12px;color:{TEXT_MUTED};line-height:1.8">
                        Used in: <span style="color:{TEXT}">{int(row['total_repos']):,}</span>
                        <span>(repositories using this tool)</span><br>
                        New (90d): <span style="color:{TEXT}">{int(row['new_repos_90d']):,}</span>
                        <span>(new repositories that started using it recently)</span><br>
                        Activity: <span style="color:{TEXT}">{activity_pct:.0f}%</span>
                        <span>(share of using repositories updated in the last 30 days)</span>
                    </div>
                    <div style="margin-top:8px;font-size:11px;color:{TEXT_MUTED}">{explainer} (signal interpretation)</div>
                </div>
                """,
                    unsafe_allow_html=True,
                )

    st.markdown("\n### State of each category")
    st.markdown(
        "A category is a group of tools that solve the same problem. "
        "This view shows whether there is a clear winner or if it is still anyone's game."
    )

    categories = get_all_categories_df()
    if categories.empty:
        st.info("Category intelligence is not ready yet (run score computation).")
    else:
        cols = st.columns(3)
        for idx, row in categories.iterrows():
            category_tools = get_category_tools_df(row["category"]).sort_values("total_repos", ascending=False)
            runner_up_name = "N/A"
            runner_up_share = 0.0
            if len(category_tools) > 1:
                total_cat = max(1, category_tools["total_repos"].sum())
                runner = category_tools.iloc[1]
                runner_up_name = runner["display_name"]
                runner_up_share = (float(runner["total_repos"]) / total_cat) * 100

            with cols[idx % 3]:
                st.markdown(
                    f"""
                <div style="background:{BG2};border:1px solid {BORDER};border-radius:12px;padding:16px;min-height:200px;margin-bottom:14px">
                    <div style="font-family:'DM Sans',sans-serif;font-size:21px;color:{TEXT};font-weight:600">{row['category']}</div>
                    <div style="display:inline-block;margin-top:8px;padding:4px 10px;border-radius:999px;
                                background:rgba(59,130,246,0.14);border:1px solid rgba(59,130,246,0.33);
                                color:#93C5FD;font-size:10px;font-family:'IBM Plex Mono',monospace">{row['market_phase']}</div>
                    <div style="font-size:12px;color:{TEXT_MUTED};margin-top:10px">{_phase_short_label(row['market_phase'])} (competitive state)</div>
                    <div style="height:1px;background:{BORDER};margin:12px 0"></div>
                    <div style="font-size:12px;color:{TEXT_MUTED};line-height:1.9">
                        Top tool: <span style="color:{TEXT}">{row['top_tool']}</span>
                        <span>({float(row['top_tool_share_pct']):.0f}% of repos in this category)</span><br>
                        Runner up: <span style="color:{TEXT}">{runner_up_name}</span>
                        <span>({runner_up_share:.0f}% of repos in this category)</span>
                    </div>
                </div>
                """,
                    unsafe_allow_html=True,
                )

    st.markdown("\n")
    st.markdown(
        f"""
    <div style="background:{BG2};border:1px solid {BORDER};border-radius:12px;padding:18px 20px;line-height:1.8;color:{TEXT}">
        <strong>How to read this:</strong> Numbers here come from scanning real code repositories on GitHub.
        When we say "8,102 repos use Vitest", we mean 8,102 public projects with 500+ GitHub stars have Vitest in
        their dependency file. This is ground-truth adoption data (what is installed in code) - not surveys, social
        media, or self-reported usage.
    </div>
    """,
        unsafe_allow_html=True,
    )
