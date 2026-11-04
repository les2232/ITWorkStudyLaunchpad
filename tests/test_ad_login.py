"""AD HTTP/session boundaries with synthetic identities and no directory calls.

Transport, credential verification and GUID extraction are exercised separately
by adapter tests. Here the adapter's verified-identity boundary is mocked while
real forms, persistent accounts, permissions, scoring and sessions are used.
"""
from contextlib import closing, redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from werkzeug.datastructures import MultiDict

from launchpad import create_app
from launchpad.accounts import (
    assign_mentor, create_auth_session, enroll_account, get_session_account,
    set_account_active,
)
from launchpad.ad import ADLoginError, authenticate_ad as authenticate_ad_adapter
from launchpad.ad_state import ADStateError, initialize_ad_state
from launchpad.demo import synthetic_beginner_responses
from launchpad.quizzes import get_module_quiz
from launchpad.real_data import initialize_real_database
from launchpad.storage import (
    activity_progress, connect, latest_assessment_result,
    latest_module_quiz_result, module_is_complete,
)
from tests import test_real_authorization as authz_fixture
from tests import test_real_login_flow as tls_fixture
from scripts.manage_real_data import main as manage_data


class ADLoginTests(unittest.TestCase):
    base_url = "https://launchpad.example"
    cookie_name = "__Host-launchpad_session"
    namespace = "8d858f93-c6cf-4310-9379-a11f1c941c25"
    issuer = "urn:launchpad:ad:" + namespace
    first_guid = "c2790bd9-a8e7-45b4-8caa-bc98c8bce138"
    second_guid = "69b53249-37e8-49ad-8dc8-dc22d76d0fbb"
    mentor_guid = "bf3e6493-92c5-4ac5-adfd-1bcb891c5cba"
    reads = authz_fixture.RealAuthorizationTests.reads
    writes = authz_fixture.RealAuthorizationTests.writes
    learner_tables = authz_fixture.RealAuthorizationTests.learner_tables

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="launchpad-ad-http-", dir="/tmp")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.database = self.directory / "learners.sqlite"
        self.state_path = self.directory / "ad-security.sqlite"
        initialize_real_database(self.database)
        initialize_ad_state(self.state_path)
        certificate, _key = tls_fixture.RealLoginProcessTests.make_certificate(self)
        self.first = enroll_account(self.issuer, self.first_guid, "Same synthetic name", db_path=self.database)
        self.second = enroll_account(self.issuer, self.second_guid, "Same synthetic name", db_path=self.database)
        self.mentor = enroll_account(self.issuer, self.mentor_guid, role="mentor", db_path=self.database)
        self.config = {
            "TESTING": True, "LAUNCHPAD_REAL_MODE": True,
            "LAUNCHPAD_DEMO_MODE": False, "LAUNCHPAD_PILOT_MODE": False,
            "LAUNCHPAD_DB_PATH": str(self.database),
            "SECRET_KEY": "synthetic-ad-http-signing-key-at-least-32-characters",
            "LAUNCHPAD_TRUSTED_HOSTS": "launchpad.example",
            "LAUNCHPAD_AUTH_BACKEND": "ad",
            "LAUNCHPAD_AD_HOST": "dc.example.test", "LAUNCHPAD_AD_PORT": "636",
            "LAUNCHPAD_AD_CA_FILE": str(certificate), "LAUNCHPAD_AD_DOMAIN": "example.test",
            "LAUNCHPAD_AD_BASE_DN": "DC=example,DC=test",
            "LAUNCHPAD_AD_GROUP_DN": "CN=Training,DC=example,DC=test",
            "LAUNCHPAD_AD_GROUP_POLICY": "direct",
            "LAUNCHPAD_AD_IDENTITY_NAMESPACE": self.namespace,
            "LAUNCHPAD_AD_LOOKUP_USERNAME": "reader@example.test",
            "LAUNCHPAD_AD_LOOKUP_PASSWORD": "synthetic-directory-reader-password",
            "LAUNCHPAD_AD_REVALIDATE_SECONDS": "60",
            "LAUNCHPAD_AD_STATE_PATH": str(self.state_path),
        }
        self.clock = patch("launchpad.real_auth.time.monotonic", return_value=1000).start()
        self.addCleanup(patch.stopall)
        self.authenticate = patch("launchpad.real_auth.authenticate_ad", return_value=self.identity(self.first)).start()
        self.revalidate = patch("launchpad.real_auth.revalidate_ad", side_effect=lambda subject, *args, **kwargs: {
            "issuer": self.issuer, "subject": subject,
        }).start()
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    @staticmethod
    def identity(account):
        return {"issuer": account["issuer"], "subject": account["subject"]}

    def get(self, path, client=None, **kwargs):
        return (client or self.client).get(path, base_url=self.base_url, **kwargs)

    def post(self, path, data=None, client=None, **kwargs):
        return (client or self.client).post(path, data=data or {}, base_url=self.base_url, **kwargs)

    def token(self, client=None):
        with (client or self.client).session_transaction(base_url=self.base_url) as browser_session:
            token = browser_session.get("csrf_token")
        if token is None:
            self.get("/auth/login", client)
            with (client or self.client).session_transaction(base_url=self.base_url) as browser_session:
                token = browser_session["csrf_token"]
        return token

    def handle(self, client=None):
        with (client or self.client).session_transaction(base_url=self.base_url) as browser_session:
            return browser_session["auth_session"]

    def submit(self, path, fields=None, client=None, **kwargs):
        return self.post(path, {**(fields or {}), "csrf_token": self.token(client)}, client, **kwargs)

    def login(self, account=None, client=None, username="invented.user"):
        account = account or self.first
        client = client or self.client
        self.authenticate.return_value = self.identity(account)
        response = self.submit("/auth/login", {"username": username, "password": "invented-password"}, client)
        self.assertEqual(response.status_code, 302)
        return client

    def snapshot(self, learner_id=None):
        with closing(connect(self.database)) as db:
            result = {}
            for table in self.learner_tables:
                field = "id" if table == "students" else "student_id"
                query = f"SELECT * FROM {table}"
                arguments = ()
                if learner_id is not None:
                    query += f" WHERE {field}=?"
                    arguments = (learner_id,)
                result[table] = [tuple(row) for row in db.execute(query + " ORDER BY id", arguments)]
            return result

    def copied_cookie_client(self, app=None, client=None):
        source = client or self.client
        cookie = source.get_cookie(self.cookie_name, domain="launchpad.example").value
        target = (app or self.app).test_client()
        target.set_cookie(self.cookie_name, cookie, domain="launchpad.example", secure=True)
        return target

    def test_ad_form_needs_no_oidc_registration_and_anonymous_endpoints_are_protected(self):
        self.assertFalse(any(key.startswith("LAUNCHPAD_OIDC_") for key in self.config))
        page = self.get("/auth/login")
        self.assertEqual(page.status_code, 200)
        self.assertRegex(page.text, r'name="username"')
        self.assertRegex(page.text, r'type="password"')
        self.assertRegex(page.text, r'name="csrf_token"')
        self.assertNotIn("does not ask for your password", page.text)
        for path in self.reads:
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status_code, 401)
        for path in self.writes:
            with self.subTest(path=path):
                self.assertEqual(self.post(path, {"completed": "1"}).status_code, 401)
        self.authenticate.assert_not_called()
        self.revalidate.assert_not_called()
        self.assertEqual(self.get("/auth/callback?code=unused&state=unused").status_code, 404)

    def test_incomplete_ad_startup_refuses_before_opening_learner_database(self):
        before = self.database.read_bytes()
        overrides = (
            {"LAUNCHPAD_AD_LOOKUP_USERNAME": ""},
            {"LAUNCHPAD_AD_LOOKUP_USERNAME": "DOMAIN\\reader"},
            {"LAUNCHPAD_AD_LOOKUP_USERNAME": "reader@outside.example"},
            {"LAUNCHPAD_AD_LOOKUP_PASSWORD": ""},
            {"LAUNCHPAD_AD_LOOKUP_PASSWORD": "synthetic\x00invalid"},
            {"LAUNCHPAD_AD_REVALIDATE_SECONDS": "0"},
            {"LAUNCHPAD_AD_REVALIDATE_SECONDS": "301"},
            {"LAUNCHPAD_AD_STATE_PATH": str(self.directory / "missing.sqlite")},
            {"LAUNCHPAD_AD_STATE_PATH": str(self.database)},
        )
        for values in overrides:
            with self.subTest(values=tuple(values)), patch("launchpad.web.validate_real_database") as opened:
                with self.assertRaises(ValueError):
                    create_app({**self.config, **values})
                opened.assert_not_called()
                self.assertEqual(self.database.read_bytes(), before)
        self.assertFalse((self.directory / "missing.sqlite").exists())
        self.authenticate.assert_not_called()
        self.revalidate.assert_not_called()

    def test_ad_username_field_has_cca_label_and_accessible_w_number_hint(self):
        page = self.get("/auth/login")
        self.assertRegex(page.text, r'<label for="username">CCA username</label>')
        username_input = re.search(r'<input\b[^>]*\bid="username"[^>]*>', page.text)
        self.assertIsNotNone(username_input)
        description = re.search(r'\baria-describedby="([^"]+)"', username_input.group())
        self.assertIsNotNone(description)
        hint_text = []
        for hint_id in description.group(1).split():
            hint = re.search(r'<[^>]*\bid="' + re.escape(hint_id) + r'"[^>]*>([^<]*)<', page.text)
            self.assertIsNotNone(hint)
            hint_text.append(hint.group(1))
        self.assertIn("W-number", " ".join(hint_text))

    def test_w_number_and_upn_forms_keep_guid_enrollment_and_exact_password(self):
        before = self.snapshot()
        password = "  Invented Password\t "
        self.authenticate.side_effect = authenticate_ad_adapter
        aliases = (
            "W00001001",
            "w00001001@example.test",
            " \tW00001001\n",
            " W00001001@EXAMPLE.TEST ",
        )
        with patch("launchpad.ad._query", return_value=self.identity(self.first)) as directory:
            for username in aliases:
                with self.subTest(username=username):
                    response = self.submit("/auth/login", {"username": username, "password": password})
                    self.assertEqual(response.status_code, 302)
                    directory.assert_called_with(
                        "(userPrincipalName=w00001001@example.test)",
                        "w00001001@example.test", password,
                        self.app.extensions["launchpad_ad"],
                    )
                    account = get_session_account(self.handle(), self.database)
                    self.assertEqual(account["id"], self.first["id"])
                    self.assertEqual(account["subject"], self.first_guid)
                    self.assertEqual(account["learner_id"], self.first["learner_id"])
                    self.assertNotEqual(account["learner_id"], self.second["learner_id"])
                    self.assertEqual(self.get("/student").status_code, 200)
                    self.assertEqual(self.submit("/auth/logout").status_code, 302)
            self.assertEqual(directory.call_count, len(aliases))
        self.assertEqual(self.snapshot(), before)

    def test_malformed_username_forms_are_generic_and_never_query_directory(self):
        before = self.snapshot()
        self.authenticate.side_effect = authenticate_ad_adapter
        invalid = (
            " \t\n ", "W0000 1001", "W00001001@", "@example.test",
            "W00001001@outside.test", "W00001001@example.test@example.test",
            "DOMAIN\\W00001001", "W00001001)(objectClass=*)", "W00001001\x00",
        )
        with patch("launchpad.ad._query") as directory:
            for username in invalid:
                with self.subTest(username=username):
                    response = self.submit("/auth/login", {"username": username, "password": "invented"})
                    self.assertEqual(response.status_code, 401)
                    self.assertIn("Sign-in could not be completed. Check your details or contact IT.", response.text)
                    self.assertEqual(self.get("/student").status_code, 401)
            directory.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_operator_cli_initializes_only_new_state_and_verifies_without_changes(self):
        output = io.StringIO()
        errors = io.StringIO()
        new_state = self.directory / "new-state.sqlite"
        original_umask = os.umask(0o077)
        try:
            with redirect_stdout(output), redirect_stderr(errors):
                self.assertEqual(manage_data(["initialize-ad-state", "--path", str(new_state)]), 0)
                before = new_state.read_bytes()
                self.assertEqual(manage_data(["verify-ad-state", "--path", str(new_state)]), 0)
                self.assertEqual(new_state.read_bytes(), before)
                self.assertEqual(manage_data(["initialize-ad-state", "--path", str(new_state)]), 2)
                self.assertEqual(new_state.read_bytes(), before)
        finally:
            os.umask(original_umask)
        self.assertNotIn(str(new_state), output.getvalue() + errors.getvalue())
        self.assertEqual(new_state.stat().st_mode & 0o777, 0o600)

    def test_login_csrf_foreign_origin_and_duplicate_credentials_do_not_reach_directory(self):
        self.get("/auth/login")
        self.assertEqual(self.post("/auth/login", {"username": "invented.user", "password": "invented"}).status_code, 400)
        self.assertEqual(self.submit("/auth/login", {"username": "invented.user", "password": "invented"},
                                     headers={"Origin": "https://outside.example"}).status_code, 400)
        for name in ("username", "password"):
            fields = MultiDict([("csrf_token", self.token()), ("username", "invented.user"),
                                ("password", "invented"), (name, "duplicate")])
            with self.subTest(name=name):
                self.assertEqual(self.post("/auth/login", fields).status_code, 401)
        self.authenticate.assert_not_called()

    def test_invalid_credentials_and_unenrolled_identity_share_generic_errors_without_echo(self):
        before = self.snapshot()
        self.authenticate.side_effect = ADLoginError("private-directory-detail")
        failed = self.submit("/auth/login", {"username": "private-login-name", "password": "private-login-password"})
        self.assertEqual(failed.status_code, 401)
        self.authenticate.side_effect = None
        self.authenticate.return_value = {"issuer": self.issuer, "subject": "9f1590a2-c36e-4f3d-a812-695f407ebd64"}
        unenrolled = self.submit("/auth/login", {"username": "other-invented-user", "password": "private-login-password"})
        self.assertEqual(unenrolled.status_code, 401)
        # Compare user-facing failure copy, allowing fresh anti-CSRF tokens.
        for marker in ("private-directory-detail", "private-login-name", "private-login-password", self.config["LAUNCHPAD_AD_LOOKUP_PASSWORD"]):
            self.assertNotIn(marker, failed.text + unenrolled.text)
        def without_csrf_token(page):
            return re.sub(r'name="csrf_token" value="[^"]+"', 'name="csrf_token" value="fresh-token"', page)
        self.assertEqual(without_csrf_token(failed.text), without_csrf_token(unenrolled.text))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.get("/student").status_code, 401)

    def test_username_upn_case_aliases_share_persistent_throttle_and_sixth_never_binds(self):
        self.authenticate.side_effect = ADLoginError("synthetic refusal")
        for username in ("invented.user", "INVENTED.USER", "invented.user@example.test", "Invented.User@EXAMPLE.TEST", "invented.user"):
            response = self.submit("/auth/login", {"username": username, "password": "invented"})
            self.assertEqual(response.status_code, 401)
        self.assertEqual(self.authenticate.call_count, 5)
        restarted = create_app(self.config).test_client()
        response = self.submit("/auth/login", {"username": "invented.user@example.test", "password": "invented"}, restarted)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("Retry-After"), "300")
        self.assertEqual(self.authenticate.call_count, 5)
        self.assertNotIn(b"invented.user", self.state_path.read_bytes())

    def test_w_number_upn_case_and_whitespace_aliases_share_persistent_throttle(self):
        self.authenticate.side_effect = ADLoginError("synthetic refusal")
        aliases = (
            "W00001001", " w00001001 ", "W00001001@example.test",
            "\tw00001001@EXAMPLE.TEST\n", " w00001001@Example.Test ",
        )
        for username in aliases:
            with self.subTest(username=username):
                response = self.submit("/auth/login", {"username": username, "password": "invented"})
                self.assertEqual(response.status_code, 401)
        self.assertEqual(self.authenticate.call_count, 5)
        restarted = create_app(self.config).test_client()
        blocked = self.submit("/auth/login", {"username": "W00001001", "password": "invented"}, restarted)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.headers.get("Retry-After"), "300")
        self.assertEqual(self.authenticate.call_count, 5)
        # This is the account's shared limit, not an accidental global lockout.
        another = self.submit("/auth/login", {"username": "W00001002", "password": "invented"}, restarted)
        self.assertEqual(another.status_code, 401)
        self.assertEqual(self.authenticate.call_count, 6)
        state = self.state_path.read_bytes().lower()
        self.assertNotIn(b"w00001001", state)
        self.assertNotIn(b"invented", state)

    def test_throttle_storage_failure_never_calls_directory_or_exposes_internal_error(self):
        before = self.snapshot()
        with patch("launchpad.real_auth.reserve_login_attempt", side_effect=ADStateError("private file details")):
            response = self.submit("/auth/login", {"username": "invented.user", "password": "invented"})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("private file details", response.text)
        self.authenticate.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_ad_identity_cannot_attach_to_oidc_binding_or_claim_role_fields(self):
        oidc = enroll_account("https://identity.example.invalid", self.first_guid, "Same synthetic name", db_path=self.database)
        self.login()
        self.assertNotEqual(get_session_account(self.handle(), self.database)["id"], oidc["id"])
        before = self.snapshot()
        for field, value in (("student_id", self.second["learner_id"]), ("learner_id", self.second["learner_id"]),
                             ("subject", self.second_guid), ("role", "admin"), ("issuer", oidc["issuer"])):
            with self.subTest(field=field):
                self.assertEqual(self.submit("/modules/hardware_basics", {field: value, "completed": "1"}).status_code, 403)
        self.assertEqual(self.get("/supervisor").status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_learner_cross_record_reads_writes_and_selectors_are_denied(self):
        self.login()
        before = self.snapshot()
        for path in self.reads:
            with self.subTest(path=path):
                self.assertEqual(self.get(path, query_string={"learner_id": self.second["learner_id"]}).status_code, 403)
        for path in self.writes:
            with self.subTest(path=path):
                self.assertEqual(self.submit(path, {"student_id": self.second["learner_id"], "completed": "1"}).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_mentor_reads_only_assigned_learner_and_cannot_write(self):
        assign_mentor(self.mentor["id"], self.first["learner_id"], self.database)
        self.login(self.mentor)
        self.assertEqual(self.get("/supervisor").status_code, 200)
        self.assertEqual(self.get(f"/supervisor/learners/{self.first['learner_id']}").status_code, 200)
        self.assertEqual(self.get(f"/supervisor/learners/{self.second['learner_id']}").status_code, 404)
        before = self.snapshot()
        for path in self.writes:
            with self.subTest(path=path):
                self.assertEqual(self.submit(path, {"completed": "1"}).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_cached_session_has_bounded_delay_then_directory_denial_revokes_every_session(self):
        self.login()
        first_token = self.handle()
        other_client = self.login(client=self.app.test_client(), username="another.synthetic.login")
        other_token = self.handle(other_client)
        replay = self.copied_cookie_client(client=other_client)
        self.revalidate.side_effect = ADLoginError("removed, disabled, or unavailable")
        self.clock.return_value = 1059
        self.assertEqual(self.get("/student").status_code, 200)
        self.revalidate.assert_not_called()
        before = self.snapshot()
        self.clock.return_value = 1060
        self.assertEqual(self.submit("/modules/hardware_basics", {"completed": "1"}).status_code, 503)
        self.revalidate.assert_called_once()
        self.assertIsNone(get_session_account(first_token, self.database))
        self.assertIsNone(get_session_account(other_token, self.database))
        self.assertEqual(self.get("/student", replay).status_code, 401)
        self.assertEqual(self.snapshot(), before)

    def test_directory_outage_after_app_recreation_denies_before_learner_writes(self):
        self.login()
        before = self.snapshot()
        recreated = create_app(self.config)
        restarted_client = self.copied_cookie_client(recreated)
        self.revalidate.side_effect = ADLoginError("synthetic network timeout")
        response = self.submit("/modules/hardware_basics", {"completed": "1"}, restarted_client)
        self.assertEqual(response.status_code, 503)
        self.revalidate.assert_called_once()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(module_is_complete(self.first["learner_id"], "hardware_basics", self.database))

    def test_revalidation_cannot_replace_a_session_with_another_directory_identity(self):
        self.login()
        token = self.handle()
        before = self.snapshot()
        self.clock.return_value = 1060
        self.revalidate.side_effect = None
        self.revalidate.return_value = self.identity(self.second)
        self.assertEqual(self.submit("/modules/hardware_basics", {"completed": "1"}).status_code, 503)
        self.assertIsNone(get_session_account(token, self.database))
        self.assertEqual(self.snapshot(), before)

    def test_logout_still_revokes_during_outage_and_replay_stays_denied(self):
        self.login()
        token = self.handle()
        replay = self.copied_cookie_client()
        self.clock.return_value = 1060
        self.revalidate.side_effect = ADLoginError("synthetic outage")
        self.assertEqual(self.submit("/auth/logout").status_code, 302)
        self.assertIsNone(get_session_account(token, self.database))
        self.assertEqual(self.get("/student", replay).status_code, 401)

    def test_local_disablement_is_immediate_inside_directory_cache_window(self):
        self.login()
        token = self.handle()
        set_account_active(self.first["id"], False, self.database)
        self.assertEqual(self.get("/student").status_code, 401)
        self.assertIsNone(get_session_account(token, self.database))
        self.revalidate.assert_not_called()

    def test_namespace_change_and_old_oidc_tokens_cannot_cross_authentication_backends(self):
        self.login()
        changed = create_app({**self.config, "LAUNCHPAD_AD_IDENTITY_NAMESPACE": "8820f899-35d6-4086-a869-a045c0d0880a"})
        changed_client = self.copied_cookie_client(changed)
        self.assertEqual(self.get("/student", changed_client).status_code, 401)
        oidc = enroll_account("https://identity.example.invalid", self.first_guid, "Same synthetic name", db_path=self.database)
        old_token = create_auth_session(oidc["id"], self.database)
        with self.client.session_transaction(base_url=self.base_url) as browser_session:
            browser_session["auth_session"] = old_token
        self.assertEqual(self.get("/student").status_code, 401)
        self.assertIsNone(get_session_account(old_token, self.database))
        self.revalidate.assert_not_called()

    def test_scoring_completion_navigation_reload_and_recreation_keep_only_own_progress(self):
        untouched = self.snapshot(self.second["learner_id"])
        self.login()
        self.assertEqual(self.submit("/pre-assessment", synthetic_beginner_responses()).status_code, 302)
        self.assertIn(b"18%", self.get("/assessment-results").data)
        self.assertEqual(latest_assessment_result(self.first["learner_id"], "pre", self.database)["technical_score"], 18)
        self.assertEqual(self.submit("/modules/hardware_basics", {"completed": "1"}).status_code, 302)
        quiz = get_module_quiz("hardware_basics")
        answer = {question["id"]: question["answer"] for question in quiz["questions"]}
        response = self.submit("/modules/hardware_basics/quiz", answer)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"3 / 3 correct (100%)", response.data)
        self.assertEqual(latest_module_quiz_result(self.first["learner_id"], "hardware_basics", self.database)["score"], 100)
        self.assertEqual(self.submit("/training-path/beginner/activities/beginner_shadow_mentor", {"completed": "1"}).status_code, 302)
        self.assertIn("beginner_shadow_mentor", activity_progress(self.first["learner_id"], self.database))
        saved = self.snapshot(self.first["learner_id"])
        for path in ("/learn", "/help", "/student", "/student"):
            self.assertEqual(self.get(path).status_code, 200)
        restarted = self.copied_cookie_client(create_app(self.config))
        self.assertEqual(self.get("/student", restarted).status_code, 200)
        self.revalidate.assert_called_once()
        self.assertIn(b"3 / 3 correct (100%)", self.get("/modules/hardware_basics", restarted).data)
        self.assertTrue(module_is_complete(self.first["learner_id"], "hardware_basics", self.database))
        self.assertEqual(self.snapshot(self.first["learner_id"]), saved)
        self.assertEqual(self.snapshot(self.second["learner_id"]), untouched)


if __name__ == "__main__":
    unittest.main()
