"""Bounded login rejection evidence; invented data and no directory traffic."""
import io
import logging
import unittest
from unittest.mock import patch

from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import BadRequest

from launchpad import create_app
from launchpad.accounts import revoke_all_sessions
from launchpad.ad import ADLoginError, authenticate_ad as authenticate_ad_adapter
from launchpad.ad_state import ADStateError
from launchpad.demo import synthetic_beginner_responses
from tests import test_controlled_ad_mode as fixture


class LoginDiagnosticsTests(unittest.TestCase):
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

    logger_name = "launchpad.login_diagnostic"
    private = "DO-NOT-LOG-invented-private-data"

    def setUp(self):
        fixture.ControlledADModeTests.setUp(self)
        self.login()
        self.assertEqual(self.submit("/pre-assessment", synthetic_beginner_responses()).status_code, 302)
        self.saved_progress = self.snapshot()
        self.client = self.app.test_client()
        self.authenticate.reset_mock()

    def fields(self):
        return {"csrf_token": self.token(), "username": "W00001001", "password": "  " + self.private + "  "}

    def rejected(self, reason, status, fields, **kwargs):
        cookie = self.client.get_cookie(self.cookie_name, domain="launchpad.example")
        token = fields.get("csrf_token") if fields is not None else None
        with self.assertLogs(self.logger_name, level="WARNING") as captured:
            response = self.post("/auth/login?never_record=" + self.private, fields, **kwargs)
        self.assertEqual(response.status_code, status)
        self.assertEqual(len(captured.records), 1)
        record = captured.records[0]
        self.assertRegex(record.getMessage(),
                         r"^timestamp=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00 method=POST path=/auth/login status="
                         + str(status) + r" reason=" + reason + r"$")
        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.stack_info)
        for secret in (self.private, token, cookie.value if cookie else None):
            if secret:
                self.assertNotIn(secret, record.getMessage())
        self.assertEqual(self.snapshot(), self.saved_progress)
        self.revalidate.assert_not_called()
        return response

    def test_missing_cookie_and_csrf_fields_are_distinguished_without_logging_secrets(self):
        fields = self.fields()
        self.client.delete_cookie(self.cookie_name, domain="launchpad.example")
        before = self.state_path.read_bytes()
        self.rejected("csrf_session_absent", 400, fields, headers={
            "Authorization": "Bearer " + self.private, "User-Agent": self.private,
            "X-Forwarded-For": self.private,
        })
        self.authenticate.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_csrf_token_count_and_mismatch_have_bounded_reasons(self):
        for kind in ("missing", "duplicate", "mismatch"):
            with self.subTest(kind=kind):
                self.client = self.app.test_client()
                fields = MultiDict(self.fields())
                if kind == "missing":
                    fields.pop("csrf_token")
                elif kind == "duplicate":
                    fields.add("csrf_token", self.private)
                else:
                    fields["csrf_token"] = self.private
                before = self.state_path.read_bytes()
                self.rejected("csrf_mismatch" if kind == "mismatch" else "csrf_token_count", 400, fields)
                self.assertEqual(self.state_path.read_bytes(), before)
        self.authenticate.assert_not_called()

    def test_origin_value_is_not_logged(self):
        before = self.state_path.read_bytes()
        self.rejected("origin_rejected", 400, self.fields(),
                      headers={"Origin": "https://" + self.private + ".invalid"})
        self.authenticate.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_expired_or_revoked_local_session_is_identified_without_claiming_which(self):
        for invalidation in ("expiry", "revocation"):
            with self.subTest(invalidation=invalidation):
                self.wall_clock.return_value = self.start
                self.client = self.app.test_client()
                self.login()
                fields = self.fields()
                self.authenticate.reset_mock()
                if invalidation == "expiry":
                    self.wall_clock.return_value = self.start + 900
                else:
                    revoke_all_sessions(self.database, account_id=self.first["id"])
                before = self.state_path.read_bytes()
                self.rejected("csrf_after_session_invalid", 400, fields)
                self.authenticate.assert_not_called()
                self.assertEqual(self.state_path.read_bytes(), before)

    def test_missing_duplicate_and_oversized_login_fields_remain_pre_directory(self):
        for kind in ("missing", "duplicate", "oversized"):
            with self.subTest(kind=kind):
                self.client = self.app.test_client()
                fields = MultiDict(self.fields())
                if kind == "missing":
                    fields.pop("password")
                elif kind == "duplicate":
                    fields.add("username", self.private)
                else:
                    fields["password"] = self.private * 40
                before = self.state_path.read_bytes()
                self.rejected("login_fields_invalid", 401, fields)
                self.assertEqual(self.state_path.read_bytes(), before)
        self.authenticate.assert_not_called()

    def test_invalid_username_uses_existing_validation_and_throttle_without_directory(self):
        fields = self.fields()
        fields["username"] = self.private + "@outside.invalid"
        self.authenticate.side_effect = authenticate_ad_adapter
        with patch("launchpad.ad._query") as directory:
            self.rejected("login_identity_invalid", 401, fields)
            directory.assert_not_called()

    def test_throttle_and_unavailable_ad_state_are_distinct_and_do_not_bind(self):
        for rejected, reason, status in (
            (False, "login_throttled", 429),
            (ADStateError(self.private), "ad_state_unavailable", 401),
        ):
            with self.subTest(reason=reason):
                self.client = self.app.test_client()
                fields = self.fields()
                with patch("launchpad.real_auth.reserve_login_attempt", return_value=rejected,
                           side_effect=rejected if isinstance(rejected, Exception) else None):
                    response = self.rejected(reason, status, fields)
                if status == 429:
                    self.assertEqual(response.headers["Retry-After"], "300")
        self.authenticate.assert_not_called()

    def test_directory_and_local_enrollment_failures_do_not_expose_identity_or_exception(self):
        cases = (
            (ADLoginError(self.private), None, "ad_denied_or_unavailable"),
            (None, {"issuer": "unapproved-" + self.private, "subject": self.private}, "identity_issuer_mismatch"),
            (None, {"issuer": self.issuer, "subject": "11111111-2222-3333-4444-555555555555"}, "enrollment_denied"),
        )
        for error, identity, reason in cases:
            with self.subTest(reason=reason):
                self.client = self.app.test_client()
                self.authenticate.side_effect = error
                self.authenticate.return_value = identity
                self.rejected(reason, 401, self.fields())

    def test_trusted_host_and_size_rejections_are_classified_without_echoing_request(self):
        fields = self.fields()
        with self.assertLogs(self.logger_name, level="WARNING") as captured:
            response = self.client.post("/auth/login?token=" + self.private,
                                        base_url="https://" + self.private + ".invalid", data=fields)
        # Anonymous authorization already returns 401 before Flask dispatches
        # its pending untrusted-host exception. Diagnostics must not change it.
        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(captured.records), 1)
        self.assertIn("reason=trusted_host_rejected", captured.records[0].getMessage())
        self.assertNotIn(self.private, str(captured.output))
        self.client = self.app.test_client()
        fields = self.fields()
        fields["password"] = self.private * 3000
        self.rejected("request_too_large", 413, fields)
        self.authenticate.assert_not_called()

    def test_body_read_error_and_unexpected_exception_never_log_exception_details(self):
        class BrokenInput(io.BytesIO):
            def readinto(stream, buffer):
                raise BadRequest(self.private)

        self.token()
        self.rejected("request_bad_request", 400, None, environ_overrides={
            "wsgi.input": BrokenInput(b"unread"), "CONTENT_LENGTH": "6",
            "CONTENT_TYPE": "application/x-www-form-urlencoded",
        })
        self.authenticate.assert_not_called()
        self.client = self.app.test_client()
        self.authenticate.side_effect = RuntimeError(self.private)
        self.rejected("internal_error", 500, self.fields())

    def test_success_get_and_production_mode_do_not_emit_controlled_rejection_diagnostics(self):
        with self.assertNoLogs(self.logger_name, level=logging.WARNING):
            self.get("/auth/login")
            self.login()
        production = create_app({**self.config,
            "LAUNCHPAD_AD_SESSION_POLICY": "revalidate",
            "LAUNCHPAD_AD_LOOKUP_USERNAME": "reader@example.test",
            "LAUNCHPAD_AD_LOOKUP_PASSWORD": "invented-lookup-password",
            "LAUNCHPAD_AD_REVALIDATE_SECONDS": "60",
        })
        with self.assertNoLogs(self.logger_name, level=logging.WARNING):
            response = production.test_client().post("/auth/login", base_url=self.base_url)
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
