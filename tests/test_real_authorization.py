"""Real-mode access checks against disposable accounts and learner records.

The callback verifier is mocked at its validated-identity boundary here; actual
OIDC signatures/state/nonce/PKCE have separate tests. No organization is contacted.
"""
from contextlib import closing
import re
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.datastructures import MultiDict
from werkzeug.security import generate_password_hash

from launchpad import create_app
from launchpad.accounts import (
    assign_mentor, create_auth_session, enroll_account, get_session_account,
    set_account_active, unassign_mentor,
)
from launchpad.assessment import all_questions, load_assessment
from launchpad.demo import synthetic_beginner_responses
from launchpad.oidc import OIDCLoginError
from launchpad.quizzes import get_module_quiz
from launchpad.real_data import RealDataError, assert_non_real_database, initialize_real_database
from launchpad.scenarios import get_scenario
from launchpad.storage import (
    activity_progress, checklist_progress, connect, latest_assessment_result,
    init_db, latest_module_quiz_result, module_is_complete,
)


class RealAuthorizationTests(unittest.TestCase):
    base_url = "https://launchpad.example"
    issuer = "https://identity.example/approved-tenant"
    cookie_name = "__Host-launchpad_session"
    reads = (
        "/", "/learn", "/help", "/student", "/pre-assessment", "/assessment-results",
        "/post-assessment", "/training-path/beginner", "/modules", "/modules/hardware_basics",
        "/modules/hardware_basics/quiz", "/checklists/day_1", "/scenarios",
        "/scenarios/ticket_term_unknown", "/scenarios/classroom_no_display", "/ask", "/stuck",
        "/mentor-summary", "/supervisor",
    )
    writes = (
        "/student", "/pre-assessment", "/post-assessment", "/modules/hardware_basics",
        "/modules/hardware_basics/quiz", "/checklists/day_1",
        "/training-path/beginner/activities/beginner_shadow_mentor",
        "/scenarios/ticket_term_unknown", "/scenarios/classroom_no_display/actions",
        "/scenarios/classroom_no_display/complete", "/ask", "/stuck",
    )
    learner_tables = (
        "students", "assessment_results", "module_progress", "module_quiz_results",
        "checklist_progress", "activity_progress", "scenario_attempts", "stuck_reports",
    )

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="launchpad-real-authz-", dir="/tmp")
        self.addCleanup(directory.cleanup)
        self.database = Path(directory.name) / "isolated.sqlite"
        initialize_real_database(self.database)
        self.first = enroll_account(self.issuer, "learner-a", "Avery Example", db_path=self.database)
        self.second = enroll_account(self.issuer, "learner-b", "Blair Example", db_path=self.database)
        self.mentor = enroll_account(self.issuer, "mentor-one", role="mentor", db_path=self.database)
        self.admin = enroll_account(self.issuer, "admin-one", role="admin", db_path=self.database)
        self.config = {
            "TESTING": True, "LAUNCHPAD_REAL_MODE": True, "LAUNCHPAD_DEMO_MODE": False,
            "LAUNCHPAD_PILOT_MODE": False, "LAUNCHPAD_DB_PATH": str(self.database),
            "SECRET_KEY": "isolated-real-user-test-signing-key-at-least-32-chars",
            "LAUNCHPAD_TRUSTED_HOSTS": "launchpad.example",
            "LAUNCHPAD_OIDC_ISSUER": self.issuer,
            "LAUNCHPAD_OIDC_CLIENT_ID": "isolated-test-client",
            "LAUNCHPAD_OIDC_CLIENT_SECRET": "isolated-test-client-secret",
            "LAUNCHPAD_OIDC_REDIRECT_URI": self.base_url + "/auth/callback",
            "LAUNCHPAD_OIDC_CLIENT": object(),
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    def get(self, path, client=None, **kwargs):
        return (client or self.client).get(path, base_url=self.base_url, **kwargs)

    def post(self, path, data=None, client=None, **kwargs):
        return (client or self.client).post(path, data=data or {}, base_url=self.base_url, **kwargs)

    def login(self, account=None, client=None, extra_claims=None):
        account = account or self.first
        client = client or self.client
        identity = {"issuer": account["issuer"], "subject": account["subject"], **(extra_claims or {})}
        with patch("launchpad.real_auth.complete_login", return_value=identity):
            response = self.get("/auth/callback?state=verified&code=verified", client)
        self.assertEqual(response.status_code, 302)
        with client.session_transaction(base_url=self.base_url) as browser_session:
            browser_session["csrf_token"] = "isolated-request-token-at-least-32-characters"
        return client

    def token(self, client=None):
        with (client or self.client).session_transaction(base_url=self.base_url) as browser_session:
            return browser_session["csrf_token"]

    def handle(self, client=None):
        with (client or self.client).session_transaction(base_url=self.base_url) as browser_session:
            return browser_session["auth_session"]

    def submit(self, path, fields=None, client=None, **kwargs):
        return self.post(path, {**(fields or {}), "csrf_token": self.token(client)}, client, **kwargs)

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

    def seed_private_records(self, account, marker):
        client = self.login(account, self.app.test_client())
        answers = synthetic_beginner_responses()
        answers["q3"] = marker + " assessment answer"
        self.assertEqual(self.submit("/pre-assessment", answers, client).status_code, 302)
        self.assertEqual(self.submit("/scenarios/ticket_term_unknown", {"student_response": marker + " scenario draft"}, client).status_code, 200)
        report = {
            "topic": "practice", "trying_to_do": marker + " help request",
            "what_happened": "The practice display was blank", "already_checked": "Approved cable checks",
            "current_blocker": "Need a mentor's approved next step", "related_item": "Hardware Basics",
        }
        self.assertEqual(self.submit("/stuck", report, client).status_code, 200)
        return client

    def test_real_dataset_cannot_start_with_missing_or_downgraded_authentication_flags(self):
        before = self.database.read_bytes()
        invitation_hash = generate_password_hash("isolated-unused-invitation")
        baseline = {key: value for key, value in self.config.items() if key != "LAUNCHPAD_REAL_MODE"}
        baseline.update(LAUNCHPAD_PILOT_USERNAME="isolated", LAUNCHPAD_PILOT_PASSWORD_HASH=invitation_hash)
        for flags in (
            {}, {"LAUNCHPAD_REAL_MODE": False},
            {"LAUNCHPAD_REAL_MODE": False, "LAUNCHPAD_DEMO_MODE": True},
            {"LAUNCHPAD_REAL_MODE": False, "LAUNCHPAD_DEMO_MODE": True, "LAUNCHPAD_PILOT_MODE": True},
            {"LAUNCHPAD_REAL_MODE": False, "LAUNCHPAD_PILOT_MODE": True},
        ):
            with self.subTest(flags=flags), patch.dict("os.environ", {"LAUNCHPAD_REAL_MODE": "0"}):
                with self.assertRaises(ValueError):
                    create_app({**baseline, **flags})
                self.assertEqual(self.database.read_bytes(), before)

    def test_partial_real_schema_refuses_ordinary_mode_without_rewriting_anything(self):
        for table in ("accounts", "auth_sessions", "mentor_assignments", "access_audit", "real_dataset_metadata", "ACCOUNTS"):
            with self.subTest(table=table):
                path = self.database.parent / f"partial-{table}.sqlite"
                init_db(path)
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute(f"CREATE TABLE {table} (id INTEGER)")
                before = path.read_bytes()
                with self.assertRaises(RealDataError):
                    assert_non_real_database(path)
                with self.assertRaises(RealDataError):
                    create_app({"TESTING": True, "LAUNCHPAD_DB_PATH": str(path), "LAUNCHPAD_REAL_MODE": False,
                                "LAUNCHPAD_DEMO_MODE": False, "LAUNCHPAD_PILOT_MODE": False})
                self.assertEqual(path.read_bytes(), before)

    def test_mode_guard_keeps_ordinary_initialization_and_refuses_unreadable_data(self):
        missing = self.database.parent / "ordinary-missing.sqlite"
        assert_non_real_database(missing)
        self.assertFalse(missing.exists())
        ordinary = create_app({"TESTING": True, "LAUNCHPAD_DB_PATH": str(missing), "LAUNCHPAD_REAL_MODE": False,
                               "LAUNCHPAD_DEMO_MODE": False, "LAUNCHPAD_PILOT_MODE": False})
        self.assertEqual(ordinary.test_client().get("/supervisor").status_code, 200)
        before = missing.read_bytes()
        assert_non_real_database(missing)
        self.assertEqual(missing.read_bytes(), before)
        corrupt = self.database.parent / "unreadable.sqlite"
        corrupt.write_bytes(b"Not a SQLite database; preserve this artifact")
        before = corrupt.read_bytes()
        with self.assertRaises(RealDataError):
            assert_non_real_database(corrupt)
        self.assertEqual(corrupt.read_bytes(), before)

    def test_unauthenticated_reads_and_direct_writes_cannot_access_records(self):
        before = self.snapshot()
        for path in self.reads + (f"/supervisor/learners/{self.first['learner_id']}",):
            with self.subTest(method="GET", path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 401)
                for private in (b"Avery Example", b"Blair Example", b"learner-a", b"learner-b"):
                    self.assertNotIn(private, response.data)
        for path in self.writes:
            with self.subTest(method="POST", path=path):
                self.assertEqual(self.post(path, {"student_id": self.first["learner_id"], "completed": "1"}).status_code, 401)
        self.assertEqual(self.snapshot(), before)

    def test_cross_learner_query_identifiers_are_rejected_without_record_changes(self):
        self.login()
        before = self.snapshot()
        for path in self.reads:
            with self.subTest(path=path):
                response = self.get(path, query_string={"learner_id": self.second["learner_id"]})
                self.assertEqual(response.status_code, 403)
                self.assertNotIn(b"Blair Example", response.data)
        self.assertEqual(self.snapshot(), before)

    def test_cross_learner_form_identifiers_and_selector_requests_are_rejected(self):
        self.login()
        before = self.snapshot()
        for path in self.writes:
            with self.subTest(path=path):
                response = self.submit(path, {"student_id": self.second["learner_id"], "completed": "1"})
                self.assertEqual(response.status_code, 403)
        for field, value in (
            ("student", "Blair Example"), ("display_name", "Blair Example"),
            ("learner_id", self.second["learner_id"]), ("account_id", self.second["id"]),
            ("role", "admin"), ("issuer", self.issuer), ("subject", self.second["subject"]),
        ):
            with self.subTest(field=field):
                self.assertEqual(self.submit("/modules/hardware_basics", {field: value, "completed": "1"}).status_code, 403)
                self.assertEqual(self.get("/student", query_string={field: value}).status_code, 403)
        self.assertEqual(self.submit("/student").status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_legacy_cookie_fields_and_identity_headers_cannot_switch_account_or_role(self):
        self.login()
        with self.client.session_transaction(base_url=self.base_url) as browser_session:
            browser_session.update(student_id=self.second["learner_id"], student_display_name="Blair Example",
                                   account_id=self.admin["id"], role="admin", subject=self.second["subject"])
        headers = {"Remote-User": self.second["subject"], "X-Forwarded-User": self.second["subject"], "X-User-Role": "admin"}
        page = self.get("/student", headers=headers)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Avery Example", page.data)
        self.assertNotIn(b"Blair Example", page.data)
        self.assertEqual(self.get("/supervisor", headers=headers).status_code, 403)
        self.assertEqual(self.submit("/modules/hardware_basics", {"completed": "1"}, headers=headers).status_code, 302)
        self.assertTrue(module_is_complete(self.first["learner_id"], "hardware_basics", self.database))
        self.assertFalse(module_is_complete(self.second["learner_id"], "hardware_basics", self.database))
        with self.client.session_transaction(base_url=self.base_url) as browser_session:
            self.assertNotIn("student_id", browser_session)
            self.assertNotIn("student_display_name", browser_session)
        unauthenticated = self.app.test_client()
        with unauthenticated.session_transaction(base_url=self.base_url) as browser_session:
            browser_session.update(student_id=self.first["learner_id"], role="admin")
        self.assertEqual(self.get("/student", unauthenticated, headers=headers).status_code, 401)

    def test_validated_identity_claims_do_not_grant_roles_or_claim_another_learner(self):
        self.login(extra_claims={"role": "admin", "roles": ["mentor", "admin"], "learner_id": self.second["learner_id"], "name": "Blair Example"})
        self.assertEqual(self.get("/supervisor").status_code, 403)
        self.assertIn(b"Avery Example", self.get("/student").data)
        self.assertEqual(get_session_account(self.handle(), self.database)["id"], self.first["id"])
        before = self.snapshot()
        unknown = self.app.test_client()
        with patch("launchpad.real_auth.complete_login", return_value={"issuer": self.issuer, "subject": "not-enrolled", "name": "Avery Example", "role": "admin"}):
            self.assertEqual(self.get("/auth/callback?code=verified", unknown).status_code, 403)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.get("/student", unknown).status_code, 401)

    def test_matching_names_do_not_merge_progress_in_web_requests(self):
        duplicate = enroll_account(self.issuer, "different-identity-same-name", "Avery Example", db_path=self.database)
        self.login(duplicate)
        self.assertEqual(self.submit("/modules/hardware_basics", {"completed": "1"}).status_code, 302)
        self.assertTrue(module_is_complete(duplicate["learner_id"], "hardware_basics", self.database))
        self.assertFalse(module_is_complete(self.first["learner_id"], "hardware_basics", self.database))

    def test_legitimate_scoring_completion_navigation_reload_and_app_recreation_keep_own_records(self):
        other_before = self.snapshot(self.second["learner_id"])
        self.login()
        result = self.submit("/pre-assessment", synthetic_beginner_responses())
        self.assertEqual(result.status_code, 302)
        self.assertIn(b"18%", self.get("/assessment-results").data)
        self.assertEqual(latest_assessment_result(self.first["learner_id"], "pre", self.database)["technical_score"], 18)
        self.assertEqual(self.submit("/modules/hardware_basics", {"completed": "1"}).status_code, 302)
        quiz = get_module_quiz("hardware_basics")
        result = self.submit("/modules/hardware_basics/quiz", {question["id"]: question["answer"] for question in quiz["questions"]})
        self.assertEqual(result.status_code, 200)
        self.assertIn(b"3 / 3 correct (100%)", result.data)
        self.assertEqual(self.submit("/checklists/day_1", {"completed_items": ["0", "2"]}).status_code, 302)
        self.assertEqual(self.submit("/training-path/beginner/activities/beginner_shadow_mentor", {"completed": "1"}).status_code, 302)
        scenario = get_scenario("classroom_no_display")
        self.assertEqual(self.submit("/scenarios/classroom_no_display/complete").status_code, 400)
        self.assertNotIn(scenario["activity_id"], activity_progress(self.first["learner_id"], self.database))
        for action in (*scenario["required_inspections"], scenario["resolution"]["action_id"]):
            self.assertEqual(self.submit("/scenarios/classroom_no_display/actions", {"action_id": action}).status_code, 302)
        self.assertNotIn(scenario["activity_id"], activity_progress(self.first["learner_id"], self.database))
        self.assertEqual(self.submit("/scenarios/classroom_no_display/complete").status_code, 302)
        post_answers = {
            question["id"]: (
                "Invented complete reflection for mentor review" if question["type"] == "free_response"
                else "5" if question["type"] == "rating" else question["correct_answer"]
            )
            for question in all_questions(load_assessment("post_assessment_v1"))
        }
        self.assertEqual(self.submit("/post-assessment", post_answers).status_code, 200)
        saved_post = latest_assessment_result(self.first["learner_id"], "post", self.database)
        self.assertEqual(saved_post["technical_score"], 100)
        self.assertEqual(saved_post["readiness_level"], "Strong Beginner Progress")
        self.assertEqual(saved_post["answers"], post_answers)
        saved = self.snapshot(self.first["learner_id"])
        for path in ("/learn", "/help", "/student", "/student"):
            self.assertEqual(self.get(path).status_code, 200)
        cookie = self.client.get_cookie(self.cookie_name, domain="launchpad.example").value
        recreated = create_app(self.config).test_client()
        recreated.set_cookie(self.cookie_name, cookie, domain="launchpad.example", secure=True)
        self.assertEqual(self.get("/student", recreated).status_code, 200)
        self.assertIn(b"3 / 3 correct (100%)", self.get("/modules/hardware_basics", recreated).data)
        self.assertIn(b"This troubleshooting lab is complete", self.get("/scenarios/classroom_no_display", recreated).data)
        self.assertEqual(self.snapshot(self.first["learner_id"]), saved)
        self.assertEqual(self.snapshot(self.second["learner_id"]), other_before)
        self.assertEqual(latest_module_quiz_result(self.first["learner_id"], "hardware_basics", self.database)["score"], 100)
        self.assertTrue(checklist_progress(self.first["learner_id"], "day_1", self.database)["2"])

    def test_valid_wrong_answers_keep_exact_score_without_marking_module_complete(self):
        self.login()
        quiz = get_module_quiz("hardware_basics")
        answers = {question["id"]: question["answer"] for question in quiz["questions"]}
        first_question = quiz["questions"][0]
        answers[first_question["id"]] = next(choice["value"] for choice in first_question["choices"] if choice["value"] != first_question["answer"])
        result = self.submit("/modules/hardware_basics/quiz", answers)
        self.assertEqual(result.status_code, 200)
        self.assertIn(b"2 / 3 correct (67%)", result.data)
        self.assertFalse(module_is_complete(self.first["learner_id"], "hardware_basics", self.database))
        self.assertIsNone(latest_module_quiz_result(self.second["learner_id"], "hardware_basics", self.database))
        self.assertEqual(latest_module_quiz_result(self.first["learner_id"], "hardware_basics", self.database)["score"], 67)

    def test_mentor_sees_only_assigned_list_and_detail_records(self):
        self.seed_private_records(self.first, "private-a-only")
        self.seed_private_records(self.second, "private-b-only")
        assign_mentor(self.mentor["id"], self.first["learner_id"], self.database)
        self.login(self.mentor)
        overview = self.get("/supervisor")
        self.assertEqual(overview.status_code, 200)
        self.assertIn(b"Avery Example", overview.data)
        self.assertNotIn(b"Blair Example", overview.data)
        self.assertNotIn(b"private-b-only", overview.data)
        self.assertIn(f"/supervisor/learners/{self.first['learner_id']}".encode(), overview.data)
        detail = self.get(f"/supervisor/learners/{self.first['learner_id']}")
        self.assertEqual(detail.status_code, 200)
        for record in (b"private-a-only assessment answer", b"private-a-only scenario draft", b"private-a-only help request"):
            self.assertIn(record, detail.data)
        self.assertNotIn(b"private-b-only", detail.data)
        denied = self.get(f"/supervisor/learners/{self.second['learner_id']}")
        missing = self.get("/supervisor/learners/999999")
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(denied.data, missing.data)
        self.assertNotIn(b"Blair Example", denied.data)

    def test_admin_role_alone_does_not_grant_global_reads(self):
        self.seed_private_records(self.first, "first-private")
        self.login(self.admin)
        overview = self.get("/supervisor")
        self.assertEqual(overview.status_code, 200)
        self.assertNotIn(b"Avery Example", overview.data)
        self.assertNotIn(b"Blair Example", overview.data)
        self.assertEqual(self.get(f"/supervisor/learners/{self.first['learner_id']}").status_code, 404)
        assign_mentor(self.admin["id"], self.first["learner_id"], self.database)
        self.assertIn(b"first-private", self.get(f"/supervisor/learners/{self.first['learner_id']}").data)
        self.assertEqual(self.get(f"/supervisor/learners/{self.second['learner_id']}").status_code, 404)

    def test_learners_cannot_open_mentor_views_and_staff_cannot_mutate_training(self):
        self.login()
        self.assertEqual(self.get("/supervisor").status_code, 403)
        self.assertEqual(self.get(f"/supervisor/learners/{self.first['learner_id']}").status_code, 403)
        before = self.snapshot()
        for account in (self.mentor, self.admin):
            self.login(account)
            for path in self.writes:
                with self.subTest(role=account["role"], path=path):
                    self.assertEqual(self.submit(path, {"completed": "1"}).status_code, 403)
            for personal in ("/student", "/pre-assessment", "/post-assessment", "/assessment-results"):
                self.assertEqual(self.get(personal).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_csrf_foreign_origin_and_duplicate_tokens_reject_mutation(self):
        self.login()
        token = self.token()
        before = self.snapshot()
        for data, headers in (
            ({"completed": "1"}, {}),
            ({"completed": "1", "csrf_token": "forged"}, {}),
            (MultiDict([("completed", "1"), ("csrf_token", token), ("csrf_token", token)]), {}),
            ({"completed": "1", "csrf_token": token}, {"Origin": "https://foreign.example"}),
            ({"completed": "1", "csrf_token": token}, {"Origin": "null"}),
        ):
            with self.subTest(headers=headers, data=list(data)):
                self.assertEqual(self.post("/modules/hardware_basics", data, headers=headers).status_code, 400)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.submit("/modules/hardware_basics", {"completed": "1"}, headers={"Origin": self.base_url}).status_code, 302)

    def test_logout_revokes_replayed_signed_cookie_and_requires_csrf(self):
        self.login()
        cookie = self.client.get_cookie(self.cookie_name, domain="launchpad.example").value
        handle = self.handle()
        self.assertEqual(self.post("/auth/logout").status_code, 400)
        self.assertIsNotNone(get_session_account(handle, self.database))
        self.assertEqual(self.submit("/auth/logout").status_code, 302)
        self.assertIsNone(get_session_account(handle, self.database))
        replay = self.app.test_client()
        replay.set_cookie(self.cookie_name, cookie, domain="launchpad.example", secure=True)
        self.assertEqual(self.get("/student", replay).status_code, 401)
        self.assertEqual(self.get("/student").status_code, 401)

    def test_disablement_and_grant_removal_take_effect_on_existing_browser_sessions(self):
        self.login()
        set_account_active(self.first["id"], False, self.database)
        self.assertEqual(self.get("/student").status_code, 401)
        with patch("launchpad.real_auth.complete_login", return_value={"issuer": self.issuer, "subject": self.first["subject"]}):
            self.assertEqual(self.get("/auth/callback?code=verified").status_code, 403)
        assign_mentor(self.mentor["id"], self.second["learner_id"], self.database)
        self.login(self.mentor)
        self.assertEqual(self.get(f"/supervisor/learners/{self.second['learner_id']}").status_code, 200)
        unassign_mentor(self.mentor["id"], self.second["learner_id"], self.database)
        self.assertEqual(self.get(f"/supervisor/learners/{self.second['learner_id']}").status_code, 401)
        self.login(self.mentor)
        self.assertEqual(self.get(f"/supervisor/learners/{self.second['learner_id']}").status_code, 404)

    def test_absolute_and_idle_expiry_reject_existing_signed_browser_cookie(self):
        for expiry in ("absolute", "idle"):
            with self.subTest(expiry=expiry):
                self.login()
                now = int(time.time())
                with closing(connect(self.database)) as db, db:
                    if expiry == "absolute":
                        db.execute("UPDATE auth_sessions SET created_at=?, last_seen_at=?, expires_at=? WHERE revoked_at IS NULL", (now - 3600, now - 1, now))
                    else:
                        db.execute("UPDATE auth_sessions SET created_at=?, last_seen_at=?, expires_at=? WHERE revoked_at IS NULL", (now - 3600, now - 1800, now + 3600))
                before = self.snapshot()
                self.assertEqual(self.get("/student").status_code, 401)
                self.assertEqual(self.post("/modules/hardware_basics", {"completed": "1"}).status_code, 401)
                self.assertEqual(self.snapshot(), before)

    def test_session_from_a_different_configured_issuer_is_rejected(self):
        foreign = enroll_account("https://other-tenant.example", "same-subject", "Other Tenant Learner", db_path=self.database)
        token = create_auth_session(foreign["id"], self.database)
        with self.client.session_transaction(base_url=self.base_url) as browser_session:
            browser_session["auth_session"] = token
        self.assertEqual(self.get("/student").status_code, 401)
        self.assertIsNone(get_session_account(token, self.database))

    def test_login_requires_csrf_and_starting_login_revokes_prior_account_session(self):
        page = self.get("/auth/login")
        self.assertEqual(page.status_code, 200)
        token_match = re.search(rb'name="csrf_token" value="([^"]+)"', page.data)
        self.assertIsNotNone(token_match)
        with patch("launchpad.real_auth.begin_login") as begin:
            self.assertEqual(self.post("/auth/login").status_code, 400)
            begin.assert_not_called()
        self.login()
        old_handle = self.handle()
        with patch("launchpad.real_auth.begin_login", side_effect=OIDCLoginError("not logged")):
            response = self.submit("/auth/login")
        self.assertEqual(response.status_code, 503)
        self.assertIsNone(get_session_account(old_handle, self.database))
        self.assertEqual(self.get("/student").status_code, 401)

    def test_callback_failure_unknown_account_and_opaque_cookie_do_not_expose_identity_tokens(self):
        with patch("launchpad.real_auth.complete_login", side_effect=OIDCLoginError("private-provider-diagnostic")):
            response = self.get("/auth/callback?code=private-code&state=invalid")
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(b"private", response.data)
        with patch("launchpad.real_auth.complete_login", return_value={"issuer": self.issuer, "subject": self.first["subject"]}):
            response = self.get("/auth/callback?state=verified&code=private-code")
        self.assertEqual(response.status_code, 302)
        cookie_header = response.headers["Set-Cookie"]
        for flag in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/"):
            self.assertIn(flag, cookie_header)
        self.assertNotIn("Domain=", cookie_header)
        cookie = self.client.get_cookie(self.cookie_name, domain="launchpad.example").value
        decoded = self.app.session_interface.get_signing_serializer(self.app).loads(cookie)
        self.assertEqual(set(decoded), {"auth_session"})
        for private in (self.issuer, self.first["subject"], "Avery Example", "private-code"):
            self.assertNotIn(private, str(decoded))

    def test_oidc_callback_keeps_query_referrers_private_on_success_and_failure(self):
        self.assertEqual(self.get("/auth/login").headers["Referrer-Policy"], "same-origin")
        for outcome, expected in (("verified", 302), ("invalid", 401), ("unenrolled", 403)):
            with self.subTest(outcome=outcome):
                client = self.app.test_client()
                verified = {"issuer": self.issuer, "subject": self.first["subject"] if outcome == "verified" else "not-enrolled"}
                with patch("launchpad.real_auth.complete_login", return_value=verified,
                           side_effect=OIDCLoginError("synthetic rejection") if outcome == "invalid" else None):
                    response = self.get("/auth/callback?code=synthetic-code&state=synthetic-state", client)
                self.assertEqual(response.status_code, expected)
                self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertNotIn("synthetic-code", response.text)
                self.assertNotIn("synthetic-state", response.text)

    def test_invalid_required_submissions_and_storage_errors_never_claim_a_save(self):
        self.login()
        before = self.snapshot()
        for path in ("/pre-assessment", "/post-assessment", "/modules/hardware_basics/quiz", "/stuck", "/scenarios/ticket_term_unknown"):
            with self.subTest(path=path):
                self.assertEqual(self.submit(path).status_code, 400)
        self.assertEqual(self.snapshot(), before)
        with patch("launchpad.web.mark_module_complete", side_effect=sqlite3.OperationalError("private-record-diagnostic")):
            with self.assertLogs(self.app.logger, level="ERROR") as observed:
                response = self.submit("/modules/hardware_basics", {"completed": "1"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"private-record-diagnostic", response.data)
        self.assertNotIn("private-record-diagnostic", " ".join(observed.output))
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
