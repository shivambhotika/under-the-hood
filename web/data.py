from __future__ import annotations

import sqlite3
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable

import numpy as np

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "uth.db"


def ttl_cache(seconds: int = 3600) -> Callable:
    def decorator(func: Callable) -> Callable:
        cache: dict[Any, tuple[float, Any]] = {}

        @wraps(func)
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.time()
            if key in cache:
                ts, value = cache[key]
                if now - ts < seconds:
                    return value
            value = func(*args, **kwargs)
            cache[key] = (now, value)
            return value

        return wrapper

    return decorator


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _row_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


@ttl_cache(60)
def db_has_data() -> bool:
    try:
        with _conn() as conn:
            tools = conn.execute("SELECT COUNT(*) AS c FROM tools").fetchone()["c"]
            snaps = conn.execute("SELECT COUNT(*) AS c FROM tool_snapshots").fetchone()["c"]
        return tools > 0 and snaps > 0
    except Exception:
        return False


@ttl_cache(900)
def latest_snapshot_date() -> str | None:
    with _conn() as conn:
        row = conn.execute("SELECT MAX(snapshot_date) AS d FROM tool_snapshots").fetchone()
    return row["d"] if row and row["d"] else None


@ttl_cache(900)
def get_summary_stats() -> dict[str, Any]:
    snap = latest_snapshot_date()
    if not snap:
        return {"total_repos": 0, "total_tools": 0, "total_categories": 0, "biggest_mover": None}

    with _conn() as conn:
        total_repos = conn.execute(
            "SELECT COALESCE(SUM(total_repos), 0) AS s FROM tool_snapshots WHERE snapshot_date = ?",
            (snap,),
        ).fetchone()["s"]
        total_tools = conn.execute("SELECT COUNT(*) AS c FROM tools").fetchone()["c"]
        total_categories = conn.execute("SELECT COUNT(DISTINCT category) AS c FROM tools").fetchone()["c"]
        biggest_mover = conn.execute(
            """
            SELECT t.canonical_name, t.display_name, s.total_repos, s.emergence_score
            FROM tool_snapshots s
            JOIN tools t ON t.canonical_name = s.canonical_name
            WHERE s.snapshot_date = ?
            ORDER BY s.emergence_score DESC
            LIMIT 1
            """,
            (snap,),
        ).fetchone()

    return {
        "snapshot_date": snap,
        "total_repos": int(total_repos or 0),
        "total_tools": int(total_tools or 0),
        "total_categories": int(total_categories or 0),
        "biggest_mover": dict(biggest_mover) if biggest_mover else None,
    }


@ttl_cache(900)
def get_all_tools(ecosystem: str | None = None, category: str | None = None) -> list[dict[str, Any]]:
    snap = latest_snapshot_date()
    with _conn() as conn:
        query = """
            SELECT
                t.canonical_name, t.display_name, t.ecosystem, t.category, t.description, t.github_repo,
                COALESCE(s.total_repos, 0) AS total_repos,
                COALESCE(s.active_repos, 0) AS active_repos,
                COALESCE(s.new_repos_90d, 0) AS new_repos_90d,
                COALESCE(s.emergence_score, 0) AS emergence_score,
                COALESCE(s.stars_median, 0) AS stars_median
            FROM tools t
            LEFT JOIN tool_snapshots s
              ON s.canonical_name = t.canonical_name
             AND s.snapshot_date = ?
            WHERE 1 = 1
        """
        params: list[Any] = [snap]
        if ecosystem:
            query += " AND t.ecosystem = ?"
            params.append(ecosystem)
        if category:
            query += " AND t.category = ?"
            params.append(category)
        query += " ORDER BY total_repos DESC, t.display_name ASC"
        rows = conn.execute(query, params).fetchall()
    return _row_dicts(rows)


@ttl_cache(900)
def get_top_movers(n: int = 6) -> list[dict[str, Any]]:
    snap = latest_snapshot_date()
    if not snap:
        return []
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT t.canonical_name, t.display_name, t.ecosystem, t.category, t.description,
                   s.total_repos, s.new_repos_90d, s.emergence_score, s.active_repos
            FROM tools t
            JOIN tool_snapshots s ON s.canonical_name = t.canonical_name
            WHERE s.snapshot_date = ? AND s.total_repos > 10
            ORDER BY s.emergence_score DESC
            LIMIT ?
            """,
            (snap, n),
        ).fetchall()
    return _row_dicts(rows)


@ttl_cache(900)
def get_tool_detail(canonical_name: str) -> dict[str, Any] | None:
    snap = latest_snapshot_date()
    if not snap:
        return None

    with _conn() as conn:
        tool = conn.execute(
            """
            SELECT
                t.canonical_name, t.display_name, t.ecosystem, t.category,
                t.description, t.github_repo,
                COALESCE(s.total_repos, 0) AS total_repos,
                COALESCE(s.active_repos, 0) AS active_repos,
                COALESCE(s.new_repos_90d, 0) AS new_repos_90d,
                COALESCE(s.emergence_score, 0) AS emergence_score,
                COALESCE(s.stars_median, 0) AS stars_median
            FROM tools t
            LEFT JOIN tool_snapshots s
              ON s.canonical_name = t.canonical_name
             AND s.snapshot_date = ?
            WHERE t.canonical_name = ?
            """,
            (snap, canonical_name),
        ).fetchone()
        if not tool:
            return None

        versions = conn.execute(
            """
            SELECT version_normalized, COUNT(*) AS cnt
            FROM tool_repos
            WHERE canonical_name = ?
              AND version_normalized IS NOT NULL
              AND version_normalized != ''
              AND COALESCE(stars, 0) != -1
            GROUP BY version_normalized
            ORDER BY cnt DESC
            LIMIT 6
            """,
            (canonical_name,),
        ).fetchall()

        top_repos = conn.execute(
            """
            SELECT repo_full_name, stars
            FROM tool_repos
            WHERE canonical_name = ? AND stars > 0
            ORDER BY stars DESC
            LIMIT 8
            """,
            (canonical_name,),
        ).fetchall()

        history = conn.execute(
            """
            SELECT snapshot_date, total_repos, emergence_score
            FROM tool_snapshots
            WHERE canonical_name = ?
            ORDER BY snapshot_date ASC
            """,
            (canonical_name,),
        ).fetchall()

    out = dict(tool)
    out["version_spread"] = _row_dicts(versions)
    out["top_repos"] = _row_dicts(top_repos)
    out["history"] = _row_dicts(history)
    return out


@ttl_cache(900)
def get_all_categories() -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM categories ORDER BY tool_count DESC, category ASC").fetchall()
    return _row_dicts(rows)


@ttl_cache(900)
def get_category_tools(category: str) -> list[dict[str, Any]]:
    return get_all_tools(category=category)


def signal_label(emergence_score: float, total_repos: int) -> tuple[str, str, str]:
    if total_repos > 15000:
        return "Dominant", "#A855F7", "Used by almost everyone in this category"
    if emergence_score > 40:
        return "Breakout", "#22C55E", "Growing extremely fast from a small base"
    if emergence_score > 20:
        return "Rising", "#22C55E", "Growing faster than average"
    if emergence_score < 5 and total_repos > 1000:
        return "Fading", "#EF4444", "Still widely used, but losing ground"
    if emergence_score < 3:
        return "Stable", "#F59E0B", "Established tool, not growing or shrinking much"
    return "Active", "#F59E0B", "Healthy and in use"


def phase_explainer(phase: str) -> str:
    return {
        "Mature": "Like Microsoft Word in word processors: one tool won and most people use it.",
        "Consolidating": "Like smartphones before iPhone vs Android settled: a winner is becoming clear.",
        "Early / Competing": "Like early social media: many players, no one has won yet.",
        "Fragmenting": "Lots of tools exist but developers cannot agree on any of them.",
        "In Transition": "Something is changing. Yesterday's winner might not be tomorrow's.",
    }.get(phase, "")


def generate_tool_insight(tool_data: dict[str, Any]) -> str:
    name = tool_data["display_name"]
    total = int(tool_data["total_repos"])
    new_90d = int(tool_data["new_repos_90d"])
    active = int(tool_data["active_repos"])
    emergence = float(tool_data["emergence_score"])

    adoption_pct = (new_90d / max(1, total)) * 100
    activity_pct = (active / max(1, total)) * 100

    if emergence > 40:
        momentum = (
            f"{name} is in breakout growth: {new_90d:,} new projects adopted it in the last 90 days, "
            f"which is {adoption_pct:.0f}% of its current base (share of users that are recent adopters)."
        )
    elif emergence > 15:
        momentum = f"{name} is growing steadily, with {new_90d:,} new projects adopting it in the last 90 days (recent adoption momentum)."
    elif emergence < 5 and total > 500:
        momentum = (
            f"{name} is widely used ({total:,} repos) but not gaining new adopters quickly. "
            "It looks like established infrastructure rather than a fast-growth tool."
        )
    else:
        momentum = f"{name} has a stable user base of {total:,} repos (projects currently using it)."

    if activity_pct > 70:
        health = "Its user base is highly active: most projects using it were updated in the last 30 days (maintenance activity signal)."
    elif activity_pct > 40:
        health = "Most projects using it are still actively maintained (updated within the last 30 days)."
    else:
        health = (
            f"Only {activity_pct:.0f}% of using repos were updated in the last 30 days (maintenance activity signal). "
            "That can mean stable long-lived projects, or reduced engagement."
        )
    return f"{momentum} {health}"


def median_stars_for_tool(canonical_name: str) -> float:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT stars FROM tool_repos WHERE canonical_name = ? AND stars > 0",
            (canonical_name,),
        ).fetchall()
    stars = [int(r["stars"]) for r in rows]
    return float(np.median(stars)) if stars else 0.0
