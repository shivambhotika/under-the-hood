from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent.parent
DB_PATH = ROOT_DIR / "data" / "uth.db"

load_dotenv(ROOT_DIR / ".env")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()

_SCHEMA_SQL = """
-- The canonical list of tools we track
CREATE TABLE IF NOT EXISTS tools (
    tool_id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    ecosystem TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    github_repo TEXT,
    usage_model TEXT DEFAULT 'dependency_first',
    npm_package TEXT,
    pypi_package TEXT,
    website_domain TEXT,
    is_official INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Aliases so "react-query" and "@tanstack/react-query" map to same tool
CREATE TABLE IF NOT EXISTS tool_aliases (
    alias TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    FOREIGN KEY (canonical_name) REFERENCES tools(canonical_name)
);

-- Daily snapshots: one row per tool per day
-- This is how we build trend lines over time
CREATE TABLE IF NOT EXISTS tool_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    total_repos INTEGER DEFAULT 0,
    active_repos INTEGER DEFAULT 0,
    new_repos_90d INTEGER DEFAULT 0,
    stars_median REAL DEFAULT 0,
    emergence_score REAL DEFAULT 0,
    enterprise_repo_count INTEGER DEFAULT 0,
    weekly_downloads INTEGER DEFAULT 0,
    downloads_source TEXT,
    sample_size INTEGER DEFAULT 0,
    confidence_tier TEXT DEFAULT 'Low',
    sample_tier TEXT DEFAULT 'Low',
    trend_tier TEXT DEFAULT 'Early',
    confidence_tooltip TEXT,
    is_trend_reliable INTEGER DEFAULT 0,
    repos_delta_7d INTEGER DEFAULT 0,
    downloads_delta_7d INTEGER DEFAULT 0,
    last_ecosystem_activity TEXT,
    days_since_ecosystem_activity INTEGER,
    active_builder_count INTEGER DEFAULT 0,
    UNIQUE(canonical_name, snapshot_date),
    FOREIGN KEY (canonical_name) REFERENCES tools(canonical_name)
);

-- Individual repos found containing a tool
CREATE TABLE IF NOT EXISTS tool_repos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    repo_full_name TEXT NOT NULL,
    stars INTEGER DEFAULT 0,
    pushed_at TEXT,
    created_at TEXT,
    dep_type TEXT DEFAULT 'runtime',
    version_declared TEXT,
    version_normalized TEXT,
    is_enterprise_repo INTEGER DEFAULT 0,
    found_at TEXT DEFAULT (datetime('now')),
    UNIQUE(canonical_name, repo_full_name),
    FOREIGN KEY (canonical_name) REFERENCES tools(canonical_name)
);

-- Co-install data: which tools appear together
CREATE TABLE IF NOT EXISTS co_installs (
    tool_a TEXT NOT NULL,
    tool_b TEXT NOT NULL,
    shared_repo_count INTEGER DEFAULT 0,
    computed_at TEXT,
    PRIMARY KEY (tool_a, tool_b)
);

-- Category-level aggregates (pre-computed, updated by pipeline)
CREATE TABLE IF NOT EXISTS categories (
    category TEXT PRIMARY KEY,
    ecosystem TEXT NOT NULL,
    tool_count INTEGER DEFAULT 0,
    description TEXT,
    market_phase TEXT,
    market_phase_explanation TEXT,
    fragmentation_index REAL DEFAULT 0,
    fragmentation_plain TEXT,
    top_tool TEXT,
    top_tool_share_pct REAL DEFAULT 0,
    insight_text TEXT,
    computed_at TEXT
);

-- Maps tracked OSS tools to the proprietary products they can replace
CREATE TABLE IF NOT EXISTS tool_alternatives (
    canonical_name TEXT NOT NULL,
    proprietary_name TEXT NOT NULL,
    proprietary_slug TEXT NOT NULL,
    proprietary_description TEXT,
    proprietary_website TEXT,
    proprietary_category TEXT,
    alternative_type TEXT DEFAULT 'full',
    PRIMARY KEY (canonical_name, proprietary_slug),
    FOREIGN KEY (canonical_name) REFERENCES tools(canonical_name)
);



-- Repository universe discovered from GitHub repo search
CREATE TABLE IF NOT EXISTS repo_universe (
    repo_full_name TEXT PRIMARY KEY,
    language TEXT,
    ecosystem_hint TEXT,
    stars INTEGER DEFAULT 0,
    default_branch TEXT,
    pushed_at TEXT,
    created_at TEXT,
    is_archived INTEGER DEFAULT 0,
    is_fork INTEGER DEFAULT 0,
    last_seen_at TEXT DEFAULT (datetime('now'))
);

-- Cached manifest contents for deterministic parsing and resume safety
CREATE TABLE IF NOT EXISTS repo_manifests (
    repo_full_name TEXT NOT NULL,
    manifest_path TEXT NOT NULL,
    sha TEXT,
    content_text TEXT,
    fetched_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (repo_full_name, manifest_path)
);

-- Top contributors by tool
CREATE TABLE IF NOT EXISTS tool_contributors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    github_login TEXT NOT NULL,
    contributions INTEGER DEFAULT 0,
    avatar_url TEXT,
    html_url TEXT,
    name TEXT,
    company TEXT,
    bio TEXT,
    location TEXT,
    followers INTEGER DEFAULT 0,
    public_repos INTEGER DEFAULT 0,
    twitter_username TEXT,
    fetched_at TEXT,
    UNIQUE(canonical_name, github_login),
    FOREIGN KEY (canonical_name) REFERENCES tools(canonical_name)
);

-- Weekly downloads by registry for each tool snapshot
CREATE TABLE IF NOT EXISTS download_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    weekly_downloads INTEGER DEFAULT 0,
    source TEXT NOT NULL,
    fetched_at TEXT,
    UNIQUE(canonical_name, snapshot_date),
    FOREIGN KEY (canonical_name) REFERENCES tools(canonical_name)
);

-- Dependency and vulnerability health signals by tool
CREATE TABLE IF NOT EXISTS tool_health (
    canonical_name TEXT PRIMARY KEY,

    -- Release health
    last_release_days INTEGER,
    latest_version TEXT,

    -- Dependency complexity
    direct_dep_count INTEGER,
    transitive_dep_count INTEGER,

    -- License
    license TEXT,
    license_is_permissive INTEGER,

    -- Vulnerabilities (from OSV)
    advisory_critical INTEGER DEFAULT 0,
    advisory_high INTEGER DEFAULT 0,
    advisory_medium INTEGER DEFAULT 0,
    advisory_low INTEGER DEFAULT 0,
    advisory_total INTEGER DEFAULT 0,

    -- Computed score
    health_score REAL DEFAULT 0,
    health_tier TEXT DEFAULT 'Unknown',
    health_tier_reason TEXT,

    -- Data quality
    deps_dev_found INTEGER DEFAULT 0,
    osv_found INTEGER DEFAULT 0,
    fetched_at TEXT,

    FOREIGN KEY (canonical_name) REFERENCES tools(canonical_name)
);

-- Pipeline run health logs
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date TEXT NOT NULL,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL,
    duration_seconds REAL,
    tools_processed INTEGER DEFAULT 0,
    snapshots_created INTEGER DEFAULT 0,
    downloads_fetched INTEGER DEFAULT 0,
    contributors_fetched INTEGER DEFAULT 0,
    validation_passed INTEGER DEFAULT 1,
    notes TEXT,
    completed_at TEXT
);

-- API response cache
CREATE TABLE IF NOT EXISTS api_cache (
    cache_key TEXT PRIMARY KEY,
    response_json TEXT NOT NULL,
    cached_at TEXT NOT NULL
);
"""


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    cols = _table_columns(conn, table)
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def run_migrations(conn: sqlite3.Connection) -> None:
    _ensure_column(
        conn,
        "tool_repos",
        "is_enterprise_repo",
        "is_enterprise_repo INTEGER DEFAULT 0",
    )
    _ensure_column(
        conn,
        "tool_snapshots",
        "enterprise_repo_count",
        "enterprise_repo_count INTEGER DEFAULT 0",
    )
    _ensure_column(
        conn,
        "tool_snapshots",
        "weekly_downloads",
        "weekly_downloads INTEGER DEFAULT 0",
    )
    _ensure_column(
        conn,
        "tool_snapshots",
        "downloads_source",
        "downloads_source TEXT",
    )
    _ensure_column(
        conn,
        "tool_snapshots",
        "sample_size",
        "sample_size INTEGER DEFAULT 0",
    )
    _ensure_column(
        conn,
        "tool_snapshots",
        "confidence_tier",
        "confidence_tier TEXT DEFAULT 'Low'",
    )
    _ensure_column(
        conn,
        "tool_snapshots",
        "sample_tier",
        "sample_tier TEXT DEFAULT 'Low'",
    )
    _ensure_column(
        conn,
        "tool_snapshots",
        "trend_tier",
        "trend_tier TEXT DEFAULT 'Early'",
    )
    _ensure_column(
        conn,
        "tool_snapshots",
        "confidence_tooltip",
        "confidence_tooltip TEXT",
    )
    _ensure_column(
        conn,
        "tool_snapshots",
        "is_trend_reliable",
        "is_trend_reliable INTEGER DEFAULT 0",
    )
    _ensure_column(
        conn,
        "tool_snapshots",
        "repos_delta_7d",
        "repos_delta_7d INTEGER DEFAULT 0",
    )
    _ensure_column(
        conn,
        "tool_snapshots",
        "downloads_delta_7d",
        "downloads_delta_7d INTEGER DEFAULT 0",
    )
    _ensure_column(
        conn,
        "tool_snapshots",
        "last_ecosystem_activity",
        "last_ecosystem_activity TEXT",
    )
    _ensure_column(
        conn,
        "tool_snapshots",
        "days_since_ecosystem_activity",
        "days_since_ecosystem_activity INTEGER",
    )
    _ensure_column(
        conn,
        "tool_snapshots",
        "active_builder_count",
        "active_builder_count INTEGER DEFAULT 0",
    )
    _ensure_column(
        conn,
        "tools",
        "usage_model",
        "usage_model TEXT DEFAULT 'dependency_first'",
    )
    _ensure_column(
        conn,
        "tools",
        "npm_package",
        "npm_package TEXT",
    )
    _ensure_column(
        conn,
        "tools",
        "pypi_package",
        "pypi_package TEXT",
    )
    _ensure_column(
        conn,
        "tools",
        "website_domain",
        "website_domain TEXT",
    )
    _ensure_column(
        conn,
        "tools",
        "is_official",
        "is_official INTEGER DEFAULT 0",
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_alternatives (
            canonical_name TEXT NOT NULL,
            proprietary_name TEXT NOT NULL,
            proprietary_slug TEXT NOT NULL,
            proprietary_description TEXT,
            proprietary_website TEXT,
            proprietary_category TEXT,
            alternative_type TEXT DEFAULT 'full',
            PRIMARY KEY (canonical_name, proprietary_slug),
            FOREIGN KEY (canonical_name) REFERENCES tools(canonical_name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS download_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name TEXT NOT NULL,
            snapshot_date TEXT NOT NULL,
            weekly_downloads INTEGER DEFAULT 0,
            source TEXT NOT NULL,
            fetched_at TEXT,
            UNIQUE(canonical_name, snapshot_date),
            FOREIGN KEY (canonical_name) REFERENCES tools(canonical_name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL,
            run_type TEXT NOT NULL,
            status TEXT NOT NULL,
            duration_seconds REAL,
            tools_processed INTEGER DEFAULT 0,
            snapshots_created INTEGER DEFAULT 0,
            downloads_fetched INTEGER DEFAULT 0,
            contributors_fetched INTEGER DEFAULT 0,
            validation_passed INTEGER DEFAULT 1,
            notes TEXT,
            completed_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_health (
            canonical_name TEXT PRIMARY KEY,
            last_release_days INTEGER,
            latest_version TEXT,
            direct_dep_count INTEGER,
            transitive_dep_count INTEGER,
            license TEXT,
            license_is_permissive INTEGER,
            advisory_critical INTEGER DEFAULT 0,
            advisory_high INTEGER DEFAULT 0,
            advisory_medium INTEGER DEFAULT 0,
            advisory_low INTEGER DEFAULT 0,
            advisory_total INTEGER DEFAULT 0,
            health_score REAL DEFAULT 0,
            health_tier TEXT DEFAULT 'Unknown',
            health_tier_reason TEXT,
            deps_dev_found INTEGER DEFAULT 0,
            osv_found INTEGER DEFAULT 0,
            fetched_at TEXT,
            FOREIGN KEY (canonical_name) REFERENCES tools(canonical_name)
        )
        """
    )


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(_SCHEMA_SQL)
        run_migrations(conn)
        conn.commit()


def _is_fresh(cached_at: str, ttl_hours: int) -> bool:
    try:
        ts = datetime.fromisoformat(cached_at)
    except ValueError:
        try:
            ts = datetime.strptime(cached_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return False
    return datetime.utcnow() - ts < timedelta(hours=ttl_hours)


def is_cached(key: str, ttl_hours: int = 24) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT cached_at FROM api_cache WHERE cache_key = ?", (key,)
        ).fetchone()
        if not row:
            return False
        if _is_fresh(row["cached_at"], ttl_hours):
            return True
        conn.execute("DELETE FROM api_cache WHERE cache_key = ?", (key,))
        conn.commit()
        return False


def cache_get(key: str, ttl_hours: int = 24) -> Any | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT response_json, cached_at FROM api_cache WHERE cache_key = ?", (key,)
        ).fetchone()
        if not row:
            return None
        if not _is_fresh(row["cached_at"], ttl_hours):
            conn.execute("DELETE FROM api_cache WHERE cache_key = ?", (key,))
            conn.commit()
            return None
        try:
            return json.loads(row["response_json"])
        except json.JSONDecodeError:
            conn.execute("DELETE FROM api_cache WHERE cache_key = ?", (key,))
            conn.commit()
            return None


def cache_set(key: str, data: Any, ttl_hours: int = 24) -> None:
    payload = json.dumps(data)
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT cached_at FROM api_cache WHERE cache_key = ?", (key,)
            ).fetchone()
            if row and _is_fresh(row["cached_at"], ttl_hours):
                return
            conn.execute(
                """
                INSERT INTO api_cache(cache_key, response_json, cached_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    response_json=excluded.response_json,
                    cached_at=excluded.cached_at
                """,
                (key, payload, now),
            )
            conn.commit()
    except sqlite3.OperationalError:
        # Caching must never stop the pipeline.
        return


__all__ = [
    "DB_PATH",
    "GITHUB_TOKEN",
    "cache_get",
    "cache_set",
    "get_conn",
    "init_db",
    "is_cached",
    "run_migrations",
]
