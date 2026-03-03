from __future__ import annotations

from datetime import datetime, timezone
from statistics import median

import math

try:
    from scripts.db import get_conn, init_db
except ModuleNotFoundError:
    from db import get_conn, init_db


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
    return "In Transition", "The market is shifting. Watch the top 2-3 tools closely."


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
        f"{category} is in transition. {top_tool} currently leads at {top_pct:.0f}% but the landscape is shifting. "
        "Worth monitoring over the next 90 days."
    )


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

    conn.execute(
        """
        INSERT INTO tool_snapshots (
            canonical_name, snapshot_date, total_repos, active_repos,
            new_repos_90d, stars_median, emergence_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(canonical_name, snapshot_date) DO UPDATE SET
            total_repos=excluded.total_repos,
            active_repos=excluded.active_repos,
            new_repos_90d=excluded.new_repos_90d,
            stars_median=excluded.stars_median,
            emergence_score=excluded.emergence_score
        """,
        (canonical_name, snapshot_date, int(total), int(active), int(new_90), round(star_med, 2), emergence),
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
            f"Tools in the {category} category.",
            phase,
            phase_explanation,
            frag_idx,
            frag_plain,
            top["display_name"],
            top_share_pct,
            insight,
        ),
    )


def main() -> None:
    init_db()
    snapshot_date = datetime.now(timezone.utc).date().isoformat()

    with get_conn() as conn:
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
