"""Explicit account bindings and revocable sessions for the real-user mode.

This layer never discovers a learner by name, trusts identity-provider roles, or
creates accounts during sign-in. Its mutation helpers are operator interfaces,
not HTTP endpoints. Callers must first verify identity with the configured IdP.
All paths are explicit; the existing local/demo database is never accepted.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import UUID

from .storage import DEFAULT_DB_PATH, utc_now


class AccountError(ValueError):
    """An explicit account or session operation could not safely be completed."""


ACCOUNT_TABLES = frozenset({"accounts", "mentor_assignments", "auth_sessions", "access_audit"})
_BASE_TABLES = frozenset({
    "students", "assessment_results", "module_progress", "module_quiz_results",
    "checklist_progress", "activity_progress", "scenario_attempts", "stuck_reports",
})
_ACCOUNT_COLUMNS = {
    "accounts": {"id", "issuer", "subject", "learner_id", "role", "active", "created_at"},
    "mentor_assignments": {"account_id", "learner_id", "created_at"},
    "auth_sessions": {"token_digest", "account_id", "created_at", "expires_at", "last_seen_at", "idle_timeout_seconds", "revoked_at"},
    "access_audit": {"id", "event", "account_id", "learner_id", "created_at"},
}
_EVENTS = frozenset({
    "account_enrolled", "legacy_learner_bound", "account_enabled", "account_disabled",
    "mentor_assigned", "mentor_unassigned", "session_created", "session_revoked", "sessions_revoked",
})


def _database_path(db_path: str | Path) -> Path:
    path = Path(db_path)
    if not path.is_absolute() or path.resolve() != path or not path.is_file():
        raise AccountError("Account storage requires an existing canonical database file.")
    if path == DEFAULT_DB_PATH.resolve():
        raise AccountError("The local prototype database is not an account database.")
    return path


def _connect(db_path: str | Path, *, readonly: bool = False) -> sqlite3.Connection:
    path = _database_path(db_path)
    mode = "ro" if readonly else "rw"
    db = sqlite3.connect(f"file:{quote(str(path), safe='/')}?mode={mode}", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    if readonly:
        db.execute("PRAGMA query_only = ON")
    return db


def init_accounts_schema(db_path: str | Path, *, allow_existing_records: bool = False) -> None:
    """Initialize account tables in a dedicated base DB, never in a demo dataset.

    Existing learner rows require explicit approval of a migration *copy*. They
    remain unbound until bind_existing_learner receives a separately reviewed ID.
    """
    with closing(_connect(db_path)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "demo_dataset_metadata" in tables or not _BASE_TABLES <= tables:
            raise AccountError("Account initialization requires a complete, non-demo base database.")
        if not tables <= _BASE_TABLES | ACCOUNT_TABLES | {"sqlite_sequence", "real_dataset_metadata"}:
            raise AccountError("Account initialization found an unexpected table.")
        if tables & ACCOUNT_TABLES:
            validate_accounts_database(db_path)
            return
        if db.execute("SELECT 1 FROM students LIMIT 1").fetchone() and not allow_existing_records:
            raise AccountError("Existing learner records require an explicitly reviewed migration copy.")
        db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issuer TEXT NOT NULL,
                subject TEXT NOT NULL,
                learner_id INTEGER UNIQUE REFERENCES students(id),
                role TEXT NOT NULL CHECK (role IN ('learner', 'mentor', 'admin')),
                active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                created_at TEXT NOT NULL,
                UNIQUE (issuer, subject),
                CHECK ((role = 'learner' AND learner_id IS NOT NULL)
                    OR (role IN ('mentor', 'admin') AND learner_id IS NULL))
            );
            CREATE TABLE mentor_assignments (
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                learner_id INTEGER NOT NULL REFERENCES students(id),
                created_at TEXT NOT NULL,
                PRIMARY KEY (account_id, learner_id)
            );
            CREATE TABLE auth_sessions (
                token_digest TEXT PRIMARY KEY,
                account_id INTEGER NOT NULL REFERENCES accounts(id),
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                idle_timeout_seconds INTEGER NOT NULL CHECK (idle_timeout_seconds > 0),
                revoked_at INTEGER,
                CHECK (expires_at > created_at),
                CHECK (last_seen_at >= created_at)
            );
            CREATE INDEX auth_sessions_account ON auth_sessions(account_id);
            CREATE TABLE access_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event TEXT NOT NULL,
                account_id INTEGER REFERENCES accounts(id),
                learner_id INTEGER REFERENCES students(id),
                created_at TEXT NOT NULL
            );
            COMMIT;
        """)
    validate_accounts_database(db_path)


def validate_accounts_database(db_path: str | Path) -> None:
    """Read-only schema/integrity checks; dataset ownership is checked separately."""
    with closing(_connect(db_path, readonly=True)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not (_BASE_TABLES | ACCOUNT_TABLES) <= tables or not tables <= (
            _BASE_TABLES | ACCOUNT_TABLES | {"sqlite_sequence", "real_dataset_metadata"}
        ):
            raise AccountError("Database is not a recognized real-user account schema.")
        for table, columns in _ACCOUNT_COLUMNS.items():
            if {row[1] for row in db.execute(f"PRAGMA table_info({table})")} != columns:
                raise AccountError("Account schema columns do not match this release.")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchone():
            raise AccountError("Account database integrity verification failed.")
        if db.execute("""SELECT 1 FROM accounts WHERE active NOT IN (0, 1)
            OR role NOT IN ('learner', 'mentor', 'admin')
            OR (role = 'learner' AND learner_id IS NULL)
            OR (role != 'learner' AND learner_id IS NOT NULL) LIMIT 1""").fetchone():
            raise AccountError("Account database contains an invalid account binding.")
        if db.execute("""SELECT 1 FROM mentor_assignments m JOIN accounts a ON a.id=m.account_id
            WHERE a.role NOT IN ('mentor', 'admin') OR NOT EXISTS (
                SELECT 1 FROM accounts learner WHERE learner.learner_id=m.learner_id
                AND learner.role='learner') LIMIT 1""").fetchone():
            raise AccountError("Account database contains an invalid mentor assignment.")
        for row in db.execute("SELECT issuer, subject FROM accounts"):
            _identity(row["issuer"], row["subject"])


def _identity(issuer: str, subject: str) -> None:
    # AD identities have an explicit, disjoint namespace. Existing HTTPS/OIDC
    # bindings are never reinterpreted when switching authentication providers.
    if isinstance(issuer, str) and issuer.startswith("urn:launchpad:ad:"):
        directory_id = issuer.removeprefix("urn:launchpad:ad:")
        try:
            directory_uuid = UUID(directory_id)
            object_uuid = UUID(subject)
        except (ValueError, TypeError, AttributeError):
            raise AccountError("AD identities require canonical nonzero directory and object UUIDs.") from None
        if (str(directory_uuid) != directory_id or str(object_uuid) != subject
                or not directory_uuid.int or not object_uuid.int):
            raise AccountError("AD identities require canonical nonzero directory and object UUIDs.")
        return
    if not isinstance(issuer, str) or not 1 <= len(issuer) <= 2048 or issuer.strip() != issuer:
        raise AccountError("Identity issuer must be an exact HTTPS issuer.")
    parsed = urlsplit(issuer)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or any(ord(char) < 33 for char in issuer)):
        raise AccountError("Identity issuer must be an exact HTTPS issuer.")
    if (not isinstance(subject, str) or not 1 <= len(subject) <= 255
            or not subject.strip() or any(ord(char) < 32 for char in subject)):
        raise AccountError("Identity subject must be a nonempty opaque identifier.")


def _positive_id(value: int) -> int:
    if type(value) is not int or value < 1:
        raise AccountError("An explicit positive record ID is required.")
    return value


def _audit(db: sqlite3.Connection, event: str, account_id: int | None = None, learner_id: int | None = None) -> None:
    if event not in _EVENTS:
        raise AccountError("Unknown access event.")
    db.execute("INSERT INTO access_audit (event, account_id, learner_id, created_at) VALUES (?, ?, ?, ?)",
               (event, account_id, learner_id, utc_now()))


def _account(db: sqlite3.Connection, account_id: int) -> dict[str, Any] | None:
    row = db.execute("SELECT * FROM accounts WHERE id=?", (_positive_id(account_id),)).fetchone()
    return dict(row) if row else None


def enroll_account(issuer: str, subject: str, display_name: str = "", role: str = "learner", *, db_path: str | Path) -> dict[str, Any]:
    """Operator-only enrollment. Equal names always create independent learners."""
    _identity(issuer, subject)
    if role not in {"learner", "mentor", "admin"}:
        raise AccountError("Choose an explicit supported account role.")
    if role == "learner" and (not isinstance(display_name, str) or not display_name.strip()
            or len(display_name) > 120 or any(ord(char) < 32 for char in display_name)):
        raise AccountError("A learner display name of 1–120 characters is required.")
    try:
        with closing(_connect(db_path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            learner_id = None
            if role == "learner":
                now = utc_now()
                learner_id = db.execute(
                    "INSERT INTO students (display_name, created_at, updated_at) VALUES (?, ?, ?)",
                    (display_name.strip(), now, now),
                ).lastrowid
            account_id = db.execute(
                "INSERT INTO accounts (issuer, subject, learner_id, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (issuer, subject, learner_id, role, utc_now()),
            ).lastrowid
            _audit(db, "account_enrolled", account_id, learner_id)
            return _account(db, account_id)
    except sqlite3.IntegrityError as exc:
        raise AccountError("Enrollment refused: identity or learner binding already exists.") from exc


def bind_existing_learner(issuer: str, subject: str, learner_id: int, *, db_path: str | Path, migration_reviewed: bool = False) -> dict[str, Any]:
    """Bind an explicitly reviewed legacy-copy ID. Never use matching names."""
    if migration_reviewed is not True:
        raise AccountError("Binding existing progress requires explicit migration review.")
    _identity(issuer, subject)
    _positive_id(learner_id)
    try:
        with closing(_connect(db_path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            account_id = db.execute(
                "INSERT INTO accounts (issuer, subject, learner_id, role, created_at) VALUES (?, ?, ?, 'learner', ?)",
                (issuer, subject, learner_id, utc_now()),
            ).lastrowid
            _audit(db, "legacy_learner_bound", account_id, learner_id)
            return _account(db, account_id)
    except sqlite3.IntegrityError as exc:
        raise AccountError("Binding refused: learner is missing, already bound, or identity already exists.") from exc


def get_account_for_identity(issuer: str, subject: str, db_path: str | Path) -> dict[str, Any] | None:
    _identity(issuer, subject)
    with closing(_connect(db_path, readonly=True)) as db:
        row = db.execute("SELECT * FROM accounts WHERE issuer=? AND subject=?", (issuer, subject)).fetchone()
        return dict(row) if row else None


def get_account(account_id: int, db_path: str | Path) -> dict[str, Any] | None:
    with closing(_connect(db_path, readonly=True)) as db:
        return _account(db, account_id)


def set_account_active(account_id: int, active: bool, db_path: str | Path) -> None:
    if type(active) is not bool:
        raise AccountError("Account activation must be explicit.")
    with closing(_connect(db_path)) as db, db:
        account = _account(db, account_id)
        if account is None:
            raise AccountError("Account does not exist.")
        db.execute("UPDATE accounts SET active=? WHERE id=?", (int(active), account_id))
        if not active:
            db.execute("UPDATE auth_sessions SET revoked_at=? WHERE account_id=? AND revoked_at IS NULL", (int(time.time()), account_id))
        _audit(db, "account_enabled" if active else "account_disabled", account_id, account["learner_id"])


def assign_mentor(mentor_account_id: int, learner_id: int, db_path: str | Path) -> None:
    _positive_id(learner_id)
    with closing(_connect(db_path)) as db, db:
        account = _account(db, mentor_account_id)
        if not account or not account["active"] or account["role"] not in {"mentor", "admin"}:
            raise AccountError("An active, explicitly authorized mentor/admin account is required.")
        if not db.execute("SELECT 1 FROM accounts WHERE learner_id=? AND role='learner'", (learner_id,)).fetchone():
            raise AccountError("Only an explicitly bound learner can be assigned.")
        cursor = db.execute("INSERT OR IGNORE INTO mentor_assignments (account_id, learner_id, created_at) VALUES (?, ?, ?)",
                            (mentor_account_id, learner_id, utc_now()))
        if cursor.rowcount:
            _audit(db, "mentor_assigned", mentor_account_id, learner_id)


def unassign_mentor(mentor_account_id: int, learner_id: int, db_path: str | Path) -> None:
    _positive_id(mentor_account_id)
    _positive_id(learner_id)
    with closing(_connect(db_path)) as db, db:
        cursor = db.execute("DELETE FROM mentor_assignments WHERE account_id=? AND learner_id=?", (mentor_account_id, learner_id))
        if cursor.rowcount:
            db.execute("UPDATE auth_sessions SET revoked_at=? WHERE account_id=? AND revoked_at IS NULL", (int(time.time()), mentor_account_id))
            _audit(db, "mentor_unassigned", mentor_account_id, learner_id)


def assigned_learner_ids(account_id: int, db_path: str | Path) -> list[int]:
    with closing(_connect(db_path, readonly=True)) as db:
        account = _account(db, account_id)
        if not account or not account["active"] or account["role"] not in {"mentor", "admin"}:
            return []
        return [row[0] for row in db.execute(
            "SELECT learner_id FROM mentor_assignments WHERE account_id=? ORDER BY learner_id", (account_id,)
        )]


def create_auth_session(account_id: int, db_path: str | Path, *, lifetime_seconds: int = 28800, idle_timeout_seconds: int = 1800) -> str:
    if type(lifetime_seconds) is not int or not 1 <= lifetime_seconds <= 86400:
        raise AccountError("Session duration must be from 1 second to 24 hours.")
    if type(idle_timeout_seconds) is not int or not 1 <= idle_timeout_seconds <= 86400:
        raise AccountError("Idle duration must be from 1 second to 24 hours.")
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with closing(_connect(db_path)) as db, db:
        account = _account(db, account_id)
        if not account or not account["active"]:
            raise AccountError("An active enrolled account is required to sign in.")
        db.execute("""INSERT INTO auth_sessions
            (token_digest, account_id, created_at, expires_at, last_seen_at, idle_timeout_seconds)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (_token_digest(token), account_id, now, now + lifetime_seconds, now, min(idle_timeout_seconds, lifetime_seconds)))
        _audit(db, "session_created", account_id)
    return token


def _token_digest(token: str) -> str | None:
    if not isinstance(token, str) or re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None:
        return None
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def get_session_account(token: str, db_path: str | Path, *, max_lifetime_seconds: int | None = None) -> dict[str, Any] | None:
    if max_lifetime_seconds is not None and (type(max_lifetime_seconds) is not int or not 1 <= max_lifetime_seconds <= 86400):
        raise AccountError("Session duration cap must be from 1 second to 24 hours.")
    digest = _token_digest(token)
    if digest is None:
        return None
    now = int(time.time())
    with closing(_connect(db_path)) as db, db:
        row = db.execute("""SELECT a.* FROM auth_sessions s JOIN accounts a ON a.id=s.account_id
            WHERE s.token_digest=? AND s.revoked_at IS NULL AND s.expires_at>?
            AND s.last_seen_at + s.idle_timeout_seconds > ? AND a.active=1
            AND (? IS NULL OR s.created_at + ? > ?)""",
            (digest, now, now, max_lifetime_seconds, max_lifetime_seconds, now)).fetchone()
        if row:
            # Record activity at most once per minute. Both idle and absolute
            # expiration remain server-enforced; activity never extends the latter.
            db.execute("""UPDATE auth_sessions SET last_seen_at=?
                WHERE token_digest=? AND last_seen_at<=? AND revoked_at IS NULL""", (now, digest, now - 60))
        return dict(row) if row else None


def revoke_auth_session(token: str, db_path: str | Path) -> None:
    digest = _token_digest(token)
    if digest is None:
        return
    with closing(_connect(db_path)) as db, db:
        row = db.execute("SELECT account_id FROM auth_sessions WHERE token_digest=? AND revoked_at IS NULL", (digest,)).fetchone()
        if row:
            db.execute("UPDATE auth_sessions SET revoked_at=? WHERE token_digest=?", (int(time.time()), digest))
            _audit(db, "session_revoked", row["account_id"])


def revoke_all_sessions(db_path: str | Path, *, account_id: int | None = None) -> None:
    """Operator recovery: invalidate every old session, including restored ones."""
    with closing(_connect(db_path)) as db, db:
        if account_id is None:
            db.execute("UPDATE auth_sessions SET revoked_at=? WHERE revoked_at IS NULL", (int(time.time()),))
        else:
            if _account(db, account_id) is None:
                raise AccountError("Account does not exist.")
            db.execute("UPDATE auth_sessions SET revoked_at=? WHERE account_id=? AND revoked_at IS NULL", (int(time.time()), account_id))
        _audit(db, "sessions_revoked", account_id)
