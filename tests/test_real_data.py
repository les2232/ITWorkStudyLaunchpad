import contextlib
import hashlib
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from launchpad.accounts import (
    assigned_learner_ids, assign_mentor, create_auth_session, enroll_account,
    get_account_for_identity, get_session_account,
)
from launchpad.demo import prepare_demo_database
from launchpad.real_data import (
    REAL_SCHEMA_VERSION, RealDataError, copy_real_snapshot, initialize_real_database, validate_real_database,
)
from launchpad.storage import (
    init_db, mark_module_complete, module_is_complete,
    save_scenario_attempt, recent_scenario_attempts,
)
from scripts.manage_real_data import main


class RealDataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.root = Path(self.directory.name)
        self.database = self.root / "real.sqlite"
        initialize_real_database(self.database)

    def tearDown(self):
        self.directory.cleanup()

    def enroll(self, subject="learner-a", role="learner"):
        return enroll_account("https://identity.example.invalid", subject, "Invented learner", role, db_path=self.database)

    def test_new_dataset_empty_private_and_existing_file_never_adopted(self):
        with sqlite3.connect(self.database) as db:
            for table in ("students", "accounts", "module_progress", "assessment_results"):
                self.assertEqual(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0)
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)
        before = self.database.read_bytes()
        with self.assertRaises(RealDataError):
            initialize_real_database(self.database)
        self.assertEqual(self.database.read_bytes(), before)
        legacy = self.root / "legacy.sqlite"
        init_db(legacy)
        legacy_before = legacy.read_bytes()
        with self.assertRaises(RealDataError):
            initialize_real_database(legacy)
        self.assertEqual(legacy.read_bytes(), legacy_before)

    def test_validation_read_only_and_missing_database_not_created(self):
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        marker = validate_real_database(self.database)
        self.assertEqual(marker["schema_version"], REAL_SCHEMA_VERSION)
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), before)
        missing = self.root / "missing.sqlite"
        with self.assertRaises(RealDataError):
            validate_real_database(missing)
        self.assertFalse(missing.exists())

    def test_new_paths_reject_symlinks_sidecars_and_prototype_default(self):
        linked = self.root / "link.sqlite"
        linked.symlink_to(self.database)
        target = self.root / "sidecar.sqlite"
        sidecar = Path(f"{target}-wal")
        sidecar.write_bytes(b"preserve sidecar")
        for path in (linked, target):
            with self.subTest(path=path.name), self.assertRaises(RealDataError):
                initialize_real_database(path)
        self.assertEqual(sidecar.read_bytes(), b"preserve sidecar")
        with patch("launchpad.real_data.DEFAULT_DB_PATH", self.root / "prototype.sqlite"):
            with self.assertRaises(RealDataError):
                initialize_real_database(self.root / "prototype.sqlite")
        self.assertFalse((self.root / "prototype.sqlite").exists())

    def test_synthetic_and_unrecognized_schema_refused_without_copy(self):
        synthetic = self.root / "synthetic.sqlite"
        prepare_demo_database(synthetic)
        before = synthetic.read_bytes()
        with self.assertRaises(RealDataError):
            copy_real_snapshot(synthetic, self.root / "must-not-create.sqlite")
        self.assertEqual(synthetic.read_bytes(), before)
        self.assertFalse((self.root / "must-not-create.sqlite").exists())
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE unexpected (id INTEGER)")
        with self.assertRaises(RealDataError):
            validate_real_database(self.database)

    def test_snapshot_restore_preserves_accounts_grants_progress_and_revokes_only_restored_sessions(self):
        learner = self.enroll()
        mentor = self.enroll("mentor-a", "mentor")
        assign_mentor(mentor["id"], learner["learner_id"], self.database)
        token = create_auth_session(learner["id"], self.database)
        mark_module_complete(learner["learner_id"], "hardware_basics", True, self.database)
        save_scenario_attempt(learner["learner_id"], "example", "Practice", "Invented draft retained exactly.", self.database)
        before = self.database.read_bytes()
        backup = copy_real_snapshot(self.database, self.root / "backup.sqlite")
        self.assertEqual(self.database.read_bytes(), before)
        restored = copy_real_snapshot(backup, self.root / "restored.sqlite", restore=True)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(validate_real_database(backup), validate_real_database(restored))
        self.assertTrue(module_is_complete(learner["learner_id"], "hardware_basics", restored))
        self.assertEqual(recent_scenario_attempts(learner["learner_id"], restored)[0]["student_response"], "Invented draft retained exactly.")
        self.assertEqual(assigned_learner_ids(mentor["id"], restored), [learner["learner_id"]])
        self.assertIsNone(get_session_account(token, restored))
        self.assertEqual(get_session_account(token, self.database)["id"], learner["id"])
        self.assertEqual(get_session_account(token, backup)["id"], learner["id"])
        self.assertEqual(get_account_for_identity("https://identity.example.invalid", "learner-a", restored)["learner_id"], learner["learner_id"])
        new_token = create_auth_session(learner["id"], restored)
        self.assertIsNotNone(get_session_account(new_token, restored))
        mark_module_complete(learner["learner_id"], "hardware_basics", False, restored)
        self.assertFalse(module_is_complete(learner["learner_id"], "hardware_basics", restored))
        self.assertTrue(module_is_complete(learner["learner_id"], "hardware_basics", self.database))
        self.assertEqual(restored.stat().st_mode & 0o777, 0o600)

    def test_live_wal_snapshot_includes_committed_progress(self):
        learner = self.enroll()
        with sqlite3.connect(self.database) as active:
            active.execute("PRAGMA journal_mode=WAL")
            active.execute("PRAGMA wal_autocheckpoint=0")
            mark_module_complete(learner["learner_id"], "hardware_basics", True, self.database)
            self.assertTrue(Path(f"{self.database}-wal").exists())
            backup = copy_real_snapshot(self.database, self.root / "wal-backup.sqlite")
            self.assertTrue(module_is_complete(learner["learner_id"], "hardware_basics", backup))
        active.close()

    def test_existing_destination_and_sidecar_never_replaced(self):
        existing = self.root / "existing.sqlite"
        existing.write_bytes(b"existing artifact")
        for target in (existing, self.database):
            before = target.read_bytes()
            with self.assertRaises(RealDataError):
                copy_real_snapshot(self.database, target, restore=True)
            self.assertEqual(target.read_bytes(), before)
        other = self.root / "other.sqlite"
        Path(f"{other}-journal").write_bytes(b"journal")
        with self.assertRaises(RealDataError):
            copy_real_snapshot(self.database, other)
        self.assertFalse(other.exists())

    def test_restore_failure_leaves_source_and_existing_artifacts_untouched(self):
        source_before = self.database.read_bytes()
        target = self.root / "failed.sqlite"
        with patch("launchpad.real_data.revoke_all_sessions", side_effect=ValueError("private error")):
            with self.assertRaises(RealDataError):
                copy_real_snapshot(self.database, target, restore=True)
        self.assertEqual(self.database.read_bytes(), source_before)
        self.assertFalse(target.exists())

    def test_cli_enroll_prompts_for_identity_and_does_not_print_it(self):
        output = io.StringIO()
        with patch("scripts.manage_real_data.getpass", side_effect=["private-test-subject", "private-test-label"]), contextlib.redirect_stdout(output):
            status = main(["enroll", "--db", str(self.database), "--issuer", "https://identity.example.invalid"])
        self.assertEqual(status, 0)
        self.assertNotIn("private-test-subject", output.getvalue())
        self.assertNotIn("private-test-label", output.getvalue())
        self.assertIsNotNone(get_account_for_identity("https://identity.example.invalid", "private-test-subject", self.database))

    def test_cli_binding_requires_review_before_prompt_or_write(self):
        before = self.database.read_bytes()
        with patch("scripts.manage_real_data.getpass") as prompt, contextlib.redirect_stderr(io.StringIO()):
            status = main(["bind-existing", "--db", str(self.database), "--issuer", "https://identity.example.invalid", "--learner-id", "1"])
        self.assertEqual(status, 2)
        prompt.assert_not_called()
        self.assertEqual(self.database.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
