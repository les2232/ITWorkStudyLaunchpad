"""Snapshot or restore guarded synthetic data into a NEW file; never overwrite."""

from __future__ import annotations

import argparse
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import time
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launchpad.demo import (  # noqa: E402
    DEMO_DATASET_ID,
    DEMO_SCHEMA_VERSION,
    DemoDataError,
    safe_demo_database_path,
    validate_demo_database,
)


def copy_snapshot(source: str | Path, destination: str | Path, *, timeout: float = 30) -> Path:
    """Use SQLite's consistent backup API, including any committed journal data.

    Both paths must satisfy the existing synthetic-only /tmp guard. The source
    is opened read-only; an existing destination or sidecar is always refused.
    Restore calls this same operation and requires switching configuration later.
    """
    source_path = safe_demo_database_path(source)
    target = safe_demo_database_path(destination)
    if not source_path.is_file():
        raise DemoDataError("source must be an existing synthetic database")
    if timeout <= 0:
        raise DemoDataError("backup timeout must be positive")
    if any(os.path.lexists(Path(f"{target}{suffix}")) for suffix in ("", "-journal", "-wal", "-shm")):
        raise DemoDataError("destination and its SQLite sidecars must not exist")
    created_identity = None
    deadline = time.monotonic() + timeout

    def check_deadline(status: int, remaining: int, total: int) -> None:
        if time.monotonic() > deadline:
            raise DemoDataError("snapshot timed out; retry when the pilot is quiet")

    try:
        uri = f"file:{quote(str(source_path), safe='/')}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=timeout)) as source_db:
            source_db.execute("PRAGMA query_only = ON")
            marker = source_db.execute(
                "SELECT dataset_id, schema_version FROM demo_dataset_metadata WHERE singleton = 1"
            ).fetchone()
            if marker != (DEMO_DATASET_ID, DEMO_SCHEMA_VERSION):
                raise DemoDataError("source is not a recognized synthetic dataset")
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            created_identity = (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino)
            os.close(descriptor)
            with closing(sqlite3.connect(target)) as target_db:
                source_db.backup(target_db, pages=128, progress=check_deadline, sleep=0.05)
        validate_demo_database(target)
        with target.open("rb") as handle:
            os.fsync(handle.fileno())
        return target
    except (sqlite3.DatabaseError, OSError, DemoDataError) as exc:
        # Only remove the incomplete file created by this invocation, never source.
        if created_identity is not None and target.exists() and not target.is_symlink():
            info = target.stat()
            if (info.st_dev, info.st_ino) == created_identity:
                target.unlink()
        if isinstance(exc, DemoDataError):
            raise
        raise DemoDataError("snapshot refused; source must be readable synthetic data and destination must be new") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("backup", "restore"))
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        target = copy_snapshot(args.source, args.destination)
    except DemoDataError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    print(f"Verified synthetic snapshot created: {target}")
    if args.command == "restore":
        print("Existing data was not replaced. Stop participant traffic, set LAUNCHPAD_DB_PATH to this file, and restart.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
