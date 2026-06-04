import tempfile
import unittest
from pathlib import Path

from launchpad import create_app
from launchpad.assessment import get_training_path, load_assessment, score_assessment
from launchpad.storage import (
    checklist_progress,
    connect,
    create_or_find_student,
    init_db,
    latest_assessment_result,
    mark_module_complete,
    module_is_complete,
    save_assessment_result,
    save_checklist_progress,
    save_stuck_report,
    student_progress_summary,
)


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "launchpad.sqlite"
        init_db(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_schema_initialization_is_idempotent(self):
        init_db(self.db_path)

        with connect(self.db_path) as db:
            tables = {
                row["name"]
                for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }

        self.assertIn("students", tables)
        self.assertIn("assessment_results", tables)
        self.assertIn("module_progress", tables)
        self.assertIn("checklist_progress", tables)
        self.assertIn("stuck_reports", tables)

    def test_create_or_find_student_reuses_display_name(self):
        student = create_or_find_student("Alex Student", self.db_path)
        same_student = create_or_find_student("alex student", self.db_path)

        self.assertEqual(student["id"], same_student["id"])
        self.assertEqual(same_student["display_name"], "Alex Student")

    def test_assessment_role_alignment_and_progress_are_saved(self):
        student = create_or_find_student("Jordan", self.db_path)
        assessment = load_assessment("pre_assessment_v1")
        answers = {
            "ra1": "B",
            "ra2": "C",
            "ra3": "A",
            "ra4": "B",
            "ra5": "B",
            "ra6": "B",
            "ra7": "B",
        }
        result = score_assessment(assessment, answers)
        path = get_training_path(result["score"])
        result["path_label"] = path["label"]
        result["recommended_path"] = path["recommended_path"]

        save_assessment_result(student["id"], assessment["id"], "pre", result, answers, self.db_path)
        saved = latest_assessment_result(student["id"], "pre", self.db_path)

        self.assertEqual(saved["assessment_id"], "pre_assessment_v1")
        self.assertEqual(saved["role_alignment_recommendation"], "Hybrid IT/User Support")
        self.assertEqual(saved["answers"]["ra3"], "A")
        self.assertEqual(saved["role_alignment_summary"]["recommended_alignment"]["slug"], "hybrid_it_user_support")

    def test_module_checklist_and_stuck_progress_are_saved(self):
        student = create_or_find_student("Riley", self.db_path)

        mark_module_complete(student["id"], "hardware_basics", True, self.db_path)
        save_checklist_progress(student["id"], "day_1", "0", True, self.db_path)
        save_stuck_report(
            student["id"],
            {
                "topic": "monitor issue",
                "trying_to_do": "Check the front desk monitor",
                "what_happened": "It still said No Signal",
                "already_checked": "Power and cable",
                "current_blocker": "Need next approved step",
                "related_item": "Hardware Basics",
            },
            "Mentor-ready summary",
            self.db_path,
        )

        summary = student_progress_summary(self.db_path)[0]

        self.assertTrue(module_is_complete(student["id"], "hardware_basics", self.db_path))
        self.assertTrue(checklist_progress(student["id"], "day_1", self.db_path)["0"])
        self.assertEqual(summary["module_completed_count"], 1)
        self.assertEqual(summary["checklist_completed_count"], 1)
        self.assertEqual(summary["stuck_report_count"], 1)

    def test_supervisor_overview_loads_persisted_progress(self):
        student = create_or_find_student("Morgan", self.db_path)
        mark_module_complete(student["id"], "hardware_basics", True, self.db_path)

        app = create_app({"TESTING": True, "LAUNCHPAD_DB_PATH": str(self.db_path)})
        client = app.test_client()

        response = client.get("/supervisor")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Recent Student Progress", response.data)
        self.assertIn(b"Morgan", response.data)
        self.assertIn(b"Modules complete: 1", response.data)

    def test_web_progress_forms_create_demo_student_and_summary_counts(self):
        app = create_app({"TESTING": True, "LAUNCHPAD_DB_PATH": str(self.db_path)})
        client = app.test_client()

        module_response = client.post("/modules/hardware_basics", data={"completed": "1"})
        checklist_response = client.post(
            "/checklists/day_1",
            data={"completed_items": ["0", "1"]},
        )
        stuck_response = client.post(
            "/stuck",
            data={
                "topic": "monitor issue",
                "trying_to_do": "check a training monitor",
                "what_happened": "it still showed No Signal",
                "already_checked": "power and cable",
                "current_blocker": "need the next approved step",
                "related_item": "Hardware Basics",
            },
        )

        summary = student_progress_summary(self.db_path)

        self.assertEqual(module_response.status_code, 302)
        self.assertEqual(checklist_response.status_code, 302)
        self.assertEqual(stuck_response.status_code, 200)
        self.assertEqual(len(summary), 1)
        self.assertTrue(summary[0]["student"]["display_name"].startswith("Demo Student "))
        self.assertEqual(summary[0]["module_completed_count"], 1)
        self.assertEqual(summary[0]["checklist_completed_count"], 2)
        self.assertEqual(summary[0]["stuck_report_count"], 1)


if __name__ == "__main__":
    unittest.main()
