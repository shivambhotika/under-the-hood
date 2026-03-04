from __future__ import annotations

"""
Fetch top contributors for high-emergence tools.
Uses GitHub Contributors API + Users API.
Run after 04_compute_scores.py.
"""

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

try:
    from scripts.db import GITHUB_TOKEN, cache_get, cache_set, get_conn, init_db
except ModuleNotFoundError:
    from db import GITHUB_TOKEN, cache_get, cache_set, get_conn, init_db

API_BASE = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"token {GITHUB_TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "under-the-hood-contributors",
}
REQUEST_SLEEP_SECONDS = 1.5
TOP_TOOLS_LIMIT = int(os.getenv("CONTRIB_TOP_LIMIT", "35"))
TOP_CONTRIBUTORS_PER_TOOL = 10


def _sleep_with_log(seconds: float) -> None:
    secs = max(0.0, float(seconds))
    if secs > 0:
        print(f"  -> Sleeping {int(round(secs))}s for rate limit")
        time.sleep(secs)


def _respect_rate_limit(response: requests.Response) -> None:
    remaining = response.headers.get("X-RateLimit-Remaining")
    reset = response.headers.get("X-RateLimit-Reset")
    if remaining is None or reset is None:
        return
    try:
        remaining_i = int(remaining)
        reset_ts = int(reset)
    except ValueError:
        return

    if remaining_i < 5:
        now_ts = int(time.time())
        wait_seconds = max(0, reset_ts - now_ts) + 5
        _sleep_with_log(wait_seconds)


def _api_get(url: str, cache_key: str, ttl_hours: int, params: dict[str, Any] | None = None) -> tuple[Any | None, bool]:
    cached = cache_get(cache_key, ttl_hours=ttl_hours)
    if cached is not None:
        return cached, True

    retried_403 = False
    while True:
        try:
            response = requests.get(url, headers=HEADERS, params=params, timeout=40)
            _respect_rate_limit(response)

            if response.status_code == 403 and not retried_403:
                retried_403 = True
                _sleep_with_log(60)
                continue

            if response.status_code >= 400:
                print(f"  -> API error {response.status_code} for {cache_key}. Skipping.")
                return None, False

            payload = response.json()
            cache_set(cache_key, payload, ttl_hours=ttl_hours)
            return payload, False
        except requests.RequestException as exc:
            print(f"  -> Request failed for {cache_key}: {exc}")
            return None, False
        finally:
            time.sleep(REQUEST_SLEEP_SECONDS)


def _latest_snapshot_date(conn) -> str | None:
    row = conn.execute("SELECT MAX(snapshot_date) AS d FROM tool_snapshots").fetchone()
    return row["d"] if row and row["d"] else None


def _tool_recently_fetched(conn, canonical_name: str, hours: int = 72) -> bool:
    row = conn.execute(
        "SELECT MAX(fetched_at) AS fetched_at FROM tool_contributors WHERE canonical_name = ?",
        (canonical_name,),
    ).fetchone()
    if not row or not row["fetched_at"]:
        return False

    raw = str(row["fetched_at"])
    parsed: datetime | None = None
    for fmt in (None, "%Y-%m-%d %H:%M:%S"):
        try:
            if fmt is None:
                parsed = datetime.fromisoformat(raw)
            else:
                parsed = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue

    if parsed is None:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return datetime.now(timezone.utc) - parsed < timedelta(hours=hours)


def _save_contributors(conn, canonical_name: str, contributors: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM tool_contributors WHERE canonical_name = ?", (canonical_name,))

    for contributor in contributors:
        conn.execute(
            """
            INSERT OR REPLACE INTO tool_contributors (
                canonical_name, github_login, contributions, avatar_url, html_url,
                name, company, bio, location, followers, public_repos,
                twitter_username, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                canonical_name,
                contributor.get("github_login"),
                int(contributor.get("contributions") or 0),
                contributor.get("avatar_url"),
                contributor.get("html_url"),
                contributor.get("name"),
                contributor.get("company"),
                contributor.get("bio"),
                contributor.get("location"),
                int(contributor.get("followers") or 0),
                int(contributor.get("public_repos") or 0),
                contributor.get("twitter_username"),
            ),
        )


def main() -> None:
    init_db()

    with get_conn() as conn:
        snapshot_date = _latest_snapshot_date(conn)
        if not snapshot_date:
            print("No snapshots available. Run scoring first.")
            return

        tools = conn.execute(
            (
                """
                SELECT t.canonical_name, t.github_repo, s.emergence_score, s.total_repos
                FROM tool_snapshots s
                JOIN tools t ON t.canonical_name = s.canonical_name
                WHERE s.snapshot_date = ?
                  AND t.github_repo IS NOT NULL
                  AND TRIM(t.github_repo) != ''
                  AND COALESCE(s.total_repos, 0) > 0
                ORDER BY s.emergence_score DESC
                LIMIT ?
                """
                if TOP_TOOLS_LIMIT > 0
                else
                """
                SELECT t.canonical_name, t.github_repo, s.emergence_score, s.total_repos
                FROM tool_snapshots s
                JOIN tools t ON t.canonical_name = s.canonical_name
                WHERE s.snapshot_date = ?
                  AND t.github_repo IS NOT NULL
                  AND TRIM(t.github_repo) != ''
                  AND COALESCE(s.total_repos, 0) > 0
                ORDER BY s.emergence_score DESC
                """
            ),
            ((snapshot_date, TOP_TOOLS_LIMIT) if TOP_TOOLS_LIMIT > 0 else (snapshot_date,)),
        ).fetchall()

        total = len(tools)
        if total == 0:
            print("No eligible tools with github_repo found.")
            return

        for i, row in enumerate(tools, start=1):
            canonical_name = row["canonical_name"]
            github_repo = row["github_repo"]

            if _tool_recently_fetched(conn, canonical_name, hours=72):
                print(f"[ {i:>2}/{total} ] {canonical_name} -> skipped (fetched <72h ago)")
                continue

            contributors_url = f"{API_BASE}/repos/{github_repo}/contributors"
            contributors_payload, _ = _api_get(
                contributors_url,
                cache_key=f"contributors:{canonical_name}",
                ttl_hours=72,
                params={"per_page": TOP_CONTRIBUTORS_PER_TOOL},
            )
            if not isinstance(contributors_payload, list):
                print(f"[ {i:>2}/{total} ] {canonical_name} -> no contributor data")
                continue

            saved_rows: list[dict[str, Any]] = []
            for c in contributors_payload[:TOP_CONTRIBUTORS_PER_TOOL]:
                login = c.get("login")
                if not login:
                    continue

                user_payload, _ = _api_get(
                    f"{API_BASE}/users/{login}",
                    cache_key=f"user:{login}",
                    ttl_hours=168,
                )
                if not isinstance(user_payload, dict):
                    user_payload = {}

                saved_rows.append(
                    {
                        "github_login": login,
                        "contributions": int(c.get("contributions") or 0),
                        "avatar_url": user_payload.get("avatar_url") or c.get("avatar_url"),
                        "html_url": user_payload.get("html_url") or c.get("html_url"),
                        "name": user_payload.get("name"),
                        "company": user_payload.get("company"),
                        "bio": user_payload.get("bio"),
                        "location": user_payload.get("location"),
                        "followers": int(user_payload.get("followers") or 0),
                        "public_repos": int(user_payload.get("public_repos") or 0),
                        "twitter_username": user_payload.get("twitter_username"),
                    }
                )

            _save_contributors(conn, canonical_name, saved_rows)
            conn.commit()
            print(f"[ {i:>2}/{total} ] {canonical_name} -> fetched {len(saved_rows)} contributors")


if __name__ == "__main__":
    main()
