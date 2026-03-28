from __future__ import annotations

"""
Computes tool co-installation patterns from tool_repos.
For each pair of tools, counts how many repos use both.
This populates the co_installs table for stack compatibility analysis.
Run after 04_compute_scores.py.
"""

from collections import defaultdict
from itertools import combinations

try:
    from scripts.db import get_conn, init_db
except ModuleNotFoundError:
    from db import get_conn, init_db


def compute_coinstalls() -> None:
    init_db()
    with get_conn() as conn:
        print("Computing co-install pairs...")
        rows = conn.execute(
            """
            SELECT canonical_name, repo_full_name
            FROM tool_repos
            WHERE stars > 0
            ORDER BY repo_full_name, canonical_name
            """
        ).fetchall()

        repo_to_tools: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            repo_to_tools[str(row["repo_full_name"])].add(str(row["canonical_name"]))

        print(f"  Processing {len(repo_to_tools)} repos...")

        pair_counts: dict[tuple[str, str], int] = defaultdict(int)
        for tool_set in repo_to_tools.values():
            if len(tool_set) < 2:
                continue
            for tool_a, tool_b in combinations(sorted(tool_set), 2):
                pair_counts[(tool_a, tool_b)] += 1

        significant_pairs = {pair: count for pair, count in pair_counts.items() if count >= 3}
        print(f"  Found {len(significant_pairs)} significant co-install pairs")

        conn.execute("DELETE FROM co_installs")
        for (tool_a, tool_b), count in significant_pairs.items():
            conn.execute(
                """
                INSERT OR REPLACE INTO co_installs (tool_a, tool_b, shared_repo_count, computed_at)
                VALUES (?, ?, ?, datetime('now'))
                """,
                (tool_a, tool_b, count),
            )
        conn.commit()
        print(f"  → Stored {len(significant_pairs)} co-install pairs")


if __name__ == "__main__":
    compute_coinstalls()
