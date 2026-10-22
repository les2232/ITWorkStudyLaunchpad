"""Hosted controls are tested separately from the unchanged local-demo modes."""
import base64
import re
import sqlite3
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash
from werkzeug.datastructures import MultiDict

from launchpad import create_app
from launchpad.assessment import all_questions, load_assessment
from launchpad.demo import DEMO_NOVA_NAME, prepare_demo_database
from launchpad.quizzes import get_module_quiz
from launchpad.storage import connect, module_is_complete


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = [] if attrs.get("method", "get").lower() == "post" else None
        if tag == "input" and self.current is not None:
            if attrs.get("name") == "csrf_token":
                self.current.append(attrs)

    def handle_endtag(self, tag):
        if tag == "form" and self.current is not None:
            self.forms.append(self.current)
            self.current = None


class PilotSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = "synthetic-test-invitation-password"
        cls.password_hash = generate_password_hash(cls.password)
        cls.auth = "Basic " + base64.b64encode(f"facilitator:{cls.password}".encode()).decode()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.directory.cleanup)
        self.db_path = Path(self.directory.name) / "pilot-security.sqlite"
        prepare_demo_database(self.db_path)
        self.config = {
            "TESTING": True,
            "LAUNCHPAD_PILOT_MODE": True,
            "LAUNCHPAD_DEMO_MODE": True,
            "LAUNCHPAD_DB_PATH": str(self.db_path),
            "SECRET_KEY": "synthetic-pilot-test-secret-at-least-32-chars",
            "LAUNCHPAD_PILOT_USERNAME": "facilitator",
            "LAUNCHPAD_PILOT_PASSWORD_HASH": self.password_hash,
            "LAUNCHPAD_TRUSTED_HOSTS": "pilot.example",
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    def get(self, path, **kwargs):
        return self.client.get(path, base_url="https://pilot.example", headers={"Authorization": self.auth}, **kwargs)

    def post(self, path, data, **headers):
        return self.client.post(path, data=data, base_url="https://pilot.example", headers={"Authorization": self.auth, **headers})

    def token(self):
        page = self.get("/student")
        self.assertEqual(page.status_code, 200)
        return re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()

    def select(self):
        token = self.token()
        response = self.post("/student", {"display_name": DEMO_NOVA_NAME, "csrf_token": token})
        self.assertEqual(response.status_code, 302)
        return token

    def counts(self):
        tables = ("students", "assessment_results", "module_progress", "module_quiz_results", "checklist_progress", "activity_progress", "stuck_reports", "scenario_attempts")
        with connect(self.db_path) as db:
            return {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}

    def test_invalid_hosted_configuration_fails_before_database_creation(self):
        missing_db = Path(self.directory.name) / "must-not-create.sqlite"
        for key, value in (
            ("LAUNCHPAD_DEMO_MODE", False),
            ("SECRET_KEY", "dev-only-launchpad-secret"),
            ("LAUNCHPAD_PILOT_USERNAME", ""),
            ("LAUNCHPAD_PILOT_USERNAME", "bad:name"),
            ("LAUNCHPAD_PILOT_PASSWORD_HASH", "plaintext"),
            ("LAUNCHPAD_TRUSTED_HOSTS", ""),
            ("LAUNCHPAD_TRUSTED_HOSTS", "*.example"),
        ):
            with self.subTest(setting=key):
                config = {**self.config, "LAUNCHPAD_DB_PATH": str(missing_db), key: value}
                with self.assertRaises(ValueError):
                    create_app(config)
                self.assertFalse(missing_db.exists())

    def test_every_route_including_static_and_mentor_requires_invitation(self):
        before = self.counts()
        for rule in self.app.url_map.iter_rules():
            path = str(rule)
            path = re.sub(r"<[^>]+>", "synthetic-placeholder", path)
            for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
                with self.subTest(path=path, method=method):
                    response = self.client.open(path, method=method, base_url="https://pilot.example")
                    self.assertEqual(response.status_code, 401)
                    self.assertIn("Basic", response.headers["WWW-Authenticate"])
                    self.assertNotIn(DEMO_NOVA_NAME.encode(), response.data)
        wrong = self.client.get("/supervisor", base_url="https://pilot.example", headers={"Authorization": "Basic " + base64.b64encode(b"facilitator:wrong").decode()})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(self.counts(), before)

    def test_rejects_untrusted_host_and_returns_secure_cookie_and_headers(self):
        bad = self.client.get("/", base_url="https://untrusted.example", headers={"Authorization": self.auth})
        self.assertEqual(bad.status_code, 400)
        page = self.get("/student")
        self.assertEqual(page.status_code, 200)
        cookie = page.headers["Set-Cookie"]
        for flag in ("Secure", "HttpOnly", "SameSite=Lax"):
            self.assertIn(flag, cookie)
        self.assertLess(len(cookie), 4093)
        self.assertEqual(page.headers["Cache-Control"], "no-store")
        self.assertEqual(page.headers["X-Frame-Options"], "DENY")
        self.assertIn("form-action 'self'", page.headers["Content-Security-Policy"])

    def test_csrf_and_foreign_origin_rejections_do_not_change_records(self):
        token = self.select()
        before = self.counts()
        for fields, headers in (
            ({"completed": "1"}, {}),
            ({"completed": "1", "csrf_token": "wrong"}, {}),
            ({"completed": "1", "csrf_token": token}, {"Origin": "https://untrusted.example"}),
            ({"completed": "1", "csrf_token": token}, {"Origin": "null"}),
        ):
            with self.subTest(fields=list(fields), headers=headers):
                rejected = self.post("/modules/hardware_basics", fields, **headers)
                self.assertEqual(rejected.status_code, 400)
                self.assertEqual(self.counts(), before)
        valid = self.post("/modules/hardware_basics", {"completed": "1", "csrf_token": token}, Origin="https://pilot.example")
        self.assertEqual(valid.status_code, 302)
        with connect(self.db_path) as db:
            student_id = db.execute("SELECT id FROM students WHERE display_name=?", (DEMO_NOVA_NAME,)).fetchone()[0]
        self.assertTrue(module_is_complete(student_id, "hardware_basics", self.db_path))

    def test_every_rendered_post_form_includes_a_csrf_token(self):
        self.select()
        count = 0
        for path in ("/student", "/pre-assessment", "/post-assessment", "/modules/hardware_basics", "/modules/hardware_basics/quiz", "/checklists/day_1", "/training-path/beginner", "/training-path/developing", "/scenarios/classroom_no_display", "/scenarios/ticket_term_unknown", "/ask", "/stuck"):
            with self.subTest(path=path):
                parser = FormParser()
                page = self.get(path)
                self.assertEqual(page.status_code, 200)
                parser.feed(page.get_data(as_text=True))
                for form in parser.forms:
                    count += 1
                    self.assertEqual(len(form), 1)
                    self.assertEqual(form[0]["type"], "hidden")
                    self.assertGreaterEqual(len(form[0]["value"]), 32)
        self.assertGreater(count, 12)

    def test_invalid_and_empty_required_forms_never_create_completion_or_results(self):
        token = self.select()
        before = self.counts()
        for path, fields in (
            ("/pre-assessment", {}), ("/post-assessment", {}),
            ("/modules/hardware_basics/quiz", {}),
            ("/stuck", {"student": DEMO_NOVA_NAME}),
            ("/scenarios/ticket_term_unknown", {"student_response": "  "}),
            ("/modules/hardware_basics", {"completed": "garbage"}),
        ):
            with self.subTest(path=path):
                response = self.post(path, {**fields, "csrf_token": token})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(self.counts(), before)
        assessment = load_assessment("pre_assessment_v1")
        form = MultiDict({"csrf_token": token})
        for question in all_questions(assessment):
            if question["type"] == "rating":
                form[question["id"]] = "1"
            elif question["type"] == "free_response":
                form[question["id"]] = "Invented training response"
            else:
                form[question["id"]] = str(question["options"][0]["value"])
        form.setlist("q2", ["forged-option"])
        self.assertEqual(self.post("/pre-assessment", form).status_code, 400)
        self.assertEqual(self.counts(), before)
        large = self.post("/stuck", {"csrf_token": token, "trying_to_do": "x" * 65537})
        self.assertEqual(large.status_code, 413)
        self.assertEqual(self.counts(), before)

    def test_valid_preset_and_wrong_but_valid_quiz_answers_keep_exact_scores(self):
        token = self.select()
        response = self.post("/pre-assessment", {"csrf_token": token, "synthetic_preset": "beginner"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(b"18%", self.get("/assessment-results").data)
        quiz = get_module_quiz("hardware_basics")
        answers = {q["id"]: q["answer"] for q in quiz["questions"]}
        first = quiz["questions"][0]
        answers[first["id"]] = next(c["value"] for c in first["choices"] if c["value"] != first["answer"])
        response = self.post("/modules/hardware_basics/quiz", {**answers, "csrf_token": token})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"2 / 3 correct (67%)", response.data)
        self.assertNotIn(b"3 / 3 correct (100%)", response.data)

    def test_storage_failure_is_safe_and_does_not_claim_a_save(self):
        token = self.select()
        before = self.counts()
        with patch("launchpad.web.mark_module_complete", side_effect=sqlite3.OperationalError("sensitive detail must stay private")):
            with self.assertLogs(self.app.logger, level="ERROR") as logs:
                response = self.post("/modules/hardware_basics", {"completed": "1", "csrf_token": token})
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"Do not assume this attempt was saved", response.data)
        self.assertNotIn(b"sensitive detail", response.data)
        self.assertNotIn("sensitive detail", " ".join(logs.output))
        self.assertIn("pilot_storage_unavailable", " ".join(logs.output))
        self.assertEqual(self.counts(), before)
