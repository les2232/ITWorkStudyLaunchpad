"""Server-side draft storage preserves full text without sharing learner records."""

import hashlib
import json
import random
import string
import warnings
import sqlite3
import tempfile
import unittest
from pathlib import Path

from launchpad import create_app
from launchpad.assessment import all_questions, load_assessment, score_assessment
from launchpad.demo import (
    DEMO_NOVA_NAME,
    DemoDataError,
    prepare_demo_database,
    synthetic_beginner_responses,
    validate_demo_database,
)
from launchpad.scenarios import is_guided_scenario, list_scenarios
from launchpad.storage import (
    connect,
    create_or_find_student,
    init_db,
    mark_module_complete,
    latest_assessment_result,
    recent_scenario_attempts,
    recent_stuck_reports,
    save_assessment_result,
    save_scenario_attempt,
    save_stuck_report,
    student_progress,
    student_progress_summary,
)
from launchpad.stuck import generate_stuck_summary


class SessionStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = Path(self.tmpdir.name) / "synthetic-session-storage.sqlite"
        init_db(self.db_path)
        self.learner = create_or_find_student("Synthetic Learner One", self.db_path)
        self.other = create_or_find_student("Synthetic Learner Two", self.db_path)

    def test_assessment_lookup_preserves_full_response_and_requires_matching_learner(self):
        assessment = load_assessment("pre_assessment_v1")
        responses = synthetic_beginner_responses()
        responses["q3"] = "Invented practice response — " * 1000
        result = score_assessment(assessment, responses)
        result_id = save_assessment_result(
            self.learner["id"], assessment["id"], "pre", result, responses, self.db_path
        )
        saved = latest_assessment_result(self.learner["id"], "pre", self.db_path)
        self.assertEqual(saved["id"], result_id)
        self.assertEqual(saved["answers"], responses)
        self.assertEqual(saved["technical_score"], result["score"])
        self.assertIsNone(latest_assessment_result(self.other["id"], "pre", self.db_path))
        self.assertIsNone(latest_assessment_result(-1, "pre", self.db_path))

    def test_help_reports_preserve_full_summary_limit_display_and_separate_learners(self):
        ids = []
        summaries = []
        for number in range(12):
            submitted = {
                "student": self.learner["display_name"],
                "topic": f"Invented topic {number}",
                "trying_to_do": "Invented task detail " * 300,
                "what_happened": "A synthetic practice blocker appeared.",
                "already_checked": "Only the invented exercise setup.",
                "current_blocker": "Need mentor guidance in the exercise.",
            }
            summary = generate_stuck_summary(submitted)
            summaries.append(summary)
            ids.append(save_stuck_report(self.learner["id"], submitted, summary, self.db_path))
        save_stuck_report(self.other["id"], {}, "Other learner's invented summary", self.db_path)

        recent = recent_stuck_reports(self.learner["id"], self.db_path)
        self.assertEqual([item["id"] for item in recent], ids[-10:])
        self.assertEqual([item["summary"] for item in recent], summaries[-10:])
        self.assertEqual(recent[-1]["student"], self.learner["display_name"])
        self.assertEqual(recent[-1]["topic"], "Invented topic 11")
        other_reports = recent_stuck_reports(self.other["id"], self.db_path)
        self.assertEqual(len(other_reports), 1)
        self.assertEqual(other_reports[0]["summary"], "Other learner's invented summary")
        with connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM stuck_reports").fetchone()[0], 13)
            first = db.execute("SELECT mentor_summary FROM stuck_reports WHERE id = ?", (ids[0],)).fetchone()[0]
            self.assertEqual(first, summaries[0])

    def test_scenario_drafts_survive_reinitialization_without_truncation_or_cross_learner_leakage(self):
        scenario = list_scenarios()[0]
        drafts = [f"Invented draft {number}: " + "full practice answer — " * 300 for number in range(23)]
        ids = [
            save_scenario_attempt(self.learner["id"], scenario["id"], scenario["title"], draft, self.db_path)
            for draft in drafts
        ]
        save_scenario_attempt(self.other["id"], scenario["id"], scenario["title"], "Other learner draft", self.db_path)
        init_db(self.db_path)
        saved = recent_scenario_attempts(self.learner["id"], self.db_path)
        self.assertEqual([item["id"] for item in saved], ids[-20:])
        self.assertEqual([item["student_response"] for item in saved], drafts[-20:])
        self.assertTrue(all(item["needs_mentor_review"] for item in saved))
        self.assertTrue(all(item["scenario_title"] == scenario["title"] for item in saved))
        self.assertEqual(len(recent_scenario_attempts(self.other["id"], self.db_path)), 1)
        with connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM scenario_attempts").fetchone()[0], 24)
            first = db.execute("SELECT student_response FROM scenario_attempts WHERE id = ?", (ids[0],)).fetchone()[0]
            self.assertEqual(first, drafts[0])

    def test_current_learner_progress_is_available_beyond_overview_limit(self):
        mark_module_complete(self.learner["id"], "hardware_basics", True, self.db_path)
        for number in range(21):
            create_or_find_student(f"Later Synthetic Learner {number}", self.db_path)
        overview = student_progress_summary(self.db_path)
        self.assertEqual(len(overview), 20)
        self.assertNotIn(self.learner["id"], [item["student"]["id"] for item in overview])
        current = student_progress(self.learner["id"], self.db_path)
        self.assertEqual(current["student"]["id"], self.learner["id"])
        self.assertEqual(current["module_completed_count"], 1)
        self.assertIsNone(student_progress(-1, self.db_path))


class SessionStorageRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = Path(self.tmpdir.name) / "synthetic-session-routes.sqlite"
        self.config = {
            "TESTING": True,
            "SECRET_KEY": "synthetic-route-storage-test-secret",
            "LAUNCHPAD_DB_PATH": str(self.db_path),
            "LAUNCHPAD_DEMO_MODE": False,
            "LAUNCHPAD_PILOT_MODE": False,
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.learner_name = "Synthetic Transcript Learner"
        self.client.post("/student", data={"display_name": self.learner_name})
        with self.client.session_transaction() as browser_session:
            self.learner_id = browser_session["student_id"]
        self.scenario = next(item for item in list_scenarios() if not is_guided_scenario(item))
        self.random = random.Random(9173)

    def _invented_text(self, marker, words=120):
        # Varied deterministic text avoids an unrealistically compressible cookie.
        return marker + " " + " ".join(
            "".join(self.random.choices(string.ascii_lowercase, k=9)) for _ in range(words)
        )

    def _assert_small_cookie_without_transcripts(self, client=None, app=None, response=None, markers=()):
        client = client or self.client
        app = app or self.app
        cookie = client.get_cookie(app.config["SESSION_COOKIE_NAME"])
        self.assertIsNotNone(cookie)
        self.assertLess(len(cookie.value), 4093)
        if response is not None:
            for header in response.headers.getlist("Set-Cookie"):
                self.assertLess(len(header), 4093)
        decoded = app.session_interface.get_signing_serializer(app).loads(cookie.value)
        for key in ("pre_assessment_result", "post_assessment_result", "scenario_attempts", "stuck_reports"):
            self.assertNotIn(key, decoded)
        serialized = json.dumps(decoded)
        for marker in markers:
            self.assertNotIn(marker, serialized)

    def _help_data(self, marker):
        return {
            "student": self.learner_name,
            "topic": marker,
            "trying_to_do": self._invented_text(marker + " task"),
            "what_happened": self._invented_text(marker + " observation"),
            "already_checked": self._invented_text(marker + " checks"),
            "current_blocker": self._invented_text(marker + " blocker"),
        }

    def test_repeated_long_help_requests_keep_exact_summaries_out_of_cookie(self):
        summaries = []
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always")
            for number in range(12):
                marker = f"synthetic-help-transcript-{number}"
                data = self._help_data(marker)
                summaries.append(generate_stuck_summary(data))
                response = self.client.post("/stuck", data=data)
                self.assertEqual(response.status_code, 200)
                self._assert_small_cookie_without_transcripts(response=response, markers=(marker, data["current_blocker"]))
        self.assertFalse(any("cookie" in str(item.message).lower() and "too large" in str(item.message).lower() for item in observed))
        with connect(self.db_path) as db:
            rows = db.execute("SELECT mentor_summary FROM stuck_reports WHERE student_id = ? ORDER BY id", (self.learner_id,)).fetchall()
        self.assertEqual([row[0] for row in rows], summaries)
        self.assertEqual([item["summary"] for item in recent_stuck_reports(self.learner_id, self.db_path)], summaries[-10:])

    def test_repeated_long_scenario_drafts_keep_every_full_draft_out_of_cookie(self):
        drafts = []
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always")
            for number in range(23):
                marker = f"synthetic-scenario-transcript-{number}"
                draft = self._invented_text(marker, words=400)
                drafts.append(draft)
                response = self.client.post(f"/scenarios/{self.scenario['id']}", data={"student_response": draft})
                self.assertEqual(response.status_code, 200)
                self._assert_small_cookie_without_transcripts(response=response, markers=(marker, draft))
        self.assertFalse(any("cookie" in str(item.message).lower() and "too large" in str(item.message).lower() for item in observed))
        with connect(self.db_path) as db:
            rows = db.execute("SELECT student_response FROM scenario_attempts WHERE student_id = ? ORDER BY id", (self.learner_id,)).fetchall()
        self.assertEqual([row[0] for row in rows], drafts)
        self.assertEqual([item["student_response"] for item in recent_scenario_attempts(self.learner_id, self.db_path)], drafts[-20:])

    def test_repeated_long_assessments_preserve_scores_and_full_answers_without_cookie_text(self):
        records = []
        for kind in ("pre", "post"):
            assessment = load_assessment(f"{kind}_assessment_v1")
            for number in range(3):
                answers = synthetic_beginner_responses() if kind == "pre" else {}
                for question in all_questions(assessment):
                    if question["type"] == "free_response":
                        answers[question["id"]] = self._invented_text(f"synthetic-{kind}-mentor-answer-{number}-{question['id']}", words=500)
                    elif kind == "post":
                        if question["type"] == "rating":
                            answers[question["id"]] = "3"
                        elif question["type"] == "select_all":
                            answers[question["id"]] = [question["options"][0]["value"]]
                        else:
                            answers[question["id"]] = question.get("correct_answer", question["options"][0]["value"])
                response = self.client.post(f"/{kind}-assessment", data=answers, follow_redirects=True)
                self.assertEqual(response.status_code, 200)
                self._assert_small_cookie_without_transcripts(response=response, markers=(f"synthetic-{kind}-mentor-answer",))
                saved = latest_assessment_result(self.learner_id, kind, self.db_path)
                self.assertEqual(saved["answers"], answers)
                if kind == "pre":
                    self.assertEqual(saved["technical_score"], 18)
                records.append((kind, answers))
        with connect(self.db_path) as db:
            rows = db.execute("SELECT assessment_type, answers_json FROM assessment_results WHERE student_id = ? ORDER BY id", (self.learner_id,)).fetchall()
        self.assertEqual([(row[0], json.loads(row[1])) for row in rows], records)

    def test_mentor_text_survives_restart_fresh_session_and_stays_with_selected_learner(self):
        assessment_answers = synthetic_beginner_responses()
        assessment_answers["q3"] = self._invented_text("synthetic-persisted-assessment", words=400)
        help_data = self._help_data("synthetic-persisted-help")
        scenario_draft = self._invented_text("synthetic-persisted-scenario", words=400)
        post_answers = {}
        post_transcripts = []
        for question in all_questions(load_assessment("post_assessment_v1")):
            if question["type"] == "free_response":
                answer = self._invented_text(f"synthetic-persisted-post-{question['id']}", words=400)
                post_transcripts.append(answer)
            elif question["type"] == "rating":
                answer = "3"
            elif question["type"] == "select_all":
                answer = [question["options"][0]["value"]]
            else:
                answer = question.get("correct_answer", question["options"][0]["value"])
            post_answers[question["id"]] = answer
        self.client.post("/pre-assessment", data=assessment_answers)
        self.client.post("/post-assessment", data=post_answers)
        self.client.post("/stuck", data=help_data)
        self.client.post(f"/scenarios/{self.scenario['id']}", data={"student_response": scenario_draft})
        self.assertEqual(latest_assessment_result(self.learner_id, "post", self.db_path)["answers"], post_answers)
        expected = (assessment_answers["q3"], generate_stuck_summary(help_data), scenario_draft, *post_transcripts)

        restarted = create_app(self.config)
        fresh = restarted.test_client()
        fresh.post("/student", data={"display_name": self.learner_name})
        page = fresh.get("/supervisor")
        self.assertEqual(page.status_code, 200)
        for transcript in expected:
            self.assertIn(transcript.encode(), page.data)
        self._assert_small_cookie_without_transcripts(fresh, restarted, page, expected)

        fresh.post("/student", data={"display_name": "Different Synthetic Learner"})
        other_draft = "synthetic-second-learner-transcript"
        fresh.post(f"/scenarios/{self.scenario['id']}", data={"student_response": other_draft})
        other_page = fresh.get("/supervisor")
        self.assertIn(other_draft.encode(), other_page.data)
        for transcript in expected:
            self.assertNotIn(transcript.encode(), other_page.data)
        fresh.post("/student", data={"display_name": self.learner_name})
        first_page = fresh.get("/supervisor")
        self.assertNotIn(other_draft.encode(), first_page.data)
        for transcript in expected:
            self.assertIn(transcript.encode(), first_page.data)

    def test_old_cookie_transcript_fields_are_purged_without_replacing_saved_data(self):
        saved_answers = synthetic_beginner_responses()
        saved_answers["q3"] = "synthetic-authoritative-saved-answer"
        self.client.post("/pre-assessment", data=saved_answers)
        stale = "synthetic-stale-cookie-transcript"
        with self.client.session_transaction() as browser_session:
            browser_session["pre_assessment_result"] = {"mentor_review_items": [{"response": stale}]}
            browser_session["post_assessment_result"] = {"mentor_review_items": [{"response": stale}]}
            browser_session["scenario_attempts"] = [{"student_response": stale}]
            browser_session["stuck_reports"] = [{"summary": stale}]
        page = self.client.get("/supervisor")
        self.assertEqual(page.status_code, 200)
        self.assertIn(saved_answers["q3"].encode(), page.data)
        self.assertNotIn(stale.encode(), page.data)
        self._assert_small_cookie_without_transcripts(response=page, markers=(stale, saved_answers["q3"]))
        self.assertEqual(latest_assessment_result(self.learner_id, "pre", self.db_path)["answers"], saved_answers)


class ScenarioStorageDemoCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.tmpdir.cleanup)
        self.db_path = Path(self.tmpdir.name) / "synthetic-demo.sqlite"
        prepare_demo_database(self.db_path)
        with connect(self.db_path) as db:
            self.learner_id = db.execute("SELECT id FROM students WHERE display_name = ?", (DEMO_NOVA_NAME,)).fetchone()[0]

    def test_v1_dataset_without_optional_table_validates_readonly_then_migrates_additively(self):
        with connect(self.db_path) as db:
            db.execute("DROP TABLE scenario_attempts")
            original_rows = [tuple(row) for row in db.execute("SELECT * FROM assessment_results ORDER BY id")]
        before = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        validation = validate_demo_database(self.db_path)
        self.assertTrue(validation["session_generation"])
        self.assertEqual(hashlib.sha256(self.db_path.read_bytes()).hexdigest(), before)
        init_db(self.db_path)
        with connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM scenario_attempts").fetchone()[0], 0)
            self.assertEqual([tuple(row) for row in db.execute("SELECT * FROM assessment_results ORDER BY id")], original_rows)
        self.assertEqual(validate_demo_database(self.db_path)["session_generation"], validation["session_generation"])

    def test_optional_table_accepts_known_scenario_and_rejects_unknown_scenario(self):
        scenario = list_scenarios()[0]
        save_scenario_attempt(self.learner_id, scenario["id"], scenario["title"], "Invented exercise response", self.db_path)
        validate_demo_database(self.db_path)
        save_scenario_attempt(self.learner_id, "unknown_scenario", "Invented scenario", "Invented response", self.db_path)
        with self.assertRaisesRegex(DemoDataError, "unknown scenario_id"):
            validate_demo_database(self.db_path)

    def test_optional_table_rejects_unknown_learner_reference(self):
        scenario = list_scenarios()[0]
        # Raw sqlite connection models malformed input; normal storage enables FKs.
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "INSERT INTO scenario_attempts (student_id, scenario_id, scenario_title, student_response, created_at) VALUES (?, ?, ?, ?, ?)",
                (999, scenario["id"], scenario["title"], "Invented response", "2026-01-01T00:00:00+00:00"),
            )
        with self.assertRaisesRegex(DemoDataError, "scenario_attempts contains records for an unknown learner"):
            validate_demo_database(self.db_path)


if __name__ == "__main__":
    unittest.main()
