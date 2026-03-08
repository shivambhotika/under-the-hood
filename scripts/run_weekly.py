import subprocess
import sys
import time
from datetime import datetime

print(f"Under The Hood — Weekly Refresh")
print(f"Started: {datetime.now().isoformat()}")

scripts = [
    ("scripts/04_compute_scores.py",     "Recomputing scores"),
    ("scripts/05_fetch_downloads.py",    "Refreshing downloads"),
    ("scripts/06_fetch_contributors.py", "Refreshing contributors"),
]

for path, description in scripts:
    print(f"\n▶  {description}")
    result = subprocess.run([sys.executable, path], check=False)
    if result.returncode != 0:
        print(f"   ⚠️  {path} failed with code {result.returncode}")
    time.sleep(3)

print(f"\n✅ Done: {datetime.now().isoformat()}")
