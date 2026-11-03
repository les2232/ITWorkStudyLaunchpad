"""Day 1 reflection answers and atomic checklist saves.

Database creation is explicit. Web requests only read and write an already
validated database, using the learner ID supplied by the authenticated route.
"""
from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from typing import Mapping


MAX_ANSWER_LENGTH = 4000
DAY_ONE_QUESTIONS = (
    ("learned", "What is one thing you learned today?"),
    ("needs_explanation", "What is one word or workflow you still want explained?"),
    ("ask_for_help", "What is one situation where you should ask for help?"),
    ("needs_approval", "What is one thing you should not do without approval?"),
)
ANSWER_IDS = frozenset(key for key, _ in DAY_ONE_QUESTIONS)


class ChecklistAnswerError(ValueError):
    """A submitted answer cannot be saved; the form must retain the draft."""


def add_checklist_answers_table(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS checklist_answers (
        student_id INTEGER NOT NULL REFERENCES students(id),
        checklist_id TEXT NOT NULL CHECK (checklist_id = 'day_1'),
        answer_id TEXT NOT NULL CHECK (answer_id IN
            ('learned', 'needs_explanation', 'ask_for_help', 'needs_approval')),
        answer_text TEXT NOT NULL CHECK (length(answer_text) <= 4000),
        updated_at TEXT NOT NULL,
        PRIMARY KEY (student_id, checklist_id, answer_id)
    )""")


def validate_checklist_answers_table(db: sqlite3.Connection) -> None:
    expected = [
        ("student_id", "INTEGER", 1, 1),
        ("checklist_id", "TEXT", 1, 2),
        ("answer_id", "TEXT", 1, 3),
        ("answer_text", "TEXT", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    ]
    actual = [(r[1], r[2].upper(), r[3], r[5])
              for r in db.execute("PRAGMA table_info(checklist_answers)")]
    if actual != expected:
        raise ValueError("unsupported checklist answer columns or primary key")
    foreign_keys = [(r[2], r[3], r[4])
                    for r in db.execute("PRAGMA foreign_key_list(checklist_answers)")]
    if foreign_keys != [("students", "student_id", "id")]:
        raise ValueError("unsupported checklist answer learner reference")
    if db.execute("""SELECT 1 FROM checklist_answers
        WHERE checklist_id != 'day_1'
           OR answer_id NOT IN ('learned','needs_explanation','ask_for_help','needs_approval')
           OR typeof(answer_text) != 'text' OR length(answer_text) > 4000
           OR instr(answer_text, char(0)) > 0
        LIMIT 1""").fetchone():
        raise ValueError("invalid checklist answer record")


def submitted_day_one_answers(form: Mapping[str, str]) -> dict[str, str]:
    # Missing fields preserve answers from older, already-open checklist forms.
    return {key: form["answer_" + key] for key, _ in DAY_ONE_QUESTIONS
            if "answer_" + key in form}


def validate_answers(checklist_id: str, answers: Mapping[str, str]) -> None:
    if (checklist_id != "day_1" and answers) or set(answers) - ANSWER_IDS:
        raise ChecklistAnswerError("These answers do not belong to this checklist.")
    for value in answers.values():
        if not isinstance(value, str) or "\x00" in value:
            raise ChecklistAnswerError("An answer contains an unsupported character. Your changes have not been saved.")
        if len(value) > MAX_ANSWER_LENGTH:
            raise ChecklistAnswerError("Keep each answer to 4,000 characters or fewer. Your changes have not been saved.")


def load_checklist_answers(student_id: int, checklist_id: str, db_path: str | Path) -> dict:
    with closing(sqlite3.connect(db_path)) as db:
        rows = db.execute(
            "SELECT answer_id, answer_text, updated_at FROM checklist_answers "
            "WHERE student_id = ? AND checklist_id = ?",
            (student_id, checklist_id),
        ).fetchall()
    return {
        "answers": {row[0]: row[1] for row in rows},
        "updated_at": max((row[2] for row in rows), default=None),
    }


def save_checklist_submission(
    student_id: int,
    checklist_id: str,
    item_ids: list[str],
    completed_items: set[str],
    answers: Mapping[str, str],
    db_path: str | Path,
) -> None:
    """Commit all checkboxes and supplied answers together, or neither."""
    validate_answers(checklist_id, answers)
    if type(student_id) is not int or student_id <= 0:
        raise ChecklistAnswerError("A learner account is required to save this checklist.")
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("PRAGMA foreign_keys = ON")
        with db:
            if not db.execute("SELECT 1 FROM students WHERE id = ?", (student_id,)).fetchone():
                raise ChecklistAnswerError("A learner account is required to save this checklist.")
            for item_id in item_ids:
                completed = item_id in completed_items
                db.execute("""INSERT INTO checklist_progress
                    (student_id, checklist_id, item_id, completed, completed_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(student_id, checklist_id, item_id) DO UPDATE SET
                    completed=excluded.completed, completed_at=excluded.completed_at,
                    updated_at=excluded.updated_at""",
                    (student_id, checklist_id, item_id, int(completed), now if completed else None, now))
            for answer_id, value in answers.items():
                db.execute("""INSERT INTO checklist_answers
                    (student_id, checklist_id, answer_id, answer_text, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(student_id, checklist_id, answer_id) DO UPDATE SET
                    answer_text=excluded.answer_text, updated_at=excluded.updated_at""",
                    (student_id, checklist_id, answer_id, value, now))
            db.execute("UPDATE students SET updated_at = ? WHERE id = ?", (now, student_id))


def split_day_one_reflection(body: str) -> tuple[str, str]:
    """Replace the reflection text after rendering, preserving checkbox IDs."""
    heading = "<h2>End-of-Day Reflection</h2>"
    start = body.find(heading)
    if start < 0:
        # A renamed content heading must not make the answer form disappear.
        return body, ""
    end = body.find("<h2>", start + len(heading))
    return body[:start], body[end:] if end >= 0 else ""
