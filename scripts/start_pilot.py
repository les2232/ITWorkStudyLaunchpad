"""Fail-closed startup for the invited, synthetic-only hosted pilot."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Mapping

from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launchpad.demo import (  # noqa: E402
    DemoDataError,
    prepare_demo_database,
    safe_demo_database_path,
    validate_demo_database,
)
from launchpad.pilot import configure_pilot  # noqa: E402


def prepare_runtime(environ: Mapping[str, str]) -> Path:
    """Validate config before touching only the explicitly selected pilot data."""
    if environ.get("LAUNCHPAD_PILOT_MODE") != "1" or environ.get("LAUNCHPAD_DEMO_MODE") != "1":
        raise DemoDataError("hosted startup requires PILOT_MODE=1 and DEMO_MODE=1")
    # Use the application validator before bootstrap; never maintain a weaker copy.
    validation_app = Flask("pilot-startup-validation")
    validation_app.config.update(
        LAUNCHPAD_PILOT_MODE=True,
        LAUNCHPAD_DEMO_MODE=True,
        SECRET_KEY=environ.get("LAUNCHPAD_SECRET_KEY", ""),
        LAUNCHPAD_PILOT_USERNAME=environ.get("LAUNCHPAD_PILOT_USERNAME", ""),
        LAUNCHPAD_PILOT_PASSWORD_HASH=environ.get("LAUNCHPAD_PILOT_PASSWORD_HASH", ""),
        LAUNCHPAD_TRUSTED_HOSTS=environ.get("LAUNCHPAD_TRUSTED_HOSTS") or environ.get("RENDER_EXTERNAL_HOSTNAME", ""),
    )
    try:
        configure_pilot(validation_app)
    except ValueError as exc:
        raise DemoDataError(str(exc)) from exc

    directory = Path(environ.get("LAUNCHPAD_DATA_DIR", ""))
    if not directory.is_absolute() or directory.resolve() != directory or not directory.is_dir():
        raise DemoDataError("LAUNCHPAD_DATA_DIR must be an existing canonical absolute directory")
    if Path("/tmp") not in directory.parents:
        raise DemoDataError("synthetic pilot storage must be a dedicated directory below /tmp")
    if environ.get("RENDER") == "true" and not os.path.ismount(directory):
        raise DemoDataError("Render pilot storage must be the mounted persistent disk")
    database = safe_demo_database_path(environ.get("LAUNCHPAD_DB_PATH", ""))
    if database.parent != directory:
        raise DemoDataError("pilot database must be directly inside LAUNCHPAD_DATA_DIR")
    marker = directory / ".launchpad-initialized"
    if marker.is_symlink():
        raise DemoDataError("initialization marker must not be a symlink")
    if database.exists():
        validate_demo_database(database)
    else:
        if marker.exists():
            raise DemoDataError("initialized pilot database is missing; restore rather than reseed")
        if environ.get("LAUNCHPAD_INITIALIZE_DEMO") != "1":
            raise DemoDataError("first startup needs explicit LAUNCHPAD_INITIALIZE_DEMO=1")
        # Claim initialization first. Failed/interrupted preparation cannot silently reseed.
        with marker.open("x", encoding="utf-8") as handle:
            handle.write("Synthetic pilot initialized; preserve this marker during restores.\n")
        marker.chmod(0o600)
        prepare_demo_database(database)
    if not marker.exists():
        with marker.open("x", encoding="utf-8") as handle:
            handle.write("Existing synthetic pilot validated.\n")
        marker.chmod(0o600)
    return database


def main() -> int:
    os.umask(0o077)
    try:
        # Require the WSGI dependency before any first-run database creation.
        if importlib.util.find_spec("gunicorn") is None:
            raise DemoDataError("install requirements-pilot.txt before hosted startup")
        prepare_runtime(os.environ)
    except (DemoDataError, OSError, ValueError):
        print("Pilot startup refused. Check required configuration, disk mount and synthetic database; see docs/pilot_deployment.md.", file=sys.stderr)
        return 2
    os.chdir(PROJECT_ROOT)
    os.execv(sys.executable, [sys.executable, "-m", "gunicorn", "--config", "deploy/gunicorn.conf.py", "app:app"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
