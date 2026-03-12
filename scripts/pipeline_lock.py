"""
Simple file-based lock to prevent concurrent pipeline runs.
SQLite is single-writer — two simultaneous runs can cause lock errors.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

LOCK_FILE = Path(__file__).parent.parent / "data" / ".pipeline.lock"


class PipelineLock:
    def __enter__(self):
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        if LOCK_FILE.exists():
            age_hours = (time.time() - LOCK_FILE.stat().st_mtime) / 3600
            if age_hours > 4:
                print(f"  ⚠️  Stale lock found ({age_hours:.1f}h old). Removing.")
                LOCK_FILE.unlink()
            else:
                print(f"  ❌ Pipeline already running (lock age: {age_hours:.1f}h).")
                print(f"     If this is wrong, delete: {LOCK_FILE}")
                sys.exit(1)
        LOCK_FILE.write_text(datetime.now().isoformat())
        print("  🔒 Pipeline lock acquired.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
        print("  🔓 Pipeline lock released.")
        return False
