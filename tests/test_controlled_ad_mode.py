"""Controlled-test session boundaries with invented identities and isolated DBs.

Storage-marker enforcement has its own integration tests. These HTTP tests use
the existing AD fixtures and mock only that startup boundary and the verified
directory identity boundary. An accidental LDAP connection fails immediately.
"""
from contextlib import closing
import time
import unittest
from unittest.mock import patch

from launchpad import create_app
from launchpad.accounts import (
    create_auth_session, get_session_account, revoke_all_sessions,
    set_account_active,
)
from launchpad.ad import ADLoginError
from launchpad.demo import synthetic_beginner_responses
from launchpad.quizzes import get_module_quiz
from launchpad.scenarios import get_scenario
from launchpad.storage import (
    activity_progress, connect, latest_assessment_result, latest_module_quiz_result,
    module_is_complete,
)
from tests import test_ad_login as fixture


class ControlledADModeTests(unittest.TestCase):
    base_url = fixture.ADLoginTests.base_url
    cookie_name = fixture.ADLoginTests.cookie_name
    namespace = fixture.ADLoginTests.namespace
    issuer = fixture.ADLoginTests.issuer
    first_guid = fixture.ADLoginTests.first_guid
    second_guid = fixture.ADLoginTests.second_guid
    mentor_guid = fixture.ADLoginTests.mentor_guid
    reads = fixture.ADLoginTests.reads
    writes = fixture.ADLoginTests.writes
    learner_tables = fixture.ADLoginTests.learner_tables
    identity = staticmethod(fixture.ADLoginTests.identity)
    get = fixture.ADLoginTests.get
    post = fixture.ADLoginTests.post
    token = fixture.ADLoginTests.token
    handle = fixture.ADLoginTests.handle
    submit = fixture.ADLoginTests.submit
    login = fixture.ADLoginTests.login
    snapshot = fixture.ADLoginTests.snapshot
    copied_cookie_client = fixture.ADLoginTests.copied_cookie_client

    def setUp(self):
        fixture.ADLoginTests.setUp(self)
        patch("ldap3.Connection", side_effect=AssertionError("No live directory calls in tests")).start()
        self.guard = patch("launchpad.real_auth.validate_controlled_storage", return_value={}).start()
        self.config.update(
            LAUNCHPAD_AD_SESSION_POLICY="controlled_test",
            LAUNCHPAD_AD_LOOKUP_USERNAME="", LAUNCHPAD_AD_LOOKUP_PASSWORD="",
            LAUNCHPAD_AD_REVALIDATE_SECONDS="",
        )
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.start = int(time.time())
        self.wall_clock = patch("launchpad.accounts.time.time", return_value=self.start).start()

    def test_explicit_mode_starts_without_lookup_and_keeps_secure_form_and_cookie(self):
        page = self.get("/auth/login")
        self.assertEqual(page.status_code, 200)
        for text in ("invented training answers", "15 minutes", "no background directory checks", "AD disablement", "Previously submitted progress"):
            self.assertIn(text, page.text)
        self.login()
        with self.client.session_transaction(base_url=self.base_url) as browser_session:
            self.assertFalse(browser_session.permanent)
        cookie = self.client.get_cookie(self.cookie_name, domain="launchpad.example")
        self.assertIsNone(cookie.expires)
        self.assertTrue(cookie.secure)
        self.assertTrue(cookie.http_only)
        self.assertFalse(self.app.config["SESSION_REFRESH_EACH_REQUEST"])
        self.assertEqual(self.app.config["PERMANENT_SESSION_LIFETIME"].total_seconds(), 900)
        self.authenticate.assert_called_once()
        self.revalidate.assert_not_called()

    def test_missing_production_lookup_configuration_never_selects_controlled_mode(self):
        for policy in (None, "revalidate"):
            candidate = dict(self.config)
            if policy is None:
                candidate.pop("LAUNCHPAD_AD_SESSION_POLICY")
            else:
                candidate["LAUNCHPAD_AD_SESSION_POLICY"] = policy
            with self.subTest(policy=policy), patch("launchpad.web.validate_real_database") as opened:
                with self.assertRaisesRegex(ValueError, "lookup credentials"):
                    create_app(candidate)
                opened.assert_not_called()

    def test_invalid_or_incompatible_mode_fails_before_learner_database(self):
        for values in (
            {"LAUNCHPAD_AD_SESSION_POLICY": "test"},
            {"LAUNCHPAD_AD_SESSION_POLICY": []},
            {"LAUNCHPAD_REAL_MODE": False},
            {"LAUNCHPAD_DEMO_MODE": True},
            {"LAUNCHPAD_AUTH_BACKEND": "oidc"},
            {"LAUNCHPAD_AD_LOOKUP_USERNAME": "reader@example.test"},
            {"LAUNCHPAD_AD_LOOKUP_PASSWORD": "do-not-retain"},
            {"LAUNCHPAD_AD_LOOKUP_PASSWORD": None},
            {"LAUNCHPAD_AD_STATE_PATH": str(self.directory / "missing.sqlite")},
        ):
            with self.subTest(keys=tuple(values)), patch("launchpad.web.validate_real_database") as opened:
                with self.assertRaises(ValueError):
                    create_app({**self.config, **values})
                opened.assert_not_called()

    def test_storage_rejection_precedes_learner_database_validation(self):
        self.guard.side_effect = ValueError("Controlled storage required")
        with patch("launchpad.web.validate_real_database") as opened:
            with self.assertRaisesRegex(ValueError, "Controlled storage"):
                create_app(self.config)
            opened.assert_not_called()
        self.authenticate.assert_not_called()

    def test_absolute_expiry_at_900_seconds_despite_repeated_activity(self):
        self.login()
        token = self.handle()
        for elapsed in (1, 60, 300, 600, 899):
            self.wall_clock.return_value = self.start + elapsed
            self.assertEqual(self.get("/student").status_code, 200)
        with closing(connect(self.database)) as db:
            row = db.execute("SELECT created_at,expires_at,idle_timeout_seconds FROM auth_sessions").fetchone()
            self.assertEqual(tuple(row), (self.start, self.start + 900, 900))
        self.wall_clock.return_value = self.start + 900
        response = self.get("/student")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Previously submitted progress is retained", response.text)
        self.assertIsNone(get_session_account(token, self.database))
        self.revalidate.assert_not_called()

    def test_long_legacy_session_is_capped_even_if_cookie_was_recently_signed(self):
        token = create_auth_session(self.first["id"], self.database)
        self.wall_clock.return_value = self.start + 899
        with self.client.session_transaction(base_url=self.base_url) as browser_session:
            browser_session["auth_session"] = token
        self.assertEqual(self.get("/student").status_code, 200)
        self.wall_clock.return_value = self.start + 900
        self.assertIsNotNone(get_session_account(token, self.database))  # Stored legacy 8-hour lifetime.
        self.assertIsNone(get_session_account(token, self.database, max_lifetime_seconds=900))
        self.assertEqual(self.get("/student").status_code, 401)

    def test_app_recreation_keeps_server_expiry_without_performing_directory_recheck(self):
        self.login()
        self.wall_clock.return_value = self.start + 899
        restarted = self.copied_cookie_client(create_app(self.config))
        self.assertEqual(self.get("/student", restarted).status_code, 200)
        self.wall_clock.return_value = self.start + 900
        self.assertEqual(self.get("/student", restarted).status_code, 401)
        self.authenticate.assert_called_once()
        self.revalidate.assert_not_called()

    def test_remember_fields_and_permanent_cookie_cannot_extend_server_session(self):
        response = self.submit("/auth/login", {
            "username": "invented.user", "password": "invented-password",
            "remember": "1", "remember_me": "true", "permanent": "true",
        })
        self.assertEqual(response.status_code, 302)
        token = self.handle()
        self.wall_clock.return_value = self.start + 899
        with self.client.session_transaction(base_url=self.base_url) as browser_session:
            browser_session.permanent = True
        self.assertEqual(self.get("/student").status_code, 200)
        with self.client.session_transaction(base_url=self.base_url) as browser_session:
            self.assertFalse(browser_session.permanent)
        self.wall_clock.return_value = self.start + 900
        self.assertEqual(self.get("/student").status_code, 401)
        self.assertIsNone(get_session_account(token, self.database))

    def test_directory_changes_do_not_end_existing_session_but_fresh_signin_rechecks(self):
        self.login()
        # The adapter uses this same generic refusal for disabled/nonmember users.
        self.authenticate.side_effect = ADLoginError("group removed or account disabled")
        self.revalidate.side_effect = AssertionError("Controlled mode must not perform background lookup")
        self.wall_clock.return_value = self.start + 899
        self.assertEqual(self.get("/student").status_code, 200)
        self.wall_clock.return_value = self.start + 900
        self.assertEqual(self.get("/student").status_code, 401)
        denied = self.submit("/auth/login", {"username": "invented.user", "password": "invented-password"})
        self.assertEqual(denied.status_code, 401)
        self.assertNotIn("group removed", denied.text)
        self.assertEqual(self.authenticate.call_count, 2)
        self.assertEqual(self.get("/student").status_code, 401)
        self.revalidate.assert_not_called()

    def test_unenrolled_valid_directory_identity_is_denied_without_record_creation(self):
        before = self.snapshot()
        self.authenticate.return_value = {"issuer": self.issuer, "subject": "0f2f921d-baa2-4ea0-b8d3-6619afc5a35f"}
        response = self.submit("/auth/login", {"username": "unknown.user", "password": "invented-password"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.get("/student").status_code, 401)

    def test_logout_revokes_cookie_replay(self):
        self.login()
        replay = self.copied_cookie_client()
        token = self.handle()
        self.assertEqual(self.submit("/auth/logout").status_code, 302)
        self.assertEqual(self.get("/student", replay).status_code, 401)
        self.assertIsNone(get_session_account(token, self.database))

    def test_local_disablement_and_revocation_apply_on_next_request(self):
        self.login()
        other = self.login(client=self.app.test_client(), username="other.invented")
        before = self.snapshot()
        revoke_all_sessions(self.database, account_id=self.first["id"])
        self.assertEqual(self.get("/student").status_code, 401)
        self.assertEqual(self.post("/modules/hardware_basics", {"completed": "1"}, other).status_code, 401)
        self.assertEqual(self.snapshot(), before)
        self.login(username="third.invented")
        set_account_active(self.first["id"], False, self.database)
        self.assertEqual(self.get("/student").status_code, 401)
        self.assertEqual(self.snapshot(), before)

    def test_learner_isolation_and_forged_selectors_stay_enforced(self):
        fixture.ADLoginTests.test_learner_cross_record_reads_writes_and_selectors_are_denied(self)

    def test_mentors_keep_only_assigned_read_access(self):
        fixture.ADLoginTests.test_mentor_reads_only_assigned_learner_and_cannot_write(self)

    def test_signin_throttle_survives_recreation_without_lookup(self):
        fixture.ADLoginTests.test_username_upn_case_aliases_share_persistent_throttle_and_sixth_never_binds(self)

    def test_login_csrf_and_duplicate_fields_still_block_directory_calls(self):
        fixture.ADLoginTests.test_login_csrf_foreign_origin_and_duplicate_credentials_do_not_reach_directory(self)

    def test_unfinished_guided_steps_reset_after_expiry_but_saved_completion_survives(self):
        scenario = get_scenario("classroom_no_display")
        self.login()
        self.assertEqual(self.submit("/scenarios/classroom_no_display/actions", {"action_id": scenario["required_inspections"][0]}).status_code, 302)
        with self.client.session_transaction(base_url=self.base_url) as browser_session:
            self.assertTrue(browser_session["guided_scenario_states"])
        before = self.snapshot()
        self.wall_clock.return_value = self.start + 900
        response = self.get("/scenarios/classroom_no_display")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Unfinished guided practice must be restarted", response.text)
        self.login(username="fresh.invented")
        with self.client.session_transaction(base_url=self.base_url) as browser_session:
            self.assertNotIn("guided_scenario_states", browser_session)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.submit("/scenarios/classroom_no_display/complete").status_code, 400)
        for action in (*scenario["required_inspections"], scenario["resolution"]["action_id"]):
            self.assertEqual(self.submit("/scenarios/classroom_no_display/actions", {"action_id": action}).status_code, 302)
        self.assertEqual(self.submit("/scenarios/classroom_no_display/complete").status_code, 302)
        self.assertIn(scenario["activity_id"], activity_progress(self.first["learner_id"], self.database))
        saved = self.snapshot()
        self.wall_clock.return_value = self.start + 1800
        self.assertEqual(self.get("/student").status_code, 401)
        self.login(username="third.invented")
        self.assertIn("This troubleshooting lab is complete", self.get("/scenarios/classroom_no_display").text)
        self.assertEqual(self.snapshot(), saved)

    def test_expired_write_loses_only_unsaved_input_and_progress_survives_fresh_signin_restart(self):
        self.login()
        self.assertEqual(self.submit("/pre-assessment", synthetic_beginner_responses()).status_code, 302)
        self.assertEqual(latest_assessment_result(self.first["learner_id"], "pre", self.database)["technical_score"], 18)
        quiz = get_module_quiz("hardware_basics")
        answers = {question["id"]: question["answer"] for question in quiz["questions"]}
        self.assertEqual(self.submit("/modules/hardware_basics/quiz", answers).status_code, 200)
        self.assertEqual(latest_module_quiz_result(self.first["learner_id"], "hardware_basics", self.database)["score"], 100)
        before = self.snapshot()
        csrf = self.token()
        self.wall_clock.return_value = self.start + 900
        response = self.post("/modules/hardware_basics", {"csrf_token": csrf, "completed": "1"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("Unsaved answers and this request were not saved", response.text)
        self.assertIn("not be submitted automatically", response.text)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(module_is_complete(self.first["learner_id"], "hardware_basics", self.database))
        restarted = create_app(self.config)
        client = restarted.test_client()
        self.login(client=client, username="fresh.invented")
        self.assertEqual(self.authenticate.call_count, 2)
        self.assertEqual(self.get("/student", client).status_code, 200)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.submit("/modules/hardware_basics", {"completed": "1"}, client).status_code, 302)
        self.assertTrue(module_is_complete(self.first["learner_id"], "hardware_basics", self.database))
        self.assertFalse(module_is_complete(self.second["learner_id"], "hardware_basics", self.database))
        self.revalidate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
