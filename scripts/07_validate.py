from __future__ import annotations

import argparse
import time
from datetime import date, datetime

try:
    from scripts.db import get_conn, init_db
except ModuleNotFoundError:
    from db import get_conn, init_db


CHECKS = [
    {
        "name": "Snapshots exist for today",
        "query": "SELECT COUNT(*) FROM tool_snapshots WHERE snapshot_date = date('now')",
        "pass_if": lambda n: n > 0,
        "fail_msg": lambda n: "0 snapshots for today — pipeline may not have run",
        "severity": "failed",
        "format_value": lambda n: f"{int(n)} tools",
    },
    {
        "name": "Snapshot count reasonable",
        "query": "SELECT COUNT(*) FROM tool_snapshots WHERE snapshot_date = date('now')",
        "pass_if": lambda n: n >= 40,
        "fail_msg": lambda n: f"Only {int(n)} snapshots — expected 40+. Some tools may have failed.",
        "severity": "warning",
        "format_value": lambda n: f"{int(n)} snapshots",
    },
    {
        "name": "Download coverage",
        "query": """
            SELECT ROUND(100.0 * SUM(CASE WHEN weekly_downloads > 0 THEN 1 ELSE 0 END) / COUNT(*), 1)
            FROM tool_snapshots s
            JOIN tools t ON s.canonical_name = t.canonical_name
            WHERE s.snapshot_date = date('now')
            AND t.usage_model != 'standalone_first'
        """,
        "pass_if": lambda pct: pct is not None and float(pct) >= 40,
        "fail_msg": lambda pct: f"Only {pct}% of non-standalone tools have download data",
        "severity": "warning",
        "format_value": lambda pct: f"{pct}% coverage",
    },
    {
        "name": "High confidence tools exist",
        "query": "SELECT COUNT(*) FROM tool_snapshots WHERE snapshot_date = date('now') AND confidence_tier = 'High'",
        "pass_if": lambda n: n > 0,
        "fail_msg": lambda n: "No High confidence tools — confidence computation may have failed",
        "severity": "warning",
        "format_value": lambda n: f"{int(n)} tools",
    },
    {
        "name": "Contributors table populated",
        "query": "SELECT COUNT(*) FROM tool_contributors",
        "pass_if": lambda n: n >= 100,
        "fail_msg": lambda n: f"Only {int(n)} contributor rows — expected 100+",
        "severity": "warning",
        "format_value": lambda n: f"{int(n)} rows",
    },
    {
        "name": "Categories computed",
        "query": "SELECT COUNT(*) FROM categories WHERE computed_at >= date('now', '-7 days')",
        "pass_if": lambda n: n > 0,
        "fail_msg": lambda n: "Category insights are stale (older than 7 days)",
        "severity": "warning",
        "format_value": lambda n: f"{int(n)} categories",
    },
    {
        "name": "No data anomaly",
        "query": """
            SELECT COUNT(*) FROM tool_snapshots
            WHERE snapshot_date = date('now') AND total_repos = 0
        """,
        "pass_if": lambda n: n < 10,
        "fail_msg": lambda n: f"{int(n)} tools show 0 repos — possible search failure",
        "severity": "warning",
        "format_value": lambda n: f"{int(n)} zero-repo tools",
    },
]


def _safe_scalar(conn, query: str):
    row = conn.execute(query).fetchone()
    return row[0] if row else None


def run_validation(run_type: str = "manual") -> int:
    init_db()
    started = time.time()
    warnings: list[str] = []
    failures: list[str] = []
    rendered_rows: list[tuple[str, str, str]] = []

    with get_conn() as conn:
        for check in CHECKS:
            value = _safe_scalar(conn, check["query"])
            ok = bool(check["pass_if"](value))
            value_text = check["format_value"](value)
            if ok:
                rendered_rows.append(("✅", check["name"], value_text))
            else:
                if check["severity"] == "failed":
                    failures.append(check["fail_msg"](value))
                    rendered_rows.append(("❌", check["name"], check["fail_msg"](value)))
                else:
                    warnings.append(check["fail_msg"](value))
                    rendered_rows.append(("⚠️", check["name"], check["fail_msg"](value)))

        print("Post-Run Validation Report")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        for icon, name, msg in rendered_rows:
            print(f"{icon}  {name:<32} {msg}")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        if failures:
            status = "failed"
            exit_code = 2
            print(f"Status: FAILED ({len(failures)} hard failure{'s' if len(failures) != 1 else ''})")
        elif warnings:
            status = "warning"
            exit_code = 1
            print(f"Status: WARNING ({len(warnings)} issue{'s' if len(warnings) != 1 else ''} found)")
        else:
            status = "success"
            exit_code = 0
            print("Status: SUCCESS (all checks passed)")

        latest_snapshot = conn.execute(
            "SELECT MAX(snapshot_date) AS d FROM tool_snapshots"
        ).fetchone()["d"]
        if not latest_snapshot:
            latest_snapshot = date.today().isoformat()

        tools_processed = int(
            conn.execute("SELECT COUNT(*) AS c FROM tools").fetchone()["c"] or 0
        )
        snapshots_created = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM tool_snapshots WHERE snapshot_date = ?",
                (latest_snapshot,),
            ).fetchone()["c"]
            or 0
        )
        downloads_fetched = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM tool_snapshots WHERE snapshot_date = ? AND weekly_downloads > 0",
                (latest_snapshot,),
            ).fetchone()["c"]
            or 0
        )
        contributors_fetched = int(
            conn.execute("SELECT COUNT(*) AS c FROM tool_contributors").fetchone()["c"] or 0
        )
        duration_seconds = round(time.time() - started, 2)
        notes = " | ".join(failures + warnings) if (failures or warnings) else ""

        conn.execute(
            """
            INSERT INTO pipeline_runs (
                run_date, run_type, status, duration_seconds,
                tools_processed, snapshots_created, downloads_fetched,
                contributors_fetched, validation_passed, notes, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                date.today().isoformat(),
                run_type,
                status,
                duration_seconds,
                tools_processed,
                snapshots_created,
                downloads_fetched,
                contributors_fetched,
                1 if status in {"success", "warning"} else 0,
                notes,
                datetime.now().isoformat(),
            ),
        )
        conn.commit()

    return exit_code


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-type",
        default="manual",
        choices=["weekly", "manual", "full"],
        help="Pipeline run type to record in pipeline_runs",
    )
    args = parser.parse_args()
    raise SystemExit(run_validation(run_type=args.run_type))


if __name__ == "__main__":
    main()
