"""Controlled-login operator safeguards; all directory outcomes are synthetic."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from getpass import GetPassWarning
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch
import warnings

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from launchpad.accounts import enroll_account
from launchpad.ad import ADLoginError
from launchpad.ad_state import initialize_ad_state
from launchpad.real_data import initialize_real_database
from scripts import controlled_ad_login as helper


class ControlledADLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic controlled-login CA")])
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256())
        )
        cls.pem = certificate.public_bytes(serialization.Encoding.PEM)
        cls.bundle_hash = hashlib.sha256(cls.pem).hexdigest().upper()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="launchpad-controlled-helper-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.staging = self.root / "work" / "ad-login-test"
        self.directory = self.staging / "synthetic-run"
        self.directory.mkdir(parents=True, mode=0o700)
        self.database = self.directory / "learners.sqlite"
        self.state = self.directory / "ad-security.sqlite"
        initialize_real_database(self.database)
        initialize_ad_state(self.state)
        self.ca_file = self.root / "work" / "ad-ca-review" / "launchpad-ad-ca.pem"
        self.ca_file.parent.mkdir(mode=0o700)
        self.ca_file.write_bytes(self.pem)
        self.namespace = "7516b12d-8bcf-4a36-84a7-6fc8fb542d54"
        self.subject = "c2790bd9-a8e7-45b4-8caa-bc98c8bce138"
        self.issuer = "urn:launchpad:ad:" + self.namespace
        self.account = enroll_account(self.issuer, self.subject, "Synthetic controlled learner", db_path=self.database)
        self.config = {
            "LAUNCHPAD_REAL_MODE": True, "LAUNCHPAD_DEMO_MODE": False,
            "LAUNCHPAD_PILOT_MODE": False, "LAUNCHPAD_AUTH_BACKEND": "ad",
            "LAUNCHPAD_DATA_DIR": str(self.directory), "LAUNCHPAD_DB_PATH": str(self.database),
            "LAUNCHPAD_TRUSTED_HOSTS": helper.TEST_HOST,
            "LAUNCHPAD_AD_HOST": helper.DIRECTORY_HOST, "LAUNCHPAD_AD_PORT": 636,
            "LAUNCHPAD_AD_CA_FILE": str(self.ca_file), "LAUNCHPAD_AD_DOMAIN": "example.test",
            "LAUNCHPAD_AD_BASE_DN": "DC=example,DC=test", "LAUNCHPAD_AD_GROUP_DN": helper.GROUP_DN,
            "LAUNCHPAD_AD_GROUP_POLICY": "direct", "LAUNCHPAD_AD_IDENTITY_NAMESPACE": self.namespace,
            "LAUNCHPAD_AD_LOOKUP_USERNAME": "synthetic.reader@example.test",
            "LAUNCHPAD_AD_REVALIDATE_SECONDS": 60, "LAUNCHPAD_AD_STATE_PATH": str(self.state),
        }
        self.json_path = self.root / "non-secret.json"
        self.save_config()
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        patches = [
            patch.object(helper, "PROJECT_ROOT", self.root),
            patch.object(helper, "BUNDLE_SHA256", self.bundle_hash),
            patch("ldap3.Connection", side_effect=AssertionError("A test attempted a directory connection")),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def save_config(self, values=None):
        self.json_path.write_text(json.dumps(self.config if values is None else values), encoding="utf-8")

    def run_helper(self, *, execute=True, authenticate=None, lookup=None, username=None, subject=None):
        identity = {"issuer": self.issuer, "subject": self.subject}
        arguments = ["--config", str(self.json_path)] + (["--execute"] if execute else [])
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr), \
                patch.object(helper, "require_tty"), \
                patch.object(helper, "getpass", side_effect=[
                    username or "synthetic.learner@example.test", subject or self.subject,
                    "synthetic-lookup-secret", "synthetic-learner-secret",
                ]) as prompts, \
                patch("resource.setrlimit") as core_limit, \
                patch.object(helper.real_auth, "authenticate_ad", return_value=identity,
                             side_effect=authenticate) as login, \
                patch.object(helper.real_auth, "revalidate_ad", return_value=identity,
                             side_effect=lookup) as revalidate:
            result = helper.main(arguments)
            core_limit.assert_called_once() if execute else core_limit.assert_not_called()
        output = self.stdout.getvalue() + self.stderr.getvalue()
        for secret in ("synthetic-lookup-secret", "synthetic-learner-secret", self.subject,
                       "synthetic.learner@example.test", str(self.database)):
            self.assertNotIn(secret, output)
        return result, prompts, login, revalidate

    def test_missing_execute_refuses_before_config_read_prompt_or_database_write(self):
        before = self.database.read_bytes(), self.state.read_bytes()
        with patch.object(helper, "load_config", side_effect=AssertionError("config was read")):
            result, prompts, login, lookup = self.run_helper(execute=False)
        self.assertEqual(result, 2)
        prompts.assert_not_called()
        login.assert_not_called()
        lookup.assert_not_called()
        self.assertEqual(before, (self.database.read_bytes(), self.state.read_bytes()))

    def test_non_tty_refuses_before_config_read_or_prompts(self):
        with redirect_stdout(self.stdout), patch.object(helper.sys.stdin, "isatty", return_value=False), \
                patch.object(helper, "load_config") as config, patch.object(helper, "getpass") as prompt:
            self.assertEqual(helper.main(["--config", str(self.json_path), "--execute"]), 2)
        config.assert_not_called()
        prompt.assert_not_called()

    def test_getpass_warning_aborts_before_fallback_can_read_secret(self):
        def cannot_hide_input(*_args, **_kwargs):
            warnings.warn("Synthetic terminal lacks no-echo support", GetPassWarning)
            self.fail("GetPassWarning was not fatal")

        with patch.object(helper, "require_tty"), patch.object(helper, "getpass", side_effect=cannot_hide_input), \
                redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            with self.assertRaises(GetPassWarning):
                helper.private_input("Private input: ")
        self.assertEqual(self.stderr.getvalue(), "")

    def test_allowlist_rejects_secret_fields_missing_fields_and_unsafe_values(self):
        variants = [
            {**self.config, "LAUNCHPAD_AD_LOOKUP_PASSWORD": "synthetic forbidden file value"},
            {**self.config, "SECRET_KEY": "synthetic forbidden file value"},
            {key: value for key, value in self.config.items() if key != "LAUNCHPAD_AD_DOMAIN"},
            {**self.config, "LAUNCHPAD_AD_DOMAIN": ""},
            {**self.config, "LAUNCHPAD_REAL_MODE": "1"},
            {**self.config, "LAUNCHPAD_DEMO_MODE": True},
            {**self.config, "LAUNCHPAD_TRUSTED_HOSTS": "lesliec.ccaurora.edu"},
            {**self.config, "LAUNCHPAD_AD_HOST": "ldap://CCCDC01.ccc.ccofc.edu:389"},
            {**self.config, "LAUNCHPAD_AD_PORT": 389},
            {**self.config, "LAUNCHPAD_AD_GROUP_POLICY": ""},
            {**self.config, "LAUNCHPAD_AD_GROUP_DN": "CN=Other,DC=example,DC=test"},
            {**self.config, "LAUNCHPAD_AD_LOOKUP_USERNAME": "DOMAIN\\reader"},
            {**self.config, "LAUNCHPAD_AD_REVALIDATE_SECONDS": 0},
            {**self.config, "LAUNCHPAD_AD_REVALIDATE_SECONDS": 301},
            {**self.config, "LAUNCHPAD_AD_REVALIDATE_SECONDS": True},
        ]
        before = self.database.read_bytes(), self.state.read_bytes()
        for values in variants:
            with self.subTest(changed=[key for key in values if self.config.get(key) != values[key]]):
                self.save_config(values)
                with self.assertRaises((helper.Refused, ValueError)):
                    helper.load_config(self.json_path)
        self.assertEqual(before, (self.database.read_bytes(), self.state.read_bytes()))

    def test_duplicate_json_keys_are_rejected(self):
        self.json_path.write_text('{"LAUNCHPAD_REAL_MODE": true, "LAUNCHPAD_REAL_MODE": false}')
        with self.assertRaises(helper.Refused):
            helper.load_config(self.json_path)

    def test_protected_paths_symlinks_hardlinks_and_shared_permissions_are_rejected(self):
        values = {**self.config, "LAUNCHPAD_DB_PATH": str(self.root / "existing-real.sqlite")}
        self.save_config(values)
        with self.assertRaises(helper.Refused):
            helper.load_config(self.json_path)
        self.save_config()
        self.directory.chmod(0o750)
        with self.assertRaises(helper.Refused):
            helper.load_config(self.json_path)
        self.directory.chmod(0o700)
        self.database.chmod(0o644)
        with self.assertRaises(helper.Refused):
            helper.load_config(self.json_path)
        self.database.chmod(0o600)
        alias = self.directory / "alias.sqlite"
        alias.symlink_to(self.database)
        self.save_config({**self.config, "LAUNCHPAD_DB_PATH": str(alias)})
        with self.assertRaises(helper.Refused):
            helper.load_config(self.json_path)
        alias.unlink()
        os.link(self.database, alias)
        self.save_config()
        with self.assertRaises(helper.Refused):
            helper.load_config(self.json_path)

    def test_wrong_bundle_digest_or_external_bundle_is_rejected_without_changes(self):
        self.ca_file.write_bytes(self.pem + b"\n")
        before = self.database.read_bytes(), self.state.read_bytes()
        with self.assertRaises(helper.Refused):
            helper.load_config(self.json_path)
        self.ca_file.write_bytes(self.pem)
        self.save_config({**self.config, "LAUNCHPAD_AD_CA_FILE": "/etc/ssl/certs/ca-certificates.crt"})
        with self.assertRaises(helper.Refused):
            helper.load_config(self.json_path)
        self.assertEqual(before, (self.database.read_bytes(), self.state.read_bytes()))

    def test_success_uses_real_views_enrollment_recheck_logout_and_replay_with_one_call_each(self):
        result, prompts, login, lookup = self.run_helper()
        self.assertEqual(result, 0, self.stdout.getvalue())
        self.assertEqual(prompts.call_count, 4)
        login.assert_called_once_with("synthetic.learner@example.test", "synthetic-learner-secret")
        lookup.assert_called_once_with(self.subject, bind_username="synthetic.reader@example.test",
                                       bind_password="synthetic-lookup-secret")
        for step in ("anonymous-denied", "enrolled-login", "designated-identity", "own-learner", "learner-staff-denied",
                     "lookup-after-recreation", "logout", "old-cookie-denied"):
            self.assertIn(step + ": PASS", self.stdout.getvalue())
        for file in (self.database, self.state):
            self.assertNotIn(b"synthetic-learner-secret", file.read_bytes())
            self.assertNotIn(b"synthetic-lookup-secret", file.read_bytes())

    def test_directory_login_denial_stops_at_generic_401_without_retry_or_lookup(self):
        result, _prompts, login, lookup = self.run_helper(authenticate=ADLoginError("private directory detail"))
        self.assertEqual(result, 1)
        self.assertIn("enrolled-login: FAIL (HTTP 401)", self.stdout.getvalue())
        self.assertNotIn("private directory detail", self.stdout.getvalue())
        login.assert_called_once()
        lookup.assert_not_called()

    def test_invalid_or_foreign_upn_is_refused_before_password_prompts_or_bind(self):
        for username in ("invented.shortname", "invented@other.example", "invented*)(@example.test",
                         " invented@example.test", "invented@example.test ", "\tinvented@example.test"):
            with self.subTest(username=username):
                result, prompts, login, lookup = self.run_helper(username=username)
                self.assertEqual(result, 2)
                self.assertEqual(prompts.call_count, 1)
                login.assert_not_called()
                lookup.assert_not_called()

    def test_expected_guid_rejects_invalid_input_before_password_prompts_or_bind(self):
        result, prompts, login, lookup = self.run_helper(subject="synthetic display name")
        self.assertEqual(result, 2)
        self.assertEqual(prompts.call_count, 2)
        login.assert_not_called()
        lookup.assert_not_called()

    def test_learner_cannot_be_lookup_identity_even_with_case_variants(self):
        before = self.database.read_bytes(), self.state.read_bytes()
        for username in ("synthetic.reader@example.test", "SYNTHETIC.Reader@EXAMPLE.TEST"):
            with self.subTest(username=username):
                with patch.object(helper, "exercise") as exercise:
                    result, prompts, login, lookup = self.run_helper(username=username)
                self.assertEqual(result, 2)
                self.assertEqual(prompts.call_count, 1)
                self.assertEqual(prompts.call_args.args, ("Designated learner UPN (not recorded): ",))
                exercise.assert_not_called()
                login.assert_not_called()
                lookup.assert_not_called()
                self.assertNotIn(username, self.stdout.getvalue() + self.stderr.getvalue())
                self.assertEqual(before, (self.database.read_bytes(), self.state.read_bytes()))

    def test_different_enrolled_guid_is_denied_before_learner_page_and_session_is_revoked(self):
        import sqlite3

        result, _prompts, login, lookup = self.run_helper(subject="7516b12d-8bcf-4a36-84a7-6fc8fb542d54")
        self.assertEqual(result, 1)
        self.assertIn("designated-identity: FAIL", self.stdout.getvalue())
        self.assertNotIn("own-learner: PASS", self.stdout.getvalue())
        login.assert_called_once()
        lookup.assert_not_called()
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM auth_sessions").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM auth_sessions WHERE revoked_at IS NULL").fetchone()[0], 0)

    def test_unenrolled_directory_identity_is_denied_with_no_provisioning(self):
        with patch.object(helper.real_auth, "get_account_for_identity", return_value=None):
            result, _prompts, login, lookup = self.run_helper()
        self.assertEqual(result, 1)
        self.assertIn("enrolled-login: FAIL (HTTP 401)", self.stdout.getvalue())
        login.assert_called_once()
        lookup.assert_not_called()

    def test_lookup_denial_stops_at_503_without_a_second_attempt(self):
        result, _prompts, login, lookup = self.run_helper(lookup=ADLoginError("private outage detail"))
        self.assertEqual(result, 1)
        self.assertIn("lookup-after-recreation: FAIL (HTTP 503)", self.stdout.getvalue())
        self.assertNotIn("private outage detail", self.stdout.getvalue())
        login.assert_called_once()
        lookup.assert_called_once()

    def test_attempt_guard_never_delegates_a_second_login_or_lookup(self):
        for name in ("authenticate_ad", "revalidate_ad"):
            with self.subTest(name=name), patch.object(helper.real_auth, name) as actual:
                with helper.one_attempt_each():
                    guarded = getattr(helper.real_auth, name)
                    guarded("synthetic")
                    with self.assertRaises(helper.AttemptBudgetExceeded):
                        guarded("synthetic")
                actual.assert_called_once_with("synthetic")

    def test_deadline_restores_signal_and_interrupts_exception_handlers(self):
        previous = signal.getsignal(signal.SIGALRM)
        with patch.object(helper.signal, "setitimer") as timer:
            with self.assertRaises(helper.DeadlineExpired):
                with helper.bounded_execution():
                    handler = signal.getsignal(signal.SIGALRM)
                    try:
                        handler(signal.SIGALRM, None)
                    except Exception:
                        self.fail("Deadline can be swallowed by ordinary adapter error handling")
        self.assertEqual(signal.getsignal(signal.SIGALRM), previous)
        self.assertEqual(timer.call_args_list[0].args, (signal.ITIMER_REAL, 30, 1))
        self.assertEqual(timer.call_args_list[-1].args, (signal.ITIMER_REAL, 0))


if __name__ == "__main__":
    unittest.main()
