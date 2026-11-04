"""Local demo SQLite persistence for the MVP prototype.

This module is intentionally limited to local progress tracking. It is not an
authentication system, production student-record store, or integration boundary.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .content import configured_activity_ids


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "instance" / "launchpad.sqlite"


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS assessment_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                assessment_id TEXT NOT NULL,
                assessment_type TEXT NOT NULL,
                technical_score INTEGER,
                readiness_level TEXT,
                recommended_training_path TEXT,
                role_alignment_recommendation TEXT,
                role_alignment_summary_json TEXT,
                answers_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id)
            );

            CREATE TABLE IF NOT EXISTS module_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                module_id TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE (student_id, module_id),
                FOREIGN KEY (student_id) REFERENCES students(id)
            );

            CREATE TABLE IF NOT EXISTS module_quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                module_id TEXT NOT NULL,
                score INTEGER NOT NULL,
                earned INTEGER NOT NULL,
                possible INTEGER NOT NULL,
                answers_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id)
            );

            CREATE TABLE IF NOT EXISTS checklist_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                checklist_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE (student_id, checklist_id, item_id),
                FOREIGN KEY (student_id) REFERENCES students(id)
            );

            CREATE TABLE IF NOT EXISTS activity_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                activity_id TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
                completed_at TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE (student_id, activity_id),
                FOREIGN KEY (student_id) REFERENCES students(id)
            );

            CREATE TABLE IF NOT EXISTS scenario_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                scenario_id TEXT NOT NULL,
                scenario_title TEXT NOT NULL,
                student_response TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id)
            );

            CREATE TABLE IF NOT EXISTS stuck_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                context TEXT NOT NULL,
                what_tried TEXT NOT NULL,
                question TEXT NOT NULL,
                mentor_summary TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                FOREIGN KEY (student_id) REFERENCES students(id)
            );
            """
        )
        add_help_request_status_column(db)


def add_help_request_status_column(db: sqlite3.Connection) -> None:
    """Additively record whether the learner still needs help.

    Existing requests keep their text and creation time. A missing value means
    Open: the app cannot know that an older request was answered.
    """
    columns = {row[1] for row in db.execute("PRAGMA table_info(stuck_reports)")}
    if "resolved_at" not in columns:
        db.execute("ALTER TABLE stuck_reports ADD COLUMN resolved_at TEXT")


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db = sqlite3.connect(Path(db_path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def create_or_find_student(display_name: str, db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    name = _clean_display_name(display_name)
    now = utc_now()
    with connect(db_path) as db:
        row = db.execute(
            "SELECT * FROM students WHERE lower(display_name) = lower(?) ORDER BY id LIMIT 1",
            (name,),
        ).fetchone()
        if row:
            db.execute("UPDATE students SET updated_at = ? WHERE id = ?", (now, row["id"]))
            return row_to_dict(db.execute("SELECT * FROM students WHERE id = ?", (row["id"],)).fetchone())

        cursor = db.execute(
            "INSERT INTO students (display_name, created_at, updated_at) VALUES (?, ?, ?)",
            (name, now, now),
        )
        return row_to_dict(db.execute("SELECT * FROM students WHERE id = ?", (cursor.lastrowid,)).fetchone())


def get_student(student_id: int, db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any] | None:
    with connect(db_path) as db:
        row = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        return row_to_dict(row) if row else None


def save_assessment_result(
    student_id: int,
    assessment_id: str,
    assessment_type: str,
    result: Mapping[str, Any],
    answers: Mapping[str, Any],
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    role_alignment = result.get("role_alignment") or {}
    role_recommendation = role_alignment.get("recommended_alignment") or {}
    with connect(db_path) as db:
        cursor = db.execute(
            """
            INSERT INTO assessment_results (
                student_id,
                assessment_id,
                assessment_type,
                technical_score,
                readiness_level,
                recommended_training_path,
                role_alignment_recommendation,
                role_alignment_summary_json,
                answers_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                assessment_id,
                assessment_type,
                result.get("score"),
                result.get("path_label") or result.get("readiness_label"),
                result.get("recommended_path"),
                role_recommendation.get("label"),
                to_json(role_alignment),
                to_json(dict(answers)),
                utc_now(),
            ),
        )
        touch_student(db, student_id)
        return int(cursor.lastrowid)


def latest_assessment_result(
    student_id: int,
    assessment_type: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    with connect(db_path) as db:
        row = db.execute(
            """
            SELECT *
            FROM assessment_results
            WHERE student_id = ? AND assessment_type = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (student_id, assessment_type),
        ).fetchone()
        return assessment_row(row) if row else None


def mark_module_complete(
    student_id: int,
    module_id: str,
    completed: bool,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    now = utc_now()
    completed_at = now if completed else None
    with connect(db_path) as db:
        db.execute(
            """
            INSERT INTO module_progress (student_id, module_id, completed, completed_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(student_id, module_id)
            DO UPDATE SET completed = excluded.completed,
                          completed_at = excluded.completed_at,
                          updated_at = excluded.updated_at
            """,
            (student_id, module_id, int(completed), completed_at, now),
        )
        touch_student(db, student_id, now)


def module_is_complete(student_id: int, module_id: str, db_path: str | Path = DEFAULT_DB_PATH) -> bool:
    with connect(db_path) as db:
        row = db.execute(
            "SELECT completed FROM module_progress WHERE student_id = ? AND module_id = ?",
            (student_id, module_id),
        ).fetchone()
        return bool(row and row["completed"])


def save_module_quiz_result(
    student_id: int,
    module_id: str,
    result: Mapping[str, Any],
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    with connect(db_path) as db:
        cursor = db.execute(
            """
            INSERT INTO module_quiz_results (
                student_id,
                module_id,
                score,
                earned,
                possible,
                answers_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                module_id,
                int(result.get("score", 0)),
                int(result.get("earned", 0)),
                int(result.get("possible", 0)),
                to_json(result.get("answers", [])),
                utc_now(),
            ),
        )
        touch_student(db, student_id)
        return int(cursor.lastrowid)


def latest_module_quiz_result(
    student_id: int,
    module_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    with connect(db_path) as db:
        row = db.execute(
            """
            SELECT *
            FROM module_quiz_results
            WHERE student_id = ? AND module_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (student_id, module_id),
        ).fetchone()
        return module_quiz_row(row) if row else None


def save_checklist_progress(
    student_id: int,
    checklist_id: str,
    item_id: str,
    completed: bool,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    now = utc_now()
    completed_at = now if completed else None
    with connect(db_path) as db:
        db.execute(
            """
            INSERT INTO checklist_progress (student_id, checklist_id, item_id, completed, completed_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(student_id, checklist_id, item_id)
            DO UPDATE SET completed = excluded.completed,
                          completed_at = excluded.completed_at,
                          updated_at = excluded.updated_at
            """,
            (student_id, checklist_id, item_id, int(completed), completed_at, now),
        )
        touch_student(db, student_id, now)


def checklist_progress(
    student_id: int,
    checklist_id: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, bool]:
    with connect(db_path) as db:
        rows = db.execute(
            "SELECT item_id, completed FROM checklist_progress WHERE student_id = ? AND checklist_id = ?",
            (student_id, checklist_id),
        ).fetchall()
        return {row["item_id"]: bool(row["completed"]) for row in rows}


def set_activity_complete(
    student_id: int,
    activity_id: str,
    completed: bool,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    if not isinstance(student_id, int) or isinstance(student_id, bool):
        return False
    if not isinstance(completed, bool):
        return False
    if activity_id not in configured_activity_ids():
        return False

    now = utc_now()
    completed_at = now if completed else None
    with connect(db_path) as db:
        student = db.execute("SELECT id FROM students WHERE id = ?", (student_id,)).fetchone()
        if student is None:
            return False
        db.execute(
            """
            INSERT INTO activity_progress (student_id, activity_id, completed, completed_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(student_id, activity_id)
            DO UPDATE SET completed = excluded.completed,
                          completed_at = excluded.completed_at,
                          updated_at = excluded.updated_at
            """,
            (student_id, activity_id, int(bool(completed)), completed_at, now),
        )
        touch_student(db, student_id, now)
    return True


def activity_progress(
    student_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, bool]:
    if not isinstance(student_id, int) or isinstance(student_id, bool):
        return {}
    allowed_ids = configured_activity_ids()
    with connect(db_path) as db:
        rows = db.execute(
            "SELECT activity_id, completed FROM activity_progress WHERE student_id = ?",
            (student_id,),
        ).fetchall()
    return {
        row["activity_id"]: bool(row["completed"])
        for row in rows
        if row["activity_id"] in allowed_ids
    }


def save_stuck_report(
    student_id: int,
    submitted: Mapping[str, str],
    mentor_summary: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    context_parts = [
        submitted.get("topic", "").strip(),
        submitted.get("trying_to_do", "").strip(),
        submitted.get("what_happened", "").strip(),
        submitted.get("related_item", "").strip(),
    ]
    context = "\n".join(part for part in context_parts if part)
    with connect(db_path) as db:
        cursor = db.execute(
            """
            INSERT INTO stuck_reports (student_id, context, what_tried, question, mentor_summary, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                context,
                submitted.get("already_checked", "").strip(),
                submitted.get("current_blocker", "").strip(),
                mentor_summary,
                utc_now(),
            ),
        )
        touch_student(db, student_id)
        return int(cursor.lastrowid)


def recent_stuck_reports(
    student_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return the latest summaries, oldest first, without putting text in cookies."""
    with connect(db_path) as db:
        rows = db.execute(
            """
            SELECT report.*, student.display_name
            FROM stuck_reports AS report
            JOIN students AS student ON student.id = report.student_id
            WHERE report.student_id = ?
            ORDER BY report.id DESC LIMIT ?
            """,
            (student_id, max(0, limit)),
        ).fetchall()
        return [_stuck_report_row(row) for row in reversed(rows)]


def help_requests_for_student(
    student_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
    resolved_limit: int = 20,
) -> dict[str, Any]:
    """Return every open request and the latest resolved ones, newest first."""
    query = """
        SELECT report.*, student.display_name
        FROM stuck_reports AS report
        JOIN students AS student ON student.id = report.student_id
        WHERE report.student_id = ? AND report.resolved_at IS {} NULL
        ORDER BY report.id DESC
    """
    with connect(db_path) as db:
        open_rows = db.execute(query.format(""), (student_id,)).fetchall()
        resolved_rows = db.execute(query.format("NOT") + " LIMIT ?", (student_id, max(0, resolved_limit))).fetchall()
        resolved_total = db.execute(
            "SELECT COUNT(*) FROM stuck_reports WHERE student_id = ? AND resolved_at IS NOT NULL",
            (student_id,),
        ).fetchone()[0]
    return {
        "open": [_stuck_report_row(row) for row in open_rows],
        "resolved": [_stuck_report_row(row) for row in resolved_rows],
        "resolved_total": resolved_total,
    }


def open_stuck_reports(
    student_ids: list[int],
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    """Open requests for the given learners, oldest first so long waits stay visible."""
    if not student_ids:
        return []
    placeholders = ",".join("?" for _ in student_ids)
    with connect(db_path) as db:
        rows = db.execute(
            f"""
            SELECT report.*, student.display_name
            FROM stuck_reports AS report
            JOIN students AS student ON student.id = report.student_id
            WHERE report.student_id IN ({placeholders}) AND report.resolved_at IS NULL
            ORDER BY report.id
            """,
            [int(value) for value in student_ids],
        ).fetchall()
    return [_stuck_report_row(row) for row in rows]


def set_stuck_report_resolved(
    student_id: int,
    report_id: int,
    resolved: bool,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> bool:
    """Change only the learner's own request status; the request text is never rewritten."""
    with connect(db_path) as db:
        cursor = db.execute(
            """
            UPDATE stuck_reports
            SET resolved_at = CASE WHEN ? THEN COALESCE(resolved_at, ?) ELSE NULL END
            WHERE id = ? AND student_id = ?
            """,
            (1 if resolved else 0, utc_now(), report_id, student_id),
        )
        if cursor.rowcount != 1:
            return False
        touch_student(db, student_id)
        return True


def _stuck_report_row(row: sqlite3.Row) -> dict[str, Any]:
    item = row_to_dict(row)
    item["status"] = "resolved" if item.get("resolved_at") else "open"
    item["status_label"] = "Resolved" if item["status"] == "resolved" else "Open"
    item["student"] = item.pop("display_name")
    item["summary"] = item["mentor_summary"]
    # Existing summaries already carry the normalized topic, including records
    # created before server-side retrieval. No migration of old text is needed.
    topic = next(
        (line.removeprefix("Topic: ") for line in item["summary"].splitlines() if line.startswith("Topic: ")),
        "",
    )
    item["topic"] = "" if topic == "Not provided" else topic
    return item


def save_scenario_attempt(
    student_id: int,
    scenario_id: str,
    scenario_title: str,
    student_response: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """Persist the complete practice draft; viewing the latest 20 deletes nothing."""
    with connect(db_path) as db:
        cursor = db.execute(
            """
            INSERT INTO scenario_attempts
                (student_id, scenario_id, scenario_title, student_response, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (student_id, scenario_id, scenario_title, student_response, utc_now()),
        )
        touch_student(db, student_id)
        return int(cursor.lastrowid)


def recent_scenario_attempts(
    student_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
    limit: int = 20,
) -> list[dict[str, Any]]:
    with connect(db_path) as db:
        rows = db.execute(
            "SELECT * FROM scenario_attempts WHERE student_id = ? ORDER BY id DESC LIMIT ?",
            (student_id, max(0, limit)),
        ).fetchall()
        return [{**row_to_dict(row), "needs_mentor_review": True} for row in reversed(rows)]


def student_progress(
    student_id: int,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any] | None:
    """Load one learner independently of the recent-learner overview limit."""
    with connect(db_path) as db:
        student = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        return student_summary(db, student) if student else None


def student_progress_summary(db_path: str | Path = DEFAULT_DB_PATH, limit: int = 20) -> list[dict[str, Any]]:
    with connect(db_path) as db:
        students = db.execute(
            "SELECT * FROM students ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [student_summary(db, student) for student in students]


def student_summary(db: sqlite3.Connection, student: sqlite3.Row) -> dict[str, Any]:
    pre = db.execute(
        """
        SELECT *
        FROM assessment_results
        WHERE student_id = ? AND assessment_type = 'pre'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (student["id"],),
    ).fetchone()
    post = db.execute(
        """
        SELECT *
        FROM assessment_results
        WHERE student_id = ? AND assessment_type = 'post'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (student["id"],),
    ).fetchone()
    module_count = db.execute(
        "SELECT COUNT(*) AS count FROM module_progress WHERE student_id = ? AND completed = 1",
        (student["id"],),
    ).fetchone()["count"]
    module_quiz_count = db.execute(
        "SELECT COUNT(DISTINCT module_id) AS count FROM module_quiz_results WHERE student_id = ?",
        (student["id"],),
    ).fetchone()["count"]
    checklist_count = db.execute(
        "SELECT COUNT(*) AS count FROM checklist_progress WHERE student_id = ? AND completed = 1",
        (student["id"],),
    ).fetchone()["count"]
    stuck_count = db.execute(
        "SELECT COUNT(*) AS count FROM stuck_reports WHERE student_id = ?",
        (student["id"],),
    ).fetchone()["count"]
    open_stuck_count = db.execute(
        "SELECT COUNT(*) AS count FROM stuck_reports WHERE student_id = ? AND resolved_at IS NULL",
        (student["id"],),
    ).fetchone()["count"]

    return {
        "student": row_to_dict(student),
        "latest_pre_assessment": assessment_row(pre) if pre else None,
        "latest_post_assessment": assessment_row(post) if post else None,
        "module_completed_count": module_count,
        "module_quiz_completed_count": module_quiz_count,
        "checklist_completed_count": checklist_count,
        "stuck_report_count": stuck_count,
        "open_stuck_report_count": open_stuck_count,
    }


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def touch_student(db: sqlite3.Connection, student_id: int, timestamp: str | None = None) -> None:
    db.execute("UPDATE students SET updated_at = ? WHERE id = ?", (timestamp or utc_now(), student_id))


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def assessment_row(row: sqlite3.Row) -> dict[str, Any]:
    item = row_to_dict(row)
    item["role_alignment_summary"] = from_json(item.pop("role_alignment_summary_json", ""))
    item["answers"] = from_json(item.pop("answers_json", ""))
    return item


def module_quiz_row(row: sqlite3.Row) -> dict[str, Any]:
    item = row_to_dict(row)
    item["answers"] = from_json(item.pop("answers_json", "")) or []
    return item


def to_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def from_json(value: str) -> Any:
    if not value:
        return None
    return json.loads(value)


def _clean_display_name(display_name: str) -> str:
    name = " ".join(str(display_name or "").split())
    return name[:80] or "Demo Student"
