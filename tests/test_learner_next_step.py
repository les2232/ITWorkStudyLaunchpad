"""Learner next-step guidance: purpose, three-state status, help requests and completion follow-up.

All learners are invented and every database is disposable. These checks use
server-rendered HTML; they do not establish rendered-browser or screen-reader QA.
"""
from pathlib import Path
import tempfile
import unittest

from launchpad.accounts import create_auth_session, enroll_account
from launchpad.content import extract_checklist_items, load_json, read_checklist_markdown
from launchpad.real_data import initialize_real_database
from launchpad.storage import (
    create_or_find_student, mark_module_complete, save_assessment_result, save_checklist_progress,
    save_module_quiz_result, save_stuck_report, set_activity_complete,
)
from launchpad.web import _campus_time, create_app
from scripts.validate_content import validate_modules, validate_training_paths
from tests.test_ux_navigation import Page


def path_by_slug(slug):
    return next(path for path in load_json("training_paths.json")["levels"] if path["slug"] == slug)


def module_by_slug(slug):
    return next(module for module in load_json("modules.json") if module["slug"] == slug)


class LearnerNextStepTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="learner-next-step-")
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / "synthetic.sqlite"
        self.app = create_app({"TESTING": True, "LAUNCHPAD_DEMO_MODE": False, "LAUNCHPAD_DB_PATH": str(self.db_path)})
        self.client = self.app.test_client()

    def learner(self, name="SYN Next Step", score=0):
        self.client.post("/student", data={"display_name": name})
        student_id = create_or_find_student(name, self.db_path)["id"]
        if score is not None:
            save_assessment_result(student_id, "pre_assessment_v1", "pre", {"score": score}, {}, self.db_path)
        return student_id

    def page(self, route):
        response = self.client.get(route)
        self.assertEqual(response.status_code, 200, route)
        return Page(response)

    def complete_path(self, student_id, path):
        for item in path["required_items"]:
            if item["type"] == "module":
                mark_module_complete(student_id, item["slug"], True, self.db_path)
            elif item["type"] == "checklist":
                for index, _ in enumerate(extract_checklist_items(read_checklist_markdown(item["slug"]))):
                    save_checklist_progress(student_id, item["slug"], str(index), True, self.db_path)
            elif item["type"] == "activity":
                set_activity_complete(student_id, item["id"], True, self.db_path)

    def test_next_step_explains_what_it_is_and_why_it_matters_on_every_learner_page(self):
        self.learner()
        module = module_by_slug("what_does_it_do")
        for route, panel_id in (("/", "home-next-action"), ("/student", "progress-next-action"),
                                ("/learn", None), ("/training-path/beginner", "current-step")):
            with self.subTest(route=route):
                page = self.page(route)
                panel = page.find(id=panel_id)[0] if panel_id else page.find("section", **{"class": "focus-panel"})[0]
                for text in (module["title"], module["summary"], "Why it matters:", module["purpose"], "Not started"):
                    self.assertIn(text, panel.label)
                self.assertEqual(len(page.primary(panel)), 1)

    def test_partial_checklist_is_in_progress_without_changing_completion(self):
        student_id = self.learner(score=50)
        total = len(extract_checklist_items(read_checklist_markdown("day_1")))
        for index in range(3):
            save_checklist_progress(student_id, "day_1", str(index), True, self.db_path)
        home = self.page("/")
        focus = home.find(id="home-next-action")[0]
        self.assertIn("Next: Day 1 Checklist", focus.label)
        self.assertIn(f"In progress 3 of {total} items checked", focus.label)
        self.assertEqual(home.find("progress", id="home-path-progress")[0].attrs["value"], "0")
        badges = [node.label for node in self.page("/training-path/developing").find("span")
                  if "status-badge--in-progress" in node.attrs.get("class", "")]
        self.assertIn("In progress", badges)

    def test_saved_knowledge_check_marks_unread_module_in_progress_but_not_complete(self):
        student_id = self.learner()
        save_module_quiz_result(student_id, "what_does_it_do", {"score": 100, "answers": []}, self.db_path)
        focus = self.page("/").find(id="home-next-action")[0]
        self.assertIn("Next: What Does IT Do?", focus.label)
        self.assertIn("In progress Knowledge check saved", focus.label)
        mark_module_complete(student_id, "what_does_it_do", True, self.db_path)
        page = self.page("/training-path/beginner")
        recorded = page.find("details", id="completed-steps")[0]
        self.assertIn("Completed", recorded.label)
        self.assertIn("Next: Common IT Words", self.page("/").find(id="home-next-action")[0].label)

    def test_status_labels_are_text_and_completed_steps_drop_purpose(self):
        student_id = self.learner()
        mark_module_complete(student_id, "what_does_it_do", True, self.db_path)
        page = self.page("/training-path/beginner")
        labels = {node.label for node in page.find("span") if "status-badge" in node.attrs.get("class", "")}
        self.assertEqual(labels, {"Not started", "Completed"})
        recorded = page.find("details", id="completed-steps")[0]
        self.assertNotIn("Why it matters", recorded.label)
        remaining = page.find("details", id="remaining-steps")[0]
        self.assertIn(module_by_slug("domain_basics")["purpose"], remaining.label)
        self.assertIn(path_by_slug("beginner")["required_items"][-1]["purpose"], remaining.label)

    def test_help_request_is_shown_with_campus_time_and_escaped_text(self):
        student_id = self.learner()
        for route in ("/", "/student", "/help"):
            self.assertFalse(self.page(route).find(id="help-request-status"), route)
        report_id = save_stuck_report(student_id, {"topic": "Invented <b>topic</b>"},
                                      "Topic: Invented <b>topic</b>\n<script>alert(1)</script>", self.db_path)
        from launchpad.storage import connect
        with connect(self.db_path) as db:
            db.execute("UPDATE stuck_reports SET created_at = ? WHERE id = ?", ("2026-10-19T22:02:42+00:00", report_id))
        for route in ("/", "/student", "/help"):
            with self.subTest(route=route):
                markup = self.client.get(route).get_data(as_text=True)
                section = Page(self.client.get(route)).find(id="help-request-status")[0]
                self.assertIn("saved Oct 19, 2026, 4:02 PM MDT", section.label)
                self.assertIn("1 open request", section.label)
                self.assertIn("does not send it or notify anyone", section.label)
                self.assertIn("&lt;script&gt;", markup)
                self.assertNotIn("<script>alert(1)</script>", markup)
        other = create_or_find_student("SYN Other Learner", self.db_path)
        self.client.post("/student", data={"display_name": other["display_name"]})
        self.assertFalse(self.page("/").find(id="help-request-status"))

    def test_completed_path_follow_up_walks_through_concrete_actions(self):
        student_id = self.learner()
        path = path_by_slug("beginner")
        self.complete_path(student_id, path)

        def home_action():
            page = self.page("/")
            focus = page.find(id="home-next-action")[0]
            actions = page.primary(focus)
            self.assertEqual(len(actions), 1)
            self.assertIn("Required steps recorded", focus.label)
            self.assertIn("This app does not record mentor sign-off", focus.label)
            return focus.label, (actions[0].label, actions[0].attrs["href"])

        label, action = home_action()
        self.assertEqual(action, ("Take the Progress Check", "/post-assessment"))
        self.assertIn("Not started Knowledge checks 0 of 10 saved.", label)

        save_assessment_result(student_id, "post_assessment_v1", "post", {"score": 70}, {}, self.db_path)
        save_module_quiz_result(student_id, "what_does_it_do", {"score": 100, "answers": []}, self.db_path)
        label, action = home_action()
        self.assertEqual(action, ("Knowledge check: Common IT Words", "/modules/common_it_words/quiz"))
        self.assertIn("Completed Progress Check Saved.", label)
        self.assertIn("In progress Knowledge checks 1 of 10 saved.", label)

        for item in path["required_items"]:
            if item["type"] == "module":
                save_module_quiz_result(student_id, item["slug"], {"score": 100, "answers": []}, self.db_path)
        label, action = home_action()
        self.assertEqual(action, ("Practice a scenario", "/scenarios"))
        for route, panel_id in (("/student", "progress-next-action"), ("/training-path/beginner", "current-step")):
            page = self.page(route)
            panel = page.find(id=panel_id)[0]
            self.assertEqual([(a.label, a.attrs["href"]) for a in page.primary(panel)], [action])

    def test_home_follow_up_heading_does_not_skip_levels(self):
        student_id = self.learner()
        self.complete_path(student_id, path_by_slug("beginner"))
        page = self.page("/")
        self.assertEqual([node.label for node in page.find("h2")][0], "What to do now")
        self.assertFalse(page.find("h3", **{"class": "follow-up__heading"}))


class ContentPurposeTests(unittest.TestCase):
    def test_every_step_has_purpose_and_validator_requires_it(self):
        for module in load_json("modules.json"):
            self.assertTrue(module["purpose"].strip(), module["slug"])
        for checklist in load_json("checklists.json"):
            self.assertTrue(checklist["purpose"].strip(), checklist["slug"])
        for path in load_json("training_paths.json")["levels"]:
            for item in path["required_items"]:
                if item["type"] in {"activity", "assessment"}:
                    self.assertTrue(item["purpose"].strip(), item)
        missing = validate_training_paths({"levels": [{
            "slug": "x", "label": "X", "min_score": 0, "max_score": 100, "recommended_path": "x",
            "required_items": [{"type": "activity", "id": "invented_activity", "label": "Invented"}],
        }]})
        self.assertTrue(any("missing required field: purpose" in error for error in missing))
        self.assertEqual(validate_modules(), [])

    def test_campus_time_formats_utc_and_keeps_unreadable_values(self):
        self.assertEqual(_campus_time("2026-10-19T22:02:42+00:00"), "Oct 19, 2026, 4:02 PM MDT")
        self.assertEqual(_campus_time("2026-12-01T07:05:00+00:00"), "Dec 1, 2026, 12:05 AM MST")
        self.assertEqual(_campus_time("not a time"), "not a time")
        self.assertEqual(_campus_time("2026-10-19T09:00:00"), "2026-10-19T09:00:00")


class RealModeHelpRequestIsolationTests(unittest.TestCase):
    origin = "https://launchpad.example.invalid"

    def test_learner_sees_only_their_own_latest_help_request(self):
        directory = tempfile.TemporaryDirectory(prefix="learner-help-isolation-", dir="/tmp")
        self.addCleanup(directory.cleanup)
        database = Path(directory.name) / "synthetic.sqlite"
        initialize_real_database(database)
        issuer = "https://identity.example.invalid"
        learner = enroll_account(issuer, "invented-learner", "Invented learner", db_path=database)
        other = enroll_account(issuer, "invented-other", "Other invented learner", db_path=database)
        save_stuck_report(other["learner_id"], {"topic": "Other learner topic"}, "Topic: Other learner topic", database)
        app = create_app({
            "TESTING": True, "SECRET_KEY": "synthetic-next-step-test-signing-key-at-least-32-chars",
            "LAUNCHPAD_REAL_MODE": True, "LAUNCHPAD_DEMO_MODE": False, "LAUNCHPAD_PILOT_MODE": False,
            "LAUNCHPAD_DB_PATH": str(database), "LAUNCHPAD_TRUSTED_HOSTS": "launchpad.example.invalid",
            "LAUNCHPAD_OIDC_ISSUER": issuer, "LAUNCHPAD_OIDC_CLIENT_ID": "invented-client",
            "LAUNCHPAD_OIDC_CLIENT_SECRET": "invented-secret",
            "LAUNCHPAD_OIDC_REDIRECT_URI": self.origin + "/auth/callback", "LAUNCHPAD_OIDC_CLIENT": object(),
        })
        client = app.test_client()
        token = create_auth_session(learner["id"], database)
        with client.session_transaction(base_url=self.origin) as session:
            session["auth_session"] = token
        for route in ("/", "/student", "/help"):
            response = client.get(route, base_url=self.origin)
            self.assertEqual(response.status_code, 200, route)
            self.assertNotIn("Other learner topic", response.get_data(as_text=True))
        save_stuck_report(learner["learner_id"], {"topic": "Own invented topic"}, "Topic: Own invented topic", database)
        markup = client.get("/", base_url=self.origin).get_data(as_text=True)
        self.assertIn("Own invented topic", markup)
        self.assertNotIn("Other learner topic", markup)


if __name__ == "__main__":
    unittest.main()
