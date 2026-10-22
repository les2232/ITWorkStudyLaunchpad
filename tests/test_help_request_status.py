"""Open/Resolved help requests: learner ownership, mentor read-only scope and migration.

All learners are invented and every database is a disposable temporary file.
"""
import base64
import hashlib
from contextlib import closing, redirect_stderr, redirect_stdout
import io
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest

from werkzeug.security import generate_password_hash

from launchpad.accounts import assign_mentor, create_auth_session, enroll_account, init_accounts_schema
from launchpad.demo import DEMO_NOVA_NAME, prepare_demo_database
from launchpad.real_data import (
    REAL_SCHEMA_VERSION, RealDataError, initialize_real_database, migrate_real_database, validate_real_database,
)
from launchpad.storage import (
    connect, create_or_find_student, help_requests_for_student, init_db, open_stuck_reports,
    recent_stuck_reports, save_stuck_report, set_stuck_report_resolved, student_progress,
)
from launchpad.web import create_app
from scripts import manage_real_data
from tests.test_ux_navigation import Page

ORIGINAL_COLUMNS = ("id", "student_id", "context", "what_tried", "question", "mentor_summary", "created_at")


def save_request(student_id, topic, db_path):
    return save_stuck_report(student_id, {"topic": topic, "current_blocker": f"Invented blocker for {topic}"},
                             f"Topic: {topic}\nInvented summary for {topic}", db_path)


def original_rows(db_path):
    with closing(sqlite3.connect(db_path)) as db:
        return db.execute(f"SELECT {', '.join(ORIGINAL_COLUMNS)} FROM stuck_reports ORDER BY id").fetchall()


def resolved_values(db_path):
    with closing(sqlite3.connect(db_path)) as db:
        return dict(db.execute("SELECT id, resolved_at FROM stuck_reports ORDER BY id").fetchall())


def main_text(page):
    return page.find("main")[0].label


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_version_1_real_database(path):
    """Recreate the schema-version-1 layout: no resolved_at column, marker 1."""
    init_db(path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("ALTER TABLE stuck_reports DROP COLUMN resolved_at")
    init_accounts_schema(path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE real_dataset_metadata (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            schema_version INTEGER NOT NULL,
            dataset_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")
        db.execute("INSERT INTO real_dataset_metadata VALUES (1, 1, ?, '2026-10-01T00:00:00+00:00')", ("a" * 32,))
    path.chmod(0o600)


class HelpRequestStorageTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="help-status-storage-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.db_path = self.root / "synthetic.sqlite"
        init_db(self.db_path)
        self.learner = create_or_find_student("SYN Help Owner", self.db_path)["id"]
        self.other = create_or_find_student("SYN Help Other", self.db_path)["id"]

    def test_existing_local_database_gains_status_column_and_keeps_requests_open(self):
        legacy = self.root / "legacy.sqlite"
        init_db(legacy)
        with closing(sqlite3.connect(legacy)) as db, db:
            db.execute("ALTER TABLE stuck_reports DROP COLUMN resolved_at")
        learner = create_or_find_student("SYN Legacy Learner", legacy)["id"]
        with closing(sqlite3.connect(legacy)) as db, db:
            for index in range(3):
                db.execute(
                    "INSERT INTO stuck_reports (student_id, context, what_tried, question, mentor_summary, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (learner, f"ctx {index}", "tried", "q", f"Topic: Legacy {index}", f"2026-10-0{index + 1}T12:00:00+00:00"),
                )
        before = original_rows(legacy)
        init_db(legacy)
        init_db(legacy)  # Repeated startup stays additive and idempotent.
        self.assertEqual(original_rows(legacy), before)
        self.assertEqual(set(resolved_values(legacy).values()), {None})
        overview = help_requests_for_student(learner, legacy)
        self.assertEqual([item["topic"] for item in overview["open"]], ["Legacy 2", "Legacy 1", "Legacy 0"])
        self.assertEqual({item["status_label"] for item in overview["open"]}, {"Open"})

    def test_resolve_and_reopen_change_only_status_for_the_owner(self):
        first = save_request(self.learner, "Printer queue", self.db_path)
        other_report = save_request(self.other, "Other learner topic", self.db_path)
        before = original_rows(self.db_path)

        self.assertTrue(set_stuck_report_resolved(self.learner, first, True, self.db_path))
        resolved_at = resolved_values(self.db_path)[first]
        self.assertIsNotNone(resolved_at)
        self.assertTrue(set_stuck_report_resolved(self.learner, first, True, self.db_path))
        self.assertEqual(resolved_values(self.db_path)[first], resolved_at, "repeat resolve keeps the first time")
        self.assertTrue(set_stuck_report_resolved(self.learner, first, False, self.db_path))
        self.assertIsNone(resolved_values(self.db_path)[first])

        self.assertFalse(set_stuck_report_resolved(self.learner, other_report, True, self.db_path))
        self.assertFalse(set_stuck_report_resolved(self.other, first, True, self.db_path))
        self.assertFalse(set_stuck_report_resolved(self.learner, 9999, True, self.db_path))
        self.assertEqual(set(resolved_values(self.db_path).values()), {None})
        self.assertEqual(original_rows(self.db_path), before)

    def test_older_open_requests_stay_discoverable_behind_newer_requests(self):
        oldest = save_request(self.learner, "Oldest open", self.db_path)
        newer = [save_request(self.learner, f"Newer {index}", self.db_path) for index in range(12)]
        for report_id in newer[:-1]:
            set_stuck_report_resolved(self.learner, report_id, True, self.db_path)
        save_request(self.other, "Other learner topic", self.db_path)

        self.assertNotIn(oldest, [item["id"] for item in recent_stuck_reports(self.learner, self.db_path)])
        overview = help_requests_for_student(self.learner, self.db_path, resolved_limit=5)
        self.assertEqual([item["id"] for item in overview["open"]], [newer[-1], oldest])
        self.assertEqual(len(overview["resolved"]), 5)
        self.assertEqual(overview["resolved_total"], 11)
        self.assertEqual([item["topic"] for item in open_stuck_reports([self.learner], self.db_path)],
                         ["Oldest open", "Newer 11"])
        self.assertEqual(open_stuck_reports([], self.db_path), [])
        summary = student_progress(self.learner, self.db_path)
        self.assertEqual((summary["stuck_report_count"], summary["open_stuck_report_count"]), (13, 2))


class LocalHelpRequestRouteTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="help-status-local-")
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / "synthetic.sqlite"
        self.app = create_app({"TESTING": True, "LAUNCHPAD_DEMO_MODE": False, "LAUNCHPAD_DB_PATH": str(self.db_path)})
        self.client = self.app.test_client()

    def sign_in(self, name):
        self.client.post("/student", data={"display_name": name})
        return create_or_find_student(name, self.db_path)["id"]

    def test_learner_lists_resolves_and_reopens_requests_with_clear_wording(self):
        learner = self.sign_in("SYN Help Route")
        empty = Page(self.client.get("/help-requests"))
        self.assertIn("You have no open help requests.", main_text(empty))
        self.assertFalse(empty.find(id="help-request-status"))

        older = save_request(learner, "Older imaging question", self.db_path)
        newer = save_request(learner, "Newer asset tag question", self.db_path)
        before = original_rows(self.db_path)
        page = Page(self.client.get("/help-requests"))
        self.assertIn("It does not mean a mentor approved your work or that you have shown the skill.", main_text(page))
        self.assertIn("Saving a request does not send it or notify anyone.", main_text(page))
        open_items = page.find("ul", **{"class": "help-request-list"})[0]
        self.assertLess(open_items.label.index("Newer asset tag question"), open_items.label.index("Older imaging question"))
        self.assertIn("Open (2)", main_text(page))

        response = self.client.post(f"/help-requests/{older}/status", data={"status": "resolved"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith(f"/help-requests#help-request-{older}"))
        page = Page(self.client.get("/help-requests"))
        self.assertIn("Open (1)", main_text(page))
        self.assertIn("Resolved (1)", main_text(page))
        resolved_item = page.find(id=f"help-request-{older}")[0]
        self.assertIn("Resolved", resolved_item.label)
        self.assertIn("Marked resolved", resolved_item.label)
        self.assertIn("Reopen", resolved_item.label)
        self.assertIn("Mark resolved", page.find(id=f"help-request-{newer}")[0].label)

        home = Page(self.client.get("/")).find(id="help-request-status")[0]
        self.assertIn("1 open request", home.label)
        self.assertIn("Newer asset tag question", home.label)

        self.client.post(f"/help-requests/{newer}/status", data={"status": "resolved"})
        home = Page(self.client.get("/")).find(id="help-request-status")[0]
        self.assertIn("No open help requests. You marked 2 earlier requests resolved.", home.label)
        self.client.post(f"/help-requests/{older}/status", data={"status": "open"})
        self.assertEqual(resolved_values(self.db_path)[older], None)
        self.assertEqual(original_rows(self.db_path), before)

    def test_unowned_missing_and_malformed_status_changes_are_refused(self):
        owner = self.sign_in("SYN Help Owner")
        owned = save_request(owner, "Owner topic", self.db_path)
        self.sign_in("SYN Help Intruder")
        self.assertEqual(self.client.post(f"/help-requests/{owned}/status", data={"status": "resolved"}).status_code, 404)
        self.assertEqual(self.client.post("/help-requests/9999/status", data={"status": "resolved"}).status_code, 404)
        self.assertNotIn("Owner topic", self.client.get("/help-requests").get_data(as_text=True))
        self.sign_in("SYN Help Owner")
        for data in ({}, {"status": "done"}, {"status": ["open", "resolved"]}):
            self.assertEqual(self.client.post(f"/help-requests/{owned}/status", data=data).status_code, 400, data)
        self.assertEqual(self.client.get(f"/help-requests/{owned}/status").status_code, 405)
        fresh = self.app.test_client()
        self.assertEqual(fresh.post(f"/help-requests/{owned}/status", data={"status": "resolved"}).status_code, 404)
        self.assertIn("Choose a learner name", fresh.get("/help-requests").get_data(as_text=True))
        self.assertEqual(resolved_values(self.db_path), {owned: None})

    def test_saved_summary_links_to_status_page_and_text_is_escaped(self):
        self.sign_in("SYN Help Escape")
        response = self.client.post("/stuck", data={
            "student": "SYN Help Escape", "topic": "<b>Invented</b>", "trying_to_do": "x",
            "what_happened": "y", "already_checked": "z", "current_blocker": "<script>alert(1)</script>",
        })
        markup = response.get_data(as_text=True)
        self.assertIn("It was not sent to anyone", markup)
        self.assertIn('href="/help-requests"', markup)
        listing = self.client.get("/help-requests").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", listing)
        self.assertNotIn("<b>Invented</b>", listing)
        self.assertIn("&lt;b&gt;Invented&lt;/b&gt;", listing)


class PilotHelpRequestCsrfTests(unittest.TestCase):
    def test_status_change_requires_the_pilot_form_token(self):
        directory = tempfile.TemporaryDirectory(prefix="help-status-pilot-", dir="/tmp")
        self.addCleanup(directory.cleanup)
        db_path = Path(directory.name) / "pilot.sqlite"
        prepare_demo_database(db_path)
        password = "synthetic-test-invitation-password"
        app = create_app({
            "TESTING": True, "LAUNCHPAD_PILOT_MODE": True, "LAUNCHPAD_DEMO_MODE": True,
            "LAUNCHPAD_DB_PATH": str(db_path), "SECRET_KEY": "synthetic-pilot-test-secret-at-least-32-chars",
            "LAUNCHPAD_PILOT_USERNAME": "facilitator", "LAUNCHPAD_PILOT_PASSWORD_HASH": generate_password_hash(password),
            "LAUNCHPAD_TRUSTED_HOSTS": "pilot.example",
        })
        client = app.test_client()
        headers = {"Authorization": "Basic " + base64.b64encode(f"facilitator:{password}".encode()).decode()}
        base = "https://pilot.example"

        def token():
            page = client.get("/student", base_url=base, headers=headers)
            return re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True)).group(1)

        client.post("/student", base_url=base, headers=headers, data={"display_name": DEMO_NOVA_NAME, "csrf_token": token()})
        learner = create_or_find_student(DEMO_NOVA_NAME, db_path)["id"]
        report = save_request(learner, "Pilot invented topic", db_path)
        before = resolved_values(db_path)[report]
        for data in ({"status": "resolved"}, {"status": "resolved", "csrf_token": "wrong"}):
            response = client.post(f"/help-requests/{report}/status", base_url=base, headers=headers, data=data)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(resolved_values(db_path)[report], before)
        response = client.post(f"/help-requests/{report}/status", base_url=base, headers=headers,
                               data={"status": "resolved", "csrf_token": token()})
        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(resolved_values(db_path)[report])


class RealModeHelpRequestTests(unittest.TestCase):
    origin = "https://launchpad.example.invalid"
    issuer = "https://identity.example.invalid"

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="help-status-real-", dir="/tmp")
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "synthetic.sqlite"
        initialize_real_database(self.database)
        self.learner = enroll_account(self.issuer, "invented-learner", "Invented learner", db_path=self.database)
        self.other = enroll_account(self.issuer, "invented-other", "Unassigned learner", db_path=self.database)
        self.mentor = enroll_account(self.issuer, "invented-mentor", "", "mentor", db_path=self.database)
        assign_mentor(self.mentor["id"], self.learner["learner_id"], self.database)
        self.app = create_app({
            "TESTING": True, "SECRET_KEY": "synthetic-help-status-test-signing-key-at-least-32-chars",
            "LAUNCHPAD_REAL_MODE": True, "LAUNCHPAD_DEMO_MODE": False, "LAUNCHPAD_PILOT_MODE": False,
            "LAUNCHPAD_DB_PATH": str(self.database), "LAUNCHPAD_TRUSTED_HOSTS": "launchpad.example.invalid",
            "LAUNCHPAD_OIDC_ISSUER": self.issuer, "LAUNCHPAD_OIDC_CLIENT_ID": "invented-client",
            "LAUNCHPAD_OIDC_CLIENT_SECRET": "invented-secret",
            "LAUNCHPAD_OIDC_REDIRECT_URI": self.origin + "/auth/callback", "LAUNCHPAD_OIDC_CLIENT": object(),
        })

    def client_for(self, account):
        client = self.app.test_client()
        token = create_auth_session(account["id"], self.database)
        with client.session_transaction(base_url=self.origin) as session:
            session["auth_session"] = token
            session["csrf_token"] = "synthetic-csrf-token"
        return client

    def post_status(self, client, report_id, **data):
        headers = data.pop("headers", {})
        return client.post(f"/help-requests/{report_id}/status", base_url=self.origin, data=data, headers=headers)

    def test_learner_changes_only_own_request_with_valid_csrf(self):
        own = save_request(self.learner["learner_id"], "Own invented topic", self.database)
        foreign = save_request(self.other["learner_id"], "Other invented topic", self.database)
        learner = self.client_for(self.learner)
        page = learner.get("/help-requests", base_url=self.origin)
        self.assertEqual(page.status_code, 200)
        markup = page.get_data(as_text=True)
        self.assertIn("Own invented topic", markup)
        self.assertNotIn("Other invented topic", markup)
        self.assertIn('name="csrf_token" value="synthetic-csrf-token"', markup)

        before = original_rows(self.database)
        refused = [
            self.post_status(learner, own, status="resolved"),
            self.post_status(learner, own, status="resolved", csrf_token="wrong"),
            self.post_status(learner, own, status="resolved", csrf_token="synthetic-csrf-token",
                             headers={"Origin": "https://untrusted.example.invalid"}),
            self.post_status(learner, own, status="closed", csrf_token="synthetic-csrf-token"),
        ]
        self.assertEqual([response.status_code for response in refused], [400, 400, 400, 400])
        self.assertEqual(self.post_status(learner, foreign, status="resolved", csrf_token="synthetic-csrf-token").status_code, 404)
        self.assertEqual(self.post_status(learner, own, status="resolved", csrf_token="synthetic-csrf-token",
                                          learner_id=str(self.other["learner_id"])).status_code, 403)
        self.assertEqual(set(resolved_values(self.database).values()), {None})

        accepted = self.post_status(learner, own, status="resolved", csrf_token="synthetic-csrf-token",
                                    headers={"Origin": self.origin})
        self.assertEqual(accepted.status_code, 302)
        self.assertIsNotNone(resolved_values(self.database)[own])
        self.assertEqual(self.post_status(learner, own, status="open", csrf_token="synthetic-csrf-token").status_code, 302)
        self.assertIsNone(resolved_values(self.database)[own])
        self.assertEqual(original_rows(self.database), before)

    def test_mentor_sees_assigned_open_requests_read_only(self):
        oldest = save_request(self.learner["learner_id"], "Oldest assigned open topic", self.database)
        for index in range(11):
            save_request(self.learner["learner_id"], f"Later assigned topic {index}", self.database)
        resolved = save_request(self.learner["learner_id"], "Resolved assigned topic", self.database)
        set_stuck_report_resolved(self.learner["learner_id"], resolved, True, self.database)
        save_request(self.other["learner_id"], "Unassigned learner topic", self.database)
        mentor = self.client_for(self.mentor)

        overview = Page(mentor.get("/supervisor", base_url=self.origin))
        section = overview.find("section", **{"aria-labelledby": "open-help-heading"})[0]
        self.assertIn("Open Help Requests (12)", section.label)
        self.assertIn("Oldest assigned open topic", section.label)
        self.assertIn("Invented learner", section.label)
        self.assertNotIn("Resolved assigned topic", section.label)
        self.assertNotIn("Unassigned learner", main_text(overview))
        self.assertIn('"Resolved" is not mentor approval or demonstrated skill', section.label)
        self.assertIn("Saving a request does not notify you", section.label)
        self.assertFalse(overview.within(section, "form"))
        self.assertIn("Help requests: 13 (12 open)", main_text(overview))
        self.assertLess(section.label.index("Oldest assigned open topic"), section.label.index("Later assigned topic 0"))

        detail = mentor.get(f"/supervisor/learners/{self.learner['learner_id']}", base_url=self.origin)
        detail_page = Page(detail)
        detail_open = detail_page.find("section", **{"aria-labelledby": "open-help-heading"})[0]
        self.assertIn("Oldest assigned open topic", detail_open.label)
        self.assertIn("Learner marked resolved", main_text(detail_page))
        self.assertNotIn('action="/help-requests', detail.get_data(as_text=True))
        self.assertEqual(mentor.get(f"/supervisor/learners/{self.other['learner_id']}", base_url=self.origin).status_code, 404)

        self.assertEqual(mentor.get("/help-requests", base_url=self.origin).status_code, 403)
        refused = self.post_status(mentor, oldest, status="resolved", csrf_token="synthetic-csrf-token")
        self.assertEqual(refused.status_code, 403)
        self.assertIsNone(resolved_values(self.database)[oldest])

        anonymous = self.app.test_client()
        self.assertEqual(anonymous.get("/help-requests", base_url=self.origin).status_code, 401)
        self.assertEqual(self.post_status(anonymous, oldest, status="resolved").status_code, 401)
        self.assertIsNone(resolved_values(self.database)[oldest])


class RealDatabaseMigrationTests(unittest.TestCase):
    issuer = "https://identity.example.invalid"

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="help-status-migration-", dir="/tmp")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.source = self.root / "version1.sqlite"
        build_version_1_real_database(self.source)
        learner = enroll_account(self.issuer, "invented-learner", "Invented learner", db_path=self.source)
        mentor = enroll_account(self.issuer, "invented-mentor", "", "mentor", db_path=self.source)
        assign_mentor(mentor["id"], learner["learner_id"], self.source)
        create_auth_session(learner["id"], self.source)
        with closing(sqlite3.connect(self.source)) as db, db:
            for index in range(3):
                db.execute(
                    "INSERT INTO stuck_reports (student_id, context, what_tried, question, mentor_summary, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (learner["learner_id"], f"ctx {index}", "tried", "q", f"Topic: Old {index}",
                     f"2026-10-0{index + 1}T15:00:00+00:00"),
                )
        self.learner = learner

    def table_rows(self, path, table):
        with closing(sqlite3.connect(path)) as db:
            return db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()

    def test_version_1_database_is_refused_until_migrated_to_a_new_copy(self):
        with self.assertRaises(RealDataError):
            validate_real_database(self.source)
        self.assertEqual(validate_real_database(self.source, schema_version=1)["schema_version"], 1)
        before_hash = sha256(self.source)
        before_requests = original_rows(self.source)
        before_tables = {table: self.table_rows(self.source, table)
                         for table in ("students", "accounts", "mentor_assignments", "auth_sessions", "access_audit")}

        target = self.root / "version2.sqlite"
        migrate_real_database(self.source, target)

        self.assertEqual(sha256(self.source), before_hash, "the source must not change")
        self.assertEqual(validate_real_database(target)["schema_version"], REAL_SCHEMA_VERSION)
        self.assertEqual(original_rows(target), before_requests)
        self.assertEqual(set(resolved_values(target).values()), {None})
        for table, rows in before_tables.items():
            self.assertEqual(self.table_rows(target, table), rows, table)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(db.execute("SELECT dataset_id FROM real_dataset_metadata").fetchone()[0], "a" * 32)
        overview = help_requests_for_student(self.learner["learner_id"], target)
        self.assertEqual([item["topic"] for item in overview["open"]], ["Old 2", "Old 1", "Old 0"])

    def test_migration_refuses_existing_destinations_and_already_migrated_sources(self):
        existing = self.root / "existing.sqlite"
        existing.write_bytes(b"preserve")
        with self.assertRaises(RealDataError):
            migrate_real_database(self.source, existing)
        self.assertEqual(existing.read_bytes(), b"preserve")
        target = self.root / "version2.sqlite"
        migrate_real_database(self.source, target)
        with self.assertRaises(RealDataError):
            migrate_real_database(target, self.root / "again.sqlite")
        self.assertFalse((self.root / "again.sqlite").exists())
        current = self.root / "current.sqlite"
        initialize_real_database(current)
        with self.assertRaises(RealDataError):
            migrate_real_database(current, self.root / "from-current.sqlite")
        self.assertFalse((self.root / "from-current.sqlite").exists())

    def test_operator_cli_migrates_and_reports_without_echoing_paths(self):
        target = self.root / "cli-version2.sqlite"
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            status = manage_real_data.main(["migrate", "--source", str(self.source), "--destination", str(target)])
        self.assertEqual(status, 0)
        self.assertIn("Existing help requests start as Open", output.getvalue())
        self.assertNotIn(str(self.root), output.getvalue() + errors.getvalue())
        self.assertEqual(validate_real_database(target)["schema_version"], 2)
        with redirect_stdout(io.StringIO()), redirect_stderr(errors):
            refused = manage_real_data.main(["migrate", "--source", str(self.source), "--destination", str(target)])
        self.assertEqual(refused, 2)


if __name__ == "__main__":
    unittest.main()
