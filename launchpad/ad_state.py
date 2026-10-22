"""Dedicated, persistent admission limits for password-based directory login.

This is a separate explicitly provisioned database, never a learner database.
It retains only keyed account digests and attempt timestamps. Both successful
and unsuccessful directory calls consume a reservation. Already throttled
requests do not call the directory or add rows. No client IP is trusted.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import hmac
import os
from pathlib import Path
import sqlite3
import stat
import time
from urllib.parse import quote

from .storage import DEFAULT_DB_PATH

ACCOUNT_ATTEMPTS = 5
ACCOUNT_WINDOW_SECONDS = 300
GLOBAL_ATTEMPTS = 50
GLOBAL_WINDOW_SECONDS = 60
MAX_ROWS = 1024
BUSY_TIMEOUT_SECONDS = 2


class ADStateError(ValueError):
    """Admission state is not safe to use; callers must fail closed."""


def _path(value: str | Path, *, must_exist: bool = True) -> Path:
    try:
        path = Path(value)
        if (not path.is_absolute() or path.resolve() != path or path.suffix != ".sqlite"
                or path == DEFAULT_DB_PATH.resolve()):
            raise ADStateError("AD admission storage requires a dedicated canonical .sqlite path.")
        parent = path.parent.stat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_mode & 0o077:
            raise ADStateError("AD admission storage requires a private existing parent directory.")
        if must_exist:
            info = path.stat()
            if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                    or info.st_nlink != 1):
                raise ADStateError("AD admission storage requires a private regular file.")
        return path
    except (OSError, TypeError, RuntimeError):
        raise ADStateError("AD admission storage is unavailable.") from None


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    mode = "ro" if readonly else "rw"
    db = sqlite3.connect(f"file:{quote(str(path), safe='/')}?mode={mode}",
                         uri=True, timeout=BUSY_TIMEOUT_SECONDS)
    if readonly:
        db.execute("PRAGMA query_only = ON")
    return db


def initialize_ad_state(value: str | Path) -> Path:
    """Provision a new private file only; never adopt or alter an existing DB."""
    path = _path(value, must_exist=False)
    try:
        if any(os.path.lexists(f"{path}{suffix}") for suffix in ("", "-wal", "-shm", "-journal")):
            raise ADStateError("AD admission storage and sidecars must not already exist.")
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(descriptor)
        with closing(_connect(path)) as db, db:
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE ad_state_metadata (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    schema_version INTEGER NOT NULL CHECK(schema_version=1)
                );
                INSERT INTO ad_state_metadata VALUES (1, 1);
                CREATE TABLE login_attempts (
                    id INTEGER PRIMARY KEY,
                    account_digest TEXT NOT NULL CHECK(length(account_digest)=64),
                    attempted_at INTEGER NOT NULL CHECK(attempted_at>=0)
                );
                CREATE INDEX login_attempts_time ON login_attempts(attempted_at);
                CREATE INDEX login_attempts_account ON login_attempts(account_digest, attempted_at);
                COMMIT;
            """)
        validate_ad_state(path)
        return path
    except (OSError, sqlite3.DatabaseError):
        # If provisioning fails, preserve the new artifact for operator review.
        # A later startup must reject it; never try to repair an existing file.
        raise ADStateError("AD admission storage could not be provisioned.") from None


def validate_ad_state(value: str | Path) -> None:
    """Read-only startup validation. No schema migration or missing-file repair."""
    path = _path(value)
    try:
        with closing(_connect(path, readonly=True)) as db:
            expected = {
                "ad_state_metadata": {"singleton", "schema_version"},
                "login_attempts": {"id", "account_digest", "attempted_at"},
            }
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables != set(expected):
                raise ADStateError("AD admission storage has an unsupported schema.")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('view', 'trigger') LIMIT 1").fetchone():
                raise ADStateError("AD admission storage has an unsupported schema.")
            for table, columns in expected.items():
                if {row[1] for row in db.execute(f"PRAGMA table_info({table})")} != columns:
                    raise ADStateError("AD admission storage has an unsupported schema.")
            if db.execute("SELECT singleton, schema_version FROM ad_state_metadata").fetchall() != [(1, 1)]:
                raise ADStateError("AD admission storage has an unsupported version.")
            if (db.execute("PRAGMA quick_check").fetchone() != ("ok",)
                    or db.execute("SELECT count(*) FROM login_attempts").fetchone()[0] > MAX_ROWS):
                raise ADStateError("AD admission storage integrity validation failed.")
            for digest, attempted_at in db.execute("SELECT account_digest, attempted_at FROM login_attempts"):
                if (not isinstance(digest, str) or len(digest) != 64
                        or any(char not in "0123456789abcdef" for char in digest)
                        or type(attempted_at) is not int or attempted_at < 0):
                    raise ADStateError("AD admission storage integrity validation failed.")
    except (sqlite3.DatabaseError, OSError):
        raise ADStateError("AD admission storage validation failed.") from None


def reserve_login_attempt(value: str | Path, username_key: str, secret: str | bytes,
                          now: int | None = None) -> bool:
    """Atomically reserve a directory attempt before testing credentials.

    Caller must canonicalize username/UPN aliases to the same account key.
    The sliding-window limits persist across workers and restarts. They are
    fixed defensive defaults, not a replacement for the owner's AD lockout
    policy. Rotating the signing key changes the account digest namespace;
    existing global limits still apply.
    """
    path = _path(value)
    if not isinstance(username_key, str) or not 1 <= len(username_key) <= 320:
        raise ADStateError("AD admission input is invalid.")
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ADStateError("AD admission requires a protected signing key.")
    timestamp = int(time.time()) if now is None else now
    if type(timestamp) is not int or timestamp < 0:
        raise ADStateError("AD admission timestamp is invalid.")
    digest = hmac.new(secret, b"launchpad-ad-login-v1\x00" + username_key.encode("utf-8"), hashlib.sha256).hexdigest()
    try:
        with closing(_connect(path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""DELETE FROM login_attempts WHERE id IN (
                SELECT id FROM login_attempts WHERE attempted_at<=? ORDER BY attempted_at LIMIT ?)
                """, (timestamp - ACCOUNT_WINDOW_SECONDS, MAX_ROWS))
            if db.execute("SELECT count(*) FROM login_attempts").fetchone()[0] >= MAX_ROWS:
                return False
            # A backward wall-clock jump remains restrictive: future-dated rows
            # continue to count, rather than creating an authentication bypass.
            global_count = db.execute("SELECT count(*) FROM login_attempts WHERE attempted_at>?",
                                      (timestamp - GLOBAL_WINDOW_SECONDS,)).fetchone()[0]
            account_count = db.execute("SELECT count(*) FROM login_attempts WHERE account_digest=? AND attempted_at>?",
                                       (digest, timestamp - ACCOUNT_WINDOW_SECONDS)).fetchone()[0]
            if global_count >= GLOBAL_ATTEMPTS or account_count >= ACCOUNT_ATTEMPTS:
                return False
            db.execute("INSERT INTO login_attempts(account_digest, attempted_at) VALUES (?, ?)", (digest, timestamp))
            return True
    except (sqlite3.DatabaseError, OSError):
        raise ADStateError("AD admission is unavailable.") from None
