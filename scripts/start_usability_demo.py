"""Supervised synthetic usability demo; loopback only, no directory or TLS keys.

Only an explicitly prepared, private, guarded demo database is accepted.
This launcher never provisions/adopts data or changes any real-auth mode.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import secrets
import stat
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launchpad import create_app
from launchpad.demo import DemoDataError, safe_demo_database_path, validate_demo_database
from werkzeug.serving import WSGIRequestHandler, make_server


def _private(path: Path, *, directory: bool = False) -> None:
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (path.resolve() != path or not kind(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
            or (not directory and info.st_nlink != 1)):
        raise DemoDataError("Use an operator-owned private directory and regular private demo files.")


def prepare_runtime(db_path: Path):
    database = safe_demo_database_path(db_path)
    _private(database.parent, directory=True)
    _private(database)
    validate_demo_database(database)
    # Stable across manual restarts; never use another application's signing key.
    key_path = database.with_suffix(".session-key")
    if not os.path.lexists(key_path):
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(secrets.token_urlsafe(48))
    _private(key_path)
    if key_path.stat().st_size != 64:
        raise DemoDataError("The demo signing key is missing or invalid; do not silently replace it.")
    signing_key = key_path.read_text(encoding="ascii")
    if not re.fullmatch(r"[A-Za-z0-9_-]{64}", signing_key):
        raise DemoDataError("The existing demo signing key is invalid; do not silently replace it.")
    # Explicit config overrides any inherited production/demo environment.
    # This affects only this process, never files or the production launcher.
    app = create_app({
        "LAUNCHPAD_DB_PATH": str(database), "LAUNCHPAD_DEMO_MODE": True,
        "LAUNCHPAD_REAL_MODE": False, "LAUNCHPAD_PILOT_MODE": False,
        "LAUNCHPAD_AD_SESSION_POLICY": "revalidate",
        "SECRET_KEY": signing_key, "DEBUG": False, "TESTING": False,
        "TRUSTED_HOSTS": ["127.0.0.1", "localhost"],
        "SESSION_COOKIE_NAME": "launchpad_usability_demo",
        "SESSION_COOKIE_SECURE": False, "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Strict",
        "MAX_CONTENT_LENGTH": 64 * 1024,
    })

    @app.after_request
    def local_demo_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    return app


class MinimalRequestHandler(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        # No paths, query strings, cookies or invented answers in request logs.
        self.log("info", "demo response %s", code)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="Existing guarded synthetic .sqlite under private /tmp directory")
    parser.add_argument("--port", type=int, default=8765, help="Loopback port only (default 8765)")
    parser.add_argument("--serve", action="store_true", help="Open a supervised foreground loopback listener; otherwise preflight only")
    args = parser.parse_args(argv)
    if not 1024 <= args.port <= 65535:
        parser.error("Choose an unprivileged loopback port from 1024 through 65535.")
    os.umask(0o077)
    try:
        app = prepare_runtime(args.db)
        if not args.serve:
            print("Synthetic demo preflight passed. No listener or directory connection opened.")
            return 0
        with make_server("127.0.0.1", args.port, app, request_handler=MinimalRequestHandler) as server:
            print(f"TEST DATA ONLY: http://127.0.0.1:{args.port}/ — supervised usability, no real login or records.", flush=True)
            print("VM access requires the operator's authenticated SSH tunnel. Stop with Ctrl-C.", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError):
        print("Demo refused. Check the private synthetic dataset, signing key and loopback port; no automatic reset.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
