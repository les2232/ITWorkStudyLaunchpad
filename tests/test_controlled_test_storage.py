"""Synthetic, offline coverage of the isolated controlled-test boundary."""
from __future__ import annotations

from contextlib import closing, redirect_stdout, redirect_stderr
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from launchpad.accounts import enroll_account
from launchpad.controlled_test import (
    ControlledTestError, enroll_controlled_account, initialize_controlled_run,
    load_run_config, run_directory, runtime_config, validate_controlled_storage,
)
from launchpad.real_data import initialize_real_database
from scripts import manage_controlled_test, start_controlled_test

REPO_ROOT = Path(__file__).resolve().parents[1]
SUBJECT_A = "00000000-0000-4000-8000-000000000001"
SUBJECT_B = "00000000-0000-4000-8000-000000000002"


class ControlledStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.root = Path(self.temporary.name)
        (self.root / "deploy").mkdir(mode=0o700)
        shutil.copyfile(REPO_ROOT / "deploy" / "controlled-test.example.json", self.root / "deploy" / "controlled-test.example.json")
        self.root_patch = patch("launchpad.controlled_test.PROJECT_ROOT", self.root)
        self.root_patch.start()
        self.network_patch = patch("ldap3.Connection", side_effect=AssertionError("Offline storage checks must never contact AD"))
        self.connection = self.network_patch.start()
        self.directory = initialize_controlled_run("synthetic-run")
        self.config = load_run_config("synthetic-run")
        self.issuer = "urn:launchpad:ad:" + self.config["LAUNCHPAD_AD_IDENTITY_NAMESPACE"]

    def tearDown(self):
        self.network_patch.stop()
        self.root_patch.stop()
        self.temporary.cleanup()

    def _write_json(self, filename, value):
        (self.directory / filename).write_text(json.dumps(value), encoding="utf-8")

    def _digest_files(self):
        return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in self.directory.iterdir() if path.is_file()}

    def test_new_run_is_empty_private_and_has_stable_signing_key(self):
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.directory.parent.stat().st_mode & 0o777, 0o700)
        for path in self.directory.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        config_a = runtime_config("synthetic-run")
        config_b = runtime_config("synthetic-run")
        self.assertEqual(config_a["SECRET_KEY"], config_b["SECRET_KEY"])
        self.assertGreaterEqual(len(config_a["SECRET_KEY"]), 32)
        self.assertEqual(config_a["LAUNCHPAD_AD_LOOKUP_USERNAME"], "")
        self.assertEqual(config_a["LAUNCHPAD_AD_LOOKUP_PASSWORD"], "")
        with closing(sqlite3.connect(self.directory / "learners.sqlite")) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM students").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM accounts").fetchone()[0], 0)
        self.connection.assert_not_called()

    def test_initialize_refuses_existing_run_without_touching_any_file(self):
        before = self._digest_files()
        with self.assertRaises(FileExistsError):
            initialize_controlled_run("synthetic-run")
        self.assertEqual(before, self._digest_files())

    def test_run_identifiers_cannot_traverse_paths(self):
        for value in ("../outside", "/tmp/outside", "with/slash", "", ".", "..", "MixedCase", "space label"):
            with self.subTest(value=value), self.assertRaises(ControlledTestError):
                run_directory(value)

    def test_marker_must_match_dataset_namespace_and_fixed_session_limit(self):
        original = json.loads((self.directory / "controlled-test.json").read_text())
        for key, value in (("dataset_id", "a" * 32), ("identity_namespace", SUBJECT_A), ("session_seconds", 901), ("session_seconds", True), ("invented_training_only", False), ("version", True)):
            self._write_json("controlled-test.json", dict(original, **{key: value}))
            with self.subTest(key=key, value=value), self.assertRaises(ControlledTestError):
                load_run_config("synthetic-run")
        self._write_json("controlled-test.json", original)
        self.assertEqual(validate_controlled_storage(self.config, self.issuer)["session_seconds"], 900)

    def test_copied_unrelated_dataset_is_rejected(self):
        unrelated = self.root / "unrelated.sqlite"
        initialize_real_database(unrelated)
        before = hashlib.sha256(unrelated.read_bytes()).hexdigest()
        shutil.copyfile(unrelated, self.directory / "learners.sqlite")
        with self.assertRaises(ControlledTestError):
            load_run_config("synthetic-run")
        self.assertEqual(hashlib.sha256(unrelated.read_bytes()).hexdigest(), before)

    def test_foreign_oidc_or_admin_accounts_are_rejected(self):
        for issuer, role in (("https://identity.example.invalid", "learner"), (self.issuer, "admin")):
            with self.subTest(issuer=issuer, role=role):
                run = initialize_controlled_run("foreign-" + role)
                enroll_account(issuer, SUBJECT_A, "Invented A", role, db_path=run / "learners.sqlite")
                with self.assertRaises(ControlledTestError):
                    load_run_config("foreign-" + role)

    def test_explicit_enrollment_creates_independent_learners_without_name_matching(self):
        a = enroll_controlled_account("synthetic-run", SUBJECT_A, "Invented learner")
        b = enroll_controlled_account("synthetic-run", SUBJECT_B, "Invented learner")
        self.assertNotEqual(a["learner_id"], b["learner_id"])
        self.assertEqual(a["issuer"], self.issuer)
        load_run_config("synthetic-run")
        before = self._digest_files()
        with self.assertRaises(ValueError):
            enroll_controlled_account("synthetic-run", SUBJECT_A, "Another name")
        self.assertEqual(before, self._digest_files())
        with self.assertRaises(ControlledTestError):
            enroll_controlled_account("synthetic-run", SUBJECT_B, "Admin", "admin")

    def test_unbound_learner_records_are_rejected(self):
        with sqlite3.connect(self.directory / "learners.sqlite") as db:
            db.execute("INSERT INTO students(display_name,created_at,updated_at) VALUES('Invented imported row','synthetic','synthetic')")
        with self.assertRaises(ControlledTestError):
            load_run_config("synthetic-run")

    def test_symlink_hardlink_sidecar_and_open_permissions_refused(self):
        target = self.directory / "learners.sqlite"
        alternate = self.root / "alternate.sqlite"
        target.rename(alternate)
        target.symlink_to(alternate)
        with self.assertRaises(ControlledTestError):
            load_run_config("synthetic-run")
        target.unlink()
        alternate.rename(target)
        link = self.root / "hardlink.sqlite"
        os.link(target, link)
        with self.assertRaises(ControlledTestError):
            load_run_config("synthetic-run")
        link.unlink()
        target.chmod(0o644)
        with self.assertRaises(ControlledTestError):
            load_run_config("synthetic-run")
        target.chmod(0o600)
        sidecar = self.directory / "learners.sqlite-journal"
        sidecar.symlink_to(target)
        with self.assertRaises(ControlledTestError):
            load_run_config("synthetic-run")
        sidecar.unlink()
        self.directory.chmod(0o755)
        with self.assertRaises(ControlledTestError):
            load_run_config("synthetic-run")

    def test_fixed_paths_and_exact_config_reject_passwords_or_mode_changes(self):
        for key, value in (("LAUNCHPAD_DB_PATH", str(self.root / "outside.sqlite")), ("LAUNCHPAD_REAL_MODE", False), ("LAUNCHPAD_AD_SESSION_POLICY", "revalidate"), ("LAUNCHPAD_AD_LOOKUP_PASSWORD", "invented-value")):
            with self.subTest(key=key):
                self._write_json("config.json", dict(self.config, **{key: value}))
                with self.assertRaises(ControlledTestError):
                    load_run_config("synthetic-run")
        self._write_json("config.json", self.config)
        content = (self.directory / "config.json").read_text()
        (self.directory / "config.json").write_text(content[:-1] + ',"LAUNCHPAD_REAL_MODE":true}')
        with self.assertRaises(ControlledTestError):
            load_run_config("synthetic-run")

    def test_offline_validation_does_not_write(self):
        before = self._digest_files()
        load_run_config("synthetic-run")
        runtime_config("synthetic-run")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(manage_controlled_test.main(["verify", "--run", "synthetic-run"]), 0)
        self.assertEqual(before, self._digest_files())
        self.connection.assert_not_called()

    def test_enrollment_refuses_redirected_terminal_before_prompt_or_write(self):
        before = self._digest_files()
        with patch("scripts.manage_controlled_test.getpass") as prompt, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(manage_controlled_test.main(["enroll", "--run", "synthetic-run"]), 2)
        prompt.assert_not_called()
        self.assertEqual(before, self._digest_files())

    def test_owned_signing_key_and_no_shared_key_permissions(self):
        path = self.directory / "signing-key.txt"
        path.chmod(0o644)
        with self.assertRaises(ControlledTestError):
            runtime_config("synthetic-run")
        path.chmod(0o600)
        path.write_text("short")
        with self.assertRaises(ControlledTestError):
            runtime_config("synthetic-run")

    def _tls_files(self):
        cert = self.root / "synthetic-cert.pem"
        key = self.root / "synthetic-key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=synthetic.example.invalid", "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "subjectAltName=DNS:synthetic.example.invalid"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        key.chmod(0o600)
        return cert, key

    def _ready_config(self, cert):
        config = dict(self.config, LAUNCHPAD_TRUSTED_HOSTS="synthetic.example.invalid", LAUNCHPAD_AD_HOST="dc.example.invalid", LAUNCHPAD_AD_DOMAIN="directory.example.invalid", LAUNCHPAD_AD_BASE_DN="DC=directory,DC=example,DC=invalid", LAUNCHPAD_AD_GROUP_POLICY="direct", LAUNCHPAD_AD_CA_FILE=str(cert))
        self._write_json("config.json", config)

    def test_startup_incomplete_configuration_refuses_without_directory_contact(self):
        cert, key = self._tls_files()
        before = self._digest_files()
        with patch.dict(os.environ, {"LAUNCHPAD_TRUSTED_HOSTS": "inherited.example.invalid"}), self.assertRaises(ValueError):
            start_controlled_test.prepare_runtime("synthetic-run", cert, key)
        self.assertEqual(before, self._digest_files())
        self.connection.assert_not_called()

    def test_startup_preflight_is_offline_and_requires_private_tls_key(self):
        cert, key = self._tls_files()
        self._ready_config(cert)
        before = self._digest_files()
        app, context = start_controlled_test.prepare_runtime("synthetic-run", cert, key)
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertTrue(app.config["SESSION_COOKIE_SECURE"])
        self.assertEqual(app.config["LAUNCHPAD_AD_SESSION_POLICY"], "controlled_test")
        self.assertEqual(before, self._digest_files())
        with patch("scripts.start_controlled_test.serve") as listener, redirect_stdout(io.StringIO()):
            self.assertEqual(start_controlled_test.main(["--run", "synthetic-run", "--certfile", str(cert), "--keyfile", str(key)]), 0)
        listener.assert_not_called()
        key.chmod(0o644)
        with self.assertRaises(ControlledTestError):
            start_controlled_test.prepare_runtime("synthetic-run", cert, key)
        self.connection.assert_not_called()

    def test_startup_rejects_certificate_file_containing_private_key(self):
        cert, key = self._tls_files()
        self._ready_config(cert)
        cert.write_bytes(cert.read_bytes() + key.read_bytes())
        with self.assertRaises(ValueError):
            start_controlled_test.prepare_runtime("synthetic-run", cert, key)

    def test_gunicorn_cannot_inherit_public_bind_or_proxy_trust(self):
        cert, key = self._tls_files()
        self._ready_config(cert)
        app, context = start_controlled_test.prepare_runtime("synthetic-run", cert, key)
        with patch.dict(os.environ, {"PORT": "9000", "GUNICORN_CMD_ARGS": "--bind 0.0.0.0:9001 --reload"}), patch("gunicorn.app.base.BaseApplication.run", autospec=True) as run:
            start_controlled_test.serve(app, context, str(cert), str(key))
        cfg = run.call_args.args[0].cfg
        self.assertEqual(cfg.bind, ["127.0.0.1:8443"])
        self.assertEqual(cfg.forwarded_allow_ips, [])
        self.assertEqual(cfg.secure_scheme_headers, {})
        self.assertFalse(cfg.reload)
        self.assertEqual(cfg.workers, 1)
        self.assertIs(cfg.ssl_context(cfg, lambda: None), context)
        self.assertEqual(cfg.access_log_format, "%(t)s %(m)s %(s)s %(L)s")
        from launchpad.controlled_logging import SafeControlledLogger
        self.assertIs(cfg.logger_class, SafeControlledLogger)
        self.assertFalse(cfg.capture_output)
        self.assertEqual(Path(cfg.accesslog).parent, self.directory / "logs")
        self.assertEqual(Path(cfg.errorlog).parent, self.directory / "logs")
        self.connection.assert_not_called()

    def _close_diagnostic_handlers(self):
        logger = logging.getLogger("launchpad.login_diagnostic")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    def test_diagnostics_are_private_and_preserve_existing_storage(self):
        before = self._digest_files()
        app = SimpleNamespace(config={"LAUNCHPAD_DATA_DIR": str(self.directory)})
        self.addCleanup(self._close_diagnostic_handlers)
        directory, logger = start_controlled_test.prepare_diagnostics(app)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertFalse(logger.propagate)
        self.assertEqual(len(logger.handlers), 1)
        logger.warning("timestamp=synthetic method=POST path=/auth/login status=400 reason=csrf_session_absent")
        self.assertIn("reason=csrf_session_absent", (directory / "login-diagnostics.log").read_text())
        for path in directory.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.stat().st_uid, os.getuid())
            self.assertEqual(path.stat().st_nlink, 1)
        self.assertEqual(before, self._digest_files())
        self.connection.assert_not_called()

    def test_diagnostics_refuse_unsafe_paths_without_changing_their_contents(self):
        app = SimpleNamespace(config={"LAUNCHPAD_DATA_DIR": str(self.directory)})
        directory = self.directory / "logs"
        directory.mkdir(mode=0o700)
        target = self.root / "unrelated-diagnostic.txt"
        target.write_text("synthetic preservation marker")
        target.chmod(0o600)
        unsafe = directory / "login-diagnostics.log"
        for kind in ("symlink", "hardlink", "open_mode"):
            with self.subTest(kind=kind):
                if kind == "symlink":
                    unsafe.symlink_to(target)
                elif kind == "hardlink":
                    os.link(target, unsafe)
                else:
                    unsafe.write_text("synthetic preservation marker")
                    unsafe.chmod(0o644)
                with self.assertRaises((OSError, ValueError)):
                    start_controlled_test.prepare_diagnostics(app)
                self.assertEqual(target.read_text(), "synthetic preservation marker")
                self.assertEqual(unsafe.read_text(), "synthetic preservation marker")
                unsafe.unlink()
        directory.chmod(0o755)
        with self.assertRaises(ControlledTestError):
            start_controlled_test.prepare_diagnostics(app)
        directory.chmod(0o700)
        backup = directory / "login-diagnostics.log.1"
        backup.symlink_to(target)
        with self.assertRaises(ControlledTestError):
            start_controlled_test.prepare_diagnostics(app)
        self.assertEqual(target.read_text(), "synthetic preservation marker")
        self.connection.assert_not_called()

    def test_source_fingerprint_excludes_private_run_data(self):
        for directory in ("scripts", "launchpad", "templates", "static"):
            (self.root / directory).mkdir()
        source_files = {
            "scripts/start_controlled_test.py": "synthetic launcher",
            "deploy/gunicorn.conf.py": "synthetic server",
            "launchpad/ad.py": "synthetic adapter",
            "templates/login.html": "synthetic template",
            "static/styles.css": "synthetic style",
        }
        for name, value in source_files.items():
            (self.root / name).write_text(value)
        with patch.object(start_controlled_test, "PROJECT_ROOT", self.root):
            before = start_controlled_test.source_fingerprint()
            (self.directory / "not-source.py").write_text("invented private input")
            (self.directory / "signing-key.txt").write_text("different invented private value")
            self.assertEqual(before, start_controlled_test.source_fingerprint())
            (self.root / "launchpad/ad.py").write_text("changed synthetic adapter")
            self.assertNotEqual(before, start_controlled_test.source_fingerprint())
        self.connection.assert_not_called()

    def test_worker_ready_hook_verifies_loaded_normalization_and_rejects_stale_code(self):
        cert, key = self._tls_files()
        self._ready_config(cert)
        app, context = start_controlled_test.prepare_runtime("synthetic-run", cert, key)
        before = self._digest_files()
        self.addCleanup(self._close_diagnostic_handlers)
        with patch("gunicorn.app.base.BaseApplication.run", autospec=True) as run:
            start_controlled_test.serve(app, context, str(cert), str(key))
        hook = run.call_args.args[0].cfg.post_worker_init
        hook(SimpleNamespace())
        evidence = (self.directory / "logs/login-diagnostics.log").read_text()
        self.assertIn("event=worker_ready", evidence)
        self.assertIn("username_normalization=verified", evidence)
        self.assertIn("source_sha256=" + start_controlled_test.source_fingerprint(), evidence)
        with patch.object(start_controlled_test, "normalized_attempt_key", side_effect=lambda value: value.strip()):
            with self.assertRaisesRegex(ValueError, "normalization is stale"):
                hook(SimpleNamespace())
        self.assertEqual(evidence, (self.directory / "logs/login-diagnostics.log").read_text())
        self.assertEqual(before, self._digest_files())
        self.connection.assert_not_called()


    def test_real_https_listener_serves_login_without_any_directory_connection(self):
        cert, key = self._tls_files()
        self._ready_config(cert)
        before = self._digest_files()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        # A disposable subprocess patches only its synthetic project root and
        # listener port; the actual production launcher has no port override.
        driver = """
from pathlib import Path
import sys
from unittest.mock import patch
import launchpad.controlled_test as controlled
from scripts.start_controlled_test import prepare_runtime, serve
from gunicorn.config import Config
controlled.PROJECT_ROOT = Path(sys.argv[1])
original_set = Config.set
def isolated_set(self, name, value):
    if name == 'bind':
        value = '127.0.0.1:' + sys.argv[4]
    return original_set(self, name, value)
with patch('ldap3.Connection', side_effect=AssertionError('No AD calls allowed')), patch.object(Config, 'set', isolated_set):
    app, context = prepare_runtime('synthetic-run', sys.argv[2], sys.argv[3])
    serve(app, context, sys.argv[2], sys.argv[3])
"""
        child = subprocess.Popen([sys.executable, "-B", "-c", driver, str(self.root), str(cert), str(key), str(port)], cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            client_context = ssl.create_default_context(cafile=str(cert))
            client_context.minimum_version = ssl.TLSVersion.TLSv1_2
            deadline = time.monotonic() + 8
            response = b""
            while time.monotonic() < deadline:
                self.assertIsNone(child.poll(), "Isolated HTTPS process exited before readiness")
                try:
                    raw = socket.create_connection(("127.0.0.1", port), timeout=1)
                except ConnectionRefusedError:
                    time.sleep(0.05)
                    continue
                with raw, client_context.wrap_socket(raw, server_hostname="synthetic.example.invalid") as secure:
                    self.assertIn(secure.version(), ("TLSv1.2", "TLSv1.3"))
                    secure.sendall(b"GET /auth/login HTTP/1.1\r\nHost: synthetic.example.invalid\r\nConnection: close\r\n\r\n")
                    while True:
                        part = secure.recv(65536)
                        if not part:
                            break
                        response += part
                break
            self.assertTrue(response.startswith(b"HTTP/1.1 200"), "Isolated login page did not respond successfully")
            self.assertIn(b'type="password"', response)
            self.assertIn(b'HttpOnly', response)
            self.assertIn(b'Secure', response)
            self.assertEqual(before, self._digest_files())
        finally:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
