"""New, isolated storage for the explicit short-session AD work-study test.

This is not a production fallback, migration or roster importer. Provisioning
is operator-only; validation is read-only and never repairs an existing run.
"""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
from typing import Mapping
from urllib.parse import quote
from uuid import UUID, uuid4

from .accounts import enroll_account
from .ad_state import initialize_ad_state, validate_ad_state
from .real_data import initialize_real_database, validate_real_database

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SESSION_SECONDS = 900
_MARKER_KEYS = frozenset({"kind", "version", "dataset_id", "identity_namespace", "session_seconds", "invented_training_only"})
_CONFIG_KEYS = frozenset({
    "LAUNCHPAD_REAL_MODE", "LAUNCHPAD_DEMO_MODE", "LAUNCHPAD_PILOT_MODE", "LAUNCHPAD_AUTH_BACKEND",
    "LAUNCHPAD_AD_SESSION_POLICY", "LAUNCHPAD_DATA_DIR", "LAUNCHPAD_DB_PATH", "LAUNCHPAD_AD_STATE_PATH",
    "LAUNCHPAD_TRUSTED_HOSTS", "LAUNCHPAD_AD_HOST", "LAUNCHPAD_AD_PORT", "LAUNCHPAD_AD_CA_FILE",
    "LAUNCHPAD_AD_DOMAIN", "LAUNCHPAD_AD_BASE_DN", "LAUNCHPAD_AD_GROUP_DN", "LAUNCHPAD_AD_GROUP_POLICY",
    "LAUNCHPAD_AD_IDENTITY_NAMESPACE",
})


class ControlledTestError(ValueError):
    """A controlled test operation is unsafe or incompletely configured."""


def _private(path: Path, *, directory: bool = False) -> None:
    info = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (path.resolve() != path or not expected(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
            or (not directory and info.st_nlink != 1)):
        raise ControlledTestError("Controlled test paths must be canonical, private and owned by the operator.")


def run_directory(run_id: str) -> Path:
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", run_id):
        raise ControlledTestError("Use a short non-personal lowercase run identifier.")
    root = PROJECT_ROOT / "work" / "controlled-work-study"
    if root.resolve() != root:
        raise ControlledTestError("Controlled test storage cannot traverse symlinks.")
    return root / run_id


def _json(path: Path) -> dict:
    _private(path)
    if path.stat().st_size > 16384:
        raise ControlledTestError("Controlled test configuration is too large.")

    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ControlledTestError("Duplicate controlled test configuration key.")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    if not isinstance(value, dict):
        raise ControlledTestError("Controlled test configuration must be an object.")
    return value


def _new_text(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def validate_controlled_storage(config: Mapping, issuer: str) -> dict:
    """Read-only validation of an isolated dataset and its AD identity namespace."""
    try:
        directory = Path(config["LAUNCHPAD_DATA_DIR"])
        if directory != run_directory(directory.name):
            raise ControlledTestError("Controlled tests require their dedicated project staging directory.")
        _private(directory.parent, directory=True)
        _private(directory, directory=True)
        database = directory / "learners.sqlite"
        admission = directory / "ad-security.sqlite"
        if (Path(config["LAUNCHPAD_DB_PATH"]) != database
                or Path(config["LAUNCHPAD_AD_STATE_PATH"]) != admission):
            raise ControlledTestError("Controlled tests require their own fixed database paths.")
        for path in (database, admission):
            _private(path)
            for suffix in ("-wal", "-shm", "-journal"):
                sidecar = Path(f"{path}{suffix}")
                if os.path.lexists(sidecar):
                    _private(sidecar)
        marker = _json(directory / "controlled-test.json")
        namespace = marker.get("identity_namespace")
        if (set(marker) != _MARKER_KEYS or marker["kind"] != "launchpad-controlled-ad-test"
                or type(marker["version"]) is not int or marker["version"] != 1
                or type(marker["session_seconds"]) is not int or marker["session_seconds"] != SESSION_SECONDS
                or marker["invented_training_only"] is not True
                or not isinstance(namespace, str) or str(UUID(namespace)) != namespace or not UUID(namespace).int
                or issuer != f"urn:launchpad:ad:{namespace}"
                or config.get("LAUNCHPAD_AD_IDENTITY_NAMESPACE") != namespace):
            raise ControlledTestError("Controlled test marker or identity namespace does not match.")
        metadata = validate_real_database(database)
        if marker["dataset_id"] != metadata["dataset_id"]:
            raise ControlledTestError("Controlled test marker does not identify this dataset.")
        validate_ad_state(admission)
        with closing(sqlite3.connect(f"file:{quote(str(database), safe='/')}?mode=ro", uri=True)) as db:
            db.execute("PRAGMA query_only = ON")
            if db.execute("SELECT 1 FROM accounts WHERE issuer != ? OR role NOT IN ('learner','mentor') LIMIT 1", (issuer,)).fetchone():
                raise ControlledTestError("Controlled tests require explicitly enrolled AD learners and mentors in this namespace.")
            if db.execute("SELECT 1 FROM students s WHERE NOT EXISTS (SELECT 1 FROM accounts a WHERE a.learner_id=s.id AND a.role='learner') LIMIT 1").fetchone():
                raise ControlledTestError("Unbound or imported learner rows are not controlled test storage.")
        return marker
    except (OSError, KeyError, TypeError, AttributeError, sqlite3.DatabaseError, ValueError) as exc:
        if isinstance(exc, ControlledTestError):
            raise
        raise ControlledTestError("Controlled test storage is missing, unsafe or incompatible.") from None


def load_run_config(run_id: str) -> dict:
    """Read local non-secret inputs; reject any password or unrecognized setting."""
    directory = run_directory(run_id)
    _private(directory.parent, directory=True)
    _private(directory, directory=True)
    config = _json(directory / "config.json")
    if (set(config) != _CONFIG_KEYS or config["LAUNCHPAD_REAL_MODE"] is not True
            or config["LAUNCHPAD_DEMO_MODE"] is not False or config["LAUNCHPAD_PILOT_MODE"] is not False
            or config["LAUNCHPAD_AUTH_BACKEND"] != "ad"
            or config["LAUNCHPAD_AD_SESSION_POLICY"] != "controlled_test"
            or config["LAUNCHPAD_DATA_DIR"] != str(directory)):
        raise ControlledTestError("Controlled test configuration must explicitly select the isolated mode.")
    issuer = "urn:launchpad:ad:" + str(config["LAUNCHPAD_AD_IDENTITY_NAMESPACE"])
    validate_controlled_storage(config, issuer)
    return config


def initialize_controlled_run(run_id: str) -> Path:
    """Provision a NEW empty run, stable signing key and incomplete local config."""
    directory = run_directory(run_id)
    work = PROJECT_ROOT / "work"
    if not work.exists():
        work.mkdir(mode=0o700)
    if not work.is_dir() or work.resolve() != work:
        raise ControlledTestError("Project work directory must be a canonical directory.")
    if not directory.parent.exists():
        directory.parent.mkdir(mode=0o700)
    _private(directory.parent, directory=True)
    # Exclusive directory creation refuses every existing run, even an empty one.
    directory.mkdir(mode=0o700)
    _private(directory, directory=True)
    previous_umask = os.umask(0o077)
    try:
        database = initialize_real_database(directory / "learners.sqlite")
        admission = initialize_ad_state(directory / "ad-security.sqlite")
        namespace = str(uuid4())
        marker = {
            "kind": "launchpad-controlled-ad-test", "version": 1,
            "dataset_id": validate_real_database(database)["dataset_id"],
            "identity_namespace": namespace, "session_seconds": SESSION_SECONDS,
            "invented_training_only": True,
        }
        template = json.loads((PROJECT_ROOT / "deploy" / "controlled-test.example.json").read_text(encoding="utf-8"))
        template.update({
            "LAUNCHPAD_DATA_DIR": str(directory), "LAUNCHPAD_DB_PATH": str(database),
            "LAUNCHPAD_AD_STATE_PATH": str(admission), "LAUNCHPAD_AD_IDENTITY_NAMESPACE": namespace,
            "LAUNCHPAD_AD_CA_FILE": str(PROJECT_ROOT / "work" / "ad-ca-review" / "launchpad-ad-ca.pem"),
        })
        _new_text(directory / "controlled-test.json", json.dumps(marker, indent=2) + "\n")
        _new_text(directory / "config.json", json.dumps(template, indent=2) + "\n")
        _new_text(directory / "signing-key.txt", secrets.token_urlsafe(48) + "\n")
        load_run_config(run_id)
        return directory
    finally:
        os.umask(previous_umask)


def enroll_controlled_account(run_id: str, subject: str, label: str, role: str = "learner") -> dict:
    config = load_run_config(run_id)
    if role not in {"learner", "mentor"}:
        raise ControlledTestError("Controlled test enrollment supports learners and assigned mentors only.")
    issuer = "urn:launchpad:ad:" + config["LAUNCHPAD_AD_IDENTITY_NAMESPACE"]
    previous_umask = os.umask(0o077)
    try:
        return enroll_account(issuer, subject, label, role, db_path=config["LAUNCHPAD_DB_PATH"])
    finally:
        os.umask(previous_umask)


def runtime_config(run_id: str) -> dict:
    config = load_run_config(run_id)
    key_path = run_directory(run_id) / "signing-key.txt"
    _private(key_path)
    if key_path.stat().st_size > 256:
        raise ControlledTestError("Controlled test signing key is invalid.")
    key = key_path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{64}", key):
        raise ControlledTestError("Controlled test signing key is invalid.")
    config["SECRET_KEY"] = key
    # Explicit empty lookup values prevent inheriting a production bind secret.
    config["LAUNCHPAD_AD_LOOKUP_USERNAME"] = ""
    config["LAUNCHPAD_AD_LOOKUP_PASSWORD"] = ""
    config["LAUNCHPAD_AD_REVALIDATE_SECONDS"] = ""
    return config
