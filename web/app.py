from __future__ import annotations

import plotly.graph_objects as go
from flask import Flask, redirect, render_template, request, url_for

from web.data import (
    confidence_badge_copy,
    db_has_data,
    generate_tool_insight,
    get_all_categories,
    get_all_tools,
    get_category_tools,
    get_download_history,
    get_pre_commercial_signal,
    get_radar_snapshot,
    get_radar_tools,
    get_summary_stats,
    get_tool_detail,
    get_tool_contributors,
    get_top_movers,
    is_notable_contributor,
    phase_explainer,
    signal_label,
)

BG = "#09090B"
BG2 = "#0F0F12"
TEXT_MUTED = "#A1A1AA"
GREEN = "#22C55E"


app = Flask(__name__, template_folder="templates", static_folder="static")


def plotly_defaults() -> dict:
    return dict(
        paper_bgcolor=BG,
        plot_bgcolor=BG2,
        font=dict(family="IBM Plex Mono, monospace", color=TEXT_MUTED, size=11),
        margin=dict(l=20, r=20, t=30, b=50),
        showlegend=False,
    )


def format_compact(num: int | float) -> str:
    n = float(num)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{int(n):,}"


def phase_short_label(phase: str) -> str:
    if phase == "Mature":
        return "One tool has won"
    if phase == "Consolidating":
        return "A winner is emerging"
    return "No clear winner yet — this is an active competition"


@app.context_processor
def inject_helpers():
    return {
        "format_compact": format_compact,
        "phase_short_label": phase_short_label,
        "phase_explainer": phase_explainer,
    }


@app.get("/")
def home():
    if not db_has_data():
        return render_template("empty.html", page_title="Under The Hood")

    stats = get_summary_stats()
    movers = get_top_movers(6)
    categories = get_all_categories()
    radar_count = len(get_radar_tools())

    category_runner_ups: dict[str, dict] = {}
    for cat in categories:
        tools = sorted(get_category_tools(cat["category"]), key=lambda x: x["total_repos"], reverse=True)
        total_cat = max(1, sum(int(t["total_repos"]) for t in tools))
        if len(tools) > 1:
            ru = tools[1]
            category_runner_ups[cat["category"]] = {
                "name": ru["display_name"],
                "share": (int(ru["total_repos"]) / total_cat) * 100,
            }
        else:
            category_runner_ups[cat["category"]] = {"name": "N/A", "share": 0}

    for row in movers:
        signal, color, explainer = signal_label(float(row["emergence_score"]), int(row["total_repos"]))
        icon_map = {
            "Breakout": "🚀 Breakout",
            "Rising": "↑ Rising",
            "Fading": "↓ Fading",
            "Stable": "→ Stable",
            "Active": "→ Active",
            "Dominant": "👑 Dominant",
        }
        row["signal"] = signal
        row["signal_badge"] = icon_map.get(signal, signal)
        row["signal_color"] = color
        row["signal_explainer"] = explainer
        row["activity_pct"] = (int(row["active_repos"]) / max(1, int(row["total_repos"]))) * 100
        row["confidence_tier"] = row.get("confidence_tier") or "Low"
        row["sample_size"] = int(row.get("sample_size") or row.get("total_repos") or 0)
        row["confidence_tooltip"] = confidence_badge_copy(row["confidence_tier"], row["sample_size"])
        row["low_confidence"] = row["sample_size"] < 15 or row["confidence_tier"] == "Low"

    return render_template(
        "home.html",
        page_title="What's Happening Now",
        stats=stats,
        movers=movers,
        categories=categories,
        category_runner_ups=category_runner_ups,
        radar_count=radar_count,
    )


@app.get("/tool")
def tool_detail():
    if not db_has_data():
        return render_template("empty.html", page_title="Tool Deep Dive")

    tools = get_all_tools()
    if not tools:
        return render_template("empty.html", page_title="Tool Deep Dive")

    canonical = request.args.get("name")
    if not canonical or canonical not in {t["canonical_name"] for t in tools}:
        canonical = tools[0]["canonical_name"]

    tool = get_tool_detail(canonical)
    if not tool:
        return redirect(url_for("home"))

    contributors = get_tool_contributors(canonical)
    for c in contributors:
        c["is_notable"] = is_notable_contributor(c)
    pre_commercial_signal = get_pre_commercial_signal(
        canonical, tool.get("github_repo"), contributors=contributors
    )

    insight = generate_tool_insight(tool)
    active_pct = (int(tool["active_repos"]) / max(1, int(tool["total_repos"]))) * 100
    sample_size = int(tool.get("sample_size") or tool.get("total_repos") or 0)
    confidence_tier = tool.get("confidence_tier") or "Low"
    confidence_tooltip = confidence_badge_copy(confidence_tier, sample_size)
    trend_reliable = int(tool.get("is_trend_reliable") or 0) == 1
    weekly_downloads = int(tool.get("weekly_downloads") or 0)
    downloads_source = tool.get("downloads_source")
    usage_model = tool.get("usage_model") or "dependency_first"
    has_downloads = bool(downloads_source)
    download_history = get_download_history(canonical)

    version_chart_html = ""
    if tool.get("version_spread"):
        labels = [row["version_normalized"] for row in tool["version_spread"]]
        values = [int(row["cnt"]) for row in tool["version_spread"]]
        colors = [GREEN] + ["#52525B", "#4B5563", "#3F3F46", "#374151", "#27272A"]
        fig = go.Figure(
            go.Bar(
                x=values,
                y=labels,
                orientation="h",
                marker=dict(color=colors[: len(values)]),
                text=[f"{v:,} repos" for v in values],
                textposition="outside",
                hovertemplate="%{y}: %{x:,} repos (projects on this version)<extra></extra>",
            )
        )
        fig.update_layout(**plotly_defaults(), xaxis_title="Repos (projects on this version)", height=320)
        fig.update_yaxes(autorange="reversed")
        version_chart_html = fig.to_html(
            full_html=False,
            include_plotlyjs="cdn",
            config={"displayModeBar": False, "responsive": True},
        )

    trend_chart_html = ""
    history = tool.get("history") or []
    if len(history) > 1:
        x = [h["snapshot_date"] for h in history]
        y = [int(h["total_repos"]) for h in history]
        fig2 = go.Figure(
            go.Scatter(
                x=x,
                y=y,
                mode="lines+markers",
                line=dict(color=GREEN, width=2),
                marker=dict(size=6, color=GREEN),
                hovertemplate="%{x}: %{y:,} repos (projects using this tool)<extra></extra>",
            )
        )
        fig2.update_layout(
            **plotly_defaults(),
            xaxis_title="Snapshot date (day this measurement was recorded)",
            yaxis_title="Total repos (projects using this tool)",
            height=320,
        )
        trend_chart_html = fig2.to_html(
            full_html=False,
            include_plotlyjs=False,
            config={"displayModeBar": False, "responsive": True},
        )

    return render_template(
        "tool_detail.html",
        page_title="Tool Deep Dive",
        tools=tools,
        selected=canonical,
        tool=tool,
        contributors=contributors,
        pre_commercial_signal=pre_commercial_signal,
        insight=insight,
        active_pct=active_pct,
        confidence_tier=confidence_tier,
        confidence_tooltip=confidence_tooltip,
        sample_size=sample_size,
        trend_reliable=trend_reliable,
        weekly_downloads=weekly_downloads,
        downloads_source=downloads_source,
        usage_model=usage_model,
        has_downloads=has_downloads,
        download_history=download_history,
        version_chart_html=version_chart_html,
        trend_chart_html=trend_chart_html,
    )


@app.get("/category")
def category_view():
    if not db_has_data():
        return render_template("empty.html", page_title="Category View")

    categories = get_all_categories()
    if not categories:
        return render_template("empty.html", page_title="Category View")

    selected = request.args.get("name")
    names = {c["category"] for c in categories}
    if not selected or selected not in names:
        selected = categories[0]["category"]

    cat = next(c for c in categories if c["category"] == selected)
    tools = sorted(get_category_tools(selected), key=lambda x: x["total_repos"], reverse=True)
    total_repos = sum(int(t["total_repos"]) for t in tools)

    bar_fig = go.Figure(
        go.Bar(
            x=[int(t["total_repos"]) for t in tools],
            y=[t["display_name"] for t in tools],
            orientation="h",
            marker=dict(
                color=[
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
                ][: len(tools)]
            ),
            text=[f"{int(t['total_repos']):,}" for t in tools],
            textposition="outside",
            hovertemplate="%{y}: %{x:,} repos (projects using this tool)<extra></extra>",
        )
    )
    category_layout = plotly_defaults()
    category_layout["margin"] = dict(l=120, r=20, t=30, b=20)
    bar_fig.update_layout(
        **category_layout,
        height=420,
        xaxis_title="Total repos (projects using each tool)",
        yaxis_title="",
    )
    bar_fig.update_yaxes(autorange="reversed")
    bar_html = bar_fig.to_html(
        full_html=False,
        include_plotlyjs="cdn",
        config={"displayModeBar": False, "responsive": True},
    )

    rows = []
    for t in tools:
        signal, _, _ = signal_label(float(t["emergence_score"]), int(t["total_repos"]))
        active_pct = (int(t["active_repos"]) / max(1, int(t["total_repos"]))) * 100
        row_class = "row-default"
        if signal in {"Breakout", "Rising"}:
            row_class = "row-green"
        elif signal == "Fading":
            row_class = "row-red"
        confidence_tier = t.get("confidence_tier") or "Low"
        sample_size = int(t.get("sample_size") or t.get("total_repos") or 0)
        confidence_tooltip = confidence_badge_copy(confidence_tier, sample_size)
        rows.append(
            {
                "tool": t["display_name"],
                "used_in_raw": int(t["total_repos"]),
                "used_in": f"{int(t['total_repos']):,} (repos using this tool)",
                "new_90d_raw": int(t["new_repos_90d"]),
                "new_90d": f"{int(t['new_repos_90d']):,} (new adopters in last 90 days)",
                "active_pct_raw": active_pct,
                "active": f"{active_pct:.0f}% (share of using repos updated in last 30 days)",
                "enterprise": int(t.get("enterprise_repo_count") or 0),
                "signal": f"{signal} (momentum classification)",
                "signal_text": signal,
                "weekly_downloads": int(t.get("weekly_downloads") or 0),
                "downloads_source": t.get("downloads_source"),
                "confidence_tier": confidence_tier,
                "confidence_tooltip": confidence_tooltip,
                "sample_size": sample_size,
                "what": (t["description"][:57] + "...") if len(t["description"]) > 60 else t["description"],
                "row_class": row_class,
            }
        )

    return render_template(
        "category_view.html",
        page_title="Category View",
        categories=categories,
        selected=selected,
        cat=cat,
        total_repos=total_repos,
        bar_html=bar_html,
        rows=rows,
    )


@app.get("/radar")
def radar():
    if not db_has_data():
        return render_template("empty.html", page_title="The Radar")

    radar_snapshot = get_radar_snapshot()
    tools = radar_snapshot["tools"]
    for tool in tools:
        contributors = get_tool_contributors(tool["canonical_name"])
        top_builders = []
        for c in contributors[:2]:
            top_builders.append(
                {
                    "github_login": c.get("github_login"),
                    "followers": int(c.get("followers") or 0),
                    "company": c.get("company") or "",
                    "html_url": c.get("html_url") or "",
                }
            )
        tool["top_builders"] = top_builders
        tool["pre_commercial_signal"] = get_pre_commercial_signal(
            tool["canonical_name"], tool.get("github_repo"), contributors=contributors
        )
        ent = int(tool.get("enterprise_repo_count") or 0)
        if ent >= 1:
            tool["signal_border"] = "signal-green"
        elif tool["pre_commercial_signal"]:
            tool["signal_border"] = "signal-amber"
        else:
            tool["signal_border"] = "signal-default"

    return render_template(
        "radar.html",
        page_title="The Radar",
        tools=tools,
        radar_count=len(tools),
        radar_max_repos=400,
        radar_min_growth_pct=int(round(float(radar_snapshot["growth_threshold"]) * 100)),
        radar_target_growth_pct=int(round(float(radar_snapshot["target_growth_threshold"]) * 100)),
        radar_fallback_growth_pct=int(round(float(radar_snapshot["fallback_growth_threshold"]) * 100)),
    )


@app.get("/learn")
def learn():
    if not db_has_data():
        return render_template("empty.html", page_title="How to Read This")
    return render_template("learn.html", page_title="How to Read This")


@app.get("/healthz")
def healthz():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
