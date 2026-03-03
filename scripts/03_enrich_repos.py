from __future__ import annotations

import os
import time
from typing import Any

import requests

try:
    from scripts.db import GITHUB_TOKEN, cache_get, cache_set, get_conn, init_db
except ModuleNotFoundError:
    from db import GITHUB_TOKEN, cache_get, cache_set, get_conn, init_db

BASE_URL = "https://api.github.com/repos"
BATCH_SIZE = 50
MAX_REPOS = int(os.getenv("ENRICH_LIMIT", "2000"))


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"token {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "under-the-hood",
    }


def _respect_rate_limit(headers: dict[str, str]) -> None:
    remaining_raw = headers.get("X-RateLimit-Remaining")
    reset_raw = headers.get("X-RateLimit-Reset")
    try:
        remaining = int(remaining_raw) if remaining_raw is not None else 999
    except ValueError:
        remaining = 999

    if remaining < 3 and reset_raw:
        try:
            reset_ts = int(reset_raw)
            wait_for = max(0, reset_ts - int(time.time())) + 5
            print(f"  -> Rate limit almost reached. Sleeping {wait_for}s until reset.")
            time.sleep(wait_for)
        except ValueError:
            pass


def _api_get(repo_full_name: str, cache_key: str) -> tuple[dict[str, Any] | None, bool]:
    cached = cache_get(cache_key, ttl_hours=48)
    if cached is not None:
        return cached, True

    retries = 0
    while retries <= 1:
        try:
            response = requests.get(
                f"{BASE_URL}/{repo_full_name}",
                headers=_headers(),
                timeout=30,
            )
            _respect_rate_limit(response.headers)

            if response.status_code == 403:
                if retries == 0:
                    print("  -> 403 from GitHub API. Sleeping 60s and retrying once.")
                    retries += 1
                    time.sleep(60)
                    continue
                print(f"  -> 403 persisted for {repo_full_name}. Skipping.")
                return None, False

            if response.status_code == 422:
                print(f"  -> 422 for {repo_full_name}. Skipping.")
                return None, False

            if response.status_code == 404:
                return {
                    "stargazers_count": -1,
                    "pushed_at": None,
                    "created_at": None,
                    "archived": True,
                    "fork": True,
                }, False

            if response.status_code != 200:
                print(f"  -> API error {response.status_code} for {repo_full_name}. Skipping.")
                return None, False

            payload = response.json()
            cache_set(cache_key, payload, ttl_hours=48)
            return payload, False
        except requests.RequestException as exc:
            print(f"  -> Request failed for {repo_full_name}: {exc}. Skipping.")
            return None, False
        finally:
            time.sleep(1)

    return None, False


def _upsert_repo_meta(conn, repo_full_name: str, payload: dict[str, Any]) -> int:
    stars = int(payload.get("stargazers_count") or 0)
    pushed_at = payload.get("pushed_at")
    created_at = payload.get("created_at")
    archived = bool(payload.get("archived"))
    fork = bool(payload.get("fork"))

    # Keep the dataset focused on serious public repos.
    if archived or fork or (stars > 0 and stars < 500):
        stars = -1

    cur = conn.execute(
        """
        UPDATE tool_repos
        SET stars = ?, pushed_at = ?, created_at = ?
        WHERE repo_full_name = ?
        """,
        (stars, pushed_at, created_at, repo_full_name),
    )
    return cur.rowcount


def main() -> None:
    init_db()

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT repo_full_name
            FROM tool_repos
            WHERE COALESCE(stars, 0) = 0
            GROUP BY repo_full_name
            ORDER BY COUNT(*) DESC, MAX(found_at) DESC
            LIMIT ?
            """,
            (MAX_REPOS,),
        ).fetchall()

        repo_names = [row["repo_full_name"] for row in rows]
        total = len(repo_names)

        if total == 0:
            print("Nothing to enrich. All repos already have metadata.")
            return

        for idx, repo_full_name in enumerate(repo_names, start=1):
            cache_key = f"repo_meta:{repo_full_name}"
            payload, from_cache = _api_get(repo_full_name, cache_key)
            if payload is None:
                continue

            _upsert_repo_meta(conn, repo_full_name, payload)

            stars_out = int(payload.get("stargazers_count") or 0)
            archived = bool(payload.get("archived"))
            fork = bool(payload.get("fork"))
            if archived or fork or (stars_out > 0 and stars_out < 500):
                stars_display = "filtered"
            else:
                stars_display = f"{stars_out:,}"
            print(f"[ {idx}/{total} ] {repo_full_name} -> ★ {stars_display}")

            if idx % BATCH_SIZE == 0:
                conn.commit()

        conn.commit()

        remaining = conn.execute(
            """
            SELECT COUNT(DISTINCT repo_full_name)
            FROM tool_repos
            WHERE COALESCE(stars, 0) = 0
            """
        ).fetchone()[0]
        print(f"Remaining unenriched repos: {remaining:,}")


if __name__ == "__main__":
    main()
