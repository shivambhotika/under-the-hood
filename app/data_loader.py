from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).parent.parent / "data" / "uth.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@st.cache_data(ttl=3600)
def db_has_data() -> bool:
    """Returns True if the DB has been populated."""
    try:
        conn = get_conn()
        count = conn.execute("SELECT COUNT(*) FROM tools").fetchone()[0]
        snap = conn.execute("SELECT COUNT(*) FROM tool_snapshots").fetchone()[0]
        conn.close()
        return count > 0 and snap > 0
    except Exception:
        return False


@st.cache_data(ttl=3600)
def get_summary_stats() -> dict:
    conn = get_conn()
    total_repos = conn.execute(
        "SELECT SUM(total_repos) FROM tool_snapshots WHERE snapshot_date = date('now')"
    ).fetchone()[0] or 0
    total_tools = conn.execute("SELECT COUNT(*) FROM tools").fetchone()[0]
    total_categories = conn.execute("SELECT COUNT(DISTINCT category) FROM tools").fetchone()[0]

    biggest_mover = conn.execute(
        """
        SELECT t.display_name, s.total_repos, s.emergence_score
        FROM tool_snapshots s JOIN tools t ON s.canonical_name = t.canonical_name
        WHERE s.snapshot_date = date('now')
        ORDER BY s.emergence_score DESC LIMIT 1
        """
    ).fetchone()

    conn.close()
    return {
        "total_repos": int(total_repos),
        "total_tools": int(total_tools),
        "total_categories": int(total_categories),
        "biggest_mover": dict(biggest_mover) if biggest_mover else None,
    }


@st.cache_data(ttl=3600)
def get_all_tools_df(ecosystem: str | None = None, category: str | None = None) -> pd.DataFrame:
    """Returns all tools with latest snapshot data."""
    conn = get_conn()
    query = """
        SELECT
            t.canonical_name, t.display_name, t.ecosystem, t.category, t.description, t.github_repo,
            COALESCE(s.total_repos, 0) as total_repos,
            COALESCE(s.active_repos, 0) as active_repos,
            COALESCE(s.new_repos_90d, 0) as new_repos_90d,
            COALESCE(s.emergence_score, 0) as emergence_score,
            COALESCE(s.stars_median, 0) as stars_median
        FROM tools t
        LEFT JOIN tool_snapshots s ON t.canonical_name = s.canonical_name
            AND s.snapshot_date = date('now')
        WHERE 1=1
    """
    params: list[str] = []
    if ecosystem:
        query += " AND t.ecosystem = ?"
        params.append(ecosystem)
    if category:
        query += " AND t.category = ?"
        params.append(category)
    query += " ORDER BY total_repos DESC"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


@st.cache_data(ttl=3600)
def get_tool_detail(canonical_name: str) -> dict:
    conn = get_conn()
    tool = conn.execute(
        """
        SELECT t.*,
            COALESCE(s.total_repos,0) as total_repos,
            COALESCE(s.active_repos,0) as active_repos,
            COALESCE(s.new_repos_90d,0) as new_repos_90d,
            COALESCE(s.emergence_score,0) as emergence_score,
            COALESCE(s.stars_median,0) as stars_median
        FROM tools t
        LEFT JOIN tool_snapshots s ON t.canonical_name = s.canonical_name
            AND s.snapshot_date = date('now')
        WHERE t.canonical_name = ?
        """,
        (canonical_name,),
    ).fetchone()
    if not tool:
        conn.close()
        return {}

    result = dict(tool)

    versions = conn.execute(
        """
        SELECT version_normalized, COUNT(*) as cnt
        FROM tool_repos
        WHERE canonical_name = ? AND version_normalized IS NOT NULL AND version_normalized != ''
          AND COALESCE(stars, 0) != -1
        GROUP BY version_normalized
        ORDER BY cnt DESC LIMIT 6
        """,
        (canonical_name,),
    ).fetchall()
    result["version_spread"] = [dict(v) for v in versions]

    top_repos = conn.execute(
        """
        SELECT repo_full_name, stars
        FROM tool_repos
        WHERE canonical_name = ? AND stars > 0
        ORDER BY stars DESC LIMIT 8
        """,
        (canonical_name,),
    ).fetchall()
    result["top_repos"] = [dict(r) for r in top_repos]

    history = conn.execute(
        """
        SELECT snapshot_date, total_repos, emergence_score
        FROM tool_snapshots
        WHERE canonical_name = ?
        ORDER BY snapshot_date ASC
        """,
        (canonical_name,),
    ).fetchall()
    result["history"] = [dict(h) for h in history]

    conn.close()
    return result


@st.cache_data(ttl=3600)
def get_all_categories_df() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM categories ORDER BY tool_count DESC", conn)
    conn.close()
    return df


@st.cache_data(ttl=3600)
def get_category_tools_df(category: str) -> pd.DataFrame:
    return get_all_tools_df(category=category)


@st.cache_data(ttl=3600)
def get_top_movers(n: int = 6) -> pd.DataFrame:
    """Tools with highest emergence scores today."""
    conn = get_conn()
    df = pd.read_sql_query(
        """
        SELECT t.canonical_name, t.display_name, t.ecosystem, t.category, t.description,
               s.total_repos, s.new_repos_90d, s.emergence_score, s.active_repos
        FROM tools t
        JOIN tool_snapshots s ON t.canonical_name = s.canonical_name
        WHERE s.snapshot_date = date('now') AND s.total_repos > 10
        ORDER BY s.emergence_score DESC
        LIMIT ?
        """,
        conn,
        params=(n,),
    )
    conn.close()
    return df
