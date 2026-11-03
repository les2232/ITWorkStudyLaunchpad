"""Regression coverage for editable Day 1 answers.

All database fixtures are temporary and synthetic. These tests never open the
configured production database or contact the identity provider.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import sqlite3
import tempfile
from pathlib import Path
import unittest

from launchpad.checklist_answers import (
    ANSWER_IDS, DAY_ONE_QUESTIONS, MAX_ANSWER_LENGTH, ChecklistAnswerError,
    add_checklist_answers_table, load_checklist_answers, save_checklist_submission,
    split_day_one_reflection, submitted_day_one_answers, validate_checklist_answers_table,
)


@contextmanager
def database(path):
    with closing(sqlite3.connect(path)) as db:
        with db:
            yield db


class ChecklistAnswerStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "synthetic.sqlite"
        with database(self.db_path) as db:
            db.executescript("""
                CREATE TABLE students (id INTEGER PRIMARY KEY, updated_at TEXT NOT NULL);
                INSERT INTO students VALUES (1, 'before'), (2, 'before');
                CREATE TABLE checklist_progress (
                    student_id INTEGER NOT NULL REFERENCES students(id),
                    checklist_id TEXT NOT NULL, item_id TEXT NOT NULL,
                    completed INTEGER NOT NULL, completed_at TEXT, updated_at TEXT NOT NULL,
                    UNIQUE(student_id, checklist_id, item_id)
                );
            """)
            add_checklist_answers_table(db)

    def save(self, answers, completed=None, student=1, checklist="day_1"):
        save_checklist_submission(student, checklist, ["0", "1"],
                                  {"0"} if completed is None else completed,
                                  answers, self.db_path)

    def state(self, student=1):
        return load_checklist_answers(student, "day_1", self.db_path)

    def checked(self):
        with database(self.db_path) as db:
            return dict(db.execute("SELECT item_id, completed FROM checklist_progress WHERE student_id=1 AND checklist_id='day_1'"))

    def test_saved_answers_survive_new_connection(self):
        self.save({key: f"Synthetic answer {key}" for key in ANSWER_IDS})
        self.assertEqual(len(self.state()["answers"]), 4)
        self.assertIsNotNone(self.state()["updated_at"])
        self.assertEqual(self.checked(), {"0": 1, "1": 0})

    def test_edit_replaces_value_without_duplicate_row(self):
        self.save({"learned": "first"})
        self.save({"learned": "revised"})
        self.assertEqual(self.state()["answers"], {"learned": "revised"})

    def test_blank_answer_can_be_saved_to_clear_it(self):
        self.save({"learned": "first"})
        self.save({"learned": ""})
        self.assertEqual(self.state()["answers"]["learned"], "")

    def test_missing_fields_preserve_existing_answers(self):
        self.save({"learned": "keep this", "needs_explanation": "also keep"})
        self.save({}, completed=set())
        self.assertEqual(self.state()["answers"]["learned"], "keep this")
        self.assertEqual(self.checked(), {"0": 0, "1": 0})

    def test_partial_edit_preserves_other_answers(self):
        self.save({"learned": "first", "ask_for_help": "keep"})
        self.save({"learned": "changed"})
        self.assertEqual(self.state()["answers"]["ask_for_help"], "keep")

    def test_learners_are_isolated(self):
        self.save({"learned": "learner one"})
        self.assertEqual(self.state(2)["answers"], {})
        self.save({"learned": "learner two"}, student=2)
        self.assertEqual(self.state()["answers"]["learned"], "learner one")
        self.assertEqual(self.state(2)["answers"]["learned"], "learner two")

    def test_unknown_learner_is_rejected_before_any_write(self):
        with self.assertRaises(ChecklistAnswerError):
            self.save({"learned": "invalid"}, student=999)
        self.assertEqual(self.checked(), {})

    def test_forged_form_identity_is_not_an_answer(self):
        form = {"student_id": "2", "answer_learned": "mine", "answer_unknown": "ignore"}
        self.assertEqual(submitted_day_one_answers(form), {"learned": "mine"})

    def test_unknown_answer_key_is_rejected(self):
        with self.assertRaises(ChecklistAnswerError):
            self.save({"other": "no"})
        self.assertEqual(self.checked(), {})

    def test_answer_length_boundary(self):
        self.save({"learned": "x" * MAX_ANSWER_LENGTH})
        with self.assertRaises(ChecklistAnswerError):
            self.save({"learned": "x" * (MAX_ANSWER_LENGTH + 1)}, completed=set())
        self.assertEqual(len(self.state()["answers"]["learned"]), MAX_ANSWER_LENGTH)
        self.assertEqual(self.checked()["0"], 1)

    def test_null_character_is_rejected(self):
        with self.assertRaises(ChecklistAnswerError):
            self.save({"learned": "bad\x00answer"})
        self.assertEqual(self.checked(), {})

    def test_html_and_line_breaks_are_stored_as_text(self):
        text = '<script>alert("test")</script>\nSecond line & <tag>'
        self.save({"learned": text})
        self.assertEqual(self.state()["answers"]["learned"], text)

    def test_database_failure_rolls_back_checkboxes_and_answers(self):
        self.save({"learned": "original"})
        with database(self.db_path) as db:
            db.execute("""CREATE TRIGGER reject_answer BEFORE UPDATE ON checklist_answers
                BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.save({"learned": "replacement"}, completed=set())
        self.assertEqual(self.checked()["0"], 1)
        self.assertEqual(self.state()["answers"]["learned"], "original")

    def test_week_one_checkbox_save_does_not_change_day_one_answers(self):
        self.save({"learned": "keep"})
        self.save({}, checklist="week_1")
        self.assertEqual(self.state()["answers"]["learned"], "keep")
        with self.assertRaises(ChecklistAnswerError):
            self.save({"learned": "invalid"}, checklist="week_1")

    def test_schema_initialization_is_idempotent(self):
        self.save({"learned": "keep"})
        with database(self.db_path) as db:
            add_checklist_answers_table(db)
            validate_checklist_answers_table(db)
        self.assertEqual(self.state()["answers"]["learned"], "keep")

    def test_schema_requires_learner_foreign_key(self):
        with database(self.db_path) as db:
            db.execute("DROP TABLE checklist_answers")
            db.execute("""CREATE TABLE checklist_answers (
                student_id INTEGER NOT NULL, checklist_id TEXT NOT NULL,
                answer_id TEXT NOT NULL, answer_text TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(student_id, checklist_id, answer_id))""")
            with self.assertRaises(ValueError):
                validate_checklist_answers_table(db)


class ChecklistAnswerRenderingTests(unittest.TestCase):
    def test_reflection_replacement_keeps_existing_checkbox_ids(self):
        before = '<h1>Day 1</h1><input value="10">'
        after = '<h2>Mentor Check-Out</h2><input value="47">'
        body = before + '<h2>End-of-Day Reflection</h2><ol><li>Question</li></ol><hr>' + after
        self.assertEqual(split_day_one_reflection(body), (before, after))

    def test_renamed_heading_keeps_content_and_still_allows_form(self):
        self.assertEqual(split_day_one_reflection("<p>Updated training</p>"), ("<p>Updated training</p>", ""))


class ChecklistAnswerTemplateTests(unittest.TestCase):
    def test_four_labeled_fields_escape_saved_text(self):
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        env = Environment(loader=FileSystemLoader(str(Path(__file__).resolve().parents[1] / "templates")),
                          autoescape=select_autoescape(["html"]))
        env.filters["campus_time"] = str
        html = env.get_template("_day_one_answers.html").render(
            reflection_questions=DAY_ONE_QUESTIONS,
            reflection_answers={"learned": '</textarea><script>alert("test")</script>'},
            answers_saved_at=None, answer_error=None, learner_required=False,
            max_answer_length=MAX_ANSWER_LENGTH,
        )
        self.assertEqual(html.count("<textarea "), 4)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;/textarea&gt;", html)
        for key, _ in DAY_ONE_QUESTIONS:
            self.assertIn(f'for="answer-{key}"', html)
            self.assertIn(f'id="answer-{key}"', html)


class ChecklistAnswerMigrationTests(unittest.TestCase):
    """Run in the actual development checkout, with its account schema."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name).resolve()

    def legacy(self, version):
        from launchpad.real_data import initialize_real_database, validate_real_database
        path = self.directory / f"v{version}.sqlite"
        initialize_real_database(path)
        with database(path) as db:
            db.execute("DROP TABLE checklist_answers")
            if version == 1:
                db.execute("ALTER TABLE stuck_reports DROP COLUMN resolved_at")
            db.execute("UPDATE real_dataset_metadata SET schema_version=?", (version,))
        validate_real_database(path, schema_version=version)
        return path

    def test_migrate_v1_and_v2_to_new_v3_files(self):
        from launchpad.real_data import migrate_real_database, validate_real_database
        for version in (1, 2):
            with self.subTest(version=version):
                source = self.legacy(version)
                before = source.read_bytes()
                old_marker = validate_real_database(source, schema_version=version)
                target = self.directory / f"from-v{version}.sqlite"
                migrate_real_database(source, target)
                self.assertEqual(before, source.read_bytes())
                marker = validate_real_database(target)
                self.assertEqual(marker["schema_version"], 3)
                self.assertEqual(marker["dataset_id"], old_marker["dataset_id"])
                with database(target) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM checklist_answers").fetchone()[0], 0)

    def test_v2_fails_current_startup_validation_until_migrated(self):
        from launchpad.real_data import RealDataError, validate_real_database
        source = self.legacy(2)
        with self.assertRaises(RealDataError):
            validate_real_database(source)

    def test_migration_refuses_existing_destination(self):
        from launchpad.real_data import RealDataError, migrate_real_database
        source = self.legacy(2)
        target = self.directory / "existing.sqlite"
        target.write_bytes(b"preserve this file")
        with self.assertRaises(RealDataError):
            migrate_real_database(source, target)
        self.assertEqual(target.read_bytes(), b"preserve this file")

    def test_v3_without_answer_table_is_rejected(self):
        from launchpad.real_data import RealDataError, initialize_real_database, validate_real_database
        path = self.directory / "broken.sqlite"
        initialize_real_database(path)
        with database(path) as db:
            db.execute("DROP TABLE checklist_answers")
        with self.assertRaises(RealDataError):
            validate_real_database(path)


if __name__ == "__main__":
    unittest.main()
