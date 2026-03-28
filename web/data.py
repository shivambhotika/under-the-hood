from __future__ import annotations

import os
import shutil
import sqlite3
import time
from datetime import date, datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from statistics import median

try:
    from scripts.enterprise_orgs import ENTERPRISE_ORGS
    from scripts.db import init_db
except ModuleNotFoundError:
    from enterprise_orgs import ENTERPRISE_ORGS
    from db import init_db

def _db_candidates() -> list[Path]:
    here = Path(__file__).resolve()
    candidates: list[Path] = []

    env_path = os.getenv("UTH_DB_PATH")
    if env_path:
        candidates.append(Path(env_path))

    candidates.extend(
        [
            here.parent.parent / "data" / "uth.db",
            here.parents[2] / "data" / "uth.db" if len(here.parents) > 2 else here.parent.parent / "data" / "uth.db",
            Path.cwd() / "data" / "uth.db",
            Path("/var/task/user/data/uth.db"),
            Path("/var/task/data/uth.db"),
        ]
    )

    deduped: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        key = str(p)
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped


def _resolve_db_path() -> Path:
    candidates = _db_candidates()
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def _is_valid_db(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        tables = {
            str(r["name"])
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        conn.close()
        return "tools" in tables and "tool_snapshots" in tables
    except Exception:
        return False


def _prepare_runtime_db_path() -> Path:
    global _RUNTIME_DB_PATH, DB_PATH
    if _RUNTIME_DB_PATH is not None:
        return _RUNTIME_DB_PATH

    chosen: Path | None = None
    for p in _db_candidates():
        if _is_valid_db(p):
            chosen = p
            break

    if chosen is None:
        chosen = _resolve_db_path()

    # Serverless runtimes are safest reading sqlite from /tmp.
    if os.getenv("VERCEL") and chosen.exists():
        runtime_copy = Path("/tmp/uth.db")
        try:
            if (not runtime_copy.exists()) or runtime_copy.stat().st_size != chosen.stat().st_size:
                shutil.copy2(chosen, runtime_copy)
            _RUNTIME_DB_PATH = runtime_copy
            DB_PATH = _RUNTIME_DB_PATH
            return _RUNTIME_DB_PATH
        except Exception:
            pass

    _RUNTIME_DB_PATH = chosen
    DB_PATH = _RUNTIME_DB_PATH
    return _RUNTIME_DB_PATH

RADAR_MAX_REPOS = 400
RADAR_TARGET_GROWTH_RATIO = 0.20
RADAR_FALLBACK_GROWTH_RATIO = 0.15
RADAR_MIN_TOTAL_REPOS = 8
_SCHEMA_READY = False
_RUNTIME_DB_PATH: Path | None = None
DB_PATH: Path = _resolve_db_path()

NOTABLE_INSTITUTIONS = {
    "mit",
    "stanford",
    "uc berkeley",
    "berkeley",
    "carnegie mellon",
    "cmu",
    "oxford",
    "cambridge",
    "eth zurich",
    "epfl",
    "toronto",
    "deepmind",
    "google brain",
    "google research",
    "microsoft research",
    "meta ai",
    "fair",
    "openai",
    "anthropic",
    "nvidia research",
    "apple",
    "amazon science",
}


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


def cache_with_ttl(seconds: int = 3600) -> Callable:
    return ttl_cache(seconds)


def _conn() -> sqlite3.Connection:
    global _SCHEMA_READY
    db_path = _prepare_runtime_db_path()
    if not _SCHEMA_READY:
        if not db_path.exists():
            init_db()
            db_path = _prepare_runtime_db_path()
        _SCHEMA_READY = True
    if db_path.exists():
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _row_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def _decorate_repo_rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        full = str(item.get("repo_full_name") or "")
        if "/" in full:
            org, repo = full.split("/", 1)
        else:
            org, repo = full, ""
        item["org"] = org
        item["repo"] = repo
        out.append(item)
    return out


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
def get_latest_snapshot_date() -> str:
    """Returns the most recent snapshot date as a formatted string."""
    result = latest_snapshot_date()
    if not result:
        return "No data yet"
    try:
        dt = datetime.strptime(result, "%Y-%m-%d")
        return dt.strftime("%b %d, %Y")
    except Exception:
        return result


@ttl_cache(900)
def get_snapshot_freshness_status() -> str:
    snapshot = latest_snapshot_date()
    if not snapshot:
        return "stale"
    try:
        dt = datetime.strptime(snapshot, "%Y-%m-%d").date()
    except Exception:
        return "aging"
    age_days = (date.today() - dt).days
    if age_days < 8:
        return "fresh"
    if age_days <= 21:
        return "aging"
    return "stale"


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
                COALESCE(t.usage_model, 'dependency_first') AS usage_model,
                COALESCE(s.total_repos, 0) AS total_repos,
                COALESCE(s.active_repos, 0) AS active_repos,
                COALESCE(s.new_repos_90d, 0) AS new_repos_90d,
                COALESCE(s.emergence_score, 0) AS emergence_score,
                COALESCE(s.stars_median, 0) AS stars_median,
                COALESCE(s.enterprise_repo_count, 0) AS enterprise_repo_count,
                COALESCE(s.weekly_downloads, 0) AS weekly_downloads,
                s.downloads_source AS downloads_source,
                COALESCE(s.sample_size, 0) AS sample_size,
                COALESCE(s.confidence_tier, 'Low') AS confidence_tier,
                COALESCE(s.sample_tier, 'Low') AS sample_tier,
                COALESCE(s.trend_tier, 'Early') AS trend_tier,
                COALESCE(s.confidence_tooltip, '') AS confidence_tooltip,
                COALESCE(s.is_trend_reliable, 0) AS is_trend_reliable,
                COALESCE(s.repos_delta_7d, 0) AS repos_delta_7d,
                COALESCE(s.downloads_delta_7d, 0) AS downloads_delta_7d,
                s.last_ecosystem_activity AS last_ecosystem_activity,
                s.days_since_ecosystem_activity AS days_since_ecosystem_activity,
                COALESCE(s.active_builder_count, 0) AS active_builder_count
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
                   s.total_repos, s.new_repos_90d, s.emergence_score, s.active_repos,
                   COALESCE(s.sample_size, 0) AS sample_size,
                   COALESCE(s.confidence_tier, 'Low') AS confidence_tier,
                   COALESCE(s.sample_tier, 'Low') AS sample_tier,
                   COALESCE(s.trend_tier, 'Early') AS trend_tier,
                   COALESCE(s.confidence_tooltip, '') AS confidence_tooltip,
                   COALESCE(s.repos_delta_7d, 0) AS repos_delta_7d,
                   COALESCE(s.downloads_delta_7d, 0) AS downloads_delta_7d,
                   COALESCE(s.weekly_downloads, 0) AS weekly_downloads,
                   s.downloads_source,
                   COALESCE(s.is_trend_reliable, 0) AS is_trend_reliable
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
                t.description, t.github_repo, COALESCE(t.usage_model, 'dependency_first') AS usage_model,
                COALESCE(s.total_repos, 0) AS total_repos,
                COALESCE(s.active_repos, 0) AS active_repos,
                COALESCE(s.new_repos_90d, 0) AS new_repos_90d,
                COALESCE(s.emergence_score, 0) AS emergence_score,
                COALESCE(s.stars_median, 0) AS stars_median,
                COALESCE(s.enterprise_repo_count, 0) AS enterprise_repo_count,
                COALESCE(s.weekly_downloads, 0) AS weekly_downloads,
                s.downloads_source AS downloads_source,
                COALESCE(s.sample_size, 0) AS sample_size,
                COALESCE(s.confidence_tier, 'Low') AS confidence_tier,
                COALESCE(s.sample_tier, 'Low') AS sample_tier,
                COALESCE(s.trend_tier, 'Early') AS trend_tier,
                COALESCE(s.confidence_tooltip, '') AS confidence_tooltip,
                COALESCE(s.is_trend_reliable, 0) AS is_trend_reliable,
                COALESCE(s.repos_delta_7d, 0) AS repos_delta_7d,
                COALESCE(s.downloads_delta_7d, 0) AS downloads_delta_7d,
                s.last_ecosystem_activity AS last_ecosystem_activity,
                s.days_since_ecosystem_activity AS days_since_ecosystem_activity,
                COALESCE(s.active_builder_count, 0) AS active_builder_count
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

        enterprise_repos = conn.execute(
            """
            SELECT repo_full_name, stars
            FROM tool_repos
            WHERE canonical_name = ?
              AND stars > 0
              AND is_enterprise_repo = 1
            ORDER BY stars DESC
            LIMIT 8
            """,
            (canonical_name,),
        ).fetchall()

        community_repos = conn.execute(
            """
            SELECT repo_full_name, stars
            FROM tool_repos
            WHERE canonical_name = ?
              AND stars > 0
              AND COALESCE(is_enterprise_repo, 0) = 0
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

        health = conn.execute(
            "SELECT * FROM tool_health WHERE canonical_name = ?",
            (canonical_name,),
        ).fetchone()

    out = dict(tool)
    out["version_spread"] = _row_dicts(versions)
    out["enterprise_repos"] = _decorate_repo_rows(enterprise_repos)
    out["community_repos"] = _decorate_repo_rows(community_repos)
    out["top_repos"] = out["community_repos"]
    out["history"] = _row_dicts(history)
    out["health"] = dict(health) if health else {}
    return out


@ttl_cache(900)
def get_all_categories() -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM categories ORDER BY tool_count DESC, category ASC").fetchall()
    return _row_dicts(rows)


@ttl_cache(900)
def get_category_tools(category: str) -> list[dict[str, Any]]:
    return get_all_tools(category=category)


@cache_with_ttl(3600)
def get_category_share_bars() -> dict[str, list[tuple[str, int]]]:
    """
    Returns category -> top tool share tuples for mini concentration bars.
    """
    today = latest_snapshot_date()
    if not today:
        return {}

    result: dict[str, list[tuple[str, int]]] = {}
    with _conn() as conn:
        categories = conn.execute("SELECT DISTINCT category FROM tools ORDER BY category").fetchall()
        for row in categories:
            category = str(row["category"])
            tools = conn.execute(
                """
                SELECT t.display_name, COALESCE(s.total_repos, 0) AS repos
                FROM tools t
                LEFT JOIN tool_snapshots s
                  ON t.canonical_name = s.canonical_name
                 AND s.snapshot_date = ?
                WHERE t.category = ?
                ORDER BY repos DESC
                LIMIT 4
                """,
                (today, category),
            ).fetchall()
            total = sum(int(tool["repos"] or 0) for tool in tools) or 1
            result[category] = [
                (str(tool["display_name"]), round((int(tool["repos"] or 0) / total) * 100))
                for tool in tools
                if int(tool["repos"] or 0) > 0
            ]
    return result


@ttl_cache(3600)
def get_download_history(canonical_name: str) -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT snapshot_date, weekly_downloads, source
            FROM download_snapshots
            WHERE canonical_name = ?
            ORDER BY snapshot_date DESC
            LIMIT 12
            """,
            (canonical_name,),
        ).fetchall()
    return _row_dicts(rows)


@cache_with_ttl(3600)
def get_tool_health(canonical_name: str) -> dict[str, Any]:
    """Returns health data for a single tool. Returns {} if not found."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM tool_health WHERE canonical_name = ?",
            (canonical_name,),
        ).fetchone()
    return dict(row) if row else {}


@cache_with_ttl(1800)
def get_health_leaderboard(category: str | None = None, tier: str | None = None):
    """
    Returns all tools with health data, joined to snapshot data.
    Sorted by health_score DESC by default.
    Optionally filter by category or health_tier.
    """
    import pandas as pd

    conn = _conn()
    query = """
        SELECT
            t.canonical_name, t.display_name, t.ecosystem, t.category,
            t.description,
            h.health_score, h.health_tier, h.health_tier_reason,
            h.last_release_days, h.advisory_total, h.advisory_critical,
            h.transitive_dep_count, h.license, h.license_is_permissive,
            h.deps_dev_found, h.osv_found,
            COALESCE(s.total_repos, 0) as total_repos,
            COALESCE(s.emergence_score, 0) as emergence_score,
            COALESCE(s.confidence_tier, 'Low') as confidence_tier,
            COALESCE(s.enterprise_repo_count, 0) as enterprise_repo_count,
            COALESCE(s.repos_delta_7d, 0) as repos_delta_7d
        FROM tools t
        JOIN tool_health h ON t.canonical_name = h.canonical_name
        LEFT JOIN tool_snapshots s ON t.canonical_name = s.canonical_name
            AND s.snapshot_date = (SELECT MAX(snapshot_date) FROM tool_snapshots)
        WHERE h.health_tier != 'Unknown'
    """
    params = []
    if category:
        query += " AND t.category = ?"
        params.append(category)
    if tier:
        query += " AND h.health_tier = ?"
        params.append(tier)
    query += " ORDER BY h.health_score DESC, s.total_repos DESC"

    try:
        return pd.read_sql_query(query, conn, params=params)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()


@ttl_cache(3600)
def get_tool_contributors(canonical_name: str) -> list[dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT canonical_name, github_login, contributions, avatar_url, html_url,
                   name, company, bio, location, followers, public_repos,
                   twitter_username, fetched_at
            FROM tool_contributors
            WHERE canonical_name = ?
            ORDER BY contributions DESC, followers DESC
            LIMIT 8
            """,
            (canonical_name,),
        ).fetchall()
    return _row_dicts(rows)


@ttl_cache(3600)
def get_tool_top_contributors(canonical_name: str, limit: int = 3) -> list[dict[str, Any]]:
    """
    Returns top N contributors for a tool, sorted by contributions DESC.
    Used on Radar cards for team display.
    """
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT github_login, contributions, company, followers,
                   bio, html_url, name
            FROM tool_contributors
            WHERE canonical_name = ?
            ORDER BY contributions DESC
            LIMIT ?
            """,
            (canonical_name, limit),
        ).fetchall()
    return _row_dicts(rows)


def format_activity_signal(days_since: int | None) -> str:
    """Converts days integer to human-readable string."""
    if days_since is None:
        return "Unknown"
    if days_since <= 1:
        return "Today"
    if days_since <= 7:
        return f"{days_since} days ago"
    if days_since <= 30:
        weeks = days_since // 7
        return f"{weeks} week{'s' if weeks > 1 else ''} ago"
    if days_since <= 90:
        months = days_since // 30
        return f"{months} month{'s' if months > 1 else ''} ago"
    return f"{days_since} days ago"


def format_delta(delta: int | None) -> tuple[str, str]:
    """
    Returns (display_string, css_class) for week-over-week deltas.
    """
    if delta is None or int(delta) == 0:
        return "—", "delta-none"
    if int(delta) > 0:
        return f"+{int(delta):,}", "delta-positive"
    return f"{int(delta):,}", "delta-negative"


def is_notable_contributor(contributor: dict[str, Any]) -> bool:
    followers = int(contributor.get("followers") or 0)
    if followers >= 500:
        return True
    company = str(contributor.get("company") or "").lower().strip().lstrip("@")
    return any(inst in company for inst in NOTABLE_INSTITUTIONS)


def get_pre_commercial_signal(
    canonical_name: str, github_repo: str | None, contributors: list[dict[str, Any]] | None = None
) -> bool:
    _ = canonical_name
    if not github_repo:
        return False
    org = github_repo.split("/")[0].lower()
    if org in ENTERPRISE_ORGS:
        return False
    if contributors:
        top_login = str(contributors[0].get("github_login") or "").lower()
        if top_login and top_login == org:
            return True
    return True


def _query_radar_rows(conn: sqlite3.Connection, snapshot_date: str, growth_ratio: float) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            t.canonical_name,
            t.display_name,
            t.ecosystem,
            t.category,
            t.description,
            t.github_repo,
            COALESCE(s.total_repos, 0) AS total_repos,
            COALESCE(s.new_repos_90d, 0) AS new_repos_90d,
            COALESCE(s.active_repos, 0) AS active_repos,
            COALESCE(s.emergence_score, 0) AS emergence_score,
            COALESCE(s.enterprise_repo_count, 0) AS enterprise_repo_count,
            COALESCE(s.weekly_downloads, 0) AS weekly_downloads,
            s.downloads_source AS downloads_source,
            COALESCE(s.sample_size, 0) AS sample_size,
            COALESCE(s.confidence_tier, 'Low') AS confidence_tier,
            COALESCE(s.sample_tier, 'Low') AS sample_tier,
            COALESCE(s.trend_tier, 'Early') AS trend_tier,
            COALESCE(s.confidence_tooltip, '') AS confidence_tooltip,
            COALESCE(s.is_trend_reliable, 0) AS is_trend_reliable,
            COALESCE(s.repos_delta_7d, 0) AS repos_delta_7d,
            COALESCE(s.downloads_delta_7d, 0) AS downloads_delta_7d,
            s.last_ecosystem_activity AS last_ecosystem_activity,
            s.days_since_ecosystem_activity AS days_since_ecosystem_activity,
            COALESCE(s.active_builder_count, 0) AS active_builder_count
        FROM tools t
        JOIN tool_snapshots s ON s.canonical_name = t.canonical_name
        WHERE s.snapshot_date = ?
          AND s.total_repos >= ?
          AND s.total_repos <= ?
          AND (
            (1.0 * COALESCE(s.new_repos_90d, 0)) /
            CASE WHEN COALESCE(s.total_repos, 0) <= 0 THEN 1 ELSE s.total_repos END
          ) >= ?
        ORDER BY s.emergence_score DESC, s.total_repos DESC
        """,
        (snapshot_date, RADAR_MIN_TOTAL_REPOS, RADAR_MAX_REPOS, growth_ratio),
    ).fetchall()


@ttl_cache(3600)
def get_radar_snapshot() -> dict[str, Any]:
    snap = latest_snapshot_date()
    if not snap:
        return {
            "tools": [],
            "growth_threshold": RADAR_TARGET_GROWTH_RATIO,
            "target_growth_threshold": RADAR_TARGET_GROWTH_RATIO,
            "fallback_growth_threshold": RADAR_FALLBACK_GROWTH_RATIO,
        }
    with _conn() as conn:
        rows = _query_radar_rows(conn, snap, RADAR_TARGET_GROWTH_RATIO)
        used_growth = RADAR_TARGET_GROWTH_RATIO
        if not rows:
            rows = _query_radar_rows(conn, snap, RADAR_FALLBACK_GROWTH_RATIO)
            used_growth = RADAR_FALLBACK_GROWTH_RATIO

    result = _row_dicts(rows)
    for row in result:
        total = int(row.get("total_repos") or 0)
        new_90d = int(row.get("new_repos_90d") or 0)
        row["growth_ratio"] = (new_90d / max(1, total)) if total else 0.0
        row["pre_commercial_signal"] = get_pre_commercial_signal(
            row.get("canonical_name"), row.get("github_repo")
        )
    return {
        "tools": result,
        "growth_threshold": used_growth,
        "target_growth_threshold": RADAR_TARGET_GROWTH_RATIO,
        "fallback_growth_threshold": RADAR_FALLBACK_GROWTH_RATIO,
    }


@ttl_cache(1800)
def get_weeks_on_radar(
    canonical_name: str, max_repos: int = 400, min_growth_ratio: float = 0.20
) -> int:
    """
    Counts consecutive weekly snapshots where this tool met Radar criteria.
    """
    with _conn() as conn:
        snapshots = conn.execute(
            """
            SELECT snapshot_date, total_repos, new_repos_90d
            FROM tool_snapshots
            WHERE canonical_name = ?
            ORDER BY snapshot_date DESC
            LIMIT 12
            """,
            (canonical_name,),
        ).fetchall()
    if not snapshots:
        return 0

    weeks = 0
    for snap in snapshots:
        total = int(snap["total_repos"] or 0)
        new_90d = int(snap["new_repos_90d"] or 0)
        ratio = new_90d / max(1, total)
        if total <= max_repos and ratio >= min_growth_ratio and total >= RADAR_MIN_TOTAL_REPOS:
            weeks += 1
        else:
            break
    return weeks


@ttl_cache(1800)
def get_radar_tools() -> list[dict[str, Any]]:
    snapshot = get_radar_snapshot()
    tools = [dict(tool) for tool in snapshot["tools"]]
    if not tools:
        return []

    today = latest_snapshot_date()
    category_averages: dict[str, float] = {}
    if today:
        with _conn() as conn:
            rows = conn.execute(
                """
                SELECT t.category, AVG(s.emergence_score) AS avg_emergence
                FROM tool_snapshots s
                JOIN tools t ON s.canonical_name = t.canonical_name
                WHERE s.snapshot_date = ?
                GROUP BY t.category
                """,
                (today,),
            ).fetchall()
        for row in rows:
            category_averages[str(row["category"])] = float(row["avg_emergence"] or 1)

    min_growth_ratio = float(snapshot.get("growth_threshold") or RADAR_TARGET_GROWTH_RATIO)
    for tool in tools:
        cat_avg = category_averages.get(str(tool.get("category") or ""), 1.0)
        ratio = round(float(tool.get("emergence_score") or 0) / max(0.1, cat_avg), 1)
        tool["emergence_relative"] = ratio
        if ratio >= 3:
            tool["emergence_label"] = f"Growing {ratio:.0f}× faster than category average"
        elif ratio >= 1.5:
            tool["emergence_label"] = f"Growing {ratio:.1f}× faster than average"
        else:
            tool["emergence_label"] = "Near category average growth"
        tool["weeks_on_radar"] = get_weeks_on_radar(
            str(tool["canonical_name"]),
            max_repos=RADAR_MAX_REPOS,
            min_growth_ratio=min_growth_ratio,
        )
    return tools


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
        "In Transition": "Something is shifting here. The current leader may not hold.",
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
            f"{name} is in a breakout phase. Adoption is compounding quickly from a smaller base, which is exactly where category leaders are often formed."
        )
    elif emergence > 15:
        momentum = (
            f"{name} is consolidating real momentum. It is not just popular in conversation — it is getting installed in new production code."
        )
    elif emergence < 5 and total > 500:
        momentum = (
            f"{name} already behaves like infrastructure. Growth is slower because it is mature, not because it is fading out."
        )
    else:
        momentum = (
            f"{name} has a live, investable footprint but is still proving whether it can become a category default."
        )

    if activity_pct > 70:
        health = "Its install base is actively maintained, which lowers durability risk."
    elif activity_pct > 40:
        health = "A meaningful share of adopters are still shipping updates, so usage appears healthy."
    else:
        health = "Maintenance activity is weaker, so treat this as directional until another snapshot confirms momentum."
    return (
        f"{momentum} {name} is currently in {total:,} tracked repos with {new_90d:,} new adopters in the last 90 days "
        f"({adoption_pct:.0f}% of its base). {health}"
    )


def confidence_badge_copy(tier: str, sample_size: int, snapshot_count: int | None = None) -> str:
    s = int(sample_size or 0)
    if snapshot_count is None:
        if tier == "High":
            return f"Sample: based on {s} repos · Trend: 4+ snapshots"
        if tier == "Medium":
            return f"Sample: based on {s} repos — reasonable signal · Trend: building history"
        return f"Sample: only {s} repos — treat as directional · Trend: early"

    if snapshot_count >= 4:
        trend_note = f"{snapshot_count} weeks of history"
    elif snapshot_count >= 2:
        trend_note = f"{snapshot_count} snapshots — trend still forming"
    else:
        trend_note = "1 snapshot — no trend data yet"

    if tier == "High":
        return f"Sample: based on {s} repos · Trend: {trend_note}"
    if tier == "Medium":
        return f"Sample: based on {s} repos — reasonable signal · Trend: {trend_note}"
    return f"Sample: only {s} repos — treat as directional · Trend: {trend_note}"


def median_stars_for_tool(canonical_name: str) -> float:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT stars FROM tool_repos WHERE canonical_name = ? AND stars > 0",
            (canonical_name,),
        ).fetchall()
    stars = [int(r["stars"]) for r in rows]
    return float(median(stars)) if stars else 0.0


def generate_health_section(top, top_health, runner_up, runner_up_health):
    if not top_health:
        return "Dependency health data not yet collected. Run scripts/08_enrich_health.py."

    th = dict(top_health)
    top_name = top["display_name"]
    tier = th.get("health_tier", "Unknown")
    score = float(th.get("health_score") or 0)
    reason = th.get("health_tier_reason", "")
    release_days = th.get("last_release_days")
    advisories = int(th.get("advisory_total") or 0)

    if tier == "Healthy":
        base = f"{top_name} scores well on dependency health ({score:.0f}/100). "
    elif tier == "Monitoring Required":
        base = (
            f"{top_name} shows some health signals worth watching (score: {score:.0f}/100). "
            f"{reason}. "
        )
    elif tier in ("Declining Health", "Critical Concerns"):
        base = (
            f"{top_name} has notable dependency health concerns (score: {score:.0f}/100). "
            f"{reason}. This warrants deeper diligence before building on it. "
        )
    else:
        base = f"Health data for {top_name} is not yet available. "

    if release_days is not None:
        if release_days <= 30:
            base += f"Active release cadence — last version {release_days} days ago. "
        elif release_days <= 90:
            base += f"Reasonable release pace — last version {release_days} days ago. "
        elif release_days > 180:
            base += f"Release cadence has slowed — last version {release_days} days ago. "

    if advisories == 0:
        base += "No known vulnerabilities in tracked versions. "
    elif advisories <= 2:
        base += f"{advisories} advisory noted — review severity before adopting in production. "
    else:
        base += f"{advisories} advisories on record — security review recommended. "

    if runner_up and runner_up_health:
        rh = dict(runner_up_health)
        ru_name = runner_up["display_name"]
        ru_score = float(rh.get("health_score") or 0)
        if abs(score - ru_score) < 10:
            base += f"Health parity with {ru_name} ({ru_score:.0f}/100) — comparable risk profile. "
        elif score > ru_score:
            base += (
                f"{ru_name} scores lower at {ru_score:.0f}/100 — "
                f"{top_name} is healthier from a dependency perspective. "
            )
        else:
            base += f"Notably, {ru_name} scores higher at {ru_score:.0f}/100 despite lower adoption. "

    return base.strip()


def generate_comparison_verdict(
    tool_a: dict[str, Any],
    tool_b: dict[str, Any],
    health_a: dict[str, Any],
    health_b: dict[str, Any],
) -> str:
    """Generates a 3-4 sentence plain-English comparison verdict."""
    name_a = tool_a["display_name"]
    name_b = tool_b["display_name"]
    repos_a = int(tool_a.get("total_repos") or 0)
    repos_b = int(tool_b.get("total_repos") or 0)
    growth_a = int(tool_a.get("new_repos_90d") or 0)
    growth_b = int(tool_b.get("new_repos_90d") or 0)
    downloads_a = int(tool_a.get("weekly_downloads") or 0)
    downloads_b = int(tool_b.get("weekly_downloads") or 0)
    enterprise_a = int(tool_a.get("enterprise_repo_count") or 0)
    enterprise_b = int(tool_b.get("enterprise_repo_count") or 0)
    health_score_a = float(health_a.get("health_score") or 0)
    health_score_b = float(health_b.get("health_score") or 0)

    if growth_a > growth_b:
        momentum = (
            f"{name_a} is winning the greenfield race, with {growth_a:,} new adopters "
            f"in the last 90 days versus {growth_b:,} for {name_b}."
        )
    elif growth_b > growth_a:
        momentum = (
            f"{name_b} is winning the greenfield race, with {growth_b:,} new adopters "
            f"in the last 90 days versus {growth_a:,} for {name_a}."
        )
    else:
        momentum = (
            "Momentum is close: both tools added roughly the same number of "
            "new adopters in the last 90 days."
        )

    if health_score_a > health_score_b:
        health_line = (
            f"{name_a} also looks healthier as a production dependency "
            f"({health_score_a:.0f} vs {health_score_b:.0f}), which lowers maintenance risk."
        )
    elif health_score_b > health_score_a:
        health_line = (
            f"{name_b} looks healthier as a production dependency "
            f"({health_score_b:.0f} vs {health_score_a:.0f}), which matters if your team wants lower operational drag."
        )
    else:
        health_line = (
            "Dependency health is effectively tied, so adoption and team fit matter more than maintenance risk here."
        )

    if repos_a > repos_b or downloads_a > downloads_b or enterprise_a > enterprise_b:
        installed_base_winner = (
            name_a
            if (repos_a + downloads_a + enterprise_a) > (repos_b + downloads_b + enterprise_b)
            else name_b
        )
        installed_base_other = name_b if installed_base_winner == name_a else name_a
        base_line = (
            f"{installed_base_winner} still has the larger installed base and validation footprint, "
            f"so {installed_base_other} is the challenger rather than the incumbent."
        )
    else:
        base_line = (
            "Neither tool has clearly locked in the installed base yet, so this category still has room to move."
        )

    if growth_a > growth_b and health_score_a >= health_score_b:
        recommendation = f"For a new build, {name_a} is the stronger default choice right now."
    elif growth_b > growth_a and health_score_b >= health_score_a:
        recommendation = f"For a new build, {name_b} is the stronger default choice right now."
    else:
        recommendation = (
            "The practical decision depends on whether you value installed-base safety or forward momentum more."
        )

    verdict = " ".join([momentum, health_line, base_line, recommendation])

    a_delta = int(tool_a.get("repos_delta_7d") or 0)
    b_delta = int(tool_b.get("repos_delta_7d") or 0)
    if a_delta > 0 and b_delta <= 0:
        verdict += (
            f" At current trajectory, {name_a} is gaining ground while {name_b} loses it — migration pressure is building."
        )
    elif b_delta > 0 and a_delta <= 0:
        verdict += (
            f" At current trajectory, {name_b} is gaining ground while {name_a} loses it — migration pressure is building."
        )
    elif a_delta > b_delta * 2 and a_delta > 0:
        verdict += f" {name_a} is growing significantly faster week-over-week — the gap is likely to widen."
    elif b_delta > a_delta * 2 and b_delta > 0:
        verdict += f" {name_b} is growing significantly faster week-over-week — the gap is likely to widen."

    return verdict


@ttl_cache(1800)
def generate_category_memo(category: str) -> dict[str, Any] | None:
    """
    Generates a category intelligence brief from adoption data.
    Returns a dict with all sections. No LLM, deterministic templates.
    """
    snapshot_date = latest_snapshot_date()
    if not snapshot_date:
        return None

    with _conn() as conn:
        cat_row = conn.execute(
            "SELECT * FROM categories WHERE category = ?",
            (category,),
        ).fetchone()
        if not cat_row:
            return None
        cat = dict(cat_row)

        tools_rows = conn.execute(
            """
            SELECT t.canonical_name, t.display_name, t.ecosystem,
                   t.description, t.github_repo,
                   COALESCE(s.total_repos, 0) AS total_repos,
                   COALESCE(s.new_repos_90d, 0) AS new_repos_90d,
                   COALESCE(s.active_repos, 0) AS active_repos,
                   COALESCE(s.emergence_score, 0) AS emergence_score,
                   COALESCE(s.weekly_downloads, 0) AS weekly_downloads,
                   COALESCE(s.enterprise_repo_count, 0) AS enterprise_repo_count,
                   COALESCE(s.confidence_tier, 'Low') AS confidence_tier,
                   COALESCE(s.active_builder_count, 0) AS active_builder_count,
                   COALESCE(s.days_since_ecosystem_activity, 999) AS days_since_activity
            FROM tools t
            LEFT JOIN tool_snapshots s ON t.canonical_name = s.canonical_name
                AND s.snapshot_date = ?
            WHERE t.category = ?
            ORDER BY total_repos DESC
            """,
            (snapshot_date, category),
        ).fetchall()
        tools = _row_dicts(tools_rows)
        if not tools:
            return None

        total_category_repos = sum(int(t["total_repos"] or 0) for t in tools)
        for tool in tools:
            tool["share_pct"] = round((int(tool["total_repos"] or 0) / max(1, total_category_repos)) * 100, 1)

        top = tools[0] if len(tools) > 0 else None
        runner_up = tools[1] if len(tools) > 1 else None
        dark_horse = max(tools, key=lambda x: float(x.get("emergence_score") or 0)) if tools else None
        if dark_horse and top and dark_horse["canonical_name"] == top["canonical_name"]:
            alternatives = [t for t in tools if t["canonical_name"] != top["canonical_name"]]
            dark_horse = max(alternatives, key=lambda x: float(x.get("emergence_score") or 0), default=None)

        phase = cat.get("market_phase", "In Transition")
        frag = float(cat.get("fragmentation_index") or 0.5)

        def get_top_contributors_for_memo(canonical: str, n: int = 2) -> list[dict[str, Any]]:
            rows = conn.execute(
                """
                SELECT github_login, contributions, company, followers, name
                FROM tool_contributors
                WHERE canonical_name = ?
                ORDER BY contributions DESC
                LIMIT ?
                """,
                (canonical, n),
            ).fetchall()
            return _row_dicts(rows)

        top_contributors = get_top_contributors_for_memo(top["canonical_name"]) if top else []
        runner_up_contributors = (
            get_top_contributors_for_memo(runner_up["canonical_name"]) if runner_up else []
        )

        enterprise_orgs: list[str] = []
        if top:
            org_rows = conn.execute(
                """
                SELECT DISTINCT SUBSTR(repo_full_name, 1, INSTR(repo_full_name, '/') - 1) AS org
                FROM tool_repos
                WHERE canonical_name = ? AND is_enterprise_repo = 1
                LIMIT 5
                """,
                (top["canonical_name"],),
            ).fetchall()
            enterprise_orgs = [r["org"] for r in org_rows if r["org"]]

        top_health = (
            conn.execute(
                "SELECT * FROM tool_health WHERE canonical_name = ?",
                (top["canonical_name"],),
            ).fetchone()
            if top
            else None
        )
        runner_up_health = (
            conn.execute(
                "SELECT * FROM tool_health WHERE canonical_name = ?",
                (runner_up["canonical_name"],),
            ).fetchone()
            if runner_up
            else None
        )

    def generate_verdict(current_phase: str, top_tool: dict[str, Any] | None) -> str:
        name = top_tool["display_name"] if top_tool else "No clear leader"
        share = float(top_tool["share_pct"]) if top_tool else 0.0
        if current_phase == "Mature":
            return f"{name} has won this category with {share:.0f}% of tracked repos. The market has decided."
        if current_phase == "Consolidating":
            return f"{name} is pulling ahead at {share:.0f}%. This category has months, not years, before it settles."
        if current_phase == "Early / Competing":
            return f"No winner yet. {name} leads with only {share:.0f}% — this is an active competition."
        if current_phase == "Fragmenting":
            return "Fragmented with no momentum behind any tool. Either unsolved or moving to non-OSS solutions."
        return f"{name} currently leads at {share:.0f}%, but the landscape is shifting. Worth monitoring closely."

    def generate_data_section(
        top_tool: dict[str, Any] | None,
        second_tool: dict[str, Any] | None,
        frag_index: float,
        category_repos: int,
    ) -> str:
        if not top_tool:
            return "Insufficient data to generate analysis."

        top_name = top_tool["display_name"]
        top_share = float(top_tool["share_pct"])
        top_repos = int(top_tool["total_repos"])
        top_growth = round((int(top_tool["new_repos_90d"]) / max(1, top_repos)) * 100)

        frag_label = (
            "highly fragmented — no tool has meaningful concentration"
            if frag_index > 0.65
            else "moderately fragmented — a leader is emerging but not dominant"
            if frag_index > 0.45
            else "concentrating — one or two tools pulling clearly ahead"
            if frag_index > 0.25
            else "concentrated — one tool has structural dominance"
        )

        base = (
            f"Across {category_repos:,} tracked repositories in this category, the adoption picture is {frag_label}. "
            f"{top_name} leads with {top_repos:,} repos ({top_share:.0f}% share), with {top_growth}% of its base added in the last 90 days. "
        )

        if second_tool:
            second_name = second_tool["display_name"]
            second_share = float(second_tool["share_pct"])
            gap = top_share - second_share
            if gap < 10:
                base += (
                    f"{second_name} is close behind at {second_share:.0f}% — a gap of only {gap:.0f} points. "
                    "The outcome here is genuinely uncertain."
                )
            elif gap < 25:
                base += f"{second_name} holds {second_share:.0f}%, a {gap:.0f}-point gap that is widening."
            else:
                base += (
                    f"The runner-up, {second_name}, holds {second_share:.0f}% — a gap large enough that catching up would require a significant shift."
                )
        return base

    def generate_team_section(
        top_tool: dict[str, Any] | None,
        top_builder_rows: list[dict[str, Any]],
    ) -> str:
        if not top_tool:
            return "No contributor data available."

        top_name = top_tool["display_name"]
        builder_count = int(top_tool["active_builder_count"] or 0)
        days_active = int(top_tool["days_since_activity"] or 999)

        if days_active <= 7:
            activity_note = "with commits as recently as this week"
        elif days_active <= 30:
            activity_note = f"last commit {days_active} days ago"
        elif days_active <= 90:
            activity_note = f"last activity {days_active} days ago — moderate pace"
        else:
            activity_note = f"last activity {days_active} days ago — slowing"

        if builder_count == 0:
            team_note = f"Contributor data not yet collected for {top_name}."
        elif builder_count == 1:
            team_note = (
                f"{top_name} is currently maintained by a single contributor ({activity_note}). "
                "High bus factor risk — sole maintainer dependency is a due diligence flag."
            )
        elif builder_count <= 4:
            team_note = (
                f"{top_name} is built by a small team of {builder_count} contributors ({activity_note}). "
                "Small teams with this trajectory often represent the pre-company stage."
            )
        else:
            team_note = (
                f"{top_name} has {builder_count} active contributors ({activity_note}), "
                "suggesting a healthy community or established team behind the project."
            )

        notable = next((c for c in top_builder_rows if int(c.get("followers") or 0) >= 500), None)
        if notable:
            name_str = notable.get("name") or notable["github_login"]
            company_str = f" ({notable['company']})" if notable.get("company") else ""
            followers = int(notable.get("followers") or 0)
            team_note += (
                f" The most prominent contributor is {name_str}{company_str}, "
                f"with {followers:,} GitHub followers — indicating strong community reputation."
            )
        return team_note

    def generate_enterprise_section(top_tool: dict[str, Any] | None, orgs: list[str]) -> str:
        if not top_tool:
            return ""

        top_name = top_tool["display_name"]
        ent_count = int(top_tool["enterprise_repo_count"] or 0)
        if ent_count == 0:
            return (
                f"No enterprise adoption detected for {top_name} in tracked repositories. "
                "This is typical for tools still in the developer/OSS phase — enterprise adoption usually follows OSS momentum by 12–18 months. "
                "Absence of enterprise signal is not a negative at this stage; it indicates the tool is earlier in the adoption curve."
            )
        if ent_count <= 3:
            orgs_str = ", ".join(orgs[:3]) if orgs else f"{ent_count} orgs"
            return (
                f"{top_name} has been adopted by {ent_count} enterprise-grade organization{'s' if ent_count > 1 else ''} ({orgs_str}). "
                "Early enterprise adoption is a quality signal — these organizations apply rigorous technical evaluation before adding dependencies."
            )

        orgs_str = ", ".join(orgs[:3]) if orgs else ""
        and_more = f" and {ent_count - 3} more" if ent_count > 3 else ""
        return (
            f"{top_name} has meaningful enterprise adoption across {ent_count} tracked organizations ({orgs_str}{and_more}). "
            "This level of enterprise presence suggests the tool has crossed from OSS curiosity to production-grade infrastructure."
        )

    def generate_watch_section(
        current_phase: str,
        top_tool: dict[str, Any] | None,
        second_tool: dict[str, Any] | None,
        rising_tool: dict[str, Any] | None,
    ) -> list[str]:
        items: list[str] = []

        if second_tool and float(second_tool.get("emergence_score") or 0) > 15:
            growth = round((int(second_tool["new_repos_90d"]) / max(1, int(second_tool["total_repos"]))) * 100)
            items.append(
                f"**{second_tool['display_name']}** is the tool to watch most closely. Growing at {growth}% in 90 days and gaining ground. If this trajectory holds for another 2 quarters, the category share picture changes materially."
            )

        if rising_tool and float(rising_tool.get("emergence_score") or 0) > 20:
            dh_repos = int(rising_tool["total_repos"])
            dh_growth = round((int(rising_tool["new_repos_90d"]) / max(1, dh_repos)) * 100)
            items.append(
                f"**{rising_tool['display_name']}** is the dark horse — only {dh_repos:,} repos using it but {dh_growth}% of those were added in the last 90 days. Small base, fast growth. Check back in 60 days."
            )

        if current_phase == "Mature" and top_tool:
            items.append(
                f"In a mature category, the question shifts from who wins to who disrupts. Watch for a new entrant targeting {top_tool['display_name']}'s weakest points, usually performance or cold-start time."
            )

        if not items:
            items.append("No strong directional signal on the competitive dynamics yet. Revisit when more weekly snapshots have accumulated.")
        return items

    return {
        "category": category,
        "phase": phase,
        "generated_at": datetime.now().strftime("%B %d, %Y"),
        "tool_count": len(tools),
        "total_repos": total_category_repos,
        "top_tool": top,
        "runner_up": runner_up,
        "dark_horse": dark_horse,
        "enterprise_orgs": enterprise_orgs,
        "verdict": generate_verdict(phase, top),
        "data_section": generate_data_section(top, runner_up, frag, total_category_repos),
        "team_section": generate_team_section(top, top_contributors),
        "enterprise_section": generate_enterprise_section(top, enterprise_orgs),
        "health_section": generate_health_section(top, top_health, runner_up, runner_up_health),
        "watch_items": generate_watch_section(phase, top, runner_up, dark_horse),
        "all_tools": tools,
        "top_contributors": top_contributors,
        "runner_up_contributors": runner_up_contributors,
        "snapshot_date": snapshot_date,
        "generated_iso_date": date.today().isoformat(),
    }


@cache_with_ttl(3600)
def get_org_tools(org_name: str) -> list[dict[str, Any]]:
    """Returns all tools used by repos in this org."""
    today = latest_snapshot_date()
    if not today:
        return []
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT
                   t.display_name, t.canonical_name, t.category,
                   t.ecosystem, t.description,
                   tr.repo_full_name,
                   COALESCE(s.total_repos, 0) AS total_repos,
                   COALESCE(s.emergence_score, 0) AS emergence_score
            FROM tool_repos tr
            JOIN tools t ON tr.canonical_name = t.canonical_name
            LEFT JOIN tool_snapshots s
              ON t.canonical_name = s.canonical_name
             AND s.snapshot_date = ?
            WHERE LOWER(SUBSTR(tr.repo_full_name, 1, INSTR(tr.repo_full_name, '/') - 1)) = LOWER(?)
            ORDER BY total_repos DESC, t.display_name ASC
            """,
            (today, org_name),
        ).fetchall()
    return _row_dicts(rows)


def get_ops_data() -> dict[str, Any]:
    """Operational health data. Intentionally uncached."""
    with _conn() as conn:
        latest_snapshot = conn.execute(
            "SELECT MAX(snapshot_date) AS d FROM tool_snapshots"
        ).fetchone()["d"]
        snapshot_summary_row = conn.execute(
            """
            SELECT
                COUNT(*) AS tool_count,
                MAX(snapshot_date) AS latest_date,
                COALESCE(SUM(total_repos), 0) AS total_repos,
                SUM(CASE WHEN confidence_tier = 'High' THEN 1 ELSE 0 END) AS high_conf,
                SUM(CASE WHEN confidence_tier = 'Medium' THEN 1 ELSE 0 END) AS med_conf,
                SUM(CASE WHEN confidence_tier = 'Low' THEN 1 ELSE 0 END) AS low_conf,
                SUM(CASE WHEN weekly_downloads > 0 THEN 1 ELSE 0 END) AS with_downloads,
                SUM(CASE WHEN repos_delta_7d != 0 THEN 1 ELSE 0 END) AS with_deltas
            FROM tool_snapshots
            WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM tool_snapshots)
            """
        ).fetchone()
        snapshot_summary = dict(snapshot_summary_row) if snapshot_summary_row else {}

        table_counts: dict[str, Any] = {}
        for table in [
            "tools",
            "tool_repos",
            "tool_snapshots",
            "tool_contributors",
            "download_snapshots",
            "categories",
            "api_cache",
            "pipeline_runs",
        ]:
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                table_counts[table] = int(cnt or 0)
            except Exception:
                table_counts[table] = "table missing"

        try:
            recent_runs_rows = conn.execute(
                """
                SELECT run_date, run_type, status, duration_seconds,
                       tools_processed, validation_passed, notes, completed_at
                FROM pipeline_runs
                ORDER BY id DESC
                LIMIT 5
                """
            ).fetchall()
            recent_runs = _row_dicts(recent_runs_rows)
        except Exception:
            recent_runs = []

        zero_repos_rows = conn.execute(
            """
            SELECT t.display_name, t.ecosystem, t.category
            FROM tool_snapshots s
            JOIN tools t ON s.canonical_name = t.canonical_name
            WHERE s.snapshot_date = (SELECT MAX(snapshot_date) FROM tool_snapshots)
            AND s.total_repos = 0
            ORDER BY t.display_name
            """
        ).fetchall()

        zero_download_rows = conn.execute(
            """
            SELECT t.display_name, t.ecosystem, t.npm_package, t.pypi_package
            FROM tool_snapshots s
            JOIN tools t ON s.canonical_name = t.canonical_name
            WHERE s.snapshot_date = (SELECT MAX(snapshot_date) FROM tool_snapshots)
              AND s.weekly_downloads = 0
              AND COALESCE(t.usage_model, 'dependency_first') != 'standalone_first'
            ORDER BY s.total_repos DESC
            LIMIT 15
            """
        ).fetchall()

    freshness_days = None
    if latest_snapshot:
        try:
            freshness_days = (date.today() - datetime.fromisoformat(latest_snapshot).date()).days
        except Exception:
            freshness_days = None

    return {
        "snapshot_summary": snapshot_summary,
        "table_counts": table_counts,
        "recent_runs": recent_runs,
        "zero_repos_tools": _row_dicts(zero_repos_rows),
        "zero_download_tools": _row_dicts(zero_download_rows),
        "generated_at": datetime.now().isoformat(),
        "latest_snapshot": latest_snapshot,
        "freshness_days": freshness_days,
    }
