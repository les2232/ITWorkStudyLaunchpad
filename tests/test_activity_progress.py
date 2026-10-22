import sqlite3
import tempfile
import unittest
from pathlib import Path

from launchpad import create_app
from launchpad.content import extract_checklist_items, read_checklist_markdown
from launchpad.storage import (
    activity_progress,
    connect,
    create_or_find_student,
    init_db,
    mark_module_complete,
    save_assessment_result,
    save_checklist_progress,
    set_activity_complete,
)
from scripts.validate_content import validate_training_paths


class ActivityProgressStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "activity-progress.sqlite"
        init_db(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_new_database_includes_activity_progress_table(self):
        with connect(self.db_path) as db:
            tables = {
                row["name"]
                for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }

        self.assertIn("activity_progress", tables)

    def test_initialization_adds_table_to_existing_database_without_rewriting_data(self):
        old_db_path = Path(self.tmpdir.name) / "existing.sqlite"
        init_db(old_db_path)
        existing_student = create_or_find_student("Existing Student", old_db_path)
        with sqlite3.connect(old_db_path) as db:
            db.execute("DROP TABLE activity_progress")

        init_db(old_db_path)

        with connect(old_db_path) as db:
            saved_student = db.execute(
                "SELECT display_name FROM students WHERE id = ?", (existing_student["id"],)
            ).fetchone()["display_name"]
            activity_table = db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'activity_progress'"
            ).fetchone()
        self.assertEqual(saved_student, "Existing Student")
        self.assertIsNotNone(activity_table)

    def test_activity_can_be_completed_idempotently_and_reopened(self):
        student = create_or_find_student("Activity Student", self.db_path)
        activity_id = "beginner_shadow_mentor"

        self.assertTrue(set_activity_complete(student["id"], activity_id, True, self.db_path))
        self.assertTrue(set_activity_complete(student["id"], activity_id, True, self.db_path))
        with connect(self.db_path) as db:
            row_count = db.execute(
                "SELECT COUNT(*) AS count FROM activity_progress WHERE student_id = ? AND activity_id = ?",
                (student["id"], activity_id),
            ).fetchone()["count"]
        self.assertEqual(row_count, 1)
        self.assertTrue(activity_progress(student["id"], self.db_path)[activity_id])

        self.assertTrue(set_activity_complete(student["id"], activity_id, False, self.db_path))
        self.assertFalse(activity_progress(student["id"], self.db_path)[activity_id])

    def test_unknown_activity_and_missing_student_are_rejected(self):
        student = create_or_find_student("Safe Student", self.db_path)

        self.assertFalse(set_activity_complete(student["id"], "unknown_activity", True, self.db_path))
        self.assertFalse(set_activity_complete(999999, "beginner_shadow_mentor", True, self.db_path))
        self.assertFalse(set_activity_complete("bad", "beginner_shadow_mentor", True, self.db_path))
        self.assertFalse(set_activity_complete(student["id"], "beginner_shadow_mentor", "yes", self.db_path))
        self.assertEqual(activity_progress("bad", self.db_path), {})
        with connect(self.db_path) as db:
            count = db.execute("SELECT COUNT(*) AS count FROM activity_progress").fetchone()["count"]
        self.assertEqual(count, 0)

    def test_stale_activity_rows_are_ignored(self):
        student = create_or_find_student("Stale Student", self.db_path)
        with connect(self.db_path) as db:
            db.execute(
                """
                INSERT INTO activity_progress (student_id, activity_id, completed, completed_at, updated_at)
                VALUES (?, 'retired_activity', 1, NULL, '2026-01-01T00:00:00+00:00')
                """,
                (student["id"],),
            )

        self.assertEqual(activity_progress(student["id"], self.db_path), {})


class TrainingPathActivityValidationTests(unittest.TestCase):
    def _path_data(self, activities):
        return {
            "levels": [
                {
                    "slug": "test_path",
                    "label": "Test Path",
                    "min_score": 0,
                    "max_score": 100,
                    "recommended_path": "Test path",
                    "required_items": activities,
                }
            ]
        }

    def test_activity_id_is_required_and_must_use_stable_format(self):
        missing = validate_training_paths(
            self._path_data([{"type": "activity", "label": "Mentor check-in"}])
        )
        malformed = validate_training_paths(
            self._path_data([{"type": "activity", "id": "Mentor Check In", "label": "Mentor check-in"}])
        )

        self.assertTrue(any("missing required field: id" in error for error in missing))
        self.assertTrue(any("invalid activity id: Mentor Check In" in error for error in malformed))

    def test_duplicate_activity_ids_are_rejected(self):
        errors = validate_training_paths(
            self._path_data(
                [
                    {"type": "activity", "id": "same_activity", "label": "First"},
                    {"type": "activity", "id": "same_activity", "label": "Second"},
                ]
            )
        )

        self.assertTrue(any("duplicate activity id: same_activity" in error for error in errors))


class ProgressAwareContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "continuation.sqlite"
        self.app = create_app({"TESTING": True, "LAUNCHPAD_DB_PATH": str(self.db_path)})
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _student_with_score(self, name, score):
        student = create_or_find_student(name, self.db_path)
        save_assessment_result(
            student["id"],
            "pre_assessment_v1",
            "pre",
            {"score": score, "path_label": "Saved", "recommended_path": "Saved recommendation"},
            {},
            self.db_path,
        )
        self.client.post("/student", data={"display_name": name})
        return student

    def _complete_checklist(self, student_id, checklist_id="day_1"):
        items = extract_checklist_items(read_checklist_markdown(checklist_id))
        for index in range(len(items)):
            save_checklist_progress(student_id, checklist_id, str(index), True, self.db_path)

    def test_first_unfinished_item_moves_across_checklist_activity_and_module(self):
        student = self._student_with_score("Mixed Student", 75)
        self._complete_checklist(student["id"])

        first = self.client.get("/student")
        self.assertIn(b"Your Next Step: Department expectations review", first.data)
        self.assertIn(b"#activity-ready_to_shadow_department_expectations", first.data)

        set_activity_complete(
            student["id"], "ready_to_shadow_department_expectations", True, self.db_path
        )
        second = self.client.get("/student")
        self.assertIn(b"Your Next Step: Confidentiality basics review", second.data)

        set_activity_complete(
            student["id"], "ready_to_shadow_confidentiality_review", True, self.db_path
        )
        third = self.client.get("/student")
        self.assertIn(b"Your Next Step: Computer Imaging Overview", third.data)
        self.assertIn(b'href="/modules/imaging_overview"', third.data)

    def test_fully_completed_path_shows_completion_state(self):
        student = self._student_with_score("Complete Student", 0)
        for module_id in (
            "what_does_it_do",
            "common_it_words",
            "domain_basics",
            "configuration_manager_overview",
            "imaging_overview",
            "ticket_basics",
            "asset_tag_basics",
            "hardware_basics",
            "how_to_ask_for_help",
            "escalation_rules",
        ):
            mark_module_complete(student["id"], module_id, True, self.db_path)
        self._complete_checklist(student["id"])
        set_activity_complete(student["id"], "beginner_shadow_mentor", True, self.db_path)

        response = self.client.get("/student")

        self.assertIn(b"Required steps recorded", response.data)
        self.assertIn(b"Beginner path", response.data)
        self.assertIn(b"not mentor-confirmed readiness", response.data)
        self.assertNotIn(b"Continue with", response.data)

        home = self.client.get("/")
        self.assertIn(b"Review onboarding", home.data)
        self.assertIn(b"Required steps recorded", home.data)
        self.assertIn(b"Beginner path", home.data)
        # Completion offers a concrete follow-up instead of looping back to Progress.
        self.assertIn(b'<a class="button primary" href="/post-assessment">Take the Progress Check</a>', home.data)
        self.assertIn(b"This app does not record mentor sign-off", home.data)

    def test_unknown_and_stale_activity_progress_cannot_skip_required_activity(self):
        student = self._student_with_score("Stale Path Student", 75)
        self._complete_checklist(student["id"])
        with connect(self.db_path) as db:
            db.execute(
                """
                INSERT INTO activity_progress (student_id, activity_id, completed, completed_at, updated_at)
                VALUES (?, 'old_department_review', 1, NULL, '2026-01-01T00:00:00+00:00')
                """,
                (student["id"],),
            )

        response = self.client.get("/student")
        rejected = self.client.post(
            "/training-path/ready_to_shadow/activities/old_department_review",
            data={"completed": "1"},
        )

        self.assertIn(b"Your Next Step: Department expectations review", response.data)
        self.assertEqual(rejected.status_code, 404)

    def test_malformed_and_out_of_range_saved_scores_fall_back_safely(self):
        for name, score in (("Malformed Score", "not-a-score"), ("Unknown Score", 101)):
            with self.subTest(score=score):
                self._student_with_score(name, score)
                response = self.client.get("/student")
                self.assertIn(b"Find Your Starting Path", response.data)
                self.assertIn(b'href="/pre-assessment"', response.data)

    def test_post_assessment_uses_existing_assessment_progress(self):
        student = self._student_with_score("Assessment Student", 90)
        self._complete_checklist(student["id"])
        for activity_id in (
            "advanced_beginner_department_expectations",
            "advanced_beginner_confidentiality_review",
            "advanced_beginner_scenario_practice",
            "advanced_beginner_mentor_check_in",
        ):
            set_activity_complete(student["id"], activity_id, True, self.db_path)
        mark_module_complete(student["id"], "imaging_overview", True, self.db_path)
        mark_module_complete(student["id"], "escalation_rules", True, self.db_path)

        before = self.client.get("/student")
        self.assertIn(b"Your Next Step: Progress Check", before.data)
        self.assertIn(b'href="/post-assessment"', before.data)

        save_assessment_result(
            student["id"],
            "post_assessment_v1",
            "post",
            {"score": 50, "readiness_label": "Developing"},
            {},
            self.db_path,
        )
        after = self.client.get("/student")
        self.assertIn(b"Required steps recorded", after.data)
        self.assertIn(b"Advanced Beginner path", after.data)
        self.assertIn(b"not mentor-confirmed readiness", after.data)

    def test_activity_control_requires_explicit_post_and_can_reopen(self):
        student = self._student_with_score("Control Student", 75)
        activity_id = "ready_to_shadow_department_expectations"

        viewed = self.client.get("/training-path/ready_to_shadow")
        self.assertEqual(activity_progress(student["id"], self.db_path), {})
        self.assertIn(b"Mark Activity Complete", viewed.data)

        completed = self.client.post(
            f"/training-path/ready_to_shadow/activities/{activity_id}",
            data={"completed": "1"},
        )
        self.assertEqual(completed.status_code, 302)
        self.assertTrue(activity_progress(student["id"], self.db_path)[activity_id])

        reopened = self.client.post(
            f"/training-path/ready_to_shadow/activities/{activity_id}",
            data={"completed": "0"},
        )
        self.assertEqual(reopened.status_code, 302)
        self.assertFalse(activity_progress(student["id"], self.db_path)[activity_id])


if __name__ == "__main__":
    unittest.main()
