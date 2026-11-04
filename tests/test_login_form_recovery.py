"""Login form state across restart and expiry, using disposable data only.

The existing controlled-mode fixture rejects live LDAP calls. These tests use
synthetic credentials and check the HTTP boundary before the mocked directory
adapter; no CCA configuration, browser session or learner record is loaded.
"""
import re
import unittest

from launchpad import create_app
from launchpad.accounts import revoke_all_sessions
from launchpad.demo import synthetic_beginner_responses
from launchpad.storage import latest_assessment_result
from tests import test_controlled_ad_mode as fixture


class LoginFormRecoveryTests(unittest.TestCase):
    base_url = fixture.ControlledADModeTests.base_url
    cookie_name = fixture.ControlledADModeTests.cookie_name
    namespace = fixture.ControlledADModeTests.namespace
    issuer = fixture.ControlledADModeTests.issuer
    first_guid = fixture.ControlledADModeTests.first_guid
    second_guid = fixture.ControlledADModeTests.second_guid
    mentor_guid = fixture.ControlledADModeTests.mentor_guid
    learner_tables = fixture.ControlledADModeTests.learner_tables
    identity = staticmethod(fixture.ControlledADModeTests.identity)
    get = fixture.ControlledADModeTests.get
    post = fixture.ControlledADModeTests.post
    token = fixture.ControlledADModeTests.token
    handle = fixture.ControlledADModeTests.handle
    submit = fixture.ControlledADModeTests.submit
    login = fixture.ControlledADModeTests.login
    snapshot = fixture.ControlledADModeTests.snapshot
    copied_cookie_client = fixture.ControlledADModeTests.copied_cookie_client

    username = "W00001001"
    password = " invented password with surrounding spaces "

    def setUp(self):
        fixture.ControlledADModeTests.setUp(self)
        self.login()
        self.assertEqual(self.submit("/pre-assessment", synthetic_beginner_responses()).status_code, 302)
        self.assertEqual(latest_assessment_result(self.first["learner_id"], "pre", self.database)["technical_score"], 18)
        self.saved_progress = self.snapshot()
        self.client = self.app.test_client()
        self.authenticate.reset_mock()

    def form_token(self, client=None):
        response = self.get("/auth/login", client)
        self.assertEqual(response.status_code, 200)
        form = re.search(r'<form\b[^>]*action="/auth/login"[^>]*>(.*?)</form>', response.text, re.DOTALL)
        self.assertIsNotNone(form)
        tokens = re.findall(r'name="csrf_token" value="([^"]+)"', form.group(1))
        self.assertEqual(len(tokens), 1)
        return tokens[0]

    def post_form(self, token, client=None, origin=None):
        return self.post("/auth/login", {
            "username": self.username, "password": self.password, "csrf_token": token,
        }, client, headers={"Origin": origin or self.base_url})

    def assert_rejected_before_directory(self, response, admission_before):
        self.assertEqual(response.status_code, 400)
        self.authenticate.assert_not_called()
        self.revalidate.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), admission_before)
        self.assertEqual(self.snapshot(), self.saved_progress)
        self.assertNotIn(self.username, response.text)
        self.assertNotIn(self.password, response.text)

    def assert_fresh_form_recovers(self, client=None):
        fresh_token = self.form_token(client)
        response = self.post_form(fresh_token, client)
        self.assertEqual(response.status_code, 302)
        self.authenticate.assert_called_once_with(self.username, self.password)
        self.revalidate.assert_not_called()
        self.assertEqual(self.get("/student", client).status_code, 200)
        self.assertEqual(self.snapshot(), self.saved_progress)

    def test_fresh_login_form_survives_app_restart_with_same_signing_key(self):
        token = self.form_token()
        restarted = self.copied_cookie_client(create_app(self.config))
        response = self.post_form(token, restarted)
        self.assertEqual(response.status_code, 302)
        self.authenticate.assert_called_once_with(self.username, self.password)
        self.revalidate.assert_not_called()
        self.assertEqual(self.get("/student", restarted).status_code, 200)
        self.assertEqual(self.snapshot(), self.saved_progress)

    def test_changed_signing_key_rejects_old_form_before_directory_and_fresh_get_recovers(self):
        token = self.form_token()
        restarted = self.copied_cookie_client(create_app({
            **self.config, "SECRET_KEY": "different-synthetic-signing-key-at-least-32-characters",
        }))
        admission_before = self.state_path.read_bytes()
        self.assert_rejected_before_directory(self.post_form(token, restarted), admission_before)
        self.assert_fresh_form_recovers(restarted)

    def test_cookie_older_than_900_seconds_rejects_form_before_directory_and_fresh_get_recovers(self):
        token = self.form_token()
        admission_before = self.state_path.read_bytes()
        # TimestampSigner accepts age == max_age. The server-side account
        # boundary expires at exactly 900; an anonymous cookie expires after it.
        self.wall_clock.return_value = self.start + 901
        self.assert_rejected_before_directory(self.post_form(token), admission_before)
        self.assert_fresh_form_recovers()

    def test_expired_server_session_rejects_still_signed_form_before_directory(self):
        self.login()
        self.wall_clock.return_value = self.start + 899
        token = self.form_token()  # Cookie is freshly signed, not expired.
        self.authenticate.reset_mock()
        admission_before = self.state_path.read_bytes()
        self.wall_clock.return_value = self.start + 900
        self.assert_rejected_before_directory(self.post_form(token), admission_before)
        self.assert_fresh_form_recovers()

    def test_revoked_server_session_rejects_form_before_directory_and_fresh_get_recovers(self):
        self.login()
        token = self.form_token()
        self.authenticate.reset_mock()
        admission_before = self.state_path.read_bytes()
        revoke_all_sessions(self.database, account_id=self.first["id"])
        self.assert_rejected_before_directory(self.post_form(token), admission_before)
        self.assert_fresh_form_recovers()

    def test_foreign_origin_rejects_valid_form_without_directory_or_progress_changes(self):
        token = self.form_token()
        admission_before = self.state_path.read_bytes()
        response = self.post_form(token, origin="https://outside.example")
        self.assert_rejected_before_directory(response, admission_before)
        self.assert_fresh_form_recovers()

    def test_same_origin_form_policy_covers_login_lesson_and_logout(self):
        # Native navigation POSTs derive Origin from the document's policy.
        # A test-client POST alone cannot detect a no-referrer regression.
        for path, status in (("/auth/login", 200), ("/student", 401)):
            with self.subTest(path=path):
                page = self.get(path)
                self.assertEqual(page.status_code, status)
                self.assertEqual(page.headers["Referrer-Policy"], "same-origin")
                self.assertEqual(page.headers["Cache-Control"], "no-store")
                self.assertIn("form-action 'self'", page.headers["Content-Security-Policy"])
        response = self.post_form(self.form_token())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
        self.authenticate.assert_called_once_with(self.username, self.password)
        self.revalidate.assert_not_called()
        lesson = self.get("/modules/hardware_basics")
        self.assertEqual(lesson.status_code, 200)
        self.assertEqual(lesson.headers["Referrer-Policy"], "same-origin")
        response = self.submit("/auth/logout", headers={"Origin": self.base_url})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
        self.assertEqual(self.get("/student").status_code, 401)
        self.assertEqual(self.snapshot(), self.saved_progress)

    def test_null_foreign_downgrade_and_wrong_port_origins_still_reject_valid_csrf(self):
        token = self.form_token()
        admission_before = self.state_path.read_bytes()
        for origin in ("null", "https://outside.example", "http://launchpad.example", "https://launchpad.example:8443"):
            with self.subTest(origin=origin):
                response = self.post_form(token, origin=origin)
                self.assert_rejected_before_directory(response, admission_before)
                self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
        self.assert_fresh_form_recovers()

    def test_same_origin_does_not_admit_missing_or_wrong_csrf(self):
        self.form_token()
        admission_before = self.state_path.read_bytes()
        for supplied in (None, "wrong-synthetic-token"):
            with self.subTest(token="missing" if supplied is None else "wrong"):
                fields = {"username": self.username, "password": self.password}
                if supplied is not None:
                    fields["csrf_token"] = supplied
                response = self.post("/auth/login", fields, headers={"Origin": self.base_url})
                self.assert_rejected_before_directory(response, admission_before)
        self.assert_fresh_form_recovers()


if __name__ == "__main__":
    unittest.main()
