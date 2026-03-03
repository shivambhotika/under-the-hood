from __future__ import annotations

from urllib.parse import quote_plus

import plotly.graph_objects as go
from flask import Flask, redirect, render_template, request, url_for

from web.data import (
    db_has_data,
    generate_tool_insight,
    get_all_categories,
    get_all_tools,
    get_category_tools,
    get_summary_stats,
    get_tool_detail,
    get_top_movers,
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
    return "Still competing"


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

    return render_template(
        "home.html",
        page_title="What's Happening Now",
        stats=stats,
        movers=movers,
        categories=categories,
        category_runner_ups=category_runner_ups,
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

    insight = generate_tool_insight(tool)
    active_pct = (int(tool["active_repos"]) / max(1, int(tool["total_repos"]))) * 100

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
        version_chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn", config={"displayModeBar": False})

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
            height=360,
        )
        trend_chart_html = fig2.to_html(full_html=False, include_plotlyjs=False, config={"displayModeBar": False})

    return render_template(
        "tool_detail.html",
        page_title="Tool Deep Dive",
        tools=tools,
        selected=canonical,
        tool=tool,
        insight=insight,
        active_pct=active_pct,
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
    bar_fig.update_layout(
        **plotly_defaults(),
        height=420,
        xaxis_title="Total repos (projects using each tool)",
        yaxis_title="",
    )
    bar_fig.update_yaxes(autorange="reversed")
    bar_html = bar_fig.to_html(full_html=False, include_plotlyjs="cdn", config={"displayModeBar": False})

    rows = []
    for t in tools:
        signal, _, _ = signal_label(float(t["emergence_score"]), int(t["total_repos"]))
        active_pct = (int(t["active_repos"]) / max(1, int(t["total_repos"]))) * 100
        row_class = "row-default"
        if signal in {"Breakout", "Rising"}:
            row_class = "row-green"
        elif signal == "Fading":
            row_class = "row-red"
        rows.append(
            {
                "tool": t["display_name"],
                "used_in": f"{int(t['total_repos']):,} (repos using this tool)",
                "new_90d": f"{int(t['new_repos_90d']):,} (new adopters in last 90 days)",
                "active": f"{active_pct:.0f}% (share of using repos updated in last 30 days)",
                "signal": f"{signal} (momentum classification)",
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
