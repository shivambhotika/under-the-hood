import subprocess
import sys
import time
from datetime import datetime

try:
    from scripts.pipeline_lock import PipelineLock
except ModuleNotFoundError:
    from pipeline_lock import PipelineLock

print(f"Under The Hood — Weekly Refresh")
print(f"Started: {datetime.now().isoformat()}")

scripts = [
    ("scripts/04_compute_scores.py",     "Recomputing scores"),
    ("scripts/05_fetch_downloads.py",    "Refreshing downloads"),
    ("scripts/06_fetch_contributors.py", "Refreshing contributors"),
    ("scripts/08_enrich_health.py",      "Enriching dependency health data"),
    ("scripts/07_validate.py",           "Running post-run validation"),
]

with PipelineLock():
    for path, description in scripts:
        print(f"\n▶  {description}")
        if path.endswith("07_validate.py"):
            result = subprocess.run([sys.executable, path, "--run-type", "weekly"], check=False)
        else:
            result = subprocess.run([sys.executable, path], check=False)
        if result.returncode != 0:
            print(f"   ⚠️  {path} failed with code {result.returncode}")
        if path.endswith("07_validate.py"):
            if result.returncode == 2:
                print("❌ Validation FAILED — check pipeline_runs table")
            elif result.returncode == 1:
                print("⚠️  Validation passed with warnings")
            else:
                print("✅ Validation passed cleanly")
        time.sleep(3)

print(f"\n✅ Done: {datetime.now().isoformat()}")
