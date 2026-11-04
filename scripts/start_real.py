"""Fail-closed WSGI startup for explicitly provisioned real-user storage."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
from typing import Mapping

from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launchpad.real_auth import configure_real_security  # noqa: E402
from launchpad.real_data import RealDataError, real_database_path, validate_real_database  # noqa: E402


def prepare_runtime(environ: Mapping[str, str]) -> Path:
    """Validate identity configuration and existing storage; never initialize."""
    if environ.get("LAUNCHPAD_AD_SESSION_POLICY", "revalidate") not in {"revalidate", "signin"}:
        raise RealDataError("production startup cannot use controlled-test session policy; use the isolated test launcher")
    if environ.get("LAUNCHPAD_REAL_MODE") != "1" or any(
        environ.get(key, "0").lower() not in {"0", "false", "no", ""}
        for key in ("LAUNCHPAD_DEMO_MODE", "LAUNCHPAD_PILOT_MODE")
    ):
        raise RealDataError("real startup requires REAL_MODE=1 and demo/pilot modes disabled")
    validator = Flask("real-startup-validation")
    validator.config.update(
        LAUNCHPAD_REAL_MODE=True,
        LAUNCHPAD_DEMO_MODE=False,
        LAUNCHPAD_PILOT_MODE=False,
        SECRET_KEY=environ.get("LAUNCHPAD_SECRET_KEY", ""),
        LAUNCHPAD_TRUSTED_HOSTS=environ.get("LAUNCHPAD_TRUSTED_HOSTS", ""),
        LAUNCHPAD_AUTH_BACKEND=environ.get("LAUNCHPAD_AUTH_BACKEND", "oidc"),
        LAUNCHPAD_SESSION_MAX_HOURS=environ.get("LAUNCHPAD_SESSION_MAX_HOURS", "4"),
        **{key: value for key, value in environ.items() if key.startswith("LAUNCHPAD_AD_")},
        **{key: environ.get(key, "") for key in (
            "LAUNCHPAD_OIDC_ISSUER", "LAUNCHPAD_OIDC_CLIENT_ID",
            "LAUNCHPAD_OIDC_CLIENT_SECRET", "LAUNCHPAD_OIDC_REDIRECT_URI",
        )},
    )
    configure_real_security(validator)
    directory = Path(environ.get("LAUNCHPAD_DATA_DIR", ""))
    if not directory.is_absolute() or directory.resolve() != directory or not directory.is_dir():
        raise RealDataError("LAUNCHPAD_DATA_DIR must be an existing canonical absolute directory")
    if environ.get("RENDER") == "true" and not os.path.ismount(directory):
        raise RealDataError("Render real-user storage must be the mounted persistent disk")
    database = real_database_path(environ.get("LAUNCHPAD_DB_PATH", ""))
    if database.parent != directory:
        raise RealDataError("real-user database must be directly inside LAUNCHPAD_DATA_DIR")
    validate_real_database(database)
    return database


def main() -> int:
    os.umask(0o077)
    try:
        if any(importlib.util.find_spec(name) is None for name in ("gunicorn", "authlib", "ldap3")):
            raise RealDataError("install requirements-real.txt before real-user startup")
        prepare_runtime(os.environ)
    except (OSError, ValueError):
        print("Real-user startup refused. Check approved identity configuration, persistent storage and the provisioned database; see docs/real_user_operations.md.", file=sys.stderr)
        return 2
    os.chdir(PROJECT_ROOT)
    os.execv(sys.executable, [sys.executable, "-m", "gunicorn", "--config", "deploy/gunicorn.conf.py", "app:app"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
