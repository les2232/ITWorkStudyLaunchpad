"""Persistent AD login throttling uses disposable storage and synthetic names."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from launchpad.ad_state import (
    ADStateError, MAX_ROWS, initialize_ad_state, reserve_login_attempt,
    validate_ad_state,
)
from launchpad.real_data import initialize_real_database


class ADStateTests(unittest.TestCase):
    secret = "synthetic-admission-key-never-used-in-production"

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.database = self.root / "ad-security.sqlite"
        initialize_ad_state(self.database)

    def attempt(self, key="invented.user", now=1000):
        return reserve_login_attempt(self.database, key, self.secret, now)

    def test_initialization_is_explicit_private_and_never_adopts_an_existing_file(self):
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)
        before = self.database.read_bytes()
        with self.assertRaises(ADStateError):
            initialize_ad_state(self.database)
        self.assertEqual(self.database.read_bytes(), before)
        real = self.root / "learners.sqlite"
        initialize_real_database(real)
        original = real.read_bytes()
        for operation in (initialize_ad_state, validate_ad_state):
            with self.assertRaises(ADStateError):
                operation(real)
        self.assertEqual(real.read_bytes(), original)

    def test_startup_validation_is_read_only_and_does_not_create_missing_storage(self):
        self.assertTrue(self.attempt())
        before = hashlib.sha256(self.database.read_bytes()).digest()
        validate_ad_state(self.database)
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).digest(), before)
        missing = self.root / "missing.sqlite"
        for operation in (validate_ad_state, lambda path: reserve_login_attempt(path, "invented", self.secret)):
            with self.assertRaises(ADStateError):
                operation(missing)
        self.assertFalse(missing.exists())

    def test_symlinks_prototype_sidecars_and_nonprivate_paths_are_refused(self):
        linked = self.root / "link.sqlite"
        linked.symlink_to(self.database)
        for operation in (initialize_ad_state, validate_ad_state):
            with self.assertRaises(ADStateError):
                operation(linked)
        with patch("launchpad.ad_state.DEFAULT_DB_PATH", self.database):
            with self.assertRaises(ADStateError):
                validate_ad_state(self.database)
        target = self.root / "sidecar.sqlite"
        sidecar = Path(f"{target}-wal")
        sidecar.write_bytes(b"preserve existing artifact")
        with self.assertRaises(ADStateError):
            initialize_ad_state(target)
        self.assertFalse(target.exists())
        self.assertEqual(sidecar.read_bytes(), b"preserve existing artifact")
        public = self.root / "public"
        public.mkdir(mode=0o755)
        with self.assertRaises(ADStateError):
            initialize_ad_state(public / "state.sqlite")
        self.database.chmod(0o644)
        with self.assertRaises(ADStateError):
            validate_ad_state(self.database)

    def test_per_account_sliding_window_counts_attempts_without_success_reset(self):
        self.assertEqual([self.attempt(now=1000 + offset) for offset in range(5)], [True] * 5)
        self.assertFalse(self.attempt(now=1005))
        self.assertFalse(self.attempt(now=1299))
        self.assertTrue(self.attempt(now=1300))
        self.assertFalse(self.attempt(now=1300))
        self.assertTrue(self.attempt(key="another.invented.user", now=1300))

    def test_global_window_limits_distributed_usernames_without_trusting_client_ips(self):
        self.assertTrue(all(self.attempt(f"invented-{number}") for number in range(50)))
        self.assertFalse(self.attempt("another-invented-name", now=1059))
        self.assertTrue(self.attempt("another-invented-name", now=1060))

    def test_concurrent_workers_cannot_overreserve(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.attempt(), range(40)))
        self.assertEqual(results.count(True), 5)
        self.assertEqual(results.count(False), 35)

    def test_reservations_survive_a_new_process(self):
        for _ in range(5):
            self.assertTrue(self.attempt())
        script = (
            "import sys; from launchpad.ad_state import reserve_login_attempt; "
            "print(reserve_login_attempt(sys.argv[1], 'invented.user', sys.argv[2], 1001))"
        )
        result = subprocess.run([sys.executable, "-B", "-c", script, str(self.database), self.secret],
                                capture_output=True, text=True, check=True, timeout=10)
        self.assertEqual(result.stdout.strip(), "False")

    def test_account_names_are_not_stored_and_expired_state_stays_bounded(self):
        for window in range(15):
            for offset in range(50):
                self.assertTrue(self.attempt(f"invented-{window}-{offset}", now=1000 + window * 60))
        with sqlite3.connect(self.database) as db:
            rows = db.execute("SELECT account_digest, attempted_at FROM login_attempts").fetchall()
        self.assertEqual(len(rows), 250)
        self.assertLess(len(rows), MAX_ROWS)
        self.assertTrue(all(len(digest) == 64 for digest, _ in rows))
        self.assertNotIn(b"invented", self.database.read_bytes())
        self.assertNotIn(self.secret.encode(), self.database.read_bytes())
        validate_ad_state(self.database)

    def test_backward_clock_remains_restrictive(self):
        for _ in range(5):
            self.assertTrue(self.attempt(now=1000))
        self.assertFalse(self.attempt(now=900))

    def test_schema_changes_fail_startup_without_repairing_the_file(self):
        with sqlite3.connect(self.database) as db:
            db.execute("CREATE TABLE unexpected(id INTEGER)")
        before = self.database.read_bytes()
        with self.assertRaises(ADStateError):
            validate_ad_state(self.database)
        self.assertEqual(self.database.read_bytes(), before)

    def test_locked_or_unreadable_state_denies_admission_with_generic_error(self):
        with sqlite3.connect(self.database) as blocker:
            blocker.execute("BEGIN EXCLUSIVE")
            with patch("launchpad.ad_state.BUSY_TIMEOUT_SECONDS", 0.01):
                with self.assertRaisesRegex(ADStateError, "^AD admission is unavailable\\.$"):
                    self.attempt()
        with patch("launchpad.ad_state._connect", side_effect=sqlite3.OperationalError("private detail")):
            with self.assertRaises(ADStateError) as error:
                self.attempt()
        self.assertNotIn("private detail", str(error.exception))


if __name__ == "__main__":
    unittest.main()
