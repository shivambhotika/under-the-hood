from __future__ import annotations

import os
import traceback

from flask import Flask, jsonify

_BOOT_ERROR = None

try:
    from web.app import app as app
except Exception:
    _BOOT_ERROR = traceback.format_exc()
    app = Flask(__name__)

    @app.get("/")
    def emergency_home():
        return (
            "Under The Hood is temporarily in recovery mode. "
            "Check /_boot_error for diagnostics.",
            503,
        )

    @app.get("/healthz")
    def emergency_healthz():
        return jsonify({"ok": False, "boot_error": "import_failed"}), 500

    @app.get("/_boot_error")
    def boot_error():
        return f"<pre>{_BOOT_ERROR}</pre>", 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=False)
