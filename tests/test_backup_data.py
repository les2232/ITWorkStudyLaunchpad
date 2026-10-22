import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from launchpad.demo import DemoDataError, prepare_demo_database, validate_demo_database
from launchpad.scenarios import list_scenarios
from launchpad.storage import mark_module_complete, module_is_complete, save_scenario_attempt, recent_scenario_attempts
from scripts.backup_data import copy_snapshot


class BackupDataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.root = Path(self.directory.name)
        self.source = self.root / "source.sqlite"
        prepare_demo_database(self.source)

    def tearDown(self):
        self.directory.cleanup()

    def test_snapshot_and_restore_preserve_progress_without_changing_source(self):
        mark_module_complete(1, "hardware_basics", True, self.source)
        scenario = next(item for item in list_scenarios() if not item.get("type") == "guided")
        save_scenario_attempt(1, scenario["id"], scenario["title"], "Invented restore-drill answer.", self.source)
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        snapshot = copy_snapshot(self.source, self.root / "backup.sqlite")
        restored = copy_snapshot(snapshot, self.root / "restored.sqlite")
        self.assertTrue(module_is_complete(1, "hardware_basics", restored))
        self.assertEqual(recent_scenario_attempts(1, restored)[0]["student_response"], "Invented restore-drill answer.")
        self.assertEqual(before, hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
        self.assertEqual(restored.stat().st_mode & 0o777, 0o600)
        self.assertEqual(validate_demo_database(self.source)["session_generation"],
                         validate_demo_database(restored)["session_generation"])

    def test_snapshot_includes_committed_wal_while_connection_stays_open(self):
        with sqlite3.connect(self.source) as active:
            active.execute("PRAGMA journal_mode=WAL")
            active.execute("PRAGMA wal_autocheckpoint=0")
            mark_module_complete(1, "hardware_basics", True, self.source)
            self.assertTrue(Path(f"{self.source}-wal").exists())
            target = copy_snapshot(self.source, self.root / "wal-backup.sqlite")
            self.assertTrue(module_is_complete(1, "hardware_basics", target))
        active.close()

    def test_existing_destination_and_source_are_never_overwritten(self):
        target = self.root / "existing.sqlite"
        target.write_bytes(b"preserve this existing artifact")
        for destination in (target, self.source):
            with self.subTest(destination=destination.name):
                before = destination.read_bytes()
                with self.assertRaises(DemoDataError):
                    copy_snapshot(self.source, destination)
                self.assertEqual(destination.read_bytes(), before)

    def test_symlinks_and_destination_sidecars_are_refused(self):
        source_link = self.root / "source-link.sqlite"
        source_link.symlink_to(self.source)
        with self.assertRaises(DemoDataError):
            copy_snapshot(source_link, self.root / "unused.sqlite")
        target = self.root / "target.sqlite"
        target.symlink_to(self.source)
        with self.assertRaises(DemoDataError):
            copy_snapshot(self.source, target)
        sidecar_target = self.root / "sidecar.sqlite"
        sidecar = Path(f"{sidecar_target}-journal")
        sidecar.write_bytes(b"preserve")
        with self.assertRaises(DemoDataError):
            copy_snapshot(self.source, sidecar_target)
        self.assertEqual(sidecar.read_bytes(), b"preserve")
        self.assertFalse(sidecar_target.exists())

    def test_missing_or_unrecognized_source_does_not_leave_a_snapshot(self):
        target = self.root / "invalid.sqlite"
        with self.assertRaises(DemoDataError):
            copy_snapshot(self.root / "missing.sqlite", target)
        self.assertFalse((self.root / "missing.sqlite").exists())
        with sqlite3.connect(self.source) as database:
            database.execute("CREATE TABLE unknown_records (id INTEGER)")
        with self.assertRaises(DemoDataError):
            copy_snapshot(self.source, target)
        self.assertFalse(target.exists())
        with sqlite3.connect(self.source) as database:
            self.assertIsNotNone(database.execute(
                "SELECT name FROM sqlite_master WHERE name='unknown_records'"
            ).fetchone())

    def test_regular_database_without_synthetic_marker_is_refused(self):
        unrelated = self.root / "unrelated.sqlite"
        with sqlite3.connect(unrelated) as database:
            database.execute("CREATE TABLE unrelated (id INTEGER)")
        before = unrelated.read_bytes()
        with self.assertRaises(DemoDataError):
            copy_snapshot(unrelated, self.root / "refused.sqlite")
        self.assertEqual(unrelated.read_bytes(), before)
        self.assertFalse((self.root / "refused.sqlite").exists())

    def test_snapshot_refuses_non_tmp_target_without_touching_it(self):
        with self.assertRaises(DemoDataError):
            copy_snapshot(self.source, Path.cwd() / "must-not-create.sqlite")
        self.assertFalse((Path.cwd() / "must-not-create.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
