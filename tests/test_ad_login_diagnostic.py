"""Standalone diagnostic boundaries; invented identities, no real directory."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import UUID
import warnings

import ldap3
from ldap3.strategy.base import BaseStrategy
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from scripts import diagnose_ad_login as diagnostic


class ADLoginDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic diagnostic CA")])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
        cls.ca = cert.public_bytes(serialization.Encoding.PEM)

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="launchpad-diagnostic-isolated-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.folder = self.root / "work" / "ad-login-test"
        self.folder.mkdir(parents=True, mode=0o700)
        self.path = self.folder / "pilot-a-identity.local.json"
        self.guid = "11223344-5566-7788-9900-aabbccddeeff"
        self.upn = "synthetic.learner@example.test"
        self.password = "synthetic-never-display-password"
        self.identity = {
            "purpose": "Synthetic isolated preparation", "label": "Pilot A", "role": "learner",
            "upn": self.upn, "object_guid": self.guid, "upn_suffix": "example.test",
            "identity_source": "Synthetic fixture", "reported_date": "2026-01-01",
            "reported_date_timezone": "America/Denver", "enrollment_status": "prepared_not_enrolled",
            "use_as_lookup_account": False, "progress_policy": "new_isolated_dataset_only",
            "test_namespace": None, "planned_database_path": None, "directory_search_base": None,
            "lookup_account_upn": None,
        }
        self.write_identity()
        self.bundle = self.root / "work" / "ad-ca-review" / "launchpad-ad-ca.pem"
        self.bundle.parent.mkdir()
        self.bundle.write_bytes(self.ca)
        for patcher in (
            patch.object(diagnostic, "PROJECT_ROOT", self.root),
            patch.object(diagnostic, "BUNDLE_SHA256", hashlib.sha256(self.ca).hexdigest().upper()),
            patch("sqlite3.connect", side_effect=AssertionError("No database access permitted")),
            patch("launchpad.create_app", side_effect=AssertionError("No app creation permitted")),
            patch("socket.socket", side_effect=AssertionError("No actual network permitted")),
            patch.object(diagnostic.resource, "setrlimit"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.real_connection = ldap3.Connection
        self.connection_patch = patch.object(ldap3, "Connection", side_effect=self.fake_connection)
        self.factory = self.connection_patch.start()
        self.addCleanup(self.connection_patch.stop)
        self.calls = []
        self.connections = []
        self.bind_ok = True
        self.search_ok = True
        self.search_result = {"result": 0}
        self.response = [{"type": "searchResEntry", "raw_attributes": {"objectGUID": [UUID(self.guid).bytes_le]}}]
        self.unbind_error = False

    def write_identity(self):
        self.path.write_text(json.dumps(self.identity))
        self.path.chmod(0o600)

    def fake_connection(self, server, **kwargs):
        self.calls.append(("connection", server, kwargs))
        owner = self

        class FakeConnection:
            closed = True
            bound = False
            password = kwargs["password"]
            socket = Mock()

            def open(self, **options):
                owner.calls.append(("open", options))
                self.closed = False

            def bind(self, **options):
                owner.calls.append(("bind", options))
                self.bound = owner.bind_ok
                return self.bound

            def search(self, **options):
                owner.calls.append(("search", options))
                self.result, self.response = owner.search_result, owner.response
                return owner.search_ok

            def unbind(self):
                owner.calls.append(("unbind",))
                if owner.unbind_error:
                    raise RuntimeError(owner.password)
                self.closed = True

        instance = FakeConnection()
        self.connections.append(instance)
        return instance

    def run_main(self, *, execute=False, args=None):
        if args is None:
            args = ["--base-dn", "DC=example,DC=test", "--group-policy", "direct"]
        if execute:
            args = [*args, "--execute"]
        output = io.StringIO()
        with redirect_stdout(output), patch.object(diagnostic, "require_tty"), \
                patch.object(diagnostic, "getpass", return_value=self.password) as prompt:
            code = diagnostic.main(args)
        text = output.getvalue()
        for secret in (self.password, self.upn, self.guid, "DC=example,DC=test"):
            self.assertNotIn(secret, text)
        return code, text, prompt

    def test_preflight_reads_only_and_never_prompts_or_contacts_directory(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        code, text, prompt = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("PREFLIGHT PASS", text)
        prompt.assert_not_called()
        self.factory.assert_not_called()
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_one_bind_same_connection_search_unbind_and_force_close(self):
        code, text, prompt = self.run_main(execute=True)
        self.assertEqual(code, 0)
        self.assertIn("PASS:", text)
        prompt.assert_called_once()
        self.assertEqual([call[0] for call in self.calls], ["connection", "open", "bind", "search", "unbind"])
        connection = self.connections[0]
        connection.socket.close.assert_called_once()
        self.assertIsNone(connection.password)
        server, options = self.calls[0][1:]
        self.assertEqual(server.host, diagnostic.DIRECTORY_HOST.lower())
        self.assertEqual(server.port, 636)
        self.assertTrue(server.ssl)
        self.assertEqual(server.allowed_referral_hosts, [])
        self.assertEqual(server.connect_timeout, 3)
        self.assertFalse(options["auto_referrals"])
        self.assertFalse(options["auto_bind"])
        self.assertTrue(options["read_only"])
        self.assertEqual(options["receive_timeout"], 5)
        query = self.calls[3][1]
        self.assertIn("(userPrincipalName=" + self.upn + ")", query["search_filter"])
        self.assertIn("(memberOf=" + diagnostic.GROUP_DN + ")", query["search_filter"])
        self.assertIn("(!(userAccountControl:1.2.840.113556.1.4.803:=2))", query["search_filter"])
        self.assertEqual(query["attributes"], ["objectGUID"])
        self.assertEqual(query["time_limit"], 3)
        self.assertEqual(query["size_limit"], 2)
        self.assertEqual(query["dereference_aliases"], ldap3.DEREF_NEVER)

    def test_tls_context_uses_pinned_ca_hostname_and_minimum_version(self):
        configured, username, subject = diagnostic.preflight("DC=example,DC=test", "direct")
        self.assertEqual((username, subject), (self.upn, self.guid))
        self.assertEqual(configured.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(configured.context.check_hostname)
        self.assertGreaterEqual(configured.context.minimum_version, ssl.TLSVersion.TLSv1_2)
        from launchpad.ad import _tls
        wrapped = Mock()
        transport = Mock(socket=object())
        with patch.object(configured.context, "wrap_socket", return_value=wrapped) as wrap:
            _tls(configured).wrap_socket(transport)
        self.assertEqual(wrap.call_args.kwargs, {"server_hostname": configured.host, "do_handshake_on_connect": True})
        self.assertIs(transport.socket, wrapped)

    def test_nested_membership_only_when_explicitly_selected(self):
        code, _text, _prompt = self.run_main(execute=True, args=["--base-dn", "DC=example,DC=test", "--group-policy", "nested"])
        self.assertEqual(code, 0)
        self.assertIn("memberOf:1.2.840.113556.1.4.1941:", self.calls[3][1]["search_filter"])

    def test_guid_mismatch_denied_without_retry_or_identifiers(self):
        self.response[0]["raw_attributes"]["objectGUID"] = [UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee").bytes_le]
        code, _text, _prompt = self.run_main(execute=True)
        self.assertEqual(code, 1)
        self.factory.assert_called_once()
        self.connections[0].socket.close.assert_called_once()

    def test_bind_failure_stops_before_search_and_closes(self):
        self.bind_ok = False
        code, _text, _prompt = self.run_main(execute=True)
        self.assertEqual(code, 1)
        self.assertEqual([call[0] for call in self.calls], ["connection", "open", "bind", "unbind"])
        self.connections[0].socket.close.assert_called_once()

    def test_empty_group_result_fails_and_closes(self):
        self.response = []
        code, _text, _prompt = self.run_main(execute=True)
        self.assertEqual(code, 1)
        self.factory.assert_called_once()
        self.connections[0].socket.close.assert_called_once()

    def test_unbind_error_still_force_closes_without_exposing_error(self):
        self.unbind_error = True
        code, _text, _prompt = self.run_main(execute=True)
        self.assertEqual(code, 0)
        self.connections[0].socket.close.assert_called_once()
        self.assertIsNone(self.connections[0].password)

    def test_first_tls_failure_prevents_dns_candidate_retry_and_bind(self):
        address = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.5", 636), None)
        tracked = []
        transport = Mock()

        def failed_socket(strategy, *_args, **_kwargs):
            tracked.append(strategy.connection)
            strategy.connection.socket = transport
            raise ssl.SSLCertVerificationError(self.password)

        with patch.object(ldap3, "Connection", self.real_connection), \
                patch.object(ldap3.Server, "candidate_addresses", return_value=[address, address]), \
                patch.object(BaseStrategy, "_open_socket", side_effect=failed_socket, autospec=True) as attempt, \
                patch.object(self.real_connection, "bind", side_effect=AssertionError("TLS failure must precede bind")) as bind:
            code, _text, _prompt = self.run_main(execute=True)
        self.assertEqual(code, 1)
        attempt.assert_called_once()
        bind.assert_not_called()
        transport.close.assert_called_once()
        self.assertIsNone(tracked[0].password)

    def test_timeout_is_bounded_and_still_closes(self):
        original = self.fake_connection

        def timed_out(*args, **kwargs):
            conn = original(*args, **kwargs)
            conn.search = Mock(side_effect=diagnostic.DeadlineExpired())
            return conn

        self.factory.side_effect = timed_out
        with patch.object(diagnostic.signal, "setitimer") as timer:
            code, text, _prompt = self.run_main(execute=True)
        self.assertEqual(code, 1)
        self.assertIn("time limit", text)
        self.assertEqual(timer.call_args_list[0].args, (diagnostic.signal.ITIMER_REAL, 30, 1))
        self.assertEqual(timer.call_args_list[-1].args, (diagnostic.signal.ITIMER_REAL, 0))
        self.connections[0].socket.close.assert_called_once()

    def test_missing_or_extra_arguments_fail_before_private_read_and_hide_values(self):
        for args in ([], ["--base-dn", "DC=example,DC=test"],
                     ["--base-dn", "DC=example,DC=test", "--group-policy", self.password],
                     ["--base-dn", "DC=example,DC=test", "--group-policy", "direct", "--password", self.password]):
            with self.subTest(args=len(args)), patch.object(diagnostic, "preflight") as preflight:
                code, _text, prompt = self.run_main(args=args)
                self.assertEqual(code, 1)
                preflight.assert_not_called()
                prompt.assert_not_called()

    def test_tty_and_getpass_warning_refused_before_network(self):
        with patch.object(diagnostic.sys, "stdin", Mock(isatty=Mock(return_value=False))), self.assertRaises(diagnostic.Refused):
            diagnostic.private_password()
        with patch.object(diagnostic, "require_tty"), patch.object(diagnostic, "getpass", side_effect=lambda *_a, **_k: warnings.warn("synthetic warning", diagnostic.GetPassWarning)), self.assertRaises(diagnostic.GetPassWarning):
            diagnostic.private_password()
        self.factory.assert_not_called()

    def test_invalid_password_rejected_without_directory_attempt(self):
        for password in ("", "x" * 4097, "x\x00y"):
            with self.subTest(length=len(password)), patch.object(diagnostic, "require_tty"), patch.object(diagnostic, "getpass", return_value=password), self.assertRaises(diagnostic.Refused):
                diagnostic.private_password()
        self.factory.assert_not_called()

    def test_private_file_permissions_links_and_size_fail_closed(self):
        for mode in (0o644, 0o640, 0o400):
            self.path.chmod(mode)
            code, _text, prompt = self.run_main(execute=True)
            self.assertEqual(code, 1)
            prompt.assert_not_called()
        self.path.chmod(0o600)
        os.link(self.path, self.folder / "hardlink")
        self.assertEqual(self.run_main()[0], 1)
        (self.folder / "hardlink").unlink()
        saved = self.folder / "saved"
        self.path.rename(saved)
        self.path.symlink_to(saved)
        self.assertEqual(self.run_main()[0], 1)
        self.path.unlink()
        saved.rename(self.path)
        self.path.write_text("x" * (16 * 1024 + 1))
        self.assertEqual(self.run_main()[0], 1)
        self.factory.assert_not_called()

    def test_private_parent_and_owner_checks(self):
        self.folder.chmod(0o755)
        self.assertEqual(self.run_main()[0], 1)
        self.folder.chmod(0o700)
        with patch.object(diagnostic.os, "getuid", return_value=os.getuid() + 1):
            self.assertEqual(self.run_main()[0], 1)

    def test_identity_constraints_and_password_key_rejected(self):
        original = dict(self.identity)
        for key, value in (("role", "mentor"), ("use_as_lookup_account", True),
                           ("enrollment_status", "enrolled"), ("progress_policy", "existing"),
                           ("lookup_account_upn", self.upn), ("planned_database_path", "/existing.sqlite"),
                           ("upn", "bad*)(upn=*)@example.test"), ("upn_suffix", "other.test"),
                           ("object_guid", "00000000-0000-0000-0000-000000000000"),
                           ("password", self.password)):
            self.identity = {**original, key: value}
            self.write_identity()
            with self.subTest(key=key):
                code, _text, prompt = self.run_main(execute=True)
                self.assertEqual(code, 1)
                prompt.assert_not_called()
        self.factory.assert_not_called()

    def test_duplicate_keys_and_changed_bundle_fail_before_password(self):
        self.path.write_text(json.dumps(self.identity)[:-1] + ', "role": "learner"}')
        self.assertEqual(self.run_main()[0], 1)
        self.write_identity()
        self.bundle.write_bytes(self.ca + b"\n")
        code, _text, prompt = self.run_main(execute=True)
        self.assertEqual(code, 1)
        prompt.assert_not_called()
        self.factory.assert_not_called()

    def test_wrong_issuer_denied_and_no_password_environment_read(self):
        with patch.object(diagnostic, "authenticate_ad", return_value={"issuer": "wrong", "subject": self.guid}) as authenticate, \
                patch.dict(os.environ, {"LAUNCHPAD_AD_LOOKUP_PASSWORD": "ignored", "LAUNCHPAD_AD_PASSWORD": "ignored"}):
            self.assertEqual(self.run_main(execute=True)[0], 1)
        authenticate.assert_called_once()
        self.assertEqual(authenticate.call_args.args[1], self.password)


if __name__ == "__main__":
    unittest.main()
