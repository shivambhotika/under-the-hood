from __future__ import annotations

import math

import plotly.graph_objects as go
from flask import Flask, redirect, render_template, request, url_for

from web.data import (
    confidence_badge_copy,
    db_has_data,
    format_delta,
    format_activity_signal,
    generate_tool_insight,
    get_all_categories,
    get_all_tools,
    get_category_tools,
    get_download_history,
    get_health_leaderboard,
    get_ops_data,
    generate_category_memo,
    get_pre_commercial_signal,
    get_radar_snapshot,
    get_radar_tools,
    get_summary_stats,
    get_tool_detail,
    get_tool_contributors,
    get_tool_top_contributors,
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


def format_followers(value: int | float) -> str:
    n = float(value or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{int(n):,}"


def format_compact_delta(num: int | float) -> str:
    n = int(num or 0)
    if n == 0:
        return "—"
    sign = "+" if n > 0 else ""
    abs_n = abs(n)
    if abs_n >= 1_000_000:
        return f"{sign}{(n / 1_000_000):.1f}M"
    if abs_n >= 1_000:
        return f"{sign}{(n / 1_000):.1f}K"
    return f"{sign}{n:,}"


def phase_short_label(phase: str) -> str:
    if phase == "Mature":
        return "One tool has won"
    if phase == "Consolidating":
        return "A winner is emerging"
    return "No clear winner yet — this is an active competition"


def format_days_ago(days: int | None) -> str:
    if days is None:
        return "unknown"
    if days < 30:
        return f"{days} days ago"
    if days < 365:
        months = max(1, int(round(days / 30)))
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = max(1, int(round(days / 365)))
    return f"{years} year{'s' if years != 1 else ''} ago"


def health_tier_meta(tier: str) -> tuple[str, str]:
    if tier == "Healthy":
        return "✅", "health-tier-healthy"
    if tier == "Monitoring Required":
        return "⚠️", "health-tier-monitoring"
    if tier == "Declining Health":
        return "🔴", "health-tier-declining"
    if tier == "Critical Concerns":
        return "❌", "health-tier-critical"
    return "❓", "health-tier-unknown"


@app.context_processor
def inject_helpers():
    return {
        "format_compact": format_compact,
        "format_followers": format_followers,
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
        row["confidence_tooltip"] = (
            row.get("confidence_tooltip")
            or confidence_badge_copy(row["confidence_tier"], row["sample_size"])
        )
        row["trend_reliable"] = int(row.get("is_trend_reliable") or 0) == 1
        repos_delta = int(row.get("repos_delta_7d") or 0)
        row["repos_delta_display"], row["repos_delta_class"] = format_delta(repos_delta)
        row["show_repos_delta"] = not (repos_delta == 0 and not row["trend_reliable"])
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
    confidence_tooltip = tool.get("confidence_tooltip") or confidence_badge_copy(
        confidence_tier, sample_size
    )
    trend_reliable = int(tool.get("is_trend_reliable") or 0) == 1
    weekly_downloads = int(tool.get("weekly_downloads") or 0)
    repos_delta_7d = int(tool.get("repos_delta_7d") or 0)
    downloads_delta_7d = int(tool.get("downloads_delta_7d") or 0)
    repos_delta_display, repos_delta_class = format_delta(repos_delta_7d)
    downloads_delta_display, downloads_delta_class = format_delta(downloads_delta_7d)
    show_repos_delta = not (repos_delta_7d == 0 and not trend_reliable)
    show_downloads_delta = not (downloads_delta_7d == 0 and not trend_reliable)
    downloads_source = tool.get("downloads_source")
    usage_model = tool.get("usage_model") or "dependency_first"
    has_downloads = bool(downloads_source)
    download_history = get_download_history(canonical)

    health = tool.get("health") or {}
    has_health_data = bool(health)
    deps_dev_found = int(health.get("deps_dev_found") or 0) if has_health_data else 0
    osv_found = int(health.get("osv_found") or 0) if has_health_data else 0
    show_health_section = has_health_data
    health_data_available = deps_dev_found == 1 or osv_found == 1

    health_score = float(health.get("health_score") or 0) if has_health_data else 0.0
    health_tier = str(health.get("health_tier") or "Unknown") if has_health_data else "Unknown"
    health_reason = str(health.get("health_tier_reason") or "") if has_health_data else ""
    health_icon, health_tier_class = health_tier_meta(health_tier)

    last_release_days = health.get("last_release_days") if has_health_data else None
    if isinstance(last_release_days, (int, float)):
        last_release_days_int = int(last_release_days)
    else:
        last_release_days_int = None
    last_release_text = format_days_ago(last_release_days_int)
    if last_release_days_int is None:
        last_release_class = "health-muted"
    elif last_release_days_int <= 30:
        last_release_class = "health-good"
    elif last_release_days_int <= 90:
        last_release_class = "health-default"
    elif last_release_days_int <= 180:
        last_release_class = "health-warn"
    else:
        last_release_class = "health-bad"

    advisory_total = int(health.get("advisory_total") or 0) if has_health_data else 0
    advisory_critical = int(health.get("advisory_critical") or 0) if has_health_data else 0
    advisory_high = int(health.get("advisory_high") or 0) if has_health_data else 0
    if advisory_total == 0:
        advisory_text = "None"
        advisory_class = "health-good"
    elif advisory_total <= 2:
        advisory_text = f"{advisory_total} advisories ({advisory_critical}C {advisory_high}H)"
        advisory_class = "health-warn"
    else:
        advisory_text = f"{advisory_total} advisories ({advisory_critical}C {advisory_high}H)"
        advisory_class = "health-bad"

    transitive_dep_count = health.get("transitive_dep_count") if has_health_data else None
    if isinstance(transitive_dep_count, (int, float)):
        transitive_dep_count_int = int(transitive_dep_count)
    else:
        transitive_dep_count_int = None
    transitive_dep_text = (
        f"{transitive_dep_count_int:,} packages" if transitive_dep_count_int is not None else "unknown"
    )
    if transitive_dep_count_int is None:
        transitive_dep_class = "health-muted"
    elif transitive_dep_count_int <= 50:
        transitive_dep_class = "health-good"
    elif transitive_dep_count_int <= 200:
        transitive_dep_class = "health-default"
    elif transitive_dep_count_int <= 500:
        transitive_dep_class = "health-warn"
    else:
        transitive_dep_class = "health-bad"

    license_value = str(health.get("license") or "") if has_health_data else ""
    license_is_permissive = int(health.get("license_is_permissive") or 0) if has_health_data else 0
    if not license_value:
        license_text = "unknown"
        license_class = "health-muted"
    elif license_is_permissive == 1:
        license_text = license_value
        license_class = "health-good"
    else:
        license_text = f"{license_value} (non-permissive)"
        license_class = "health-warn"

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
        repos_delta_display=repos_delta_display,
        repos_delta_class=repos_delta_class,
        show_repos_delta=show_repos_delta,
        downloads_delta_display=downloads_delta_display,
        downloads_delta_class=downloads_delta_class,
        show_downloads_delta=show_downloads_delta,
        downloads_delta_compact=format_compact_delta(downloads_delta_7d),
        downloads_source=downloads_source,
        usage_model=usage_model,
        has_downloads=has_downloads,
        download_history=download_history,
        show_health_section=show_health_section,
        health_data_available=health_data_available,
        health_score=health_score,
        health_tier=health_tier,
        health_reason=health_reason,
        health_icon=health_icon,
        health_tier_class=health_tier_class,
        last_release_text=last_release_text,
        last_release_class=last_release_class,
        advisory_text=advisory_text,
        advisory_class=advisory_class,
        transitive_dep_text=transitive_dep_text,
        transitive_dep_class=transitive_dep_class,
        license_text=license_text,
        license_class=license_class,
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
        confidence_tooltip = (
            t.get("confidence_tooltip")
            or confidence_badge_copy(confidence_tier, sample_size)
        )
        trend_reliable = int(t.get("is_trend_reliable") or 0) == 1
        repos_delta = int(t.get("repos_delta_7d") or 0)
        repos_delta_display, repos_delta_class = format_delta(repos_delta)
        show_repos_delta = not (repos_delta == 0 and not trend_reliable)
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
                "repos_delta_7d": repos_delta,
                "repos_delta_display": repos_delta_display,
                "repos_delta_class": repos_delta_class,
                "show_repos_delta": show_repos_delta,
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


@app.get("/memo")
def memo():
    if not db_has_data():
        return render_template("empty.html", page_title="Briefs")

    categories = get_all_categories()
    selected = request.args.get("category", "").strip()
    memo_data = None
    if selected:
        memo_data = generate_category_memo(selected)
    return render_template(
        "memo.html",
        page_title="Briefs",
        categories=categories,
        selected=selected,
        memo=memo_data,
    )


@app.route("/health")
def health_page():
    if not db_has_data():
        return render_template("empty.html", page_title="Tool Health Rankings")

    category_filter = request.args.get("category", "").strip()
    tier_filter = request.args.get("tier", "").strip()

    df = get_health_leaderboard(
        category=category_filter or None,
        tier=tier_filter or None,
    )
    base_df = get_health_leaderboard(category=category_filter or None, tier=None)
    categories = get_all_categories()

    tools = df.to_dict("records") if not df.empty else []
    for row in tools:
        tier = str(row.get("health_tier") or "Unknown")
        icon, tier_class = health_tier_meta(tier)
        row["health_icon"] = icon
        row["health_tier_class"] = tier_class
        row["health_score"] = float(row.get("health_score") or 0)
        row["health_score_pct"] = max(0, min(100, int(round(row["health_score"]))))

        signal, _, _ = signal_label(float(row.get("emergence_score") or 0), int(row.get("total_repos") or 0))
        icon_map = {
            "Breakout": "🚀 Breakout",
            "Rising": "↑ Rising",
            "Fading": "↓ Fading",
            "Stable": "→ Stable",
            "Active": "→ Active",
            "Dominant": "👑 Dominant",
        }
        row["momentum_label"] = icon_map.get(signal, signal)

        advisories_total = int(row.get("advisory_total") or 0)
        advisories_critical = int(row.get("advisory_critical") or 0)
        advisories_high = int(row.get("advisory_high") or 0)
        if advisories_total == 0:
            row["advisories_text"] = "None"
            row["advisories_class"] = "health-good"
        else:
            row["advisories_text"] = f"{advisories_critical}C {advisories_high}H"
            row["advisories_class"] = "health-warn" if advisories_total <= 2 else "health-bad"

        last_release_days = row.get("last_release_days")
        if isinstance(last_release_days, float) and math.isnan(last_release_days):
            row["last_release_text"] = "unknown"
        elif isinstance(last_release_days, (int, float)):
            row["last_release_text"] = format_days_ago(int(last_release_days))
        else:
            row["last_release_text"] = "unknown"

        enterprise_count = int(row.get("enterprise_repo_count") or 0)
        row["enterprise_text"] = f"{enterprise_count} orgs" if enterprise_count > 0 else "—"

        if tier == "Healthy":
            row["health_row_class"] = "health-row-healthy"
        elif tier == "Monitoring Required":
            row["health_row_class"] = "health-row-monitoring"
        elif tier in {"Declining Health", "Critical Concerns"}:
            row["health_row_class"] = "health-row-critical"
        else:
            row["health_row_class"] = "row-default"

    if base_df.empty:
        healthy_count = 0
        monitoring_count = 0
        declining_count = 0
        critical_count = 0
        known_count = 0
    else:
        healthy_count = int((base_df["health_tier"] == "Healthy").sum())
        monitoring_count = int((base_df["health_tier"] == "Monitoring Required").sum())
        declining_count = int((base_df["health_tier"] == "Declining Health").sum())
        critical_count = int((base_df["health_tier"] == "Critical Concerns").sum())
        known_count = int(len(base_df))

    total_tools_in_scope = len(get_all_tools(category=category_filter or None))
    unknown_count = max(0, total_tools_in_scope - known_count)
    critical_or_unknown = critical_count + unknown_count

    return render_template(
        "health.html",
        page_title="Tool Health Rankings",
        tools=tools,
        categories=categories,
        selected_category=category_filter,
        selected_tier=tier_filter,
        total_count=len(tools),
        healthy_count=healthy_count,
        monitoring_count=monitoring_count,
        declining_count=declining_count,
        critical_or_unknown_count=critical_or_unknown,
    )


@app.get("/ops")
def ops():
    data = get_ops_data()
    return render_template("ops.html", page_title="Ops", data=data)


@app.get("/radar")
def radar():
    if not db_has_data():
        return render_template("empty.html", page_title="The Radar")

    radar_snapshot = get_radar_snapshot()
    tools = radar_snapshot["tools"]
    for tool in tools:
        tool["confidence_tooltip"] = tool.get("confidence_tooltip") or confidence_badge_copy(
            tool.get("confidence_tier") or "Low",
            int(tool.get("sample_size") or tool.get("total_repos") or 0),
        )
        trend_reliable = int(tool.get("is_trend_reliable") or 0) == 1
        repos_delta = int(tool.get("repos_delta_7d") or 0)
        tool["repos_delta_display"], tool["repos_delta_class"] = format_delta(repos_delta)
        tool["show_repos_delta"] = not (repos_delta == 0 and not trend_reliable)

        contributors = get_tool_top_contributors(tool["canonical_name"], limit=3)
        top_builders = []
        for c in contributors:
            top_builders.append(
                {
                    "github_login": c.get("github_login"),
                    "name": c.get("name") or "",
                    "contributions": int(c.get("contributions") or 0),
                    "followers": int(c.get("followers") or 0),
                    "company": c.get("company") or "",
                    "bio": c.get("bio") or "",
                    "html_url": c.get("html_url") or "",
                    "is_notable": int(c.get("followers") or 0) >= 500,
                }
            )
        tool["top_builders"] = top_builders
        tool["has_contributor_data"] = len(top_builders) > 0

        days_since = tool.get("days_since_ecosystem_activity")
        days_since_int = int(days_since) if days_since is not None else None
        tool["activity_signal"] = format_activity_signal(days_since_int)
        tool["days_since_ecosystem_activity"] = days_since_int
        tool["activity_class"] = "activity-muted"
        tool["low_activity_note"] = ""
        if days_since_int is not None:
            if days_since_int <= 7:
                tool["activity_class"] = "activity-green"
            elif days_since_int <= 30:
                tool["activity_class"] = "activity-amber"
            elif days_since_int <= 90:
                tool["activity_class"] = "activity-muted"
            else:
                tool["activity_class"] = "activity-red"
                tool["low_activity_note"] = "(low recent activity)"

        builder_count = int(tool.get("active_builder_count") or 0)
        if builder_count == 0 and not tool["has_contributor_data"]:
            tool["builder_note"] = "Contributor data not yet collected — run scripts/06_fetch_contributors.py"
            tool["builder_note_class"] = "builder-note-muted"
        elif builder_count == 1:
            tool["builder_note"] = "Single maintainer — bus factor risk"
            tool["builder_note_class"] = "builder-note-amber"
        elif 2 <= builder_count <= 5:
            tool["builder_note"] = "Small focused team"
            tool["builder_note_class"] = "builder-note-muted"
        else:
            tool["builder_note"] = f"Active community ({builder_count} contributors)"
            tool["builder_note_class"] = "builder-note-green"

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
