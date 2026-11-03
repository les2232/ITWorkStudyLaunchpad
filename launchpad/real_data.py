"""Explicit real-user database provisioning and new-file recovery operations.

No helper defaults to the repository database or creates data during web startup.
All account mappings are separate, explicit operator actions.
"""
from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import quote

from .accounts import init_accounts_schema, revoke_all_sessions, validate_accounts_database
from .storage import DEFAULT_DB_PATH, add_help_request_status_column, init_db, utc_now
from .checklist_answers import add_checklist_answers_table, validate_checklist_answers_table

# Version 2 adds help-request status; version 3 adds Day 1 reflection answers.
# Existing files are never upgraded in place: migration creates a NEW copy.
REAL_SCHEMA_VERSION = 3
BASE_TABLES = frozenset({
    "students", "assessment_results", "module_progress", "module_quiz_results",
    "checklist_progress", "activity_progress", "scenario_attempts", "stuck_reports",
})
ACCOUNT_TABLES = frozenset({"accounts", "mentor_assignments", "auth_sessions", "access_audit"})
ALLOWED_TABLES = BASE_TABLES | ACCOUNT_TABLES | {"checklist_answers", "real_dataset_metadata", "sqlite_sequence"}


class RealDataError(ValueError):
    """The explicitly requested operation could not be performed safely."""


def real_database_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.resolve() != path or path.suffix != ".sqlite":
        raise RealDataError("database must be a canonical absolute .sqlite path without symlinks")
    if path == DEFAULT_DB_PATH.resolve():
        raise RealDataError("the default prototype database is never a real-user target")
    if not path.parent.is_dir():
        raise RealDataError("database parent directory must already exist")
    if path.exists() and not path.is_file():
        raise RealDataError("database path must name a regular file")
    return path


def _readonly(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(f"file:{quote(str(path), safe='/')}?mode=ro", uri=True)
    db.execute("PRAGMA query_only = ON")
    return db


def assert_non_real_database(value: str | Path) -> None:
    """Refuse a real-user dataset before an unauthenticated mode can open it.

    Missing ordinary databases remain eligible for normal local initialization.
    Existing files are inspected through a read-only connection, including the
    committed WAL view. Even a partial real schema must never become demo data.
    """
    path = Path(value)
    try:
        if not path.exists():
            return
        protected = sorted(ACCOUNT_TABLES | {"real_dataset_metadata"})
        placeholders = ",".join("?" for _ in protected)
        with closing(_readonly(path.absolute())) as db:
            found = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') "
                f"AND lower(name) IN ({placeholders}) LIMIT 1", protected,
            ).fetchone()
        if found:
            raise RealDataError("Real-user account data requires authenticated real-user mode.")
    except (sqlite3.DatabaseError, OSError) as exc:
        raise RealDataError("Cannot safely verify the existing database for local/demo mode.") from exc


def validate_real_database(value: str | Path, *, schema_version: int = REAL_SCHEMA_VERSION) -> dict[str, object]:
    """Validate recognized real-user data without initializing or rewriting it."""
    if schema_version not in (1, 2, 3):
        raise RealDataError("unsupported real-user schema version")
    path = real_database_path(value)
    if not path.is_file():
        raise RealDataError("real-user database is missing; provision explicitly or restore it")
    try:
        with closing(_readonly(path)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = BASE_TABLES | ACCOUNT_TABLES | {"real_dataset_metadata"}
            allowed = ALLOWED_TABLES
            if schema_version >= 3:
                required = required | {"checklist_answers"}
            else:
                allowed = allowed - {"checklist_answers"}
            if not required <= tables or tables - allowed:
                raise RealDataError("database is not the supported real-user schema")
            marker = db.execute(
                "SELECT schema_version, dataset_id FROM real_dataset_metadata WHERE singleton=1"
            ).fetchone()
            if not marker or marker[0] != schema_version or not isinstance(marker[1], str) or len(marker[1]) != 32:
                raise RealDataError("real-user database marker is invalid or unsupported")
            help_columns = {row[1] for row in db.execute("PRAGMA table_info(stuck_reports)")}
            if ("resolved_at" in help_columns) != (schema_version >= 2):
                raise RealDataError("real-user help-request columns do not match the schema version")
            if schema_version >= 3:
                validate_checklist_answers_table(db)
            if db.execute("SELECT count(*) FROM real_dataset_metadata").fetchone()[0] != 1:
                raise RealDataError("real-user database marker is invalid")
            if db.execute("PRAGMA quick_check").fetchone() != ("ok",) or db.execute("PRAGMA foreign_key_check").fetchone():
                raise RealDataError("real-user database integrity validation failed")
        validate_accounts_database(path)
    except (sqlite3.DatabaseError, OSError, ValueError) as exc:
        if isinstance(exc, RealDataError):
            raise
        raise RealDataError("real-user database validation failed") from exc
    return {"schema_version": marker[0], "dataset_id": marker[1]}


def _claim_new(path: Path) -> tuple[int, int]:
    if any(os.path.lexists(Path(f"{path}{suffix}")) for suffix in ("", "-wal", "-shm", "-journal")):
        raise RealDataError("destination and SQLite sidecars must not exist")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        return info.st_dev, info.st_ino
    finally:
        os.close(fd)


def _remove_owned_failure(path: Path, identity: tuple[int, int]) -> None:
    # Never remove an existing artifact or a replacement of our new file.
    if path.exists() and not path.is_symlink():
        info = path.stat()
        if (info.st_dev, info.st_ino) == identity:
            path.unlink()


def _flush(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def initialize_real_database(value: str | Path) -> Path:
    """Create a NEW empty dataset; never seed personas or adopt legacy records."""
    path = real_database_path(value)
    identity = _claim_new(path)
    try:
        init_db(path)
        init_accounts_schema(path)
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE real_dataset_metadata (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                schema_version INTEGER NOT NULL,
                dataset_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")
            db.execute("INSERT INTO real_dataset_metadata VALUES (1, ?, ?, ?)",
                       (REAL_SCHEMA_VERSION, secrets.token_hex(16), utc_now()))
        validate_real_database(path)
        _flush(path)
        return path
    except Exception:
        _remove_owned_failure(path, identity)
        raise


def migrate_real_database(source: str | Path, destination: str | Path, *, timeout: float = 30) -> Path:
    """Write a NEW version-3 copy of a version-1 or version-2 dataset.

    The source is unchanged. Existing records, account mappings, grants and
    sessions are copied as-is. Version-1 help requests start as Open; version-2
    help-request status is preserved. Reflection answers start empty.
    """
    source_path = real_database_path(source)
    target = real_database_path(destination)
    try:
        with closing(_readonly(source_path)) as source_db:
            row = source_db.execute(
                "SELECT schema_version FROM real_dataset_metadata WHERE singleton=1"
            ).fetchone()
        source_version = row[0] if row else None
    except (sqlite3.DatabaseError, OSError) as exc:
        raise RealDataError("migration source is not a recognized real-user dataset") from exc
    if source_version not in (1, 2):
        raise RealDataError("migration requires a version-1 or version-2 source")
    validate_real_database(source_path, schema_version=source_version)
    if timeout <= 0:
        raise RealDataError("migration timeout must be positive")
    identity = _claim_new(target)
    deadline = time.monotonic() + timeout

    def check_deadline(status: int, remaining: int, total: int) -> None:
        if time.monotonic() > deadline:
            raise RealDataError("migration copy timed out; retry during a quiet period")

    try:
        with closing(_readonly(source_path)) as original, closing(sqlite3.connect(target)) as copied:
            original.backup(copied, pages=128, progress=check_deadline, sleep=0.05)
        validate_real_database(target, schema_version=source_version)
        with closing(sqlite3.connect(target)) as copied:
            with copied:
                add_help_request_status_column(copied)
                add_checklist_answers_table(copied)
                copied.execute("UPDATE real_dataset_metadata SET schema_version=? WHERE singleton=1", (REAL_SCHEMA_VERSION,))
        validate_real_database(target)
        _flush(target)
        return target
    except (sqlite3.DatabaseError, OSError, ValueError):
        _remove_owned_failure(target, identity)
        raise RealDataError("migration refused; check the version-1 or version-2 source and a new destination") from None


def copy_real_snapshot(source: str | Path, destination: str | Path, *, restore: bool = False, timeout: float = 30) -> Path:
    """Copy a consistent snapshot; restore invalidates sessions in the NEW copy.

    Backups retain records, account bindings and scoped grants. Neither operation
    overwrites or migrates a source. Off-host encryption/retention are operator
    responsibilities; a local snapshot alone is not disaster recovery.
    """
    source_path = real_database_path(source)
    target = real_database_path(destination)
    validate_real_database(source_path)
    if timeout <= 0:
        raise RealDataError("snapshot timeout must be positive")
    identity = _claim_new(target)
    deadline = time.monotonic() + timeout

    def check_deadline(status: int, remaining: int, total: int) -> None:
        if time.monotonic() > deadline:
            raise RealDataError("snapshot timed out; retry during a quiet period")

    try:
        with closing(_readonly(source_path)) as original, closing(sqlite3.connect(target)) as copied:
            original.backup(copied, pages=128, progress=check_deadline, sleep=0.05)
        validate_real_database(target)
        if restore:
            revoke_all_sessions(target)
        validate_real_database(target)
        _flush(target)
        return target
    except (sqlite3.DatabaseError, OSError, ValueError):
        _remove_owned_failure(target, identity)
        raise RealDataError("snapshot refused; check source integrity and a new destination") from None
