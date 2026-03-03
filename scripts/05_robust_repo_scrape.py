from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any

import requests

try:
    from scripts.db import GITHUB_TOKEN, cache_get, cache_set, get_conn, init_db
except ModuleNotFoundError:
    from db import GITHUB_TOKEN, cache_get, cache_set, get_conn, init_db

REPO_SEARCH_URL = "https://api.github.com/search/repositories"
REPO_API_BASE = "https://api.github.com/repos"

DISCOVERY_PAGES = int(os.getenv("DISCOVERY_PAGES", "8"))
REPO_SCAN_LIMIT = int(os.getenv("REPO_SCAN_LIMIT", "12000"))
SEARCH_SLEEP_SECONDS = float(os.getenv("SEARCH_SLEEP_SECONDS", "2"))
CORE_SLEEP_SECONDS = float(os.getenv("CORE_SLEEP_SECONDS", "0.8"))

LANGUAGE_PROFILES = [
    ("TypeScript", "npm"),
    ("JavaScript", "npm"),
    ("Python", "pypi"),
    ("Rust", "cargo"),
    ("Go", "go"),
]
STAR_BUCKETS = ["500..1500", "1501..5000", ">5000"]

MANIFESTS_BY_ECOSYSTEM = {
    "npm": ["package.json"],
    "pypi": ["requirements.txt", "pyproject.toml"],
    "cargo": ["Cargo.toml"],
    "go": ["go.mod"],
}


def _headers(accept: str = "application/vnd.github+json") -> dict[str, str]:
    return {
        "Accept": accept,
        "Authorization": f"token {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "under-the-hood-robust-scraper",
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


def _api_get(
    url: str,
    params: dict[str, Any] | None,
    cache_key: str,
    ttl_hours: int,
    sleep_seconds: float,
    accept: str = "application/vnd.github+json",
) -> tuple[dict[str, Any] | None, bool, bool]:
    """Return payload, from_cache, made_network_call."""
    cached = cache_get(cache_key, ttl_hours=ttl_hours)
    if cached is not None:
        return cached, True, False

    retries = 0
    while retries <= 1:
        try:
            resp = requests.get(url, headers=_headers(accept), params=params, timeout=30)
            _respect_rate_limit(resp.headers)

            if resp.status_code == 403:
                if retries == 0:
                    print("  -> 403 received. Sleeping 60s and retrying once.")
                    retries += 1
                    time.sleep(60)
                    continue
                print(f"  -> 403 persisted for {cache_key}. Skipping.")
                return None, False, True

            if resp.status_code in (404, 422):
                return None, False, True

            if resp.status_code != 200:
                print(f"  -> API error {resp.status_code} for {cache_key}. Skipping.")
                return None, False, True

            payload = resp.json()
            cache_set(cache_key, payload, ttl_hours=ttl_hours)
            return payload, False, True
        except requests.RequestException as exc:
            print(f"  -> Request failed for {cache_key}: {exc}")
            return None, False, True
        finally:
            time.sleep(sleep_seconds)

    return None, False, True


def _canonical_maps(conn) -> tuple[set[str], dict[str, str]]:
    tools = conn.execute("SELECT canonical_name FROM tools").fetchall()
    aliases = conn.execute("SELECT alias, canonical_name FROM tool_aliases").fetchall()

    canonical = {row["canonical_name"] for row in tools}
    alias_map = {row["alias"].lower(): row["canonical_name"] for row in aliases}
    for c in canonical:
        alias_map[c.lower()] = c
        alias_map[c.lower().replace("_", "-")] = c
    return canonical, alias_map


def _normalize_version(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = raw.strip().strip('"\'')
    cleaned = re.sub(r"^[\^~<>=!\s]+", "", cleaned)
    match = re.search(r"\d+(?:\.\d+){0,3}", cleaned)
    return match.group(0) if match else None


def _resolve_candidate(name: str, canonical_set: set[str], alias_map: dict[str, str]) -> str | None:
    n = name.strip().lower()
    candidates = {n, n.replace("_", "-"), n.replace("-", "_")}

    if "/" in n:
        last = n.split("/")[-1]
        candidates.add(last)
        if last.startswith("v"):
            candidates.add(last[1:])

    for c in candidates:
        if c in alias_map:
            return alias_map[c]

    for c in candidates:
        if c in canonical_set:
            return c

    return None


def _parse_package_json(text: str) -> list[tuple[str, str, str | None]]:
    out: list[tuple[str, str, str | None]] = []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return out

    for section, dep_type in (
        ("dependencies", "runtime"),
        ("optionalDependencies", "runtime"),
        ("peerDependencies", "runtime"),
        ("devDependencies", "dev"),
    ):
        deps = payload.get(section) or {}
        if not isinstance(deps, dict):
            continue
        for name, version in deps.items():
            out.append((str(name), dep_type, str(version) if version is not None else None))
    return out


def _parse_requirements(text: str) -> list[tuple[str, str, str | None]]:
    out: list[tuple[str, str, str | None]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(("-r", "--", "-e", "git+")):
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*([<>=!~].+)?$", line)
        if not m:
            continue
        name = m.group(1)
        version = (m.group(2) or "").strip() or None
        out.append((name, "runtime", version))
    return out


def _parse_pyproject(text: str) -> list[tuple[str, str, str | None]]:
    out: list[tuple[str, str, str | None]] = []
    lines = text.splitlines()
    section = ""
    in_project_deps = False

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("[") and line.endswith("]"):
            section = line.lower().strip("[]")
            in_project_deps = False
            continue

        if line.lower().startswith("dependencies") and line.endswith("["):
            in_project_deps = True
            continue

        if in_project_deps:
            if line.startswith("]"):
                in_project_deps = False
                continue
            m = re.search(r'"([^\"]+)"', line)
            if m:
                dep_expr = m.group(1)
                name_match = re.match(r"^([A-Za-z0-9_.\-]+)", dep_expr)
                if name_match:
                    name = name_match.group(1)
                    version = dep_expr[len(name):].strip() or None
                    out.append((name, "runtime", version))
            continue

        if section in {"tool.poetry.dependencies", "tool.poetry.group.dev.dependencies", "dependency-groups"}:
            m = re.match(r"^([A-Za-z0-9_.\-]+)\s*=\s*(.+)$", line)
            if not m:
                continue
            name = m.group(1)
            value = m.group(2).strip()
            dep_type = "dev" if section == "tool.poetry.group.dev.dependencies" else "runtime"
            out.append((name, dep_type, value))

    return out


def _parse_cargo_toml(text: str) -> list[tuple[str, str, str | None]]:
    out: list[tuple[str, str, str | None]] = []
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line.lower().strip("[]")
            continue
        if section not in {"dependencies", "dev-dependencies"}:
            continue
        m = re.match(r"^([A-Za-z0-9_.\-]+)\s*=\s*(.+)$", line)
        if not m:
            continue
        out.append((m.group(1), "dev" if section == "dev-dependencies" else "runtime", m.group(2).strip()))
    return out


def _parse_go_mod(text: str) -> list[tuple[str, str, str | None]]:
    out: list[tuple[str, str, str | None]] = []
    in_require = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("require ("):
            in_require = True
            continue
        if in_require and line == ")":
            in_require = False
            continue

        if line.startswith("require "):
            body = line[len("require "):].strip()
            parts = body.split()
            if len(parts) >= 2:
                module = parts[0]
                ver = parts[1]
                out.append((module, "runtime", ver))
                out.append((module.split("/")[-1], "runtime", ver))
            continue

        if in_require:
            parts = line.split()
            if len(parts) >= 2:
                module = parts[0]
                ver = parts[1]
                out.append((module, "runtime", ver))
                out.append((module.split("/")[-1], "runtime", ver))
    return out


def _parse_manifest(manifest_path: str, text: str) -> list[tuple[str, str, str | None]]:
    if manifest_path == "package.json":
        return _parse_package_json(text)
    if manifest_path == "requirements.txt":
        return _parse_requirements(text)
    if manifest_path == "pyproject.toml":
        return _parse_pyproject(text)
    if manifest_path == "Cargo.toml":
        return _parse_cargo_toml(text)
    if manifest_path == "go.mod":
        return _parse_go_mod(text)
    return []


def _upsert_repo_universe(conn, item: dict[str, Any], ecosystem_hint: str) -> None:
    conn.execute(
        """
        INSERT INTO repo_universe (
            repo_full_name, language, ecosystem_hint, stars, default_branch,
            pushed_at, created_at, is_archived, is_fork, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(repo_full_name) DO UPDATE SET
            language=excluded.language,
            ecosystem_hint=excluded.ecosystem_hint,
            stars=excluded.stars,
            default_branch=excluded.default_branch,
            pushed_at=excluded.pushed_at,
            created_at=excluded.created_at,
            is_archived=excluded.is_archived,
            is_fork=excluded.is_fork,
            last_seen_at=excluded.last_seen_at
        """,
        (
            item.get("full_name"),
            item.get("language"),
            ecosystem_hint,
            int(item.get("stargazers_count") or 0),
            item.get("default_branch"),
            item.get("pushed_at"),
            item.get("created_at"),
            1 if item.get("archived") else 0,
            1 if item.get("fork") else 0,
        ),
    )


def discover_repo_universe(conn) -> None:
    print("\n[1/2] Discovering repository universe...")
    for language, ecosystem in LANGUAGE_PROFILES:
        for stars in STAR_BUCKETS:
            print(f"  -> language={language} stars={stars}")
            for page in range(1, DISCOVERY_PAGES + 1):
                q = f"language:{language} stars:{stars} archived:false fork:false"
                cache_key = f"repo_search:{language}:{stars}:{page}"
                payload, from_cache, _ = _api_get(
                    REPO_SEARCH_URL,
                    {
                        "q": q,
                        "sort": "updated",
                        "order": "desc",
                        "per_page": 100,
                        "page": page,
                    },
                    cache_key,
                    ttl_hours=24,
                    sleep_seconds=SEARCH_SLEEP_SECONDS,
                )
                if payload is None:
                    break

                items = payload.get("items") or []
                for item in items:
                    _upsert_repo_universe(conn, item, ecosystem)
                conn.commit()

                status = "cached" if from_cache else "live"
                print(f"     page {page}: {len(items)} repos ({status})")
                if len(items) < 100:
                    break


def _manifest_paths_for_ecosystem(ecosystem_hint: str | None) -> list[str]:
    if ecosystem_hint and ecosystem_hint in MANIFESTS_BY_ECOSYSTEM:
        return MANIFESTS_BY_ECOSYSTEM[ecosystem_hint]
    # Fallback: try all known manifest types.
    merged: list[str] = []
    for paths in MANIFESTS_BY_ECOSYSTEM.values():
        for p in paths:
            if p not in merged:
                merged.append(p)
    return merged


def _get_manifest_payload(repo_full_name: str, path: str) -> tuple[dict[str, Any] | None, bool]:
    cache_key = f"repo_manifest:{repo_full_name}:{path}"
    payload, from_cache, _ = _api_get(
        f"{REPO_API_BASE}/{repo_full_name}/contents/{path}",
        None,
        cache_key,
        ttl_hours=24,
        sleep_seconds=CORE_SLEEP_SECONDS,
    )
    return payload, from_cache


def _decode_manifest(payload: dict[str, Any]) -> str | None:
    if payload.get("type") != "file":
        return None
    content = payload.get("content")
    if not content:
        return None
    try:
        return base64.b64decode(content).decode("utf-8", errors="ignore")
    except Exception:
        return None


def _upsert_manifest(conn, repo_full_name: str, manifest_path: str, sha: str | None, content_text: str) -> None:
    conn.execute(
        """
        INSERT INTO repo_manifests(repo_full_name, manifest_path, sha, content_text, fetched_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(repo_full_name, manifest_path) DO UPDATE SET
            sha=excluded.sha,
            content_text=excluded.content_text,
            fetched_at=excluded.fetched_at
        """,
        (repo_full_name, manifest_path, sha, content_text),
    )


def _upsert_tool_repo(
    conn,
    canonical_name: str,
    repo_full_name: str,
    stars: int,
    pushed_at: str | None,
    created_at: str | None,
    dep_type: str,
    version_declared: str | None,
    version_normalized: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO tool_repos(
            canonical_name, repo_full_name, stars, pushed_at, created_at,
            dep_type, version_declared, version_normalized
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(canonical_name, repo_full_name) DO UPDATE SET
            stars=excluded.stars,
            pushed_at=excluded.pushed_at,
            created_at=excluded.created_at,
            dep_type=CASE
                WHEN tool_repos.dep_type = 'runtime' THEN 'runtime'
                ELSE excluded.dep_type
            END,
            version_declared=COALESCE(tool_repos.version_declared, excluded.version_declared),
            version_normalized=COALESCE(tool_repos.version_normalized, excluded.version_normalized)
        """,
        (
            canonical_name,
            repo_full_name,
            stars,
            pushed_at,
            created_at,
            dep_type,
            version_declared,
            version_normalized,
        ),
    )


def scan_and_extract(conn) -> None:
    print("\n[2/2] Scanning manifests and extracting tool usage...")
    canonical_set, alias_map = _canonical_maps(conn)

    repos = conn.execute(
        """
        SELECT repo_full_name, ecosystem_hint, stars, pushed_at, created_at, is_archived, is_fork
        FROM repo_universe
        WHERE stars >= 500 AND is_archived = 0 AND is_fork = 0
        ORDER BY stars DESC, pushed_at DESC
        LIMIT ?
        """,
        (REPO_SCAN_LIMIT,),
    ).fetchall()

    total = len(repos)
    if total == 0:
        print("  -> No repositories available. Run discovery first.")
        return

    for idx, repo in enumerate(repos, start=1):
        repo_name = repo["repo_full_name"]
        paths = _manifest_paths_for_ecosystem(repo["ecosystem_hint"])

        found_tools = 0
        for manifest_path in paths:
            payload, from_cache = _get_manifest_payload(repo_name, manifest_path)
            if payload is None:
                continue

            text = _decode_manifest(payload)
            if not text:
                continue

            sha = payload.get("sha")
            prev = conn.execute(
                "SELECT sha FROM repo_manifests WHERE repo_full_name = ? AND manifest_path = ?",
                (repo_name, manifest_path),
            ).fetchone()
            if prev and prev["sha"] == sha:
                # Already parsed this exact file content.
                continue

            _upsert_manifest(conn, repo_name, manifest_path, sha, text)
            deps = _parse_manifest(manifest_path, text)

            for dep_name, dep_type, version_declared in deps:
                canonical = _resolve_candidate(dep_name, canonical_set, alias_map)
                if not canonical:
                    continue
                found_tools += 1
                _upsert_tool_repo(
                    conn,
                    canonical_name=canonical,
                    repo_full_name=repo_name,
                    stars=int(repo["stars"] or 0),
                    pushed_at=repo["pushed_at"],
                    created_at=repo["created_at"],
                    dep_type=dep_type,
                    version_declared=version_declared,
                    version_normalized=_normalize_version(version_declared),
                )

        if idx % 50 == 0:
            conn.commit()

        if found_tools > 0:
            print(f"[ {idx}/{total} ] {repo_name} -> mapped {found_tools} dependencies")

    conn.commit()

    remaining_meta = conn.execute(
        "SELECT COUNT(*) AS c FROM tool_repos WHERE stars <= 0 OR stars IS NULL"
    ).fetchone()["c"]
    print(f"\nDone. tool_repos rows needing metadata cleanup: {remaining_meta:,}")


def main() -> None:
    init_db()
    if not GITHUB_TOKEN:
        raise SystemExit("GITHUB_TOKEN is missing. Add it to .env first.")

    with get_conn() as conn:
        discover_repo_universe(conn)
        scan_and_extract(conn)

    print("\nRobust repo-first scrape complete.")


if __name__ == "__main__":
    main()
