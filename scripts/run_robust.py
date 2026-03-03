import os
import subprocess
import sys
import time

scripts = [
    ("01_seed_tools.py", "Seeding tool universe"),
    ("05_robust_repo_scrape.py", "Robust repo-first scraping (discovery + manifest parsing)"),
    ("04_compute_scores.py", "Computing scores and insights"),
]

print("\n🔧 Under The Hood — Robust Pipeline")
print("=" * 50)

for filename, description in scripts:
    path = os.path.join("scripts", filename)
    print(f"\n▶  {description}")
    print(f"   Running: {path}")
    result = subprocess.run([sys.executable, path], check=False)
    if result.returncode != 0:
        print(f"   ⚠️  Exited with code {result.returncode}. Continuing...")
    time.sleep(2)

print("\n✅ Robust pipeline complete. Run: python3 -m flask --app web.app run --host 0.0.0.0 --port 8000")
