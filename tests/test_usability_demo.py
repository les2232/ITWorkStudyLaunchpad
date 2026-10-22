"""Isolated synthetic usability launch and real loopback HTTP workflow checks."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import http.cookiejar
import io
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request

from launchpad.demo import DEMO_NOVA_NAME, DemoDataError, prepare_demo_database, synthetic_beginner_responses
from launchpad.quizzes import get_module_quiz
from launchpad.real_data import initialize_real_database
from launchpad.storage import latest_assessment_result, latest_module_quiz_result, module_is_complete
from scripts import start_usability_demo


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class UsabilityLauncherTests(unittest.TestCase):
    def setUp(self):
        previous_umask = os.umask(0o077)
        self.addCleanup(os.umask, previous_umask)
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / "demo.sqlite"
        self.key = self.database.with_suffix(".session-key")
        self.guards = ExitStack()
        self.addCleanup(self.guards.close)
        for target in ("socket.create_connection", "socket.socket.connect", "ldap3.Connection"):
            self.guards.enter_context(patch(target, side_effect=AssertionError("Unit checks must never open a network/directory connection")))

    def snapshot(self):
        return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.root.iterdir() if path.is_file() and not path.is_symlink()}

    def test_missing_or_non_demo_database_is_refused_before_app_creation_without_changes(self):
        for payload in (None, b"Invented non-database fixture", b"SQLite format 3\x00not a guarded demo"):
            with self.subTest(payload=payload):
                if payload is not None:
                    self.database.write_bytes(payload)
                    self.database.chmod(0o600)
                before = self.snapshot()
                with patch.object(start_usability_demo, "create_app") as create, self.assertRaises((OSError, DemoDataError)):
                    start_usability_demo.prepare_runtime(self.database)
                create.assert_not_called()
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.key.exists())

    def test_isolated_real_schema_is_rejected_without_loading_records_or_mutation(self):
        # This is a brand-new empty real-mode fixture, never a deployed database.
        initialize_real_database(self.database)
        self.database.chmod(0o600)
        before = self.snapshot()
        with patch.object(start_usability_demo, "create_app") as create, self.assertRaises(DemoDataError):
            start_usability_demo.prepare_runtime(self.database)
        create.assert_not_called()
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.key.exists())

    def test_unknown_learner_refused_before_app_creation_or_key_creation(self):
        prepare_demo_database(self.database)
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE students SET display_name='UNAPPROVED invented identity' WHERE display_name=?", (DEMO_NOVA_NAME,))
        before = self.snapshot()
        with patch.object(start_usability_demo, "create_app") as create, self.assertRaises(DemoDataError):
            start_usability_demo.prepare_runtime(self.database)
        create.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_inherited_real_controlled_and_pilot_settings_cannot_select_storage_or_auth(self):
        prepare_demo_database(self.database)
        sentinel = self.root / "other-application.sqlite"
        sentinel.write_bytes(b"Never open this invented unrelated database")
        before = sentinel.read_bytes()
        environment = {
            "LAUNCHPAD_DB_PATH": str(sentinel), "LAUNCHPAD_REAL_MODE": "true",
            "LAUNCHPAD_PILOT_MODE": "true", "LAUNCHPAD_DEMO_MODE": "false",
            "LAUNCHPAD_AUTH_BACKEND": "ad", "LAUNCHPAD_AD_SESSION_POLICY": "controlled_test",
            "LAUNCHPAD_AD_HOST": "directory.invalid", "LAUNCHPAD_AD_STATE_PATH": str(sentinel),
            "LAUNCHPAD_AD_LOOKUP_USERNAME": "invented-lookup", "LAUNCHPAD_AD_LOOKUP_PASSWORD": "invented-unused-value",
            "LAUNCHPAD_SECRET_KEY": "unrelated-key-that-must-not-be-used", "FLASK_DEBUG": "1",
        }
        with patch.dict(os.environ, environment):
            app = start_usability_demo.prepare_runtime(self.database)
            self.assertEqual({key: os.environ[key] for key in environment}, environment)
        self.assertEqual(sentinel.read_bytes(), before)
        self.assertEqual(app.config["LAUNCHPAD_DB_PATH"], str(self.database))
        self.assertTrue(app.config["LAUNCHPAD_DEMO_MODE"])
        self.assertFalse(app.config["LAUNCHPAD_REAL_MODE"])
        self.assertFalse(app.config["LAUNCHPAD_PILOT_MODE"])
        self.assertEqual(app.config["LAUNCHPAD_AD_SESSION_POLICY"], "revalidate")
        self.assertFalse(app.debug)
        self.assertNotEqual(app.secret_key, environment["LAUNCHPAD_SECRET_KEY"])
        self.assertEqual(app.test_client().get("/auth/login").status_code, 404)

    def test_private_directory_database_and_key_permissions_are_required(self):
        prepare_demo_database(self.database)
        for target, insecure, secure in ((self.root, 0o755, 0o700), (self.database, 0o644, 0o600)):
            with self.subTest(target=target.name):
                target.chmod(insecure)
                before = self.snapshot()
                with patch.object(start_usability_demo, "create_app") as create, self.assertRaises(DemoDataError):
                    start_usability_demo.prepare_runtime(self.database)
                create.assert_not_called()
                self.assertEqual(self.snapshot(), before)
                target.chmod(secure)
        self.key.write_text("a" * 64)
        self.key.chmod(0o644)
        before = self.snapshot()
        with patch.object(start_usability_demo, "create_app") as create, self.assertRaises(DemoDataError):
            start_usability_demo.prepare_runtime(self.database)
        create.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_linked_key_and_database_are_refused_without_touching_targets(self):
        prepare_demo_database(self.database)
        target = self.root / "unrelated.session-key"
        target.write_text("b" * 64)
        target.chmod(0o600)
        for link_type in ("symlink", "hardlink"):
            with self.subTest(link_type=link_type):
                if link_type == "symlink":
                    self.key.symlink_to(target)
                else:
                    os.link(target, self.key)
                before = self.snapshot()
                with patch.object(start_usability_demo, "create_app") as create, self.assertRaises(DemoDataError):
                    start_usability_demo.prepare_runtime(self.database)
                create.assert_not_called()
                self.assertEqual(self.snapshot(), before)
                self.key.unlink()
        linked_database = self.root / "linked.sqlite"
        os.link(self.database, linked_database)
        before = self.snapshot()
        with patch.object(start_usability_demo, "create_app") as create, self.assertRaises(DemoDataError):
            start_usability_demo.prepare_runtime(self.database)
        create.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_existing_malformed_key_is_refused_never_replaced_or_logged(self):
        prepare_demo_database(self.database)
        for payload in (b"short", b" " * 64, b"\xff" * 64):
            with self.subTest(payload_type=payload[:1]):
                self.key.write_bytes(payload)
                self.key.chmod(0o600)
                before = self.snapshot()
                output, errors = io.StringIO(), io.StringIO()
                with patch.object(start_usability_demo, "create_app") as create, redirect_stdout(output), redirect_stderr(errors):
                    self.assertEqual(start_usability_demo.main(["--db", str(self.database)]), 2)
                create.assert_not_called()
                self.assertEqual(self.snapshot(), before)
                self.assertNotIn(str(self.database), errors.getvalue())

    def test_preflight_opens_no_listener_and_reuses_signing_key_without_reset(self):
        prepare_demo_database(self.database)
        before = self.database.read_bytes()
        with patch.object(start_usability_demo, "make_server") as server, redirect_stdout(io.StringIO()):
            self.assertEqual(start_usability_demo.main(["--db", str(self.database)]), 0)
            first_key = self.key.read_bytes()
            self.assertEqual(start_usability_demo.main(["--db", str(self.database)]), 0)
        server.assert_not_called()
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(self.key.read_bytes(), first_key)
        self.assertEqual(self.key.stat().st_mode & 0o777, 0o600)

    def test_serve_uses_only_loopback_and_ignores_host_debug_and_bind_environment(self):
        prepare_demo_database(self.database)
        environment = {"PORT": "443", "FLASK_RUN_HOST": "0.0.0.0", "FLASK_DEBUG": "1", "GUNICORN_CMD_ARGS": "--bind 0.0.0.0:8000 --reload"}
        with patch.dict(os.environ, environment), patch.object(start_usability_demo, "make_server") as server, redirect_stdout(io.StringIO()):
            self.assertEqual(start_usability_demo.main(["--db", str(self.database), "--serve"]), 0)
        host, port, app = server.call_args.args
        self.assertEqual((host, port), ("127.0.0.1", 8765))
        self.assertFalse(app.debug)
        server.return_value.__enter__.return_value.serve_forever.assert_called_once_with()

    def test_response_boundaries_reject_nonlocal_hosts_and_protect_synthetic_cookie(self):
        prepare_demo_database(self.database)
        app = start_usability_demo.prepare_runtime(self.database)
        client = app.test_client()
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"synthetic learner data only", response.data)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        cookie = response.headers["Set-Cookie"]
        self.assertTrue(cookie.startswith("launchpad_usability_demo="))
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertEqual(client.get("/", base_url="http://outside.invalid").status_code, 400)


class UsabilityHTTPWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.root = Path(self.temporary.name)
        self.database = self.root / "demo.sqlite"
        prepare_demo_database(self.database)
        self.process = None
        self.log = tempfile.TemporaryFile(mode="w+b", dir=self.root)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.browser = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def tearDown(self):
        self.stop()
        self.log.close()
        self.temporary.cleanup()

    def stop(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            self.process = None

    def start(self):
        # Exercise the actual CLI while making any outbound/AD use in the
        # disposable child fail immediately; its inbound loopback server works.
        guard = """import runpy, socket, ldap3
def denied(*args, **kwargs):
    raise AssertionError('Synthetic demo must never connect to a directory or other remote server')
socket.socket.connect = denied
socket.create_connection = denied
ldap3.Connection = denied
runpy.run_path('scripts/start_usability_demo.py', run_name='__main__')
"""
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("LAUNCHPAD_") and key not in {"FLASK_APP", "FLASK_DEBUG", "FLASK_ENV"}}
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        self.process = subprocess.Popen(
            [sys.executable, "-B", "-c", guard, "--db", str(self.database), "--port", str(self.port), "--serve"],
            cwd=PROJECT_ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.fail("Disposable synthetic launcher exited before its loopback listener opened")
            try:
                self.request("/")
                return
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.05)
        self.fail("Disposable synthetic launcher did not open its loopback listener within 10 seconds")

    def request(self, path, fields=None):
        payload = urllib.parse.urlencode(fields, doseq=True).encode() if fields is not None else None
        with self.browser.open(urllib.request.Request(self.url + path, data=payload), timeout=2) as response:
            self.assertEqual(response.status, 200)
            return response.read().decode("utf-8")

    def test_five_task_http_workflow_saves_assessment_lesson_quiz_and_survives_restart(self):
        self.start()
        home = self.request("/")
        self.assertIn("synthetic learner data only", home)
        self.assertIn('href="/student?next=/pre-assessment"', home)
        picker = self.request("/student?next=/pre-assessment")
        self.assertIn(DEMO_NOVA_NAME, picker)
        assessment = self.request("/student?next=/pre-assessment", {"display_name": DEMO_NOVA_NAME})
        self.assertIn('action="/pre-assessment"', assessment)
        result = self.request("/pre-assessment", synthetic_beginner_responses())
        self.assertIn("Auto-scored starting point: 18%", result)
        self.assertIn('href="/training-path/beginner"', result)
        plan = self.request("/training-path/beginner")
        self.assertIn('href="/modules/what_does_it_do"', plan)
        lesson = self.request("/modules/what_does_it_do")
        self.assertIn("Mark Module Complete", lesson)
        completed = self.request("/modules/what_does_it_do", {"completed": "1"})
        self.assertIn("Reading recorded as complete", completed)
        self.assertIn('href="/modules/what_does_it_do/quiz"', completed)
        self.request("/modules/what_does_it_do/quiz")
        quiz = get_module_quiz("what_does_it_do")
        feedback = self.request("/modules/what_does_it_do/quiz", {question["id"]: question["answer"] for question in quiz["questions"]})
        self.assertIn("100%", feedback)
        progress = self.request("/student")
        self.assertIn("Modules complete: 1", progress)
        self.assertIn("Module quizzes complete: 1", progress)
        self.assertIn("Your Next Step:", progress)
        self.assertIn('href="/modules/common_it_words"', progress)
        with sqlite3.connect(self.database) as database:
            learner_id = database.execute("SELECT id FROM students WHERE display_name=?", (DEMO_NOVA_NAME,)).fetchone()[0]
        self.assertEqual(latest_assessment_result(learner_id, "pre", self.database)["technical_score"], 18)
        self.assertTrue(module_is_complete(learner_id, "what_does_it_do", self.database))
        self.assertEqual(latest_module_quiz_result(learner_id, "what_does_it_do", self.database)["score"], 100)
        before = self.database.read_bytes()
        signing_key = self.database.with_suffix(".session-key").read_bytes()
        self.stop()
        self.start()
        resumed = self.request("/student")
        for marker in (DEMO_NOVA_NAME, "Modules complete: 1", "Module quizzes complete: 1", 'href="/modules/common_it_words"'):
            self.assertIn(marker, resumed)
        self.assertIn("Auto-scored starting point: 18%", self.request("/assessment-results"))
        self.assertIn("100%", self.request("/modules/what_does_it_do/quiz"))
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(self.database.with_suffix(".session-key").read_bytes(), signing_key)
        self.stop()
        self.log.seek(0)
        logs = self.log.read().decode("utf-8")
        self.assertNotIn(synthetic_beginner_responses()["q3"], logs)
        self.assertNotIn(signing_key.decode(), logs)
        self.assertNotIn("/pre-assessment", logs)


if __name__ == "__main__":
    unittest.main()
