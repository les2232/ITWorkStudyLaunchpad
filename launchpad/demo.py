"""Guarded, synthetic-only data preparation for the July 30 demonstration.

The helpers in this module deliberately accept only a new, dedicated SQLite
file below ``/tmp``.  They never infer a path from the application environment
and never operate on the normal ``instance/launchpad.sqlite`` database.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from .assessment import get_training_path, load_assessment, score_assessment
from .content import (
    configured_activity_ids,
    extract_checklist_items,
    list_checklists,
    list_modules,
    read_checklist_markdown,
)
from .scenarios import list_scenarios
from .storage import (
    DEFAULT_DB_PATH,
    connect,
    create_or_find_student,
    init_db,
    mark_module_complete,
    save_assessment_result,
    save_checklist_progress,
    set_activity_complete,
)


DEMO_NOVA_NAME = "DEMO Nova Byte"
DEMO_RILEY_NAME = "DEMO Riley Resume"
DEMO_QUINN_NAME = "DEMO Quinn Quest"
DEMO_LEARNER_NAMES = (DEMO_NOVA_NAME, DEMO_RILEY_NAME, DEMO_QUINN_NAME)

NO_DISPLAY_ACTIVITY_ID = "developing_no_display_troubleshooting"
DEMO_DATASET_ID = "it-work-study-launchpad-2026-07-30-v1"
DEMO_SCHEMA_VERSION = 1
DEMO_TIMESTAMP = "2026-07-30T08:00:00+00:00"

APPLICATION_TABLES = frozenset(
    {
        "students",
        "assessment_results",
        "module_progress",
        "module_quiz_results",
        "checklist_progress",
        "activity_progress",
        "stuck_reports",
    }
)
# This additive table is optional when reading an earlier v1 synthetic dataset.
# init_db adds it only after the existing database passes guarded validation.
OPTIONAL_APPLICATION_TABLES = frozenset({"scenario_attempts"})
DEMO_METADATA_TABLE = "demo_dataset_metadata"
ALLOWED_TABLES = APPLICATION_TABLES | OPTIONAL_APPLICATION_TABLES | {DEMO_METADATA_TABLE, "sqlite_sequence"}
STUDENT_RECORD_TABLES = (APPLICATION_TABLES | OPTIONAL_APPLICATION_TABLES) - {"students"}
SQLITE_SIDECAR_SUFFIXES = ("-journal", "-wal", "-shm")


class DemoDataError(ValueError):
    """Raised when a requested demo-data operation is not demonstrably safe."""


def synthetic_beginner_responses() -> dict[str, Any]:
    """Return the fixed, invented Beginner profile used by the demo-only preset."""

    return {
        "q1": "B",
        "q2": ["none"],
        "q3": (
            "This fictional learner is new to IT support and will ask a mentor "
            "before acting."
        ),
        "q4": "1",
        "q5": "1",
        "q6": "1",
        "q7": "1",
        "q8": "D",
        "q9": "D",
        "q10": "D",
        "q11": "D",
        "q12": "D",
        "q13": "B",
        "q14": "D",
        "q15": "D",
        "q16": "D",
        "q17": "B",
        "q18": "D",
        "q19": "D",
        "q20": "D",
        **_synthetic_role_responses(),
    }


def synthetic_ready_to_shadow_responses() -> dict[str, Any]:
    """Return the fixed, invented 75% Ready-to-Shadow profile."""

    return {
        "q1": "A",
        "q2": [
            "connected_peripherals",
            "installed_software",
            "troubleshot_computer",
            "ticketing_system",
            "customer_service",
        ],
        "q3": "This fictional learner has practiced approved checks in a training lab.",
        "q4": "4",
        "q5": "4",
        "q6": "4",
        "q7": "3",
        "q8": "B",
        "q9": "B",
        "q10": "A",
        "q11": "A",
        "q12": "A",
        "q13": "B",
        "q14": "B",
        "q15": "C",
        "q16": "D",
        "q17": "B",
        "q18": "D",
        "q19": "D",
        "q20": "C",
        **_synthetic_role_responses(),
    }


def synthetic_developing_responses() -> dict[str, Any]:
    """Return the fixed, invented 55% Developing profile."""

    return {
        "q1": "A",
        "q2": ["connected_peripherals", "installed_software", "customer_service"],
        "q3": "This fictional learner has used classroom practice equipment only.",
        "q4": "5",
        "q5": "4",
        "q6": "3",
        "q7": "3",
        "q8": "B",
        "q9": "B",
        "q10": "A",
        "q11": "D",
        "q12": "D",
        "q13": "B",
        "q14": "B",
        "q15": "C",
        "q16": "D",
        "q17": "B",
        "q18": "D",
        "q19": "D",
        "q20": "D",
        **_synthetic_role_responses(),
    }


def prepare_demo_database(db_path: str | Path) -> Path:
    """Create and seed a brand-new guarded demo database.

    Existing paths are always refused, even if they already contain a valid
    demo dataset.  Use :func:`reset_demo_database` for a verified reset.
    """

    path = safe_demo_database_path(db_path)
    _assert_no_sqlite_sidecars(path)
    if os.path.lexists(path):
        raise DemoDataError(f"prepare requires a new path; already exists: {path}")

    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise DemoDataError(f"prepare requires a new path; already exists: {path}") from exc
    os.close(descriptor)

    try:
        init_db(path)
        _seed_demo_database(path)
        os.chmod(path, 0o600)
        validate_demo_database(path)
    except Exception:
        _remove_new_database(path)
        raise

    return path


def reset_demo_database(db_path: str | Path) -> tuple[Path, Path]:
    """Quarantine a verified demo database and rebuild its deterministic seed."""

    path = safe_demo_database_path(db_path)
    _assert_no_sqlite_sidecars(path)
    identity = _file_identity(path)
    validate_demo_database(path)
    if _file_identity(path) != identity:
        raise DemoDataError("database changed while it was being verified; reset refused")

    quarantine_path = _next_quarantine_path(path)
    os.replace(path, quarantine_path)
    try:
        prepare_demo_database(path)
    except Exception:
        _remove_new_database(path)
        os.replace(quarantine_path, path)
        raise

    return path, quarantine_path


def validate_demo_database(db_path: str | Path) -> dict[str, Any]:
    """Verify that a database is a known synthetic dataset safe to quarantine."""

    path = safe_demo_database_path(db_path)
    _assert_no_sqlite_sidecars(path)
    if not path.exists() or not path.is_file():
        raise DemoDataError(f"demo database does not exist as a regular file: {path}")

    try:
        with path.open("rb") as database_file:
            header = database_file.read(16)
    except OSError as exc:
        raise DemoDataError(f"could not read demo database: {path}") from exc
    if header != b"SQLite format 3\x00":
        raise DemoDataError(f"not a SQLite database: {path}")

    uri = f"file:{quote(str(path), safe='/')}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as db:
            db.row_factory = sqlite3.Row
            quick_check = db.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or quick_check[0] != "ok":
                raise DemoDataError(f"SQLite integrity check failed: {path}")

            tables = {
                row["name"]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            missing_tables = (ALLOWED_TABLES - OPTIONAL_APPLICATION_TABLES) - tables
            unknown_tables = tables - ALLOWED_TABLES
            if missing_tables or unknown_tables:
                details = []
                if missing_tables:
                    details.append(f"missing tables: {', '.join(sorted(missing_tables))}")
                if unknown_tables:
                    details.append(f"unknown tables: {', '.join(sorted(unknown_tables))}")
                raise DemoDataError("unrecognized database schema; " + "; ".join(details))

            marker = db.execute(
                f"SELECT dataset_id, schema_version, prepared_at "
                f"FROM {DEMO_METADATA_TABLE} WHERE singleton = 1"
            ).fetchone()
            marker_count = db.execute(
                f"SELECT COUNT(*) AS count FROM {DEMO_METADATA_TABLE}"
            ).fetchone()["count"]
            if (
                marker is None
                or marker_count != 1
                or marker["dataset_id"] != DEMO_DATASET_ID
                or marker["schema_version"] != DEMO_SCHEMA_VERSION
            ):
                raise DemoDataError("database is not a recognized synthetic demo dataset")

            students = db.execute(
                "SELECT id, display_name FROM students ORDER BY id"
            ).fetchall()
            names = [row["display_name"] for row in students]
            if len(names) != len(DEMO_LEARNER_NAMES) or set(names) != set(DEMO_LEARNER_NAMES):
                raise DemoDataError(
                    "database contains learners outside the three fixed synthetic personas"
                )
            student_ids = {row["id"] for row in students}
            _assert_known_records(db, student_ids, tables)

            foreign_key_errors = db.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_key_errors:
                raise DemoDataError("database contains invalid student record references")
    except DemoDataError:
        raise
    except sqlite3.DatabaseError as exc:
        raise DemoDataError(f"not a valid recognized SQLite demo database: {path}") from exc

    return {
        "path": str(path),
        "dataset_id": DEMO_DATASET_ID,
        "learner_names": list(DEMO_LEARNER_NAMES),
        "session_generation": marker["prepared_at"],
    }


def _synthetic_role_responses() -> dict[str, str]:
    return {
        "ra1": "B",
        "ra2": "C",
        "ra3": "A",
        "ra4": "A",
        "ra5": "B",
        "ra6": "A",
        "ra7": "A",
    }


def _seed_demo_database(path: Path) -> None:
    with connect(path) as db:
        db.execute(
            f"""
            CREATE TABLE {DEMO_METADATA_TABLE} (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                dataset_id TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                prepared_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            f"""
            INSERT INTO {DEMO_METADATA_TABLE} (
                singleton, dataset_id, schema_version, prepared_at
            ) VALUES (1, ?, ?, ?)
            """,
            (
                DEMO_DATASET_ID,
                DEMO_SCHEMA_VERSION,
                datetime.now(UTC).isoformat(timespec="microseconds"),
            ),
        )

    students = {
        name: create_or_find_student(name, path)
        for name in DEMO_LEARNER_NAMES
    }

    _save_synthetic_assessment(
        students[DEMO_RILEY_NAME]["id"],
        synthetic_ready_to_shadow_responses(),
        expected_score=75,
        expected_path_slug="ready_to_shadow",
        db_path=path,
    )
    _complete_checklist(students[DEMO_RILEY_NAME]["id"], "day_1", path)
    _require_activity_completion(
        students[DEMO_RILEY_NAME]["id"],
        "ready_to_shadow_department_expectations",
        path,
    )

    _save_synthetic_assessment(
        students[DEMO_QUINN_NAME]["id"],
        synthetic_developing_responses(),
        expected_score=55,
        expected_path_slug="developing",
        db_path=path,
    )
    _complete_developing_prerequisites(students[DEMO_QUINN_NAME]["id"], path)
    _normalize_demo_timestamps(path)


def _save_synthetic_assessment(
    student_id: int,
    responses: Mapping[str, Any],
    *,
    expected_score: int,
    expected_path_slug: str,
    db_path: Path,
) -> None:
    assessment = load_assessment("pre_assessment_v1")
    result = score_assessment(assessment, dict(responses))
    path = get_training_path(result["score"])
    if result["score"] != expected_score or path["slug"] != expected_path_slug:
        raise DemoDataError(
            "assessment content changed the deterministic synthetic profile "
            f"(expected {expected_score}%/{expected_path_slug}, got "
            f"{result['score']}%/{path['slug']})"
        )
    result["path_slug"] = path["slug"]
    result["path_label"] = path["label"]
    result["recommended_path"] = path["recommended_path"]
    save_assessment_result(
        student_id,
        assessment["id"],
        "pre",
        result,
        responses,
        db_path,
    )


def _complete_checklist(student_id: int, checklist_id: str, db_path: Path) -> None:
    items = extract_checklist_items(read_checklist_markdown(checklist_id))
    if not items:
        raise DemoDataError(f"cannot seed empty checklist: {checklist_id}")
    for index in range(len(items)):
        save_checklist_progress(student_id, checklist_id, str(index), True, db_path)


def _complete_developing_prerequisites(student_id: int, db_path: Path) -> None:
    developing_path = get_training_path(55)
    found_scenario_practice = False
    for item in developing_path.get("required_items", []):
        item_type = item.get("type")
        if item_type == "checklist":
            _complete_checklist(student_id, item["slug"], db_path)
        elif item_type == "module":
            mark_module_complete(student_id, item["slug"], True, db_path)
        elif item_type == "activity":
            activity_id = item.get("id")
            if activity_id != NO_DISPLAY_ACTIVITY_ID:
                _require_activity_completion(student_id, activity_id, db_path)
            if activity_id == "developing_scenario_practice":
                found_scenario_practice = True
                break

    if not found_scenario_practice:
        raise DemoDataError("Developing path no longer contains scenario practice")


def _require_activity_completion(student_id: int, activity_id: str, db_path: Path) -> None:
    if not set_activity_complete(student_id, activity_id, True, db_path):
        raise DemoDataError(f"cannot seed configured activity: {activity_id}")


def _normalize_demo_timestamps(path: Path) -> None:
    with connect(path) as db:
        db.execute(
            "UPDATE students SET created_at = ?, updated_at = ?",
            (DEMO_TIMESTAMP, DEMO_TIMESTAMP),
        )
        db.execute("UPDATE assessment_results SET created_at = ?", (DEMO_TIMESTAMP,))
        for table in ("module_progress", "checklist_progress", "activity_progress"):
            db.execute(
                f"""
                UPDATE {table}
                SET updated_at = ?,
                    completed_at = CASE WHEN completed = 1 THEN ? ELSE NULL END
                """,
                (DEMO_TIMESTAMP, DEMO_TIMESTAMP),
            )


def _assert_no_sqlite_sidecars(path: Path) -> None:
    sidecars = [Path(f"{path}{suffix}") for suffix in SQLITE_SIDECAR_SUFFIXES]
    present = [str(sidecar) for sidecar in sidecars if os.path.lexists(sidecar)]
    if present:
        raise DemoDataError(
            "SQLite sidecar files are present; stop the app cleanly before retrying: "
            + ", ".join(present)
        )


def _assert_known_records(
    db: sqlite3.Connection, student_ids: set[int], tables: set[str]
) -> None:
    placeholders = ",".join("?" for _ in student_ids)
    for table in STUDENT_RECORD_TABLES & tables:
        unknown_student = db.execute(
            f"SELECT 1 FROM {table} WHERE student_id IS NULL OR student_id NOT IN ({placeholders}) LIMIT 1",
            tuple(sorted(student_ids)),
        ).fetchone()
        if unknown_student is not None:
            raise DemoDataError(f"{table} contains records for an unknown learner")

    _assert_column_values(
        db,
        "assessment_results",
        "assessment_id",
        {"pre_assessment_v1", "post_assessment_v1"},
    )
    _assert_column_values(db, "assessment_results", "assessment_type", {"pre", "post"})

    if "scenario_attempts" in tables:
        _assert_column_values(
            db, "scenario_attempts", "scenario_id", {scenario["id"] for scenario in list_scenarios()}
        )

    module_ids = {module["slug"] for module in list_modules()}
    _assert_column_values(db, "module_progress", "module_id", module_ids)
    _assert_column_values(db, "module_quiz_results", "module_id", module_ids)

    checklist_ids = {checklist["slug"] for checklist in list_checklists()}
    _assert_column_values(db, "checklist_progress", "checklist_id", checklist_ids)
    for row in db.execute(
        "SELECT checklist_id, item_id FROM checklist_progress"
    ).fetchall():
        valid_items = extract_checklist_items(read_checklist_markdown(row["checklist_id"]))
        if row["item_id"] not in {str(index) for index in range(len(valid_items))}:
            raise DemoDataError("checklist_progress contains an unknown checklist item")

    _assert_column_values(
        db,
        "activity_progress",
        "activity_id",
        configured_activity_ids(),
    )


def _assert_column_values(
    db: sqlite3.Connection,
    table: str,
    column: str,
    allowed: set[str],
) -> None:
    actual = {
        row[column]
        for row in db.execute(f"SELECT DISTINCT {column} FROM {table}").fetchall()
    }
    unknown = actual - allowed
    if unknown:
        raise DemoDataError(
            f"{table} contains unknown {column} values: {', '.join(sorted(unknown))}"
        )


def _file_identity(path: Path) -> tuple[int, int, int]:
    try:
        stat_result = path.stat(follow_symlinks=False)
    except (FileNotFoundError, OSError) as exc:
        raise DemoDataError(f"demo database does not exist: {path}") from exc
    return (stat_result.st_dev, stat_result.st_ino, stat_result.st_size)


def _next_quarantine_path(path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = path.with_name(f"{path.stem}.quarantine-{timestamp}{path.suffix}")
    candidate = base
    counter = 2
    while os.path.lexists(candidate):
        candidate = path.with_name(
            f"{path.stem}.quarantine-{timestamp}-{counter}{path.suffix}"
        )
        counter += 1
    return candidate


def _remove_new_database(path: Path) -> None:
    if path.exists() and path.is_file() and not path.is_symlink():
        path.unlink()
    for suffix in SQLITE_SIDECAR_SUFFIXES:
        sidecar = Path(f"{path}{suffix}")
        if sidecar.exists() and sidecar.is_file() and not sidecar.is_symlink():
            sidecar.unlink()


def safe_demo_database_path(db_path: str | Path) -> Path:
    path = Path(db_path)
    if not path.is_absolute():
        raise DemoDataError("--db must be an absolute path")

    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise DemoDataError(f"could not resolve demo database path: {path}") from exc

    if resolved == DEFAULT_DB_PATH.resolve(strict=False):
        raise DemoDataError("the application database is never a valid demo-data target")
    if resolved != path:
        raise DemoDataError("--db must be canonical and must not contain symlinks or '..'")

    tmp_root = Path("/tmp").resolve()
    if resolved == tmp_root or tmp_root not in resolved.parents:
        raise DemoDataError("--db must be a dedicated file below /tmp")
    if path.suffix != ".sqlite":
        raise DemoDataError("--db must name a .sqlite file")
    if path.is_symlink():
        raise DemoDataError("symlink database targets are not allowed")
    if not path.parent.exists() or not path.parent.is_dir():
        raise DemoDataError("--db parent directory must already exist")

    return path
