"""Mentor growth comparison uses recorded values only and never changes learner data."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from launchpad.accounts import assign_mentor, create_auth_session, enroll_account
from launchpad.assessment import MATCHED_CONFIDENCE_QUESTION, all_questions, assessment_growth, load_assessment
from launchpad.real_data import initialize_real_database
from launchpad.storage import connect, save_assessment_result
from launchpad.web import create_app


def saved(assessment_id, score, answers=None, created_at="2026-10-01T10:00:00+00:00"):
    return {"assessment_id": assessment_id, "technical_score": score, "answers": answers or {}, "created_at": created_at}


class AssessmentGrowthTests(unittest.TestCase):
    def test_matched_confidence_question_is_identical_in_current_content(self):
        prompts = []
        for side in ("pre", "post"):
            assessment_id, question_id = MATCHED_CONFIDENCE_QUESTION[side]
            question = {item["id"]: item for item in all_questions(load_assessment(assessment_id))}[question_id]
            self.assertEqual(question["type"], "rating")
            self.assertEqual(sorted(question["score_map"]), ["1", "2", "3", "4", "5"])
            prompts.append(question["prompt"])
        self.assertEqual(prompts[0], prompts[1])

    def test_needs_both_results(self):
        pre = saved("pre_assessment_v1", 50)
        self.assertIsNone(assessment_growth(pre, None))
        self.assertIsNone(assessment_growth(None, saved("post_assessment_v1", 70)))

    def test_reports_recorded_score_and_matched_rating_changes(self):
        growth = assessment_growth(
            saved("pre_assessment_v1", 55, {"q6": "2"}),
            saved("post_assessment_v1", 70, {"q1": "4"}, "2026-10-08T10:00:00+00:00"),
        )
        self.assertTrue(growth["comparable"])
        self.assertEqual((growth["pre_score"], growth["post_score"], growth["score_change"]), (55, 70, 15))
        self.assertEqual((growth["confidence"]["pre"], growth["confidence"]["post"]), (2, 4))
        self.assertEqual(growth["confidence"]["change"], 2)

    def test_progress_check_older_than_starting_point_is_not_compared(self):
        growth = assessment_growth(
            saved("pre_assessment_v1", 55, created_at="2026-10-09T10:00:00+00:00"),
            saved("post_assessment_v1", 90, created_at="2026-10-08T10:00:00+00:00"),
        )
        self.assertEqual(growth["comparable"], False)
        self.assertNotIn("score_change", growth)

    def test_missing_or_invalid_recorded_values_are_unavailable_not_zero(self):
        # (pre score, pre rating, pre assessment id, expected score change, expected rating change)
        for pre_score, pre_rating, assessment_id, score_change, rating_change in (
            (None, "2", "pre_assessment_v1", None, 2),
            (True, "9", "pre_assessment_v1", None, None),
            ("55", True, "pre_assessment_v1", None, None),
            (55, "not a rating", "pre_assessment_v1", 15, None),
            (55, "2", "pre_assessment_v2", 15, None),
        ):
            with self.subTest(pre_score=pre_score, pre_rating=pre_rating, assessment_id=assessment_id):
                growth = assessment_growth(
                    saved(assessment_id, pre_score, {"q6": pre_rating}),
                    saved("post_assessment_v1", 70, {"q1": "4"}, "2026-10-08T10:00:00+00:00"),
                )
                self.assertTrue(growth["comparable"])
                self.assertEqual(growth["score_change"], score_change)
                self.assertEqual(growth["confidence"] and growth["confidence"]["change"], rating_change)


class MentorGrowthViewTests(unittest.TestCase):
    origin = "https://launchpad.example.invalid"

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="mentor-growth-", dir="/tmp")
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "synthetic.sqlite"
        initialize_real_database(self.database)
        issuer = "https://identity.example.invalid"
        self.learner = enroll_account(issuer, "invented-learner", "Invented learner", db_path=self.database)
        self.mentor = enroll_account(issuer, "invented-mentor", role="mentor", db_path=self.database)
        assign_mentor(self.mentor["id"], self.learner["learner_id"], self.database)
        self.app = create_app({
            "TESTING": True, "SECRET_KEY": "synthetic-growth-test-signing-key-at-least-32-characters",
            "LAUNCHPAD_REAL_MODE": True, "LAUNCHPAD_DEMO_MODE": False, "LAUNCHPAD_PILOT_MODE": False,
            "LAUNCHPAD_DB_PATH": str(self.database), "LAUNCHPAD_TRUSTED_HOSTS": "launchpad.example.invalid",
            "LAUNCHPAD_OIDC_ISSUER": issuer, "LAUNCHPAD_OIDC_CLIENT_ID": "invented-client",
            "LAUNCHPAD_OIDC_CLIENT_SECRET": "invented-secret",
            "LAUNCHPAD_OIDC_REDIRECT_URI": self.origin + "/auth/callback", "LAUNCHPAD_OIDC_CLIENT": object(),
        })
        self.client = self.app.test_client()
        token = create_auth_session(self.mentor["id"], self.database)
        with self.client.session_transaction(base_url=self.origin) as session:
            session["auth_session"] = token

    def save(self, kind, score, answers):
        return save_assessment_result(
            self.learner["learner_id"], f"{kind}_assessment_v1", kind, {"score": score}, answers, self.database,
        )

    def set_saved_at(self, result_id, created_at):
        with connect(self.database) as db:
            db.execute("UPDATE assessment_results SET created_at = ? WHERE id = ?", (created_at, result_id))

    def get(self, path):
        response = self.client.get(path, base_url=self.origin)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def detail(self):
        return self.get(f"/supervisor/learners/{self.learner['learner_id']}")

    def snapshot(self):
        with connect(self.database) as db:
            return [tuple(row) for row in db.execute("SELECT * FROM assessment_results ORDER BY id")]

    def test_detail_and_overview_show_recorded_growth_without_rescoring_or_mutation(self):
        self.set_saved_at(self.save("pre", 55, {"q6": "2"}), "2026-10-01T10:00:00+00:00")
        self.set_saved_at(self.save("post", 70, {"q1": "4"}), "2026-10-08T10:00:00+00:00")
        before = self.snapshot()
        with patch("launchpad.web.score_assessment", side_effect=AssertionError("No historical rescore")):
            markup = self.detail()
            overview = self.get("/supervisor")
        for text in ("Starting Point and Progress Check", "55% to 70% (+15 percentage points)",
                     "2 to 4 (+2 on the 1-5 scale)", "Self-reported confidence", "how the learner rated themselves", "not a validated measure of learning growth", "not as readiness sign-off",
                     "2026-10-01T10:00:00+00:00", "2026-10-08T10:00:00+00:00"):
            self.assertIn(text, markup)
        self.assertIn("Score difference from starting point: +15 points (different questions; descriptive only)", overview)
        self.assertNotIn("Starting Point and Progress Check", overview)
        self.assertEqual(self.snapshot(), before)

    def test_decline_and_no_change_are_stated_plainly(self):
        self.save("pre", 80, {"q6": "3"})
        self.save("post", 72, {"q1": "3"})
        markup = self.detail()
        self.assertIn("80% to 72% (-8 percentage points)", markup)
        self.assertIn("3 to 3 (No change)", markup)

    def test_missing_progress_check_or_out_of_order_results_show_no_comparison(self):
        pre_id = self.save("pre", 55, {"q6": "2"})
        self.assertIn("A comparison appears after the learner has saved both", self.detail())
        post_id = self.save("post", 90, {"q1": "5"})
        self.set_saved_at(post_id, "2026-10-08T10:00:00+00:00")
        self.set_saved_at(pre_id, "2026-10-09T10:00:00+00:00")
        markup = self.detail()
        self.assertIn("saved before the latest starting point check, so no comparison is shown", markup)
        self.assertNotIn("percentage points", markup)
        self.assertNotIn("Score difference from starting point", self.get("/supervisor"))

    def test_missing_recorded_score_is_unavailable_not_zero(self):
        self.save("pre", None, {"q6": "2"})
        self.save("post", 70, {"q1": "4"})
        markup = self.detail()
        self.assertIn("Not available because a recorded score is missing", markup)
        self.assertIn("2 to 4", markup)
        self.assertNotIn("Score difference from starting point", self.get("/supervisor"))


class DemoMentorGrowthTests(unittest.TestCase):
    def test_demo_supervisor_compares_synthetic_learner_check_ins(self):
        directory = tempfile.TemporaryDirectory(prefix="demo-growth-", dir="/tmp")
        self.addCleanup(directory.cleanup)
        app = create_app({"TESTING": True, "LAUNCHPAD_DB_PATH": str(Path(directory.name) / "demo.sqlite")})
        client = app.test_client()
        self.assertEqual(client.post("/pre-assessment", data={"q6": "2"}, follow_redirects=True).status_code, 200)
        self.assertEqual(client.post("/post-assessment", data={"q1": "5"}).status_code, 200)
        markup = client.get("/supervisor").get_data(as_text=True)
        self.assertIn("Starting Point and Progress Check", markup)
        self.assertIn("2 to 5 (+3 on the 1-5 scale)", markup)
        self.assertIn("Score difference from starting point:", markup)


if __name__ == "__main__":
    unittest.main()
