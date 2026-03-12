from __future__ import annotations

"""
Fetches dependency health data for all tracked tools.
APIs used:
  - deps.dev: release cadence, transitive deps, license
  - OSV: vulnerability/advisory counts

Both APIs are free, no authentication required.
Run after 04_compute_scores.py.
"""

import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import requests

try:
    from scripts.db import cache_get, cache_set, get_conn, init_db
except ModuleNotFoundError:
    from db import cache_get, cache_set, get_conn, init_db

DEPS_DEV_PACKAGE_URL = "https://api.deps.dev/v3/systems/{ecosystem}/packages/{package}"
DEPS_DEV_VERSION_URL = (
    "https://api.deps.dev/v3/systems/{ecosystem}/packages/{package}/versions/{version}"
)
DEPS_DEV_DEPS_URL = (
    "https://api.deps.dev/v3/systems/{ecosystem}/packages/{package}/versions/{version}/dependencies"
)
OSV_QUERY_URL = "https://api.osv.dev/v1/query"
REQUEST_TIMEOUT = 10
PERMISSIVE_LICENSE_PREFIXES = ("MIT", "APACHE", "BSD", "ISC")


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _days_since(published_at: str | None) -> int | None:
    dt = _parse_iso_datetime(published_at)
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return max(0, (now - dt).days)


def _is_prerelease(version: str | None) -> bool:
    if not version:
        return True
    normalized = str(version).strip().lower().lstrip("v")
    if not normalized:
        return True
    if re.search(r"(alpha|beta|rc|pre|preview|dev)", normalized):
        return True
    return "-" in normalized


def _extract_version_text(version_row: Any) -> str | None:
    if isinstance(version_row, dict):
        version_key = version_row.get("versionKey")
        if isinstance(version_key, dict):
            version = version_key.get("version")
            if version:
                return str(version)
        version = version_row.get("version")
        if version:
            return str(version)
    return None


def _select_latest_non_prerelease(versions: list[dict[str, Any]]) -> str | None:
    candidates: list[tuple[datetime, str]] = []
    fallback_default: str | None = None

    for row in versions:
        version = _extract_version_text(row)
        if not version:
            continue
        if row.get("isDefault"):
            fallback_default = version
        if _is_prerelease(version):
            continue
        published_at = _parse_iso_datetime(row.get("publishedAt"))
        if published_at is None:
            published_at = datetime.min.replace(tzinfo=timezone.utc)
        elif published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        candidates.append((published_at, version))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    return fallback_default


def _extract_license(licenses: Any) -> str | None:
    if isinstance(licenses, list) and licenses:
        first = licenses[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            for key in ("spdx", "license", "name"):
                value = first.get(key)
                if value:
                    return str(value)
    if isinstance(licenses, str):
        return licenses
    return None


def _license_is_permissive(license_name: str | None) -> int:
    if not license_name:
        return 0
    normalized = str(license_name).strip().upper()
    for prefix in PERMISSIVE_LICENSE_PREFIXES:
        if normalized.startswith(prefix):
            return 1
    return 0


def _cached_api_json(
    cache_key: str,
    method: str,
    url: str,
    ttl_hours: int,
    payload: dict[str, Any] | None = None,
) -> tuple[Any | None, int, bool]:
    cached = cache_get(cache_key, ttl_hours=ttl_hours)
    if isinstance(cached, dict) and "status_code" in cached:
        return cached.get("payload"), int(cached.get("status_code") or 0), True
    if cached is not None:
        return cached, 200, True

    try:
        if method.upper() == "POST":
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        else:
            response = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        print(f"  -> API request failed [{cache_key}]: {exc}")
        return None, 0, False

    try:
        parsed_payload: Any = response.json()
    except ValueError:
        parsed_payload = {"raw": response.text[:1000]}

    cache_set(
        cache_key,
        {"status_code": int(response.status_code), "payload": parsed_payload},
        ttl_hours=ttl_hours,
    )
    return parsed_payload, int(response.status_code), False


def _parse_cvss_score(score_value: Any) -> float | None:
    if isinstance(score_value, (int, float)):
        return float(score_value)
    if isinstance(score_value, str):
        score = score_value.strip()
        if not score:
            return None
        # Vector-only scores (e.g. CVSS:3.1/...) do not carry numeric base score here.
        if score.upper().startswith("CVSS:"):
            return None
        try:
            return float(score)
        except ValueError:
            return None
    return None


def _classify_osv_vuln(vuln: dict[str, Any]) -> str:
    severities = vuln.get("severity") if isinstance(vuln, dict) else None
    best_score: float | None = None
    if isinstance(severities, list):
        for sev in severities:
            if not isinstance(sev, dict):
                continue
            if str(sev.get("type") or "").upper() != "CVSS_V3":
                continue
            parsed = _parse_cvss_score(sev.get("score"))
            if parsed is None:
                continue
            if best_score is None or parsed > best_score:
                best_score = parsed

    if best_score is None:
        return "low"
    if best_score >= 9.0:
        return "critical"
    if best_score >= 7.0:
        return "high"
    if best_score >= 4.0:
        return "medium"
    if best_score >= 0.1:
        return "low"
    return "low"


def fetch_deps_dev(package_name: str, ecosystem: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "found": 0,
        "last_release_days": None,
        "latest_version": None,
        "direct_dep_count": None,
        "transitive_dep_count": None,
        "license": None,
        "license_is_permissive": 1,
    }
    if not package_name:
        return result

    package_encoded = quote(package_name, safe="")
    package_url = DEPS_DEV_PACKAGE_URL.format(ecosystem=ecosystem, package=package_encoded)
    package_key = f"deps_dev:{ecosystem}:{package_name}"
    package_payload, package_status, _ = _cached_api_json(
        package_key, "GET", package_url, ttl_hours=72
    )
    if package_status == 404:
        print(f"  -> deps.dev package not found: {ecosystem}/{package_name}")
        return result
    if package_status < 200 or package_status >= 300 or not isinstance(package_payload, dict):
        print(f"  -> deps.dev package lookup failed ({package_status}) for {ecosystem}/{package_name}")
        return result

    versions = package_payload.get("versions")
    if not isinstance(versions, list):
        versions = []
    latest_version = _select_latest_non_prerelease(versions)
    if not latest_version:
        print(f"  -> deps.dev has no usable stable version for {ecosystem}/{package_name}")
        return result

    result["found"] = 1
    result["latest_version"] = latest_version

    version_encoded = quote(latest_version, safe="")
    version_url = DEPS_DEV_VERSION_URL.format(
        ecosystem=ecosystem,
        package=package_encoded,
        version=version_encoded,
    )
    version_key = f"deps_dev:{ecosystem}:{package_name}:{latest_version}"
    version_payload, version_status, _ = _cached_api_json(
        version_key, "GET", version_url, ttl_hours=72
    )
    if version_status == 404:
        print(f"  -> deps.dev version not found: {ecosystem}/{package_name}@{latest_version}")
        return result
    if version_status < 200 or version_status >= 300 or not isinstance(version_payload, dict):
        print(
            f"  -> deps.dev version lookup failed ({version_status}) for {ecosystem}/{package_name}@{latest_version}"
        )
        return result

    result["last_release_days"] = _days_since(version_payload.get("publishedAt"))
    license_name = _extract_license(version_payload.get("licenses"))
    result["license"] = license_name
    result["license_is_permissive"] = _license_is_permissive(license_name)
    dependencies = version_payload.get("dependencies")
    if isinstance(dependencies, list):
        result["direct_dep_count"] = len(dependencies)

    deps_url = DEPS_DEV_DEPS_URL.format(
        ecosystem=ecosystem,
        package=package_encoded,
        version=version_encoded,
    )
    deps_key = f"deps_dev:{ecosystem}:{package_name}:{latest_version}:dependencies"
    deps_payload, deps_status, _ = _cached_api_json(deps_key, "GET", deps_url, ttl_hours=72)
    if deps_status == 404:
        result["transitive_dep_count"] = None
    elif 200 <= deps_status < 300 and isinstance(deps_payload, dict):
        nodes = deps_payload.get("nodes")
        if isinstance(nodes, list):
            result["transitive_dep_count"] = len(nodes)
    else:
        print(
            f"  -> deps.dev dependency graph lookup failed ({deps_status}) for {ecosystem}/{package_name}@{latest_version}"
        )

    return result


def fetch_osv(package_name: str, osv_ecosystem: str) -> dict[str, Any]:
    result = {
        "found": 0,
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "total": 0,
    }
    if not package_name:
        return result

    query_payload = {
        "package": {
            "name": package_name,
            "ecosystem": osv_ecosystem,
        }
    }
    cache_key = f"osv:{osv_ecosystem}:{package_name}"
    response_payload, status_code, _ = _cached_api_json(
        cache_key,
        "POST",
        OSV_QUERY_URL,
        ttl_hours=48,
        payload=query_payload,
    )
    if status_code < 200 or status_code >= 300 or not isinstance(response_payload, dict):
        print(f"  -> OSV query failed ({status_code}) for {osv_ecosystem}/{package_name}")
        return result

    result["found"] = 1
    vulns = response_payload.get("vulns")
    if not isinstance(vulns, list) or not vulns:
        return result

    result["total"] = len(vulns)
    for vuln in vulns:
        severity_bucket = _classify_osv_vuln(vuln if isinstance(vuln, dict) else {})
        if severity_bucket == "critical":
            result["critical"] += 1
        elif severity_bucket == "high":
            result["high"] += 1
        elif severity_bucket == "medium":
            result["medium"] += 1
        else:
            result["low"] += 1
    return result


def compute_health_score(
    last_release_days,
    advisory_critical,
    advisory_high,
    advisory_medium,
    transitive_dep_count,
    active_builder_count,  # from tool_snapshots
    license_is_permissive,
    deps_dev_found,
    osv_found,
):
    """
    Computes health score 0-100 (higher = healthier).
    Each deduction is precise and documented.
    Returns (score, tier, reason)
    """
    if not deps_dev_found and not osv_found:
        return 0.0, "Unknown", "No health data available from registries"

    score = 100.0
    deductions = []

    # ── Release cadence ──────────────────────────────────────────
    if last_release_days is not None:
        if last_release_days > 365:
            score -= 30
            deductions.append(f"no release in {last_release_days} days")
        elif last_release_days > 180:
            score -= 15
            deductions.append(f"last release {last_release_days} days ago")
        elif last_release_days > 90:
            score -= 5

    # ── Vulnerabilities ──────────────────────────────────────────
    # Critical: -25 each, capped at -50
    critical_deduction = min(advisory_critical * 25, 50)
    if critical_deduction > 0:
        score -= critical_deduction
        deductions.append(
            f"{advisory_critical} critical vulnerabilit{'y' if advisory_critical == 1 else 'ies'}"
        )

    # High: -8 each, capped at -24
    high_deduction = min(advisory_high * 8, 24)
    if high_deduction > 0:
        score -= high_deduction
        deductions.append(
            f"{advisory_high} high-severity advisor{'y' if advisory_high == 1 else 'ies'}"
        )

    # Medium: -2 each, capped at -10
    medium_deduction = min(advisory_medium * 2, 10)
    if medium_deduction > 0:
        score -= medium_deduction

    # ── Transitive dependency complexity ─────────────────────────
    if transitive_dep_count is not None:
        if transitive_dep_count > 500:
            score -= 20
            deductions.append(f"{transitive_dep_count} transitive dependencies")
        elif transitive_dep_count > 200:
            score -= 10
            deductions.append(f"{transitive_dep_count} transitive dependencies")

    # ── Maintainer concentration ──────────────────────────────────
    if active_builder_count is not None:
        if active_builder_count == 1:
            score -= 15
            deductions.append("single maintainer")
        elif active_builder_count == 0:
            score -= 10
            deductions.append("no active contributors detected")

    # ── License ───────────────────────────────────────────────────
    if license_is_permissive == 0 and deps_dev_found:
        score -= 10
        deductions.append("non-permissive license")

    # Clamp to 0-100
    score = max(0.0, min(100.0, round(score, 1)))

    # ── Tier ──────────────────────────────────────────────────────
    if score >= 75:
        tier = "Healthy"
    elif score >= 50:
        tier = "Monitoring Required"
    elif score >= 25:
        tier = "Declining Health"
    else:
        tier = "Critical Concerns"

    # ── Reason (most impactful deduction) ─────────────────────────
    if deductions:
        reason = f"Main factor: {deductions[0]}"
    elif score >= 90:
        reason = "Active releases, no known vulnerabilities, permissive license"
    else:
        reason = "No significant health issues detected"

    return score, tier, reason


def run() -> None:
    init_db()
    conn = get_conn()

    tools = conn.execute(
        """
        SELECT t.canonical_name, t.display_name, t.ecosystem,
               t.npm_package, t.pypi_package,
               COALESCE(s.active_builder_count, 0) as active_builder_count
        FROM tools t
        LEFT JOIN tool_snapshots s ON t.canonical_name = s.canonical_name
            AND s.snapshot_date = (SELECT MAX(snapshot_date) FROM tool_snapshots)
        ORDER BY t.canonical_name
    """
    ).fetchall()

    total = len(tools)
    for i, tool in enumerate(tools, 1):
        canonical = str(tool["canonical_name"])
        print(f"[{i:3}/{total}] {tool['display_name']}")
        try:
            ecosystem = str(tool["ecosystem"] or "").lower()

            if ecosystem == "npm":
                pkg_name = str(tool["npm_package"] or canonical).strip()
                deps_ecosystem = "npm"
                osv_ecosystem = "npm"
                deps_data = fetch_deps_dev(pkg_name, deps_ecosystem)
            elif ecosystem == "pypi":
                pkg_name = str(tool["pypi_package"] or canonical).strip().lower().replace("_", "-")
                deps_ecosystem = "pypi"
                osv_ecosystem = "PyPI"
                deps_data = fetch_deps_dev(pkg_name, deps_ecosystem)
            elif ecosystem == "cargo":
                # cargo/go: skip deps.dev for now, only OSV
                pkg_name = canonical
                osv_ecosystem = "crates.io"
                deps_data = {
                    "found": 0,
                    "last_release_days": None,
                    "latest_version": None,
                    "direct_dep_count": None,
                    "transitive_dep_count": None,
                    "license": None,
                    "license_is_permissive": 1,
                }
            elif ecosystem == "go":
                # cargo/go: skip deps.dev for now, only OSV
                pkg_name = canonical
                osv_ecosystem = "Go"
                deps_data = {
                    "found": 0,
                    "last_release_days": None,
                    "latest_version": None,
                    "direct_dep_count": None,
                    "transitive_dep_count": None,
                    "license": None,
                    "license_is_permissive": 1,
                }
            else:
                pkg_name = canonical
                osv_ecosystem = ecosystem
                deps_data = {
                    "found": 0,
                    "last_release_days": None,
                    "latest_version": None,
                    "direct_dep_count": None,
                    "transitive_dep_count": None,
                    "license": None,
                    "license_is_permissive": 1,
                }

            # ── OSV ───────────────────────────────────────────────────
            osv_data = fetch_osv(pkg_name, osv_ecosystem) if osv_ecosystem else {
                "found": 0,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "total": 0,
            }

            # ── Compute health score ──────────────────────────────────
            score, tier, reason = compute_health_score(
                last_release_days=deps_data.get("last_release_days"),
                advisory_critical=osv_data.get("critical", 0),
                advisory_high=osv_data.get("high", 0),
                advisory_medium=osv_data.get("medium", 0),
                transitive_dep_count=deps_data.get("transitive_dep_count"),
                active_builder_count=tool["active_builder_count"],
                license_is_permissive=deps_data.get("license_is_permissive", 1),
                deps_dev_found=deps_data.get("found", 0),
                osv_found=osv_data.get("found", 0),
            )

            # ── Upsert to tool_health ─────────────────────────────────
            conn.execute(
                """
                INSERT OR REPLACE INTO tool_health (
                    canonical_name, last_release_days, latest_version,
                    direct_dep_count, transitive_dep_count,
                    license, license_is_permissive,
                    advisory_critical, advisory_high, advisory_medium,
                    advisory_low, advisory_total,
                    health_score, health_tier, health_tier_reason,
                    deps_dev_found, osv_found, fetched_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now')
                )
            """,
                (
                    canonical,
                    deps_data.get("last_release_days"),
                    deps_data.get("latest_version"),
                    deps_data.get("direct_dep_count"),
                    deps_data.get("transitive_dep_count"),
                    deps_data.get("license"),
                    deps_data.get("license_is_permissive", 1),
                    osv_data.get("critical", 0),
                    osv_data.get("high", 0),
                    osv_data.get("medium", 0),
                    osv_data.get("low", 0),
                    osv_data.get("total", 0),
                    score,
                    tier,
                    reason,
                    deps_data.get("found", 0),
                    osv_data.get("found", 0),
                ),
            )

            conn.commit()

            tier_symbol = {
                "Healthy": "✅",
                "Monitoring Required": "⚠️",
                "Declining Health": "🔴",
                "Critical Concerns": "❌",
                "Unknown": "❓",
            }.get(tier, "❓")
            print(f"         {tier_symbol} {tier} (score: {score}) — {reason}")
        except Exception as exc:
            print(f"  -> Error processing {canonical}: {exc}")
        # Respectful rate limiting across deps.dev + OSV per tool.
        time.sleep(1.0)

    conn.close()
    print(f"\n✅ Health enrichment complete for {total} tools.")


def main() -> None:
    run()


if __name__ == "__main__":
    main()
