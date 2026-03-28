from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import median

import math

try:
    from scripts.db import get_conn, init_db
    from scripts.enterprise_orgs import ENTERPRISE_ORGS
except ModuleNotFoundError:
    from db import get_conn, init_db
    from enterprise_orgs import ENTERPRISE_ORGS


CATEGORY_DESCRIPTIONS = {
    "Testing": "Tools for writing and running automated tests to validate software behavior.",
    "ORM": "Libraries for working with databases using application models instead of raw SQL.",
    "Linting": "Tools that enforce code quality, formatting, typing, and style consistency.",
    "Package Manager": "Tools used to install, resolve, and lock project dependencies.",
    "API Framework": "Frameworks used to build backend web services and APIs.",
    "UI Components": "Libraries of reusable interface components for front-end applications.",
    "Bundler": "Build tools that compile, bundle, and optimize application code.",
    "State Management": "Tools that manage shared application state and data flow in apps.",
    "AI/ML": "Frameworks and SDKs for building AI-powered applications and agent systems.",
    "AI Observability": "Tools for monitoring, debugging, and evaluating LLM applications and AI agents.",
    "Vector DB": "Databases optimized for storing and searching high-dimensional vector embeddings.",
    "Data Pipeline": "Tools for orchestrating, scheduling, and monitoring data workflows.",
    "MCP Servers": "Model Context Protocol servers that connect AI tools to external systems and developer workflows.",
}


def compute_emergence_score(total_repos: int, new_repos_90d: int, active_repos: int) -> float:
    if total_repos == 0:
        return 0.0
    recency_ratio = new_repos_90d / max(1, total_repos)
    activity_ratio = active_repos / max(1, total_repos)
    size_log = math.log1p(total_repos)
    score = (recency_ratio * 0.5 + activity_ratio * 0.3) * size_log * 10
    return round(min(score, 100.0), 2)


def fragmentation_index(tool_repo_counts: list[int]) -> float:
    total = sum(tool_repo_counts)
    if total == 0:
        return 0.0
    shares = [c / total for c in tool_repo_counts]
    hhi = sum(s ** 2 for s in shares)
    return round(1 - hhi, 3)


def market_phase(frag_index: float, top_share_pct: float, avg_emergence: float) -> tuple[str, str]:
    if top_share_pct > 60:
        return "Mature", "One tool dominates. The market has decided."
    if frag_index > 0.65 and avg_emergence > 20:
        return "Early / Competing", "Multiple tools are fighting for dominance. No clear winner yet."
    if frag_index <= 0.50 and top_share_pct > 35:
        return "Consolidating", "A winner is emerging. Others are losing ground."
    if frag_index > 0.65 and avg_emergence < 10:
        return "Fragmenting", "Many tools exist but none are gaining momentum."
    return "In Transition", "Something is shifting here. The current leader may not hold."


def fragmentation_plain_label(frag: float) -> str:
    if frag > 0.7:
        return "No clear winner - many tools competing"
    if 0.5 <= frag <= 0.7:
        return "A leader is emerging but not dominant yet"
    if 0.3 <= frag < 0.5:
        return "One or two tools pulling clearly ahead"
    return "One tool has won this category"


def generate_insight(
    category: str,
    phase: str,
    top_tool: str,
    top_pct: float,
    second_tool: str,
    second_pct: float,
    rising_tool: str,
    rising_emergence: float,
) -> str:
    if phase == "Mature":
        return (
            f"{top_tool} has effectively won the {category} category with {top_pct:.0f}% of repos. "
            "This is established infrastructure - safe to build on, low risk of disruption in the short term."
        )
    if phase == "Consolidating":
        return (
            f"{top_tool} is pulling ahead in {category} with {top_pct:.0f}% adoption, while {second_tool} holds "
            f"{second_pct:.0f}%. The gap is widening. Teams choosing a tool now are likely choosing between these two."
        )
    if phase == "Early / Competing":
        return (
            f"{category} has no dominant player yet - {top_tool} leads with only {top_pct:.0f}%, with several tools "
            f"close behind. {rising_tool} is the one to watch: it has the highest emergence score, meaning it's "
            "growing fastest relative to its size."
        )
    if phase == "Fragmenting":
        return (
            f"The {category} space is fragmented with no momentum behind any single tool. "
            "This sometimes signals an unsolved problem - or a category where developers prefer building their own solution."
        )
    return (
        f"{top_tool} is the current default in {category} at {top_pct:.0f}% share, but the category is not settled. "
        f"{second_tool} is still close enough to challenge leadership, and the next 90 days will likely decide whether this market consolidates or re-opens."
    )


def compute_confidence(total_repos: int, snapshot_count: int) -> tuple[str, str, str, str]:
    """
    Returns (tier, sample_tier, trend_tier, tooltip_text)

    Sample tiers:
        High:   50+ repos
        Medium: 15-49 repos
        Low:    under 15 repos

    Trend tiers:
        Stable:   4+ snapshots
        Building: 2-3 snapshots
        Early:    1 snapshot

    Overall tier = weaker of the two.
    """
    if total_repos >= 50:
        sample_tier = "High"
        sample_note = f"based on {total_repos} repos"
    elif total_repos >= 15:
        sample_tier = "Medium"
        sample_note = f"based on {total_repos} repos — reasonable signal"
    else:
        sample_tier = "Low"
        sample_note = f"only {total_repos} repos — treat as directional"

    if snapshot_count >= 4:
        trend_tier = "Stable"
        trend_note = f"{snapshot_count} weeks of history"
    elif snapshot_count >= 2:
        trend_tier = "Building"
        trend_note = f"{snapshot_count} snapshots — trend still forming"
    else:
        trend_tier = "Early"
        trend_note = "1 snapshot — no trend data yet"

    tier_rank = {"High": 3, "Medium": 2, "Low": 1, "Stable": 3, "Building": 2, "Early": 1}

    if tier_rank[sample_tier] <= tier_rank.get(trend_tier, 1):
        overall = sample_tier
    else:
        if trend_tier == "Early":
            overall = "Low"
        elif trend_tier == "Building":
            overall = "Medium" if sample_tier == "High" else "Low"
        else:
            overall = sample_tier

    tooltip = f"Sample: {sample_note} · Trend: {trend_note}"
    return overall, sample_tier, trend_tier, tooltip


def compute_deltas(canonical_name: str, today_total_repos: int, today_downloads: int, conn) -> tuple[int, int]:
    """
    Computes week-over-week change by comparing today's values
    to the most recent snapshot from 5-9 days ago.
    """
    today = date.today()
    window_start = (today - timedelta(days=9)).isoformat()
    window_end = (today - timedelta(days=5)).isoformat()

    prev = conn.execute(
        """
        SELECT total_repos, weekly_downloads
        FROM tool_snapshots
        WHERE canonical_name = ?
          AND snapshot_date BETWEEN ? AND ?
        ORDER BY snapshot_date DESC
        LIMIT 1
        """,
        (canonical_name, window_start, window_end),
    ).fetchone()

    if not prev:
        return 0, 0

    repos_delta = int(today_total_repos or 0) - int(prev["total_repos"] or 0)
    downloads_delta = int(today_downloads or 0) - int(prev["weekly_downloads"] or 0)
    return repos_delta, downloads_delta


def compute_is_trend_reliable(canonical_name: str, conn) -> int:
    count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM tool_snapshots WHERE canonical_name = ?",
        (canonical_name,),
    ).fetchone()["cnt"]
    return 1 if int(count or 0) >= 4 else 0


def compute_last_ecosystem_activity(canonical_name: str, conn):
    """
    Returns the most recent pushed_at date across all repos using this tool.
    """
    result = conn.execute(
        """
        SELECT MAX(pushed_at) AS max_pushed_at
        FROM tool_repos
        WHERE canonical_name = ? AND pushed_at IS NOT NULL AND stars > 0
        """,
        (canonical_name,),
    ).fetchone()["max_pushed_at"]
    return result


def compute_days_since_activity(last_activity_date):
    """
    Returns integer days since most recent ecosystem activity.
    Returns None if parsing fails or data is absent.
    """
    if not last_activity_date:
        return None
    try:
        last = datetime.fromisoformat(str(last_activity_date).replace("Z", "+00:00")).date()
        return (datetime.now(timezone.utc).date() - last).days
    except Exception:
        return None


def compute_active_builder_count(canonical_name: str, conn) -> int:
    """
    Distinct contributors on the tool's own repository.
    """
    result = conn.execute(
        """
        SELECT COUNT(DISTINCT github_login) AS cnt
        FROM tool_contributors
        WHERE canonical_name = ?
        """,
        (canonical_name,),
    ).fetchone()["cnt"]
    return int(result or 0)


def recompute_today_snapshot(conn, canonical_name: str, snapshot_date: str) -> None:
    total = conn.execute(
        """
        SELECT COUNT(DISTINCT repo_full_name) AS cnt
        FROM tool_repos
        WHERE canonical_name = ? AND stars > 0
        """,
        (canonical_name,),
    ).fetchone()["cnt"]

    active = conn.execute(
        """
        SELECT COUNT(DISTINCT repo_full_name) AS cnt
        FROM tool_repos
        WHERE canonical_name = ?
          AND stars > 0
          AND pushed_at IS NOT NULL
          AND datetime(pushed_at) >= datetime('now', '-30 day')
        """,
        (canonical_name,),
    ).fetchone()["cnt"]

    new_90 = conn.execute(
        """
        SELECT COUNT(DISTINCT repo_full_name) AS cnt
        FROM tool_repos
        WHERE canonical_name = ?
          AND stars > 0
          AND created_at IS NOT NULL
          AND datetime(created_at) >= datetime('now', '-90 day')
        """,
        (canonical_name,),
    ).fetchone()["cnt"]

    star_rows = conn.execute(
        "SELECT stars FROM tool_repos WHERE canonical_name = ? AND stars > 0",
        (canonical_name,),
    ).fetchall()
    star_vals = [row["stars"] for row in star_rows]
    star_med = float(median(star_vals)) if star_vals else 0.0

    emergence = compute_emergence_score(total, new_90, active)
    enterprise_repo_count = conn.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM tool_repos
        WHERE canonical_name = ? AND is_enterprise_repo = 1
        """,
        (canonical_name,),
    ).fetchone()["cnt"]

    existing_snapshot = conn.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM tool_snapshots
        WHERE canonical_name = ? AND snapshot_date = ?
        """,
        (canonical_name, snapshot_date),
    ).fetchone()["cnt"]
    snapshot_count = conn.execute(
        "SELECT COUNT(*) AS cnt FROM tool_snapshots WHERE canonical_name = ?",
        (canonical_name,),
    ).fetchone()["cnt"]
    projected_snapshots = int(snapshot_count or 0) + (0 if int(existing_snapshot or 0) > 0 else 1)
    tier, sample_tier, trend_tier, confidence_tooltip = compute_confidence(int(total), projected_snapshots)
    is_reliable = 1 if trend_tier == "Stable" else 0
    last_activity = compute_last_ecosystem_activity(canonical_name, conn)
    days_since_activity = compute_days_since_activity(last_activity)
    active_builder_count = compute_active_builder_count(canonical_name, conn)
    today_downloads_row = conn.execute(
        """
        SELECT weekly_downloads
        FROM tool_snapshots
        WHERE canonical_name = ? AND snapshot_date = ?
        """,
        (canonical_name, snapshot_date),
    ).fetchone()
    today_downloads = int(today_downloads_row["weekly_downloads"] or 0) if today_downloads_row else 0
    repos_delta_7d, downloads_delta_7d = compute_deltas(
        canonical_name, int(total), int(today_downloads), conn
    )

    conn.execute(
        """
        INSERT INTO tool_snapshots (
            canonical_name, snapshot_date, total_repos, active_repos,
            new_repos_90d, stars_median, emergence_score, enterprise_repo_count,
            sample_size, confidence_tier, sample_tier, trend_tier, confidence_tooltip,
            is_trend_reliable, repos_delta_7d, downloads_delta_7d,
            last_ecosystem_activity, days_since_ecosystem_activity, active_builder_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(canonical_name, snapshot_date) DO UPDATE SET
            total_repos=excluded.total_repos,
            active_repos=excluded.active_repos,
            new_repos_90d=excluded.new_repos_90d,
            stars_median=excluded.stars_median,
            emergence_score=excluded.emergence_score,
            enterprise_repo_count=excluded.enterprise_repo_count,
            sample_size=excluded.sample_size,
            confidence_tier=excluded.confidence_tier,
            sample_tier=excluded.sample_tier,
            trend_tier=excluded.trend_tier,
            confidence_tooltip=excluded.confidence_tooltip,
            is_trend_reliable=excluded.is_trend_reliable,
            repos_delta_7d=excluded.repos_delta_7d,
            downloads_delta_7d=excluded.downloads_delta_7d,
            last_ecosystem_activity=excluded.last_ecosystem_activity,
            days_since_ecosystem_activity=excluded.days_since_ecosystem_activity,
            active_builder_count=excluded.active_builder_count
        """,
        (
            canonical_name,
            snapshot_date,
            int(total),
            int(active),
            int(new_90),
            round(star_med, 2),
            emergence,
            int(enterprise_repo_count or 0),
            int(total),
            tier,
            sample_tier,
            trend_tier,
            confidence_tooltip,
            int(is_reliable),
            int(repos_delta_7d),
            int(downloads_delta_7d),
            last_activity,
            days_since_activity,
            int(active_builder_count),
        ),
    )
    reliable_now = compute_is_trend_reliable(canonical_name, conn)
    conn.execute(
        """
        UPDATE tool_snapshots
        SET is_trend_reliable = ?
        WHERE canonical_name = ? AND snapshot_date = ?
        """,
        (int(reliable_now), canonical_name, snapshot_date),
    )


def upsert_category(conn, category: str, snapshot_date: str) -> None:
    rows = conn.execute(
        """
        SELECT
            t.display_name,
            t.ecosystem,
            t.description,
            COALESCE(s.total_repos, 0) AS total_repos,
            COALESCE(s.emergence_score, 0) AS emergence_score
        FROM tools t
        LEFT JOIN tool_snapshots s
            ON t.canonical_name = s.canonical_name
            AND s.snapshot_date = ?
        WHERE t.category = ?
        ORDER BY total_repos DESC, t.display_name ASC
        """,
        (snapshot_date, category),
    ).fetchall()

    if not rows:
        return

    tool_count = len(rows)
    ecosystems = sorted({row["ecosystem"] for row in rows})
    ecosystem = ecosystems[0] if len(ecosystems) == 1 else "mixed"

    repo_counts = [int(row["total_repos"]) for row in rows]
    total_repos = sum(repo_counts)
    frag_idx = fragmentation_index(repo_counts)
    top = rows[0]
    second = rows[1] if len(rows) > 1 else rows[0]

    top_share_pct = round((top["total_repos"] / total_repos) * 100, 2) if total_repos else 0.0
    second_share_pct = round((second["total_repos"] / total_repos) * 100, 2) if total_repos else 0.0
    avg_emergence = sum(float(row["emergence_score"]) for row in rows) / max(1, len(rows))
    rising = max(rows, key=lambda r: float(r["emergence_score"]))

    phase, phase_explanation = market_phase(frag_idx, top_share_pct, avg_emergence)
    frag_plain = fragmentation_plain_label(frag_idx)
    insight = generate_insight(
        category=category,
        phase=phase,
        top_tool=top["display_name"],
        top_pct=top_share_pct,
        second_tool=second["display_name"],
        second_pct=second_share_pct,
        rising_tool=rising["display_name"],
        rising_emergence=float(rising["emergence_score"]),
    )

    conn.execute(
        """
        INSERT INTO categories (
            category, ecosystem, tool_count, description,
            market_phase, market_phase_explanation,
            fragmentation_index, fragmentation_plain,
            top_tool, top_tool_share_pct, insight_text, computed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(category) DO UPDATE SET
            ecosystem=excluded.ecosystem,
            tool_count=excluded.tool_count,
            description=excluded.description,
            market_phase=excluded.market_phase,
            market_phase_explanation=excluded.market_phase_explanation,
            fragmentation_index=excluded.fragmentation_index,
            fragmentation_plain=excluded.fragmentation_plain,
            top_tool=excluded.top_tool,
            top_tool_share_pct=excluded.top_tool_share_pct,
            insight_text=excluded.insight_text,
            computed_at=excluded.computed_at
        """,
        (
            category,
            ecosystem,
            tool_count,
            CATEGORY_DESCRIPTIONS.get(category, f"Tools in the {category} category."),
            phase,
            phase_explanation,
            frag_idx,
            frag_plain,
            top["display_name"],
            top_share_pct,
            insight,
        ),
    )


def flag_enterprise_repos(conn) -> None:
    cursor = conn.cursor()
    cursor.execute("UPDATE tool_repos SET is_enterprise_repo = 0")
    repos = cursor.execute("SELECT DISTINCT repo_full_name FROM tool_repos").fetchall()
    enterprise_count = 0
    for row in repos:
        repo_full_name = row["repo_full_name"]
        org = repo_full_name.split("/")[0].lower()
        if org in ENTERPRISE_ORGS:
            cursor.execute(
                "UPDATE tool_repos SET is_enterprise_repo = 1 WHERE repo_full_name = ?",
                (repo_full_name,),
            )
            enterprise_count += 1
    conn.commit()
    print(f"  -> Flagged {enterprise_count} enterprise repos")


def main() -> None:
    init_db()
    snapshot_date = datetime.now(timezone.utc).date().isoformat()

    with get_conn() as conn:
        flag_enterprise_repos(conn)

        tools = conn.execute("SELECT canonical_name FROM tools ORDER BY canonical_name").fetchall()
        for row in tools:
            recompute_today_snapshot(conn, row["canonical_name"], snapshot_date)
        conn.commit()

        categories = conn.execute(
            "SELECT DISTINCT category FROM tools ORDER BY category"
        ).fetchall()
        for row in categories:
            upsert_category(conn, row["category"], snapshot_date)
        conn.commit()

        print(f"Computed category scores for {len(categories)} categories.")
        print(f"Updated snapshots for {len(tools)} tools on {snapshot_date}.")


if __name__ == "__main__":
    main()
