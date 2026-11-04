"""Isolated AD boundary checks; no college directory or real credentials."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import socket
import ssl
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID

from flask import Flask

try:
    import ldap3
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
except ImportError as error:
    raise ImportError("AD checks require requirements-real.txt in the isolated validation environment.") from error

from launchpad.ad import (
    ADLoginError, _tls, authenticate_ad, configure_ad, normalized_attempt_key,
    revalidate_ad,
)


class ADTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="launchpad-ad-isolated-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.path = Path(cls.directory.name)
        now = datetime.now(timezone.utc)
        cls.ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Isolated AD test CA")])
        cls.ca = (
            x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(cls.ca_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(cls.ca_key, hashes.SHA256())
        )
        cls.ca_path = cls.path / "ca.pem"
        cls.ca_path.write_bytes(cls.ca.public_bytes(serialization.Encoding.PEM))
        cls.server_files = {}
        for label, hostname, expired, trusted in (
            ("valid", "ad.example.test", False, True),
            ("wrong-host", "other.example.test", False, True),
            ("expired", "ad.example.test", True, True),
            ("untrusted", "ad.example.test", False, False),
        ):
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
            cert = (
                x509.CertificateBuilder().subject_name(subject)
                .issuer_name(cls.ca.subject if trusted else subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(days=2))
                .not_valid_after(now - timedelta(days=1) if expired else now + timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .sign(cls.ca_key if trusted else key, hashes.SHA256())
            )
            cert_file, key_file = cls.path / (label + ".pem"), cls.path / (label + ".key")
            cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            cls.server_files[label] = cert_file, key_file

    def setUp(self):
        self.settings = {
            "LAUNCHPAD_AD_HOST": "ad.example.test",
            "LAUNCHPAD_AD_PORT": "636",
            "LAUNCHPAD_AD_CA_FILE": str(self.ca_path),
            "LAUNCHPAD_AD_DOMAIN": "example.test",
            "LAUNCHPAD_AD_BASE_DN": "DC=example,DC=test",
            "LAUNCHPAD_AD_GROUP_DN": "CN=Launchpad,OU=Groups,DC=example,DC=test",
            "LAUNCHPAD_AD_GROUP_POLICY": "direct",
            "LAUNCHPAD_AD_IDENTITY_NAMESPACE": "095761df-ae28-43d6-a166-d6008c30faf5",
        }
        self.guid = "11223344-5566-7788-9900-aabbccddeeff"
        self.response = [{"type": "searchResEntry", "raw_attributes": {"objectGUID": [UUID(self.guid).bytes_le]}}]
        self.result = {"result": 0}
        self.search_ok = True
        self.bind_ok = True
        self.calls = []
        self.connections = []
        self.config = self.configure()

    def configure(self, **changes):
        app = Flask(__name__)
        app.config.update({**self.settings, **changes})
        return configure_ad(app)

    def fake_connection(self, server, **kwargs):
        self.calls.append(("connection", server, kwargs))
        owner = self

        class FakeConnection:
            closed = True
            bound = False
            password = kwargs["password"]

            def open(self, **options):
                owner.calls.append(("open", options))
                self.closed = False

            def bind(self, **options):
                owner.calls.append(("bind", options))
                self.bound = owner.bind_ok
                return owner.bind_ok

            def search(self, **options):
                owner.calls.append(("search", options))
                self.response = owner.response
                self.result = owner.result
                return owner.search_ok

            def unbind(self):
                owner.calls.append(("unbind",))
                self.closed = True

        connection = FakeConnection()
        self.connections.append(connection)
        return connection

    def login(self, username="learner", password="isolated-test-password", config=None):
        with patch.object(ldap3, "Connection", side_effect=self.fake_connection):
            return authenticate_ad(username, password, config or self.config)

    def query(self):
        return next(call[1] for call in reversed(self.calls) if call[0] == "search")

    def test_configuration_has_no_directory_contact(self):
        with patch.object(ldap3, "Server", side_effect=AssertionError("No startup network object")):
            configured = self.configure()
        self.assertTrue(configured.context.check_hostname)
        self.assertEqual(configured.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreaterEqual(configured.context.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_explicit_directory_and_namespace_settings_required(self):
        for key in self.settings:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.configure(**{key: ""})
        for namespace in ("https://identity.example", "00000000-0000-0000-0000-000000000000", self.settings["LAUNCHPAD_AD_IDENTITY_NAMESPACE"].upper()):
            with self.subTest(namespace=namespace), self.assertRaises(ValueError):
                self.configure(LAUNCHPAD_AD_IDENTITY_NAMESPACE=namespace)

    def test_rejects_server_uri_port_ip_wildcard_and_unsafe_transport(self):
        for host in ("ldap://ad.example.test:389", "ldaps://ad.example.test", "ad.example.test:636", "*.example.test", "127.0.0.1", "[::1]", " ad.example.test", "ad.example.test/", "ad.example.test.", "ad"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                self.configure(LAUNCHPAD_AD_HOST=host)
        for port in (389, "389", "0636", True):
            with self.subTest(port=port), self.assertRaises(ValueError):
                self.configure(LAUNCHPAD_AD_PORT=port)

    def test_requires_readable_valid_ca_pem(self):
        bad_ca = self.path / "not-a-certificate.txt"
        bad_ca.write_text("synthetic noncertificate")
        for path in ("relative.pem", str(self.path / "missing.pem"), str(self.path), str(bad_ca)):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "AD configuration is invalid") as raised:
                self.configure(LAUNCHPAD_AD_CA_FILE=path)
            self.assertNotIn(path, str(raised.exception))
        with patch("launchpad.ad.os.access", return_value=False), self.assertRaises(ValueError):
            self.configure()

    def test_dn_and_group_policy_validation(self):
        for key, value in (("LAUNCHPAD_AD_BASE_DN", "not a dn"), ("LAUNCHPAD_AD_GROUP_DN", "CN="), ("LAUNCHPAD_AD_GROUP_DN", "CN=bad\nname,DC=test"), ("LAUNCHPAD_AD_GROUP_POLICY", "all")):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.configure(**{key: value})

    def test_success_returns_only_namespace_and_immutable_guid(self):
        identity = self.login()
        self.assertEqual(identity, {"issuer": "urn:launchpad:ad:" + self.config.namespace, "subject": self.guid})
        self.assertNotIn("learner", str(identity))
        self.assertTrue(self.connections[-1].closed)
        self.assertIsNone(self.connections[-1].password)

    def test_referrals_disabled_and_operations_bounded(self):
        self.login()
        _name, server, options = self.calls[0]
        self.assertTrue(server.ssl)
        self.assertEqual(server.port, 636)
        self.assertEqual(server.connect_timeout, 3)
        self.assertEqual(server.allowed_referral_hosts, [])
        self.assertFalse(options["auto_referrals"])
        self.assertFalse(options["auto_bind"])
        self.assertTrue(options["read_only"])
        self.assertTrue(options["raise_exceptions"])
        self.assertEqual(options["receive_timeout"], 5)
        self.assertEqual(self.query()["time_limit"], 3)
        self.assertEqual(self.query()["size_limit"], 2)
        self.assertEqual(self.query()["dereference_aliases"], ldap3.DEREF_NEVER)

    def test_refuses_library_transport_downgrade_before_connection(self):
        unsafe = SimpleNamespace(host=self.config.host, port=389, ssl=False, allowed_referral_hosts=[])
        with patch.object(ldap3, "Server", return_value=unsafe), patch.object(ldap3, "Connection") as connection, self.assertRaises(ADLoginError):
            authenticate_ad("learner", "isolated-password", self.config)
        connection.assert_not_called()

    def test_direct_group_filter_excludes_disabled_users(self):
        self.login()
        query = self.query()["search_filter"]
        self.assertIn("(userPrincipalName=learner@example.test)", query)
        self.assertIn("(memberOf=" + self.config.group_dn + ")", query)
        self.assertIn("(!(userAccountControl:1.2.840.113556.1.4.803:=2))", query)
        self.assertNotIn("1.2.840.113556.1.4.1941", query)

    def test_nested_policy_and_group_filter_escaping_are_explicit(self):
        configured = self.configure(LAUNCHPAD_AD_GROUP_POLICY="nested", LAUNCHPAD_AD_GROUP_DN="CN=Launchpad (test)*,DC=example,DC=test")
        self.login(config=configured)
        self.assertIn(r"(memberOf:1.2.840.113556.1.4.1941:=CN=Launchpad \28test\29\2a,DC=example,DC=test)", self.query()["search_filter"])

    def test_short_and_domain_upn_have_same_throttle_identity(self):
        self.assertEqual(normalized_attempt_key("Learner", self.config), normalized_attempt_key("learner@EXAMPLE.TEST", self.config))
        self.login(username="Learner@EXAMPLE.TEST")
        self.assertIn("(userPrincipalName=learner@example.test)", self.query()["search_filter"])

    def test_w_number_and_upn_normalize_bind_search_and_throttle_together(self):
        # Deliberately different synthetic domains detect hardcoded suffixes.
        for domain in ("EXAMPLE.TEST", "learners.example.test"):
            config = self.configure(LAUNCHPAD_AD_DOMAIN=domain)
            expected = "w00000001@" + domain.lower()
            for username in ("W00000001", "w00000001", " W00000001 ",
                             "\tW00000001\r\n", "W00000001@" + domain,
                             "  w00000001@" + domain.upper() + "\u00a0"):
                with self.subTest(domain=domain, username=username):
                    self.calls.clear()
                    identity = self.login(username=username, config=config)
                    self.assertEqual(self.calls[0][2]["user"], expected)
                    self.assertIn("(userPrincipalName=" + expected + ")", self.query()["search_filter"])
                    self.assertEqual(normalized_attempt_key(username, config), expected)
                    self.assertEqual(identity, {"issuer": config.issuer, "subject": self.guid})
                    self.assertIn("(memberOf=" + config.group_dn + ")", self.query()["search_filter"])

    def test_username_normalization_does_not_change_password(self):
        for password in ("  Synthetic Password  ", "\tSynthetic Password\n", " \t "):
            with self.subTest(password_length=len(password)):
                self.calls.clear()
                self.login(username=" W00000001 ", password=password)
                self.assertEqual(self.calls[0][2]["user"], "w00000001@example.test")
                self.assertEqual(self.calls[0][2]["password"], password)

    def test_malformed_w_number_or_upn_never_reaches_directory(self):
        malformed = (None, 123, " \t\n", "W0000 0001", "W0000\t0001", "W00000001 @example.test",
                     "W00000001@ example.test", "W00000001@", "@example.test",
                     "W00000001@example.test@example.test", "W00000001@other.test", "DOMAIN\\W00000001",
                     "W00000001)(memberOf=*)", "W00000001\x00", "Ｗ00000001", " W00000001 " + " " * 320)
        with patch.object(ldap3, "Server") as server, patch.object(ldap3, "Connection") as connection:
            for username in malformed:
                with self.subTest(username=username):
                    with self.assertRaises(ADLoginError):
                        authenticate_ad(username, "isolated-password", self.config)
                    self.assertTrue(normalized_attempt_key(username, self.config).startswith("invalid:"))
            server.assert_not_called()
            connection.assert_not_called()

    def test_invalid_usernames_and_passwords_never_construct_connection(self):
        with patch.object(ldap3, "Connection") as connection:
            for username in ("", "learner@foreign.test", "learner@example.test@foreign.test", "DOMAIN\\learner", "learner)(memberOf=*)", "learner\x00", "learn\ner", "léarner", "learn er", "a" * 65):
                with self.subTest(username=username), self.assertRaises(ADLoginError):
                    authenticate_ad(username, "isolated-password", self.config)
            for password in ("", "invalid\x00password", None, "x" * 4097):
                with self.subTest(password_type=type(password).__name__), self.assertRaises(ADLoginError):
                    authenticate_ad("learner", password, self.config)
            connection.assert_not_called()

    def test_failed_bind_never_searches(self):
        self.bind_ok = False
        with self.assertRaises(ADLoginError):
            self.login()
        self.assertNotIn("search", [call[0] for call in self.calls])
        self.assertTrue(self.connections[-1].closed)

    def test_denial_missing_ambiguous_and_referral_responses_fail_closed(self):
        normal = self.response[0]
        for responses, result, found in (([], {"result": 0}, False), ([normal, normal], {"result": 0}, True), ([normal], {"result": 50}, False), ([normal, {"type": "searchResRef", "uri": ["ldap://unapproved.example.test"]}], {"result": 0}, True), ([normal], {"result": 10}, False)):
            with self.subTest(result=result, count=len(responses), found=found):
                self.response, self.result, self.search_ok = responses, result, found
                with self.assertRaises(ADLoginError):
                    self.login()

    def test_missing_malformed_and_zero_guid_rejected(self):
        for raw in ({}, {"objectGUID": [b"short"]}, {"objectGUID": [b"\x00" * 16]}, {"objectGUID": [self.guid]}, {"objectGUID": [UUID(self.guid).bytes_le, UUID(self.guid).bytes_le]}):
            with self.subTest(raw=raw):
                self.response = [{"type": "searchResEntry", "raw_attributes": raw}]
                with self.assertRaises(ADLoginError):
                    self.login()

    def test_outage_certificate_and_directory_exceptions_are_safe(self):
        for failure in (TimeoutError("private directory address"), ssl.SSLCertVerificationError("private certificate path"), RuntimeError("private-bind-password")):
            with self.subTest(kind=type(failure).__name__), patch.object(ldap3, "Connection", side_effect=failure):
                with self.assertRaises(ADLoginError) as raised:
                    authenticate_ad("learner", "private-bind-password", self.config)
                self.assertEqual(str(raised.exception), "Sign-in could not be completed. Check your credentials or contact IT.")
                self.assertIsNone(raised.exception.__cause__)

    def test_mid_operation_failure_closes_connection_and_drops_password(self):
        for stage in ("open", "bind", "search"):
            def connection_factory(server, **options):
                connection = self.fake_connection(server, **options)

                def fail(**_kwargs):
                    raise TimeoutError("synthetic-private-directory-detail")

                setattr(connection, stage, fail)
                return connection

            with self.subTest(stage=stage), patch.object(ldap3, "Connection", side_effect=connection_factory):
                with self.assertRaises(ADLoginError) as raised:
                    authenticate_ad("learner", "synthetic-private-password", self.config)
                self.assertNotIn("private", str(raised.exception))
                self.assertTrue(self.connections[-1].closed)
                self.assertIsNone(self.connections[-1].password)

    def test_weakened_tls_context_cannot_reach_a_bind(self):
        self.config.context.check_hostname = False
        with patch.object(ldap3, "Connection") as connection, self.assertRaises(ADLoginError):
            authenticate_ad("learner", "isolated-password", self.config)
        connection.assert_not_called()

    def test_revalidation_uses_guid_and_same_group_disabled_boundary(self):
        with patch.object(ldap3, "Connection", side_effect=self.fake_connection):
            identity = revalidate_ad(self.guid, self.config, bind_username="lookup", bind_password="isolated-lookup-password")
        self.assertEqual(identity["subject"], self.guid)
        encoded = "".join("\\" + format(byte, "02x") for byte in UUID(self.guid).bytes_le)
        self.assertIn("(objectGUID=" + encoded + ")", self.query()["search_filter"])
        self.assertNotIn("(userPrincipalName=", self.query()["search_filter"])
        self.assertIn("(memberOf=", self.query()["search_filter"])

    def test_revalidation_cannot_accept_another_or_malformed_subject(self):
        with patch.object(ldap3, "Connection", side_effect=self.fake_connection):
            for subject in ("00000000-0000-0000-0000-000000000001", "not-a-guid", self.guid.upper()):
                with self.subTest(subject=subject), self.assertRaises(ADLoginError):
                    revalidate_ad(subject, self.config, bind_username="lookup", bind_password="isolated-lookup-password")

    def tls_handshake(self, label):
        cert_file, key_file = self.server_files[label]
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(cert_file, key_file)
        server_socket, client_socket = socket.socketpair()
        server_socket.settimeout(3)
        client_socket.settimeout(3)
        server_errors = []

        def server():
            try:
                with server_context.wrap_socket(server_socket, server_side=True):
                    pass
            except (OSError, ssl.SSLError) as error:
                server_errors.append(type(error).__name__)
            finally:
                server_socket.close()

        thread = threading.Thread(target=server, daemon=True)
        thread.start()
        connection = SimpleNamespace(socket=client_socket)
        error = None
        try:
            _tls(self.config).wrap_socket(connection, do_handshake=True)
        except Exception as failure:
            error = failure
        finally:
            connection.socket.close()
            client_socket.close()
            thread.join(timeout=4)
        self.assertFalse(thread.is_alive())
        return error

    def test_real_tls_accepts_matching_trusted_server(self):
        self.assertIsNone(self.tls_handshake("valid"))

    def test_real_tls_rejects_wrong_hostname_untrusted_and_expired_certificates(self):
        for label in ("wrong-host", "untrusted", "expired"):
            with self.subTest(label=label):
                self.assertIsInstance(self.tls_handshake(label), ssl.SSLCertVerificationError)

    def test_real_tls_handshake_honors_socket_timeout(self):
        peer, client = socket.socketpair()
        client.settimeout(0.1)
        connection = SimpleNamespace(socket=client)
        try:
            # The peer never answers the ClientHello. No LDAP message or bind
            # can run before the real SSL handshake completes successfully.
            with self.assertRaises(TimeoutError):
                _tls(self.config).wrap_socket(connection, do_handshake=True)
        finally:
            connection.socket.close()
            client.close()
            peer.close()


if __name__ == "__main__":
    unittest.main()
