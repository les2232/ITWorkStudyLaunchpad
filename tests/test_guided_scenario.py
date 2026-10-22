import tempfile
import unittest
from pathlib import Path

from launchpad import create_app
from launchpad.storage import activity_progress, connect, recent_scenario_attempts, recent_stuck_reports


SCENARIO_ID = "classroom_no_display"
ACTIVITY_ID = "developing_no_display_troubleshooting"
SCENARIO_URL = f"/scenarios/{SCENARIO_ID}"
ACTION_URL = f"{SCENARIO_URL}/actions"
COMPLETE_URL = f"{SCENARIO_URL}/complete"
REQUIRED_INSPECTIONS = (
    "computer_power",
    "monitor_status",
    "input_source",
    "display_cable",
)


class GuidedScenarioRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "guided-scenario.sqlite"
        self.app = self._new_app()
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _new_app(self):
        return create_app(
            {
                "TESTING": True,
                "LAUNCHPAD_DB_PATH": str(self.db_path),
                "SECRET_KEY": "guided-scenario-tests-only",
            }
        )

    def _select_learner(self, client=None, name="DEMO Guided Route Learner"):
        client = client or self.client
        response = client.post("/student", data={"display_name": name})
        self.assertEqual(response.status_code, 302)
        with client.session_transaction() as session:
            return int(session["student_id"])

    def _post_action(self, action_id, client=None):
        client = client or self.client
        return client.post(ACTION_URL, data={"action_id": action_id})

    def _resolve_scenario(self, client=None):
        client = client or self.client
        for inspection_id in REQUIRED_INSPECTIONS:
            response = self._post_action(inspection_id, client)
            self.assertEqual(response.status_code, 302)
        response = self._post_action("reconnect_displayport", client)
        self.assertEqual(response.status_code, 302)

    def _activity_rows(self, student_id):
        with connect(self.db_path) as db:
            return db.execute(
                """
                SELECT student_id, activity_id, completed
                FROM activity_progress
                WHERE student_id = ? AND activity_id = ?
                ORDER BY id
                """,
                (student_id, ACTIVITY_ID),
            ).fetchall()

    def test_get_creates_no_completion(self):
        student_id = self._select_learner(name="DEMO Read Only Learner")

        response = self.client.get(SCENARIO_URL)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Guided troubleshooting lab", response.data)
        self.assertIn(b"0 of 4 required checks complete", response.data)
        self.assertIn(b"Inspect", response.data)
        self.assertIn(b"Resolve", response.data)
        self.assertIn(b"Save", response.data)
        self.assertIn(b"Monitor", response.data)
        self.assertIn(b"DisplayPort connection", response.data)
        self.assertIn(b"aria-current=\x22step\x22", response.data)
        self.assertEqual(activity_progress(student_id, self.db_path), {})
        self.assertEqual(self._activity_rows(student_id), [])

    def test_anonymous_action_redirects_to_learner_selection(self):
        response = self._post_action("computer_power")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/student?next=/scenarios/classroom_no_display", response.location)
        with connect(self.db_path) as db:
            count = db.execute(
                "SELECT COUNT(*) AS count FROM activity_progress"
            ).fetchone()["count"]
        self.assertEqual(count, 0)

    def test_generic_activity_control_cannot_complete_scenario_activity(self):
        student_id = self._select_learner(name="DEMO Generic Bypass Learner")

        response = self.client.post(
            f"/training-path/developing/activities/{ACTIVITY_ID}",
            data={"completed": "1"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(activity_progress(student_id, self.db_path), {})
        self.assertEqual(self._activity_rows(student_id), [])

    def test_premature_resolution_and_unsafe_actions_do_not_complete(self):
        student_id = self._select_learner(name="DEMO Safe Coaching Learner")

        premature = self._post_action("reconnect_displayport")
        self.assertEqual(premature.status_code, 302)
        self.assertEqual(self._activity_rows(student_id), [])

        for action_id in (
            "replace_monitor",
            "open_computer_case",
            "change_bios_settings",
            "reimage_computer",
        ):
            with self.subTest(action_id=action_id):
                response = self._post_action(action_id)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(activity_progress(student_id, self.db_path), {})
                self.assertEqual(self._activity_rows(student_id), [])

        page = self.client.get(SCENARIO_URL)
        self.assertIn(b"Stop and ask a mentor", page.data)
        self.assertNotIn(b"This troubleshooting lab is complete", page.data)

    def test_unknown_action_and_direct_early_completion_return_400(self):
        student_id = self._select_learner(name="DEMO Invalid Action Learner")

        unknown = self._post_action("invented_action")
        early_complete = self.client.post(COMPLETE_URL)

        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(early_complete.status_code, 400)
        self.assertEqual(activity_progress(student_id, self.db_path), {})
        self.assertEqual(self._activity_rows(student_id), [])

    def test_resolution_requires_explicit_save_and_writes_one_activity_row(self):
        student_id = self._select_learner(name="DEMO Explicit Save Learner")
        self._resolve_scenario()

        resolved_page = self.client.get(SCENARIO_URL)
        self.assertEqual(resolved_page.status_code, 200)
        self.assertIn(b"4 of 4 required checks complete", resolved_page.data)
        self.assertIn(b"Finish and save", resolved_page.data)
        self.assertIn(b"Display restored", resolved_page.data)
        self.assertIn(b"not yet saved", resolved_page.data)
        self.assertIn(b"aria-current=\x22step\x22", resolved_page.data)
        self.assertNotIn(b"This troubleshooting lab is complete", resolved_page.data)
        self.assertEqual(activity_progress(student_id, self.db_path), {})
        self.assertEqual(self._activity_rows(student_id), [])

        saved = self.client.post(COMPLETE_URL)

        self.assertEqual(saved.status_code, 302)
        rows = self._activity_rows(student_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["student_id"], student_id)
        self.assertEqual(rows[0]["activity_id"], ACTIVITY_ID)
        self.assertEqual(rows[0]["completed"], 1)
        self.assertTrue(activity_progress(student_id, self.db_path)[ACTIVITY_ID])

        saved_again = self.client.post(COMPLETE_URL)
        self.assertEqual(saved_again.status_code, 302)
        self.assertEqual(len(self._activity_rows(student_id)), 1)

    def test_saved_completion_survives_refresh_fresh_session_and_app_restart(self):
        learner_name = "DEMO Durable Scenario Learner"
        student_id = self._select_learner(name=learner_name)
        self._resolve_scenario()
        self.assertEqual(self.client.post(COMPLETE_URL).status_code, 302)

        refreshed = self.client.get(SCENARIO_URL)
        self.assertEqual(refreshed.status_code, 200)
        self.assertIn(b"This troubleshooting lab is complete", refreshed.data)
        self.assertIn(b"Completed and saved", refreshed.data)
        self.assertIn(b"Saved completion", refreshed.data)
        self.assertNotIn(b"aria-current=\x22step\x22", refreshed.data)

        fresh_client = self.app.test_client()
        same_student_id = self._select_learner(fresh_client, learner_name)
        self.assertEqual(same_student_id, student_id)
        fresh_session_page = fresh_client.get(SCENARIO_URL)
        self.assertEqual(fresh_session_page.status_code, 200)
        self.assertIn(
            b"This troubleshooting lab is complete", fresh_session_page.data
        )

        restarted_app = self._new_app()
        restarted_client = restarted_app.test_client()
        restarted_student_id = self._select_learner(restarted_client, learner_name)
        self.assertEqual(restarted_student_id, student_id)
        restarted_page = restarted_client.get(SCENARIO_URL)
        self.assertEqual(restarted_page.status_code, 200)
        self.assertIn(b"This troubleshooting lab is complete", restarted_page.data)
        self.assertTrue(activity_progress(student_id, self.db_path)[ACTIVITY_ID])
        self.assertEqual(len(self._activity_rows(student_id)), 1)

    def test_legacy_text_scenario_still_accepts_practice_response(self):
        response_text = "I would pause and ask the DEMO mentor before acting."

        page = self.client.get("/scenarios/ticket_term_unknown")
        submitted = self.client.post(
            "/scenarios/ticket_term_unknown",
            data={"student_response": response_text},
        )

        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Your draft response", page.data)
        self.assertEqual(submitted.status_code, 200)
        self.assertIn(b"Mentor Review Guide", submitted.data)
        self.assertIn(response_text.encode(), submitted.data)
        with self.client.session_transaction() as session:
            self.assertNotIn("scenario_attempts", session)
            student_id = session["student_id"]
        self.assertEqual(recent_scenario_attempts(student_id, self.db_path)[0]["student_response"], response_text)

    def test_switching_learners_clears_cached_state_and_preserves_new_identity(self):
        first_id = self._select_learner(name="DEMO Cache Source Learner")
        cached_keys = {
            "pre_assessment_result": {"score": 12},
            "post_assessment_result": {"score": 34},
            "scenario_attempts": [{"scenario_id": "synthetic_attempt"}],
            "stuck_reports": [{"topic": "synthetic_help_request"}],
            "guided_scenario_states": {
                f"{first_id}:{SCENARIO_ID}": {
                    "inspected": ["computer_power"],
                    "resolved": False,
                }
            },
            "demo_student_token": "SYNTHETIC",
        }
        with self.client.session_transaction() as session:
            session.update(cached_keys)

        second_id = self._select_learner(name="DEMO Cache Target Learner")

        self.assertNotEqual(first_id, second_id)
        with self.client.session_transaction() as session:
            for key in cached_keys:
                self.assertNotIn(key, session)
            self.assertEqual(session["student_id"], second_id)
            self.assertEqual(
                session["student_display_name"], "DEMO Cache Target Learner"
            )

    def test_switching_identity_through_stuck_form_also_clears_cached_state(self):
        first_id = self._select_learner(name="DEMO Stuck Source Learner")
        cached_keys = {
            "pre_assessment_result": {"score": 12},
            "post_assessment_result": {"score": 34},
            "scenario_attempts": [{"scenario_id": "synthetic_attempt"}],
            "guided_scenario_states": {
                f"{first_id}:{SCENARIO_ID}": {
                    "inspected": ["computer_power"],
                    "resolved": False,
                }
            },
            "demo_student_token": "SYNTHETIC",
        }
        with self.client.session_transaction() as session:
            session.update(cached_keys)
            session["stuck_reports"] = [{"topic": "old learner report"}]

        response = self.client.post(
            "/stuck",
            data={
                "student": "DEMO Stuck Target Learner",
                "topic": "synthetic monitor practice",
                "trying_to_do": "Practice an invented troubleshooting task",
                "what_happened": "The invented display showed No Signal",
                "already_checked": "Synthetic power indicator only",
                "current_blocker": "Need synthetic mentor guidance",
                "related_item": "classroom_no_display",
            },
        )

        self.assertEqual(response.status_code, 200)
        with self.client.session_transaction() as session:
            second_id = int(session["student_id"])
            self.assertNotEqual(first_id, second_id)
            for key in cached_keys:
                self.assertNotIn(key, session)
            self.assertEqual(
                session["student_display_name"], "DEMO Stuck Target Learner"
            )
            self.assertNotIn("stuck_reports", session)
        reports = recent_stuck_reports(second_id, self.db_path)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["student"], "DEMO Stuck Target Learner")
        self.assertEqual(recent_stuck_reports(first_id, self.db_path), [])


if __name__ == "__main__":
    unittest.main()
