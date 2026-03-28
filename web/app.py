from __future__ import annotations

import logging
import math
import time
from typing import Any

from flask import Flask, redirect, render_template, request, url_for

from web.data import (
    confidence_badge_copy,
    db_has_data,
    format_activity_signal,
    generate_comparison_verdict,
    generate_category_memo,
    generate_tool_insight,
    get_all_categories,
    get_all_tools,
    get_category_share_bars,
    get_category_tools,
    get_health_leaderboard,
    get_latest_snapshot_date,
    get_ops_data,
    get_org_tools,
    get_pre_commercial_signal,
    get_radar_snapshot,
    get_radar_tools,
    get_snapshot_freshness_status,
    get_summary_stats,
    get_tool_contributors,
    get_tool_detail,
    get_tool_health,
    get_tool_top_contributors,
    is_notable_contributor,
    latest_snapshot_date,
    phase_explainer,
    signal_label,
)

app = Flask(__name__, template_folder="templates", static_folder="static")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def check_startup_health() -> None:
    """Runs on app startup. Logs warnings but never crashes the app."""
    try:
        import os

        from web.data import DB_PATH, _conn

        if not os.path.exists(DB_PATH):
            logger.warning("DB file not found at %s — app will show empty state", DB_PATH)
            return

        conn = _conn()
        count = conn.execute("SELECT COUNT(*) FROM tools").fetchone()[0]
        snap_date = conn.execute("SELECT MAX(snapshot_date) FROM tool_snapshots").fetchone()[0]
        conn.close()

        logger.info("Startup health: %s tools, latest snapshot: %s", count, snap_date)

        if count == 0:
            logger.warning("No tools in DB — run scripts/01_seed_tools.py")
        if not snap_date:
            logger.warning("No snapshots — run scripts/run_all.py")
    except Exception as exc:
        logger.error("Startup health check failed: %s", exc)


check_startup_health()


def format_number_value(n: Any) -> str:
    if n is None:
        return "—"
    value = float(n)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(int(value))


def format_downloads_value(n: Any) -> str:
    if not n:
        return "—"
    value = float(n)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return str(int(value))


def format_delta_value(n: Any) -> str:
    if not n:
        return "—"
    value = int(n)
    return f"+{value:,}" if value > 0 else f"{value:,}"


@app.template_filter("format_number")
def format_number_filter(n: Any) -> str:
    return format_number_value(n)


@app.template_filter("format_downloads")
def format_downloads_filter(n: Any) -> str:
    return format_downloads_value(n)


@app.template_filter("format_delta")
def format_delta_filter(n: Any) -> str:
    return format_delta_value(n)


def signal_info(emergence_score: Any, total_repos: Any) -> tuple[str, str]:
    score = float(emergence_score or 0)
    total = int(total_repos or 0)
    signal, _, _ = signal_label(score, total)
    mapping = {
        "Dominant": ("◆ Dominant", "purple"),
        "Breakout": ("🚀 Breakout", "green"),
        "Rising": ("↑ Rising", "green"),
        "Stable": ("→ Stable", "amber"),
        "Active": ("→ Stable", "amber"),
        "Fading": ("↓ Fading", "red"),
    }
    return mapping.get(signal, ("→ Stable", "amber"))


def health_badge(tier: str | None) -> str:
    mapping = {
        "Healthy": "green",
        "Monitoring Required": "amber",
        "Declining Health": "red",
        "Critical Concerns": "red",
        "Unknown": "neutral",
        None: "neutral",
    }
    return mapping.get(tier, "neutral")


def phase_badge(phase: str | None) -> str:
    mapping = {
        "Mature": "neutral",
        "Consolidating": "purple",
        "Early / Competing": "blue",
        "Fragmenting": "amber",
        "In Transition": "amber",
    }
    return mapping.get(phase, "neutral")


def eco_colors(ecosystem: str | None) -> tuple[str, str]:
    colors = {
        "npm": ("#FEF9C3", "#D97706"),
        "pypi": ("#EFF6FF", "#2563EB"),
        "cargo": ("#FEF2F2", "#DC2626"),
        "go": ("#F0FDF4", "#16A34A"),
    }
    return colors.get(str(ecosystem or "").lower(), ("#F4F4F5", "#71717A"))


def score_tier_class(score: Any) -> str:
    value = float(score or 0)
    if value >= 75:
        return "metric-positive"
    if value >= 50:
        return "metric-warning"
    return "metric-negative"


def format_days_ago(days: Any) -> str:
    if days is None:
        return "unknown"
    try:
        value = int(days)
    except (TypeError, ValueError):
        return "unknown"
    if value <= 30:
        return f"{value} days ago"
    if value <= 365:
        months = max(1, round(value / 30))
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = max(1, round(value / 365))
    return f"{years} year{'s' if years != 1 else ''} ago"


def health_metric_class(metric: str, value: Any, permissive: int | None = None) -> str:
    if metric == "release":
        if value is None:
            return "metric-muted"
        days = int(value)
        if days <= 30:
            return "metric-positive"
        if days <= 90:
            return "metric-default"
        if days <= 180:
            return "metric-warning"
        return "metric-negative"
    if metric == "advisories":
        total = int(value or 0)
        if total == 0:
            return "metric-positive"
        if total <= 2:
            return "metric-warning"
        return "metric-negative"
    if metric == "deps":
        if value is None:
            return "metric-muted"
        deps = int(value)
        if deps <= 50:
            return "metric-positive"
        if deps <= 200:
            return "metric-default"
        if deps <= 500:
            return "metric-warning"
        return "metric-negative"
    if metric == "license":
        if value in (None, "", "unknown"):
            return "metric-muted"
        return "metric-positive" if int(permissive or 0) == 1 else "metric-warning"
    return "metric-default"


def initials(name: str | None) -> str:
    parts = [p for p in str(name or "").replace("-", " ").split() if p]
    if not parts:
        return "UT"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[1][0]}".upper()


def signal_rank(label: str) -> int:
    return {
        "◆ Dominant": 5,
        "🚀 Breakout": 4,
        "↑ Rising": 3,
        "→ Stable": 2,
        "↓ Fading": 1,
    }.get(label, 0)


def latest_date_text() -> str:
    snap = latest_snapshot_date()
    return snap or "unknown"


TOOLTIPS = {
    "emergence_score": "Growth speed relative to size. High score means growing fast from a small base.",
    "fragmentation_index": "How spread out adoption is across tools. Higher means teams are split across many options.",
    "transitive_deps": "Total packages this tool pulls in when installed. More indirect dependencies means more inherited complexity.",
    "confidence_tier": "Data quality signal. High means 50+ repos tracked. Low means directional only.",
    "enterprise_adopters": "Repos owned by known engineering-rigorous organizations. This is a quality signal, not a guarantee.",
    "bus_factor": "How many people could leave before the project stalls. Single-maintainer tools carry more continuity risk.",
    "active_repos": "Repos using this tool that were updated in the last 30 days. A live usage signal, not just an install count.",
}


@app.context_processor
def inject_helpers():
    return dict(
        signal_info=signal_info,
        health_badge=health_badge,
        phase_badge=phase_badge,
        eco_colors=eco_colors,
        latest_date_text=latest_date_text,
        phase_explainer=phase_explainer,
        initials=initials,
        TOOLTIPS=TOOLTIPS,
        latest_snapshot_date=get_latest_snapshot_date(),
        freshness_status=get_snapshot_freshness_status(),
    )


def render_empty(page_title: str, active: str = "explore"):
    return render_template("empty.html", page_title=page_title, active=active)


def enrich_tool(tool: dict[str, Any]) -> dict[str, Any]:
    item = dict(tool)
    item["signal_label"], item["signal_class"] = signal_info(
        item.get("emergence_score"), item.get("total_repos")
    )
    item["confidence_tooltip"] = item.get("confidence_tooltip") or confidence_badge_copy(
        item.get("confidence_tier") or "Low",
        int(item.get("sample_size") or item.get("total_repos") or 0),
    )
    item["repos_delta_display"] = format_delta_value(item.get("repos_delta_7d"))
    item["downloads_display"] = format_downloads_value(item.get("weekly_downloads"))
    item["eco_class"] = f"eco-{str(item.get('ecosystem') or 'other').lower()}"
    item["tool_initials"] = initials(item.get("display_name"))
    return item


def enrich_health(tool: dict[str, Any], health: dict[str, Any] | None = None) -> dict[str, Any]:
    info = dict(health or get_tool_health(tool["canonical_name"]) or {})
    tier = info.get("health_tier") or "Unknown"
    info["health_tier"] = tier
    info["health_badge_class"] = health_badge(tier)
    info["health_score_class"] = score_tier_class(info.get("health_score"))
    info["last_release_text"] = format_days_ago(info.get("last_release_days"))
    info["advisories_text"] = "None" if int(info.get("advisory_total") or 0) == 0 else str(
        int(info.get("advisory_total") or 0)
    )
    info["transitive_text"] = (
        f"{int(info['transitive_dep_count']):,} packages"
        if info.get("transitive_dep_count") is not None
        else "unknown"
    )
    license_value = info.get("license") or "unknown"
    info["license_text"] = license_value
    info["release_class"] = health_metric_class("release", info.get("last_release_days"))
    info["advisory_class"] = health_metric_class("advisories", info.get("advisory_total"))
    info["deps_class"] = health_metric_class("deps", info.get("transitive_dep_count"))
    info["license_class"] = health_metric_class(
        "license", license_value, info.get("license_is_permissive")
    )
    return info


def build_category_cards() -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    share_bars = get_category_share_bars()
    for category in get_all_categories():
        item = dict(category)
        tools = sorted(
            [enrich_tool(t) for t in get_category_tools(item["category"])],
            key=lambda row: int(row.get("total_repos") or 0),
            reverse=True,
        )
        total_repos = sum(int(t.get("total_repos") or 0) for t in tools)
        top_a = tools[0] if tools else None
        top_b = tools[1] if len(tools) > 1 else None
        item["repo_count"] = total_repos
        item["top_tool_1"] = top_a.get("display_name") if top_a else ""
        item["top_tool_1_share"] = (
            (int(top_a.get("total_repos") or 0) / max(1, total_repos)) * 100 if top_a else 0
        )
        item["top_tool_2"] = top_b.get("display_name") if top_b else ""
        item["top_tool_2_share"] = (
            (int(top_b.get("total_repos") or 0) / max(1, total_repos)) * 100 if top_b else 0
        )
        item["phase_badge_class"] = phase_badge(item.get("market_phase"))
        item["tools"] = tools
        item["fragmentation_pct"] = min(100, max(8, int(float(item.get("fragmentation_index") or 0) * 100)))
        item["share_bar"] = share_bars.get(item["category"], [])
        cards.append(item)
    return cards


def build_category_tool_cards(category: str) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for tool in get_category_tools(category):
        item = enrich_tool(tool)
        health = enrich_health(item)
        item["health"] = health
        item["health_tier"] = health.get("health_tier")
        item["health_badge_class"] = health.get("health_badge_class")
        item["sort_repos"] = int(item.get("total_repos") or 0)
        item["sort_growth"] = float(item.get("emergence_score") or 0)
        item["sort_health"] = float(health.get("health_score") or 0)
        cards.append(item)
    cards.sort(key=lambda row: row["sort_repos"], reverse=True)
    return cards


def build_fragmentation_bars(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = sum(int(t.get("total_repos") or 0) for t in tools)
    bars: list[dict[str, Any]] = []
    for tool in tools[:6]:
        share = (int(tool.get("total_repos") or 0) / max(1, total)) * 100
        bars.append(
            {
                "name": tool["display_name"],
                "share": share,
                "label": f"{share:.0f}%",
                "signal_label": tool["signal_label"],
                "signal_class": tool["signal_class"],
            }
        )
    return bars


def build_tool_detail_payload(name: str) -> dict[str, Any] | None:
    tool = get_tool_detail(name)
    if not tool:
        return None

    item = enrich_tool(tool)
    health = enrich_health(item, item.get("health"))
    contributors = get_tool_contributors(name)[:5]
    for contributor in contributors:
        contributor["is_notable"] = is_notable_contributor(contributor)
        contributor["initials"] = initials(contributor.get("name") or contributor.get("github_login"))
    similar = [
        enrich_tool(row)
        for row in get_category_tools(item.get("category", ""))
        if row["canonical_name"] != name
    ][:4]

    enterprise_orgs = []
    seen_orgs: set[str] = set()
    for repo in item.get("enterprise_repos", []):
        org = repo.get("org")
        if org and org not in seen_orgs:
            seen_orgs.add(org)
            enterprise_orgs.append(org)

    stats = [
        {
            "label": "Repos using it",
            "value": format_number_value(item.get("total_repos")),
            "sub": "repos with 500+ stars",
            "delta": format_delta_value(item.get("repos_delta_7d")),
            "delta_class": "metric-positive" if int(item.get("repos_delta_7d") or 0) > 0 else (
                "metric-negative" if int(item.get("repos_delta_7d") or 0) < 0 else "metric-muted"
            ),
        },
        {
            "label": "New (90 days)",
            "value": format_number_value(item.get("new_repos_90d")),
            "sub": "recently adopted",
        },
        {
            "label": "Weekly downloads",
            "value": format_downloads_value(item.get("weekly_downloads")),
            "sub": item.get("downloads_source") or "not available",
            "delta": format_delta_value(item.get("downloads_delta_7d")),
            "delta_class": "metric-positive" if int(item.get("downloads_delta_7d") or 0) > 0 else (
                "metric-negative" if int(item.get("downloads_delta_7d") or 0) < 0 else "metric-muted"
            ),
        },
        {
            "label": "Health score",
            "value": f"{float(health.get('health_score') or 0):.0f}/100" if health else "—",
            "sub": "dependency health",
            "value_class": health.get("health_score_class", "metric-muted"),
        },
        {
            "label": "Enterprise",
            "value": f"{int(item.get('enterprise_repo_count') or 0)} orgs" if int(item.get("enterprise_repo_count") or 0) > 0 else "—",
            "sub": "known orgs",
        },
    ]

    trend_points = item.get("history") or []
    version_spread = item.get("version_spread") or []
    trend_chart = {
        "x": [point["snapshot_date"] for point in trend_points],
        "y": [int(point["total_repos"]) for point in trend_points],
        "mode": "lines+markers" if len(trend_points) >= 4 else "markers",
    }
    version_chart = {
        "labels": [row["version_normalized"] for row in version_spread],
        "values": [int(row["cnt"]) for row in version_spread],
    }

    version_summary = None
    top_version_pct = 0
    if version_spread:
        top_version = version_spread[0]
        total_on_top = int(top_version.get("cnt") or 0)
        total_version_repos = sum(int(row.get("cnt") or 0) for row in version_spread)
        top_version_pct = round((total_on_top / max(1, total_version_repos)) * 100)
        version_summary = (
            f"{top_version_pct}% of repos are on the most common version "
            f"({top_version.get('version_normalized', 'latest')})"
        )

    usage_panels = {
        "integration": format_number_value(item.get("total_repos")),
        "integration_sub": "GitHub dependency files",
        "downloads": format_downloads_value(item.get("weekly_downloads")),
        "downloads_sub": (
            f"{item.get('downloads_source')} registry / week" if item.get("downloads_source") else "registry signal unavailable"
        ),
    }

    return {
        "tool": item,
        "health": health,
        "contributors": contributors,
        "similar": similar,
        "enterprise_orgs": enterprise_orgs,
        "pre_commercial_signal": get_pre_commercial_signal(
            name, item.get("github_repo"), contributors=contributors
        ),
        "insight": generate_tool_insight(item),
        "stats": stats,
        "trend_chart": trend_chart,
        "version_chart": version_chart,
        "usage_panels": usage_panels,
        "trend_reliable": int(item.get("is_trend_reliable") or 0) == 1,
        "version_summary": version_summary,
        "top_version_pct": top_version_pct,
    }


def compare_metric_row(
    section: str,
    label: str,
    a_value: Any,
    b_value: Any,
    *,
    higher_is_better: bool | None = None,
) -> dict[str, Any]:
    winner = ""
    if higher_is_better is not None and a_value is not None and b_value is not None:
        if a_value != b_value:
            if higher_is_better:
                winner = "a" if a_value > b_value else "b"
            else:
                winner = "a" if a_value < b_value else "b"
    return {"section": section, "label": label, "winner": winner}


@app.route("/", endpoint="home")
def explore():
    if not db_has_data():
        return render_empty("Explore", "explore")

    categories = build_category_cards()
    stats = get_summary_stats()
    emerging = [enrich_tool(tool) for tool in get_radar_tools()[:3]]
    all_tools_flat = [
        {
            "canonical_name": tool["canonical_name"],
            "display_name": tool["display_name"],
            "category": tool["category"],
            "ecosystem": tool["ecosystem"],
        }
        for tool in get_all_tools()
    ]
    return render_template(
        "explore.html",
        page_title="Explore",
        active="explore",
        categories=categories,
        stats=stats,
        emerging=emerging,
        all_tools_flat=all_tools_flat,
    )


@app.route("/category", endpoint="category_view")
def category():
    if not db_has_data():
        return render_empty("Category View", "explore")

    categories = build_category_cards()
    if not categories:
        return render_empty("Category View", "explore")

    selected = request.args.get("name", "").strip()
    names = {category["category"] for category in categories}
    if not selected or selected not in names:
        selected = categories[0]["category"]

    cat_data = next(category for category in categories if category["category"] == selected)
    tools = build_category_tool_cards(selected)
    memo = generate_category_memo(selected)
    fragmentation_bars = build_fragmentation_bars(tools)
    return render_template(
        "category.html",
        page_title=selected,
        active="explore",
        categories=categories,
        selected=selected,
        tools=tools,
        cat_data=cat_data,
        memo=memo,
        fragmentation_bars=fragmentation_bars,
    )


@app.route("/tool", endpoint="tool_detail")
def tool():
    if not db_has_data():
        return render_empty("Tool", "explore")

    all_tools = [enrich_tool(tool) for tool in get_all_tools()]
    if not all_tools:
        return render_empty("Tool", "explore")

    selected = request.args.get("name", "").strip()
    valid_names = {tool["canonical_name"] for tool in all_tools}
    if not selected or selected not in valid_names:
        selected = all_tools[0]["canonical_name"]

    payload = build_tool_detail_payload(selected)
    if not payload:
        return render_empty("Tool", "explore")

    return render_template(
        "tool.html",
        page_title=payload["tool"]["display_name"],
        active="explore",
        all_tools=all_tools,
        tool=payload["tool"],
        health=payload["health"],
        contributors=payload["contributors"],
        similar=payload["similar"],
        enterprise_orgs=payload["enterprise_orgs"],
        pre_commercial_signal=payload["pre_commercial_signal"],
        insight=payload["insight"],
        stats=payload["stats"],
        trend_chart=payload["trend_chart"],
        version_chart=payload["version_chart"],
        usage_panels=payload["usage_panels"],
        trend_reliable=payload["trend_reliable"],
        version_summary=payload["version_summary"],
        top_version_pct=payload["top_version_pct"],
    )


@app.route("/compare")
def compare():
    if not db_has_data():
        return render_empty("Compare", "explore")

    all_tools = [enrich_tool(tool) for tool in get_all_tools()]
    selected_a = request.args.get("a", "").strip()
    selected_b = request.args.get("b", "").strip()
    valid = {tool["canonical_name"] for tool in all_tools}
    tool_a = build_tool_detail_payload(selected_a) if selected_a in valid else None
    tool_b = build_tool_detail_payload(selected_b) if selected_b in valid else None

    comparison_rows: list[dict[str, Any]] = []
    verdict = ""
    if tool_a and tool_b and tool_a["tool"]["canonical_name"] != tool_b["tool"]["canonical_name"]:
        a = tool_a["tool"]
        b = tool_b["tool"]
        health_a = tool_a["health"]
        health_b = tool_b["health"]
        a_signal = signal_info(a.get("emergence_score"), a.get("total_repos"))[0]
        b_signal = signal_info(b.get("emergence_score"), b.get("total_repos"))[0]

        rows = [
            ("Overview", "Ecosystem", a.get("ecosystem"), b.get("ecosystem"), None),
            ("Overview", "Category", a.get("category"), b.get("category"), None),
            ("Overview", "Signal", a_signal, b_signal, "signal"),
            ("Adoption", "Repos using it", int(a.get("total_repos") or 0), int(b.get("total_repos") or 0), True),
            ("Adoption", "New adopters (90d)", int(a.get("new_repos_90d") or 0), int(b.get("new_repos_90d") or 0), True),
            ("Adoption", "Week delta", int(a.get("repos_delta_7d") or 0), int(b.get("repos_delta_7d") or 0), True),
            ("Adoption", "Weekly downloads", int(a.get("weekly_downloads") or 0), int(b.get("weekly_downloads") or 0), True),
            ("Adoption", "Enterprise orgs", int(a.get("enterprise_repo_count") or 0), int(b.get("enterprise_repo_count") or 0), True),
            ("Health", "Health score", float(health_a.get("health_score") or 0), float(health_b.get("health_score") or 0), True),
            ("Health", "Health tier", health_a.get("health_tier") or "Unknown", health_b.get("health_tier") or "Unknown", None),
            ("Health", "Last release", health_a.get("last_release_days"), health_b.get("last_release_days"), False),
            ("Health", "Known advisories", int(health_a.get("advisory_total") or 0), int(health_b.get("advisory_total") or 0), False),
            ("Health", "Transitive deps", health_a.get("transitive_dep_count"), health_b.get("transitive_dep_count"), False),
            ("Health", "License", health_a.get("license") or "unknown", health_b.get("license") or "unknown", None),
            ("Team", "Active builders", int(a.get("active_builder_count") or 0), int(b.get("active_builder_count") or 0), True),
            (
                "Team",
                "Top contributor",
                tool_a["contributors"][0]["github_login"] if tool_a["contributors"] else "—",
                tool_b["contributors"][0]["github_login"] if tool_b["contributors"] else "—",
                None,
            ),
            ("Confidence", "Data confidence", a.get("confidence_tier") or "Low", b.get("confidence_tier") or "Low", None),
            (
                "Confidence",
                "Trend reliable",
                "Yes" if int(a.get("is_trend_reliable") or 0) == 1 else "Building",
                "Yes" if int(b.get("is_trend_reliable") or 0) == 1 else "Building",
                None,
            ),
        ]

        for section, label, a_value, b_value, comparator in rows:
            row = compare_metric_row(
                section,
                label,
                a_value if isinstance(a_value, (int, float)) else None,
                b_value if isinstance(b_value, (int, float)) else None,
                higher_is_better=comparator if isinstance(comparator, bool) else None,
            )
            if comparator == "signal":
                a_rank = signal_rank(a_signal)
                b_rank = signal_rank(b_signal)
                row["winner"] = "a" if a_rank > b_rank else ("b" if b_rank > a_rank else "")

            if label == "Week delta":
                row["a_display"] = format_delta_value(a_value)
                row["b_display"] = format_delta_value(b_value)
            elif label == "Weekly downloads":
                row["a_display"] = format_downloads_value(a_value)
                row["b_display"] = format_downloads_value(b_value)
            elif label == "Last release":
                row["a_display"] = format_days_ago(a_value)
                row["b_display"] = format_days_ago(b_value)
            elif label == "Known advisories":
                row["a_display"] = "None" if int(a_value or 0) == 0 else str(int(a_value or 0))
                row["b_display"] = "None" if int(b_value or 0) == 0 else str(int(b_value or 0))
            elif label == "Transitive deps":
                row["a_display"] = f"{int(a_value):,}" if a_value is not None else "unknown"
                row["b_display"] = f"{int(b_value):,}" if b_value is not None else "unknown"
            elif label == "Health score":
                row["a_display"] = f"{float(a_value or 0):.0f}"
                row["b_display"] = f"{float(b_value or 0):.0f}"
            else:
                row["a_display"] = format_number_value(a_value) if isinstance(a_value, (int, float)) else a_value
                row["b_display"] = format_number_value(b_value) if isinstance(b_value, (int, float)) else b_value
            comparison_rows.append(row)

        verdict = generate_comparison_verdict(a, b, health_a, health_b)

    return render_template(
        "compare.html",
        page_title="Compare",
        active="explore",
        all_tools=all_tools,
        selected_a=selected_a,
        selected_b=selected_b,
        tool_a=tool_a,
        tool_b=tool_b,
        comparison_rows=comparison_rows,
        verdict=verdict,
    )


@app.route("/radar")
def radar():
    if not db_has_data():
        return render_empty("Radar", "radar")

    snapshot = get_radar_snapshot()
    tools = [enrich_tool(tool) for tool in get_radar_tools()]
    for tool in tools:
        tool["activity_signal"] = format_activity_signal(tool.get("days_since_ecosystem_activity"))
        tool["pre_commercial_signal"] = get_pre_commercial_signal(
            tool["canonical_name"], tool.get("github_repo")
        )
        tool["top_builders"] = get_tool_top_contributors(tool["canonical_name"], limit=3)
        for builder in tool["top_builders"]:
            builder["is_notable"] = int(builder.get("followers") or 0) >= 500
    return render_template(
        "radar.html",
        page_title="Radar",
        active="radar",
        tools=tools,
        radar_snapshot=snapshot,
    )


@app.route("/health")
def health_page():
    if not db_has_data():
        return render_empty("Health", "health")

    category_filter = request.args.get("category", "").strip()
    tier_filter = request.args.get("tier", "").strip()
    df = get_health_leaderboard(category=category_filter or None, tier=tier_filter or None)
    full_df = get_health_leaderboard(category=category_filter or None, tier=None)

    tools = df.to_dict("records") if not df.empty else []
    for tool in tools:
        tool["signal_label"], tool["signal_class"] = signal_info(
            tool.get("emergence_score"), tool.get("total_repos")
        )
        tool["health_badge_class"] = health_badge(tool.get("health_tier"))
        tool["last_release_text"] = format_days_ago(tool.get("last_release_days"))
        tool["advisories_text"] = "None" if int(tool.get("advisory_total") or 0) == 0 else (
            f"{int(tool.get('advisory_critical') or 0)}C {int(tool.get('advisory_total') or 0)} total"
        )
        tool["advisory_class"] = health_metric_class("advisories", tool.get("advisory_total"))
        tool["enterprise_text"] = (
            f"{int(tool.get('enterprise_repo_count') or 0)} orgs"
            if int(tool.get("enterprise_repo_count") or 0) > 0
            else "—"
        )
        tier = str(tool.get("health_tier") or "Unknown")
        if tier == "Healthy":
            tool["row_tint"] = "row-tint-green"
        elif tier == "Monitoring Required":
            tool["row_tint"] = "row-tint-amber"
        else:
            tool["row_tint"] = "row-tint-red"

    healthy_count = int((full_df["health_tier"] == "Healthy").sum()) if not full_df.empty else 0
    monitoring_count = int((full_df["health_tier"] == "Monitoring Required").sum()) if not full_df.empty else 0
    declining_count = int((full_df["health_tier"] == "Declining Health").sum()) if not full_df.empty else 0
    critical_count = int((full_df["health_tier"] == "Critical Concerns").sum()) if not full_df.empty else 0
    total_known = len(full_df) if not full_df.empty else 0
    total_tools = len(get_all_tools(category=category_filter or None))
    scatter_data = [
        {
            "display_name": tool["display_name"],
            "category": tool["category"],
            "emergence_score": float(tool.get("emergence_score") or 0),
            "health_score": float(tool.get("health_score") or 0),
            "health_tier": tool.get("health_tier") or "Unknown",
            "total_repos": int(tool.get("total_repos") or 0),
        }
        for tool in tools
    ]

    return render_template(
        "health.html",
        page_title="Health",
        active="health",
        tools=tools,
        categories=build_category_cards(),
        selected_category=category_filter,
        selected_tier=tier_filter,
        total_count=len(tools),
        healthy_count=healthy_count,
        monitoring_count=monitoring_count,
        declining_count=declining_count,
        critical_or_unknown_count=max(0, total_tools - total_known) + critical_count,
        scatter_data=scatter_data,
    )


@app.route("/memo")
@app.route("/memo/<category_slug>")
def memo(category_slug: str | None = None):
    if not db_has_data():
        return render_empty("Briefs", "memo")

    categories = build_category_cards()
    if category_slug:
        slug_map = {
            cat["category"].lower().replace("/", "-").replace(" ", "-"): cat["category"]
            for cat in categories
        }
        if category_slug not in slug_map:
            return redirect(url_for("memo"))
        selected = slug_map[category_slug]
    else:
        selected = request.args.get("category", "").strip()
    memo_data = generate_category_memo(selected) if selected else None
    return render_template(
        "memo.html",
        page_title="Briefs",
        active="memo",
        categories=categories,
        selected=selected,
        memo=memo_data,
        category_slug=category_slug,
    )


@app.route("/learn")
def learn():
    if not db_has_data():
        return render_empty("About", "learn")
    return render_template("learn.html", page_title="About", active="learn")


@app.route("/ops")
def ops():
    return render_template(
        "ops.html",
        page_title="Ops",
        active="memo",
        data=get_ops_data(),
    )


@app.route("/org/<org_name>")
def org_detail(org_name: str):
    tools = [enrich_tool(tool) for tool in get_org_tools(org_name)]
    return render_template(
        "org.html",
        page_title=f"{org_name} on GitHub",
        active="explore",
        org_name=org_name,
        tools=tools,
    )


@app.route("/healthz")
def healthz():
    return {"status": "ok", "timestamp": time.time()}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
