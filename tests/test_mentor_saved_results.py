"""Mentor review uses stored values without rescoring or changing learner data."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from launchpad.accounts import assign_mentor, create_auth_session, enroll_account
from launchpad.assessment import load_assessment, score_assessment
from launchpad.real_data import initialize_real_database
from launchpad.storage import connect, save_assessment_result
from launchpad.web import create_app


class MentorSavedResultsTests(unittest.TestCase):
    origin = "https://launchpad.example.invalid"

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="mentor-saved-results-", dir="/tmp")
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "synthetic.sqlite"
        initialize_real_database(self.database)
        issuer = "https://identity.example.invalid"
        self.learner = enroll_account(issuer, "invented-learner", "Invented learner", db_path=self.database)
        self.other = enroll_account(issuer, "invented-other", "Other invented learner", db_path=self.database)
        self.mentor = enroll_account(issuer, "invented-mentor", role="mentor", db_path=self.database)
        assign_mentor(self.mentor["id"], self.learner["learner_id"], self.database)
        self.app = create_app({
            "TESTING": True, "SECRET_KEY": "synthetic-mentor-test-signing-key-at-least-32-characters",
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

    def save(self, result=None, answers=None, kind="pre", assessment_id=None, learner=None):
        return save_assessment_result(
            (learner or self.learner)["learner_id"], assessment_id or f"{kind}_assessment_v1", kind,
            result or {}, answers or {}, self.database,
        )

    def detail(self):
        return self.client.get(f"/supervisor/learners/{self.learner['learner_id']}", base_url=self.origin)

    def snapshot(self):
        with connect(self.database) as db:
            return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id")]
                    for table in ("students", "assessment_results", "module_progress", "module_quiz_results",
                                  "checklist_progress", "activity_progress", "stuck_reports", "scenario_attempts")}

    def test_uses_saved_score_and_recommendations_without_rescoring_or_mutation(self):
        self.save({
            "score": 73, "path_label": "Recorded prior level", "recommended_path": "Recorded prior path",
            "role_alignment": {"title": "Recorded work style", "recommended_alignment": {
                "label": "Recorded alignment", "summary": "Recorded historical summary"},
                "signals": [{"label": "Recorded signal", "score": 2, "possible": 9, "level": "Recorded level"}]},
        }, {"q1": "A", "q3": "Saved written response"})
        self.save({"score": 41, "readiness_label": "Recorded progress readiness"}, {"q1": "B"}, kind="post")
        before = self.snapshot()
        with patch("launchpad.web.score_assessment", side_effect=AssertionError("Historical results must not be rescored")):
            response = self.detail()
        self.assertEqual(response.status_code, 200)
        markup = response.get_data(as_text=True)
        for value in ("73%", "Recorded prior level", "Recorded prior path", "Recorded alignment",
                      "Recorded historical summary", "Recorded signal: 2 / 9", "41%",
                      "Recorded progress readiness", "pre_assessment_v1", "Saved written response"):
            self.assertIn(value, markup)
        self.assertIn("Saved:", markup)
        self.assertIn("These results have not been rescored", markup)
        self.assertEqual(self.snapshot(), before)

    def test_missing_details_are_unavailable_and_missing_post_is_not_a_zero_score(self):
        self.save()
        markup = self.detail().get_data(as_text=True)
        for text in ("Score not recorded", "Role-alignment detail was not recorded",
                     "No answer details were recorded", "point totals, and per-answer correctness were not stored",
                     "Reviewer feedback and manual scores are not stored",
                     "No progress check result is saved"):
            self.assertIn(text, markup)
        self.assertNotIn("None%", markup)
        self.assertNotIn("0%", markup)

    def test_recorded_alignment_uses_real_saved_schema_and_historical_role_labels(self):
        answers = {"ra1": "B", "ra2": "C", "ra3": "A", "ra4": "B", "ra5": "B", "ra6": "B", "ra7": "B"}
        result = score_assessment(load_assessment("pre_assessment_v1"), answers)
        alignment = result["role_alignment"]
        alignment["question_results"][0]["prompt"] = "Recorded historical role question"
        alignment["question_results"][0]["selected_label"] = "Recorded historical role answer label"
        self.save(result, answers)
        with patch("launchpad.web.score_assessment", side_effect=AssertionError("No historical rescore")):
            response = self.detail()
        self.assertEqual(response.status_code, 200)
        markup = response.get_data(as_text=True)
        for text in (alignment["recommended_alignment"]["label"], alignment["mentor_note"],
                     *alignment["recommended_alignment"]["next_steps"],
                     "Recorded historical role question", "Recorded historical role answer label",
                     "Recorded question label", "Recorded option label"):
            self.assertIn(text, markup)
        for signal in alignment["signals"]:
            self.assertIn(f"{signal['label']}: {signal['score']} / {signal['possible']}", markup)

    def test_saved_values_are_escaped_and_unknown_question_answers_are_preserved(self):
        self.save({"score": 0, "recommended_path": '<img src=x onerror="alert(1)">'}, {
            "q3": '<script>alert("saved")</script>\nsecond line',
            "retired_question": "kept historical answer", "q2": ["A", "B"],
        })
        markup = self.detail().get_data(as_text=True)
        self.assertIn("0%", markup)
        self.assertIn("&lt;script&gt;", markup)
        self.assertIn("&lt;img", markup)
        self.assertNotIn('<script>alert("saved")</script>', markup)
        self.assertNotIn('<img src=x', markup)
        self.assertIn("second line", markup)
        self.assertIn("retired_question", markup)
        self.assertIn("kept historical answer", markup)
        self.assertIn("Question label unavailable", markup)
        self.assertIn("[&#34;A&#34;, &#34;B&#34;]", markup)
        self.assertIn("labels come from current assessment content", markup)

    def test_unavailable_historical_definition_keeps_saved_results_readable(self):
        self.save({"score": 64}, {"old_q1": "Historical response"}, assessment_id="retired_assessment_v0")
        response = self.detail()
        self.assertEqual(response.status_code, 200)
        markup = response.get_data(as_text=True)
        self.assertIn("64%", markup)
        self.assertIn("retired_assessment_v0", markup)
        self.assertIn("Historical response", markup)
        self.assertIn("Question label unavailable", markup)

    def test_assessment_details_stay_with_assigned_learner(self):
        self.save({"score": 73}, {"q3": "Assigned-only private answer"})
        self.save({"score": 92}, {"q3": "Unassigned private answer"}, learner=self.other)
        response = self.detail()
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Assigned-only private answer", response.data)
        self.assertNotIn(b"Unassigned private answer", response.data)
        denied = self.client.get(f"/supervisor/learners/{self.other['learner_id']}", base_url=self.origin)
        missing = self.client.get("/supervisor/learners/999999", base_url=self.origin)
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(denied.data, missing.data)


if __name__ == "__main__":
    unittest.main()
