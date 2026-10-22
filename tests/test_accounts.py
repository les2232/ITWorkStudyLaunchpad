"""Account, assignment and session controls use only disposable learner data."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from launchpad.accounts import (
    AccountError, assigned_learner_ids, assign_mentor, bind_existing_learner,
    create_auth_session, enroll_account, get_account, get_account_for_identity,
    get_session_account, init_accounts_schema, revoke_all_sessions,
    revoke_auth_session, set_account_active, unassign_mentor, validate_accounts_database,
)
from launchpad.demo import prepare_demo_database
from launchpad.storage import (
    connect, create_or_find_student, init_db, mark_module_complete, module_is_complete,
)


class AccountsTests(unittest.TestCase):
    issuer = "https://identity.example/approved-tenant"

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "real-users.sqlite"
        init_db(self.database)
        init_accounts_schema(self.database)

    def enroll(self, subject="learner-one", name="Example Learner", role="learner"):
        return enroll_account(self.issuer, subject, name, role, db_path=self.database)

    def query(self, sql, params=()):
        with closing(connect(self.database)) as db:
            return [dict(row) for row in db.execute(sql, params)]

    def test_schema_is_idempotent_but_missing_and_demo_databases_are_refused(self):
        account = self.enroll()
        init_accounts_schema(self.database)
        self.assertEqual(get_account(account["id"], self.database), account)
        missing = Path(self.directory.name) / "missing.sqlite"
        with self.assertRaises(AccountError):
            init_accounts_schema(missing)
        self.assertFalse(missing.exists())
        demo = Path(self.directory.name) / "synthetic.sqlite"
        prepare_demo_database(demo)
        original = demo.read_bytes()
        with self.assertRaises(AccountError):
            init_accounts_schema(demo, allow_existing_records=True)
        self.assertEqual(demo.read_bytes(), original)

    def test_canonical_path_guard_refuses_symlinks_and_prototype_path_without_opening_it(self):
        alias = Path(self.directory.name) / "alias.sqlite"
        alias.symlink_to(self.database)
        with self.assertRaises(AccountError):
            init_accounts_schema(alias)
        with patch("launchpad.accounts.DEFAULT_DB_PATH", self.database):
            with self.assertRaises(AccountError):
                init_accounts_schema(self.database)

    def test_same_names_never_share_records_and_identity_matching_is_exact(self):
        first = self.enroll("case-sensitive", "Same Name")
        second = self.enroll("Case-sensitive", "Same Name")
        other_issuer = enroll_account("https://other.example", "case-sensitive", "Same Name", db_path=self.database)
        self.assertEqual(len({first["learner_id"], second["learner_id"], other_issuer["learner_id"]}), 3)
        mark_module_complete(first["learner_id"], "hardware_basics", True, self.database)
        self.assertFalse(module_is_complete(second["learner_id"], "hardware_basics", self.database))
        self.assertEqual(get_account_for_identity(self.issuer, "case-sensitive", self.database), first)
        self.assertIsNone(get_account_for_identity(self.issuer, "unknown", self.database))
        self.assertEqual(len(self.query("SELECT * FROM accounts")), 3)

    def test_duplicate_enrollment_rolls_back_new_learner_and_audit_rows(self):
        first = self.enroll()
        before = {table: self.query(f"SELECT * FROM {table}") for table in ("students", "accounts", "access_audit")}
        with self.assertRaises(AccountError):
            self.enroll(name="Different Display Name")
        self.assertEqual({table: self.query(f"SELECT * FROM {table}") for table in before}, before)
        self.assertEqual(get_account(first["id"], self.database), first)

    def test_invalid_identity_and_role_never_create_a_learner(self):
        for issuer, subject, role in (
            ("http://identity.example", "sub", "learner"),
            ("https://identity.example?tenant=wrong", "sub", "learner"),
            ("https://user:password@identity.example", "sub", "learner"),
            ("https://identity.example", "", "learner"),
            ("https://identity.example", "sub\nother", "learner"),
            (self.issuer, "subject", "owner"),
        ):
            with self.subTest(issuer=issuer, role=role), self.assertRaises(AccountError):
                enroll_account(issuer, subject, "Example", role, db_path=self.database)
        self.assertEqual(self.query("SELECT * FROM students"), [])

    def test_existing_records_require_reviewed_copy_then_explicit_id_mapping(self):
        legacy = Path(self.directory.name) / "reviewed-copy.sqlite"
        init_db(legacy)
        old = create_or_find_student("Same Name", legacy)
        mark_module_complete(old["id"], "hardware_basics", True, legacy)
        before = legacy.read_bytes()
        with self.assertRaises(AccountError):
            init_accounts_schema(legacy)
        self.assertEqual(before, legacy.read_bytes())
        init_accounts_schema(legacy, allow_existing_records=True)
        self.assertIsNone(get_account_for_identity(self.issuer, "legacy", legacy))
        new = enroll_account(self.issuer, "new", "Same Name", db_path=legacy)
        self.assertNotEqual(new["learner_id"], old["id"])
        with self.assertRaises(AccountError):
            bind_existing_learner(self.issuer, "legacy", old["id"], db_path=legacy)
        mapped = bind_existing_learner(self.issuer, "legacy", old["id"], db_path=legacy, migration_reviewed=True)
        self.assertEqual(mapped["learner_id"], old["id"])
        self.assertTrue(module_is_complete(old["id"], "hardware_basics", legacy))
        with self.assertRaises(AccountError):
            bind_existing_learner(self.issuer, "another", old["id"], db_path=legacy, migration_reviewed=True)
        with self.assertRaises(AccountError):
            bind_existing_learner(self.issuer, "missing", 99999, db_path=legacy, migration_reviewed=True)
        validate_accounts_database(legacy)

    def test_staff_have_no_learner_binding_or_implicit_progress_access(self):
        learner = self.enroll()
        for role in ("mentor", "admin"):
            with self.subTest(role=role):
                staff = self.enroll(role, role=role)
                self.assertIsNone(staff["learner_id"])
                self.assertEqual(assigned_learner_ids(staff["id"], self.database), [])
                assign_mentor(staff["id"], learner["learner_id"], self.database)
                self.assertEqual(assigned_learner_ids(staff["id"], self.database), [learner["learner_id"]])
        self.assertEqual(len(self.query("SELECT * FROM students")), 1)

    def test_learner_cannot_receive_mentor_grants_and_unmapped_records_are_not_grantable(self):
        first = self.enroll()
        second = self.enroll("second")
        with self.assertRaises(AccountError):
            assign_mentor(first["id"], second["learner_id"], self.database)
        mentor = self.enroll("mentor", role="mentor")
        legacy = create_or_find_student("Unmapped Legacy", self.database)
        with self.assertRaises(AccountError):
            assign_mentor(mentor["id"], legacy["id"], self.database)
        self.assertEqual(assigned_learner_ids(first["id"], self.database), [])
        self.assertEqual(assigned_learner_ids(mentor["id"], self.database), [])

    def test_assignment_removal_revokes_sessions_and_only_removes_the_selected_grant(self):
        first = self.enroll()
        second = self.enroll("second")
        mentor = self.enroll("mentor", role="mentor")
        assign_mentor(mentor["id"], first["learner_id"], self.database)
        assign_mentor(mentor["id"], first["learner_id"], self.database)
        assign_mentor(mentor["id"], second["learner_id"], self.database)
        token = create_auth_session(mentor["id"], self.database)
        unassign_mentor(mentor["id"], first["learner_id"], self.database)
        self.assertIsNone(get_session_account(token, self.database))
        self.assertEqual(assigned_learner_ids(mentor["id"], self.database), [second["learner_id"]])

    def test_sessions_store_only_digests_and_survive_new_application_connections(self):
        account = self.enroll()
        token = create_auth_session(account["id"], self.database)
        row = self.query("SELECT * FROM auth_sessions")[0]
        self.assertEqual(row["token_digest"], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, str(row))
        self.assertEqual(get_session_account(token, self.database), account)
        self.assertEqual(get_session_account(token, str(self.database)), account)
        for invalid in (None, "", "invalid", "' OR 1=1--", "a" * 43):
            self.assertIsNone(get_session_account(invalid, self.database))

    def test_idle_expiration_and_absolute_expiration_are_server_enforced(self):
        account = self.enroll()
        with patch("launchpad.accounts.time.time", return_value=1000):
            idle_token = create_auth_session(account["id"], self.database)
            absolute_token = create_auth_session(account["id"], self.database, lifetime_seconds=120, idle_timeout_seconds=90)
        with patch("launchpad.accounts.time.time", return_value=1059):
            self.assertEqual(get_session_account(absolute_token, self.database), account)
        self.assertEqual(self.query("SELECT last_seen_at FROM auth_sessions WHERE token_digest=?", (hashlib.sha256(absolute_token.encode()).hexdigest(),))[0]["last_seen_at"], 1000)
        with patch("launchpad.accounts.time.time", return_value=1060):
            self.assertEqual(get_session_account(absolute_token, self.database), account)
        with patch("launchpad.accounts.time.time", return_value=1120):
            self.assertIsNone(get_session_account(absolute_token, self.database))
        with patch("launchpad.accounts.time.time", return_value=2800):
            self.assertIsNone(get_session_account(idle_token, self.database))

    def test_logout_revokes_replayed_token_without_affecting_other_sessions(self):
        account = self.enroll()
        first = create_auth_session(account["id"], self.database)
        other = create_auth_session(account["id"], self.database)
        revoke_auth_session(first, self.database)
        revoke_auth_session(first, self.database)
        self.assertIsNone(get_session_account(first, self.database))
        self.assertEqual(get_session_account(other, self.database), account)

    def test_disabling_account_blocks_existing_and_new_sessions_even_after_reenable(self):
        account = self.enroll()
        token = create_auth_session(account["id"], self.database)
        set_account_active(account["id"], False, self.database)
        self.assertIsNone(get_session_account(token, self.database))
        with self.assertRaises(AccountError):
            create_auth_session(account["id"], self.database)
        set_account_active(account["id"], True, self.database)
        self.assertIsNone(get_session_account(token, self.database))
        self.assertIsNotNone(get_session_account(create_auth_session(account["id"], self.database), self.database))

    def test_active_status_is_rechecked_without_relying_only_on_revocation(self):
        account = self.enroll()
        token = create_auth_session(account["id"], self.database)
        with closing(connect(self.database)) as db, db:
            db.execute("UPDATE accounts SET active=0 WHERE id=?", (account["id"],))
        self.assertIsNone(get_session_account(token, self.database))

    def test_restore_revocation_can_target_an_account_or_everyone(self):
        first = self.enroll()
        second = self.enroll("second")
        first_token = create_auth_session(first["id"], self.database)
        second_token = create_auth_session(second["id"], self.database)
        revoke_all_sessions(self.database, account_id=first["id"])
        self.assertIsNone(get_session_account(first_token, self.database))
        self.assertIsNotNone(get_session_account(second_token, self.database))
        revoke_all_sessions(self.database)
        self.assertIsNone(get_session_account(second_token, self.database))

    def test_audit_contains_ids_and_events_but_no_identity_labels_tokens_or_answers(self):
        learner = self.enroll("private-subject", "Private Display Name")
        token = create_auth_session(learner["id"], self.database)
        revoke_auth_session(token, self.database)
        audit = self.query("SELECT * FROM access_audit")
        self.assertEqual([row["event"] for row in audit], ["account_enrolled", "session_created", "session_revoked"])
        for sensitive in (self.issuer, "private-subject", "Private Display Name", token):
            self.assertNotIn(sensitive, str(audit))
        self.assertTrue(all(row["account_id"] == learner["id"] for row in audit))

    def test_read_only_validation_preserves_database_and_rejects_broken_constraints(self):
        self.enroll()
        before = self.database.read_bytes()
        validate_accounts_database(self.database)
        self.assertEqual(self.database.read_bytes(), before)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("UPDATE accounts SET learner_id=999999 WHERE role='learner'")
        with self.assertRaises(AccountError):
            validate_accounts_database(self.database)


if __name__ == "__main__":
    unittest.main()
