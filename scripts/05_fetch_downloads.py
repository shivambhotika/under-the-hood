from __future__ import annotations

import time
from datetime import date

import requests

try:
    from scripts.db import cache_get, cache_set, get_conn, init_db
except ModuleNotFoundError:
    from db import cache_get, cache_set, get_conn, init_db


NPM_URL = "https://api.npmjs.org/downloads/point/last-week/{package}"
PYPI_URL = "https://pypistats.org/api/packages/{package}/recent"


def _is_standalone(tool_row) -> bool:
    return str(tool_row["usage_model"] or "").strip() == "standalone_first"


def fetch_npm_downloads(package: str) -> int:
    if not package:
        return 0
    package = package.strip()
    not_found_key = f"npm_downloads_notfound:{package}"
    data_key = f"npm_downloads:{package}"

    nf = cache_get(not_found_key, ttl_hours=72)
    if nf is not None:
        return 0
    cached = cache_get(data_key, ttl_hours=24)
    if cached is not None:
        try:
            return int(cached.get("downloads", 0))
        except (TypeError, ValueError, AttributeError):
            return 0

    resp = requests.get(NPM_URL.format(package=package), timeout=20)
    if resp.status_code == 404:
        cache_set(not_found_key, {"not_found": True}, ttl_hours=72)
        return 0
    if resp.status_code >= 400:
        return 0

    payload = resp.json()
    downloads = int(payload.get("downloads", 0) or 0)
    cache_set(data_key, {"downloads": downloads}, ttl_hours=24)
    return downloads


def fetch_pypi_downloads(package: str) -> int:
    if not package:
        return 0
    package = package.strip().lower()
    not_found_key = f"pypi_downloads_notfound:{package}"
    data_key = f"pypi_downloads:{package}"

    nf = cache_get(not_found_key, ttl_hours=72)
    if nf is not None:
        return 0
    cached = cache_get(data_key, ttl_hours=24)
    if cached is not None:
        try:
            return int(cached.get("downloads", 0))
        except (TypeError, ValueError, AttributeError):
            return 0

    resp = requests.get(PYPI_URL.format(package=package), timeout=20)
    if resp.status_code == 404:
        cache_set(not_found_key, {"not_found": True}, ttl_hours=72)
        return 0
    if resp.status_code >= 400:
        return 0

    payload = resp.json()
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    downloads = int(data.get("last_week", 0) or 0)
    cache_set(data_key, {"downloads": downloads}, ttl_hours=24)
    return downloads


def fetch_all_downloads() -> None:
    init_db()
    with get_conn() as conn:
        tools = conn.execute(
            """
            SELECT canonical_name, ecosystem, npm_package, pypi_package, usage_model
            FROM tools
            ORDER BY canonical_name
            """
        ).fetchall()
        latest_snapshot = conn.execute(
            "SELECT MAX(snapshot_date) AS d FROM tool_snapshots"
        ).fetchone()["d"]
        if not latest_snapshot:
            latest_snapshot = date.today().isoformat()

        for tool in tools:
            canonical = tool["canonical_name"]
            ecosystem = tool["ecosystem"]
            npm_pkg = (tool["npm_package"] or "").strip()
            pypi_pkg = (tool["pypi_package"] or "").strip()

            downloads = 0
            source = None

            # Standalone-first tools are valid signals from repo adoption, but registry
            # downloads are not a strong indicator for them.
            if _is_standalone(tool):
                source = None
                downloads = 0
            elif ecosystem == "npm":
                package = npm_pkg or canonical
                downloads = fetch_npm_downloads(package)
                source = "npm"
            elif ecosystem == "pypi":
                package = pypi_pkg or canonical
                downloads = fetch_pypi_downloads(package)
                source = "pypi"

            if source:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO download_snapshots
                    (canonical_name, snapshot_date, weekly_downloads, source, fetched_at)
                    VALUES (?, ?, ?, ?, datetime('now'))
                    """,
                    (canonical, latest_snapshot, int(downloads), source),
                )
                conn.execute(
                    """
                    UPDATE tool_snapshots
                    SET weekly_downloads = ?, downloads_source = ?
                    WHERE canonical_name = ? AND snapshot_date = ?
                    """,
                    (int(downloads), source, canonical, latest_snapshot),
                )
                source_label = source
            else:
                conn.execute(
                    """
                    UPDATE tool_snapshots
                    SET weekly_downloads = 0, downloads_source = NULL
                    WHERE canonical_name = ? AND snapshot_date = ?
                    """,
                    (canonical, latest_snapshot),
                )
                source_label = "no registry"

            print(f"  {canonical}: {downloads:,} weekly downloads ({source_label})")
            time.sleep(0.5)

        conn.commit()
    print("Downloads fetch complete.")


def main() -> None:
    fetch_all_downloads()


if __name__ == "__main__":
    main()
