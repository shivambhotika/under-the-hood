from __future__ import annotations

import argparse
import math
import os
import re
import time
from datetime import date, datetime, timezone
from statistics import median
from typing import Any

import requests

try:
    from scripts.db import GITHUB_TOKEN, cache_get, cache_set, get_conn, init_db
except ModuleNotFoundError:
    from db import GITHUB_TOKEN, cache_get, cache_set, get_conn, init_db

BASE_URL = "https://api.github.com/search/code"
PER_PAGE = 100
MAX_PAGES = int(os.getenv("SEARCH_MAX_PAGES", "10"))


def compute_emergence_score(total_repos: int, new_repos_90d: int, active_repos: int) -> float:
    """
    High score = growing fast from a small base (the most interesting signal)
    Low score = big and slow, or small and not growing
    """
    if total_repos == 0:
        return 0.0
    recency_ratio = new_repos_90d / max(1, total_repos)
    activity_ratio = active_repos / max(1, total_repos)
    size_log = math.log1p(total_repos)
    score = (recency_ratio * 0.5 + activity_ratio * 0.3) * size_log * 10
    return round(min(score, 100.0), 2)


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/vnd.github.text-match+json",
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
            now_ts = int(time.time())
            wait_for = max(0, reset_ts - now_ts) + 5
            print(f"  -> Rate limit almost reached. Sleeping {wait_for}s until reset.")
            time.sleep(wait_for)
        except ValueError:
            pass


def _api_get(url: str, params: dict[str, Any], cache_key: str, ttl_hours: int = 24) -> tuple[dict[str, Any] | None, bool, bool]:
    """Returns: (payload, from_cache, made_network_call)."""
    cached = cache_get(cache_key, ttl_hours=ttl_hours)
    if cached is not None:
        return cached, True, False

    retries = 0
    while retries <= 1:
        response = None
        try:
            response = requests.get(url, headers=_headers(), params=params, timeout=30)
            _respect_rate_limit(response.headers)

            if response.status_code == 403:
                if retries == 0:
                    print("  -> 403 from GitHub API. Sleeping 60s and retrying once.")
                    retries += 1
                    time.sleep(60)
                    continue
                print("  -> 403 persisted after retry. Skipping request.")
                return None, False, True

            if response.status_code == 422:
                print(f"  -> 422 query rejected for {cache_key}. Skipping.")
                return None, False, True

            if response.status_code != 200:
                print(f"  -> API error {response.status_code} for {cache_key}. Skipping.")
                return None, False, True

            payload = response.json()
            cache_set(cache_key, payload, ttl_hours=ttl_hours)
            return payload, False, True
        except requests.RequestException as exc:
            print(f"  -> Request failed for {cache_key}: {exc}. Skipping.")
            return None, False, True
        finally:
            time.sleep(2)

    return None, False, True


def _normalize_version(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = raw.strip().strip('"\'')
    cleaned = re.sub(r"^[\^~<>=!\s]+", "", cleaned)
    match = re.search(r"\d+(?:\.\d+){0,3}", cleaned)
    return match.group(0) if match else None


def _extract_version(item: dict[str, Any], canonical_name: str) -> tuple[str | None, str | None]:
    text_matches = item.get("text_matches") or []
    if not text_matches:
        return None, None

    patterns = [
        re.compile(rf'"{re.escape(canonical_name)}"\s*:\s*"([^\"]+)"', re.IGNORECASE),
        re.compile(rf"^{re.escape(canonical_name)}\s*[=~!<>]+\s*([^\s#]+)", re.IGNORECASE | re.MULTILINE),
        re.compile(rf"{re.escape(canonical_name)}\s*=\s*\"([^\"]+)\"", re.IGNORECASE),
    ]

    for match_obj in text_matches:
        fragment = match_obj.get("fragment") or ""
        for pattern in patterns:
            found = pattern.search(fragment)
            if found:
                declared = found.group(1)
                return declared, _normalize_version(declared)

    return None, None


def _dep_type(item: dict[str, Any], manifest: str) -> str:
    if manifest != "package.json":
        return "runtime"
    for match_obj in item.get("text_matches") or []:
        fragment = (match_obj.get("fragment") or "").lower()
        if "devdependencies" in fragment:
            return "dev"
    return "runtime"


def _process_items(conn, canonical_name: str, manifest: str, items: list[dict[str, Any]]) -> int:
    inserted = 0
    for item in items:
        repo = item.get("repository") or {}
        full_name = repo.get("full_name")
        if not full_name:
            continue

        stars = int(repo.get("stargazers_count") or 0)
        if stars and stars < 500:
            continue

        pushed_at = repo.get("pushed_at")
        created_at = repo.get("created_at")
        dep_type = _dep_type(item, manifest)
        version_declared, version_normalized = _extract_version(item, canonical_name)

        cur = conn.execute(
            """
            INSERT OR IGNORE INTO tool_repos (
                canonical_name, repo_full_name, stars, pushed_at, created_at,
                dep_type, version_declared, version_normalized
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical_name,
                full_name,
                stars,
                pushed_at,
                created_at,
                dep_type,
                version_declared,
                version_normalized,
            ),
        )
        if cur.rowcount:
            inserted += 1
    return inserted


def _search_query_pages(conn, canonical_name: str, term: str, manifest: str) -> tuple[int, bool, bool]:
    q = f'"{term}" filename:{manifest}'
    total_found = 0
    used_cache = False
    made_api_call = False

    for page in range(1, MAX_PAGES + 1):
        if term == canonical_name:
            cache_key = f"code_search:{canonical_name}:{manifest}:{page}"
        else:
            cache_key = f"code_search:{canonical_name}:{manifest}:{page}:display_name"
        payload, from_cache, did_network = _api_get(
            BASE_URL,
            {"q": q, "per_page": PER_PAGE, "page": page},
            cache_key,
            ttl_hours=24,
        )

        used_cache = used_cache or from_cache
        made_api_call = made_api_call or did_network

        if payload is None:
            break

        items = payload.get("items") or []
        _process_items(conn, canonical_name, manifest, items)
        total_found += len(items)
        conn.commit()

        if len(items) < PER_PAGE:
            break

    return total_found, used_cache, made_api_call


def _compute_snapshot(conn, canonical_name: str) -> tuple[int, int, int, float, float]:
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

    stars_rows = conn.execute(
        """
        SELECT stars
        FROM tool_repos
        WHERE canonical_name = ? AND stars > 0
        """,
        (canonical_name,),
    ).fetchall()
    stars = [row["stars"] for row in stars_rows]
    stars_median = float(median(stars)) if stars else 0.0

    emergence = compute_emergence_score(total, new_90, active)
    return int(total), int(active), int(new_90), round(stars_median, 2), emergence


def should_skip_tool(canonical_name: str, conn, force: bool = False) -> bool:
    """
    Returns True if this tool already has a snapshot for today.
    Skipping avoids redundant API calls on re-runs.
    Set force=True to override.
    """
    if force:
        return False
    today = date.today().isoformat()
    existing = conn.execute(
        """
        SELECT total_repos
        FROM tool_snapshots
        WHERE canonical_name = ? AND snapshot_date = ?
        """,
        (canonical_name, today),
    ).fetchone()
    return existing is not None and int(existing["total_repos"] or 0) > 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-process all tools even if today's snapshot already exists",
    )
    args = parser.parse_args()

    init_db()

    with get_conn() as conn:
        tools = conn.execute(
            """
            SELECT canonical_name, display_name, ecosystem
            FROM tools
            ORDER BY canonical_name
            """
        ).fetchall()

        total_tools = len(tools)
        for idx, tool in enumerate(tools, start=1):
            canonical_name = tool["canonical_name"]
            display_name = tool["display_name"]
            ecosystem = tool["ecosystem"]

            print(f"[ {idx:>2}/{total_tools} ] {display_name} ({ecosystem}) ...")
            if should_skip_tool(canonical_name, conn, force=args.force):
                print(f"  -> ✓ {display_name} — already processed today, skipping")
                continue

            manifest_counts: dict[str, int] = {}
            tool_used_cache = False
            tool_made_api_call = False

            if ecosystem == "npm":
                count, used_cache, made_api_call = _search_query_pages(
                    conn, canonical_name, canonical_name, "package.json"
                )
                manifest_counts["package.json"] = count
                tool_used_cache = tool_used_cache or used_cache
                tool_made_api_call = tool_made_api_call or made_api_call

                if count < 20 and display_name.lower() != canonical_name.lower():
                    fallback_count, used_cache, made_api_call = _search_query_pages(
                        conn, canonical_name, display_name, "package.json"
                    )
                    manifest_counts["package.json"] += fallback_count
                    tool_used_cache = tool_used_cache or used_cache
                    tool_made_api_call = tool_made_api_call or made_api_call
            elif ecosystem == "pypi":
                for manifest in ("requirements.txt", "pyproject.toml"):
                    count, used_cache, made_api_call = _search_query_pages(
                        conn, canonical_name, canonical_name, manifest
                    )
                    manifest_counts[manifest] = count
                    tool_used_cache = tool_used_cache or used_cache
                    tool_made_api_call = tool_made_api_call or made_api_call
            elif ecosystem == "cargo":
                count, used_cache, made_api_call = _search_query_pages(
                    conn, canonical_name, canonical_name, "Cargo.toml"
                )
                manifest_counts["Cargo.toml"] = count
                tool_used_cache = tool_used_cache or used_cache
                tool_made_api_call = tool_made_api_call or made_api_call
            elif ecosystem == "go":
                count, used_cache, made_api_call = _search_query_pages(
                    conn, canonical_name, canonical_name, "go.mod"
                )
                manifest_counts["go.mod"] = count
                tool_used_cache = tool_used_cache or used_cache
                tool_made_api_call = tool_made_api_call or made_api_call

            conn.commit()

            for manifest, count in manifest_counts.items():
                print(f"  -> Found {count:,} repos in {manifest}")

            total_repos, active_repos, new_repos_90d, stars_median, emergence_score = _compute_snapshot(
                conn, canonical_name
            )
            snapshot_date = datetime.now(timezone.utc).date().isoformat()
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
                (
                    canonical_name,
                    snapshot_date,
                    total_repos,
                    active_repos,
                    new_repos_90d,
                    stars_median,
                    emergence_score,
                ),
            )
            conn.commit()

            print(f"  -> Active (30d): {active_repos:,}  New (90d): {new_repos_90d:,}")
            print(f"  -> Emergence score: {emergence_score}")
            if tool_used_cache and not tool_made_api_call:
                print("  -> Cached. Skipping API.")


if __name__ == "__main__":
    main()
