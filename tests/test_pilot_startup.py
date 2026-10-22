import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash
from launchpad.demo import DemoDataError, prepare_demo_database
from launchpad.storage import mark_module_complete, module_is_complete
from scripts.start_pilot import prepare_runtime


class PilotStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash("synthetic-invitation-only-password")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.root = Path(self.directory.name)
        self.database = self.root / "pilot.sqlite"
        self.env = {
            "LAUNCHPAD_PILOT_MODE": "1",
            "LAUNCHPAD_DEMO_MODE": "1",
            "LAUNCHPAD_SECRET_KEY": "synthetic-test-signing-secret-long-enough",
            "LAUNCHPAD_PILOT_USERNAME": "facilitator",
            "LAUNCHPAD_TRUSTED_HOSTS": "localhost",
            "LAUNCHPAD_PILOT_PASSWORD_HASH": self.password_hash,
            "LAUNCHPAD_DATA_DIR": str(self.root),
            "LAUNCHPAD_DB_PATH": str(self.database),
        }

    def tearDown(self):
        self.directory.cleanup()

    def test_first_start_requires_explicit_bootstrap_and_retains_saved_work(self):
        with self.assertRaisesRegex(DemoDataError, "first startup"):
            prepare_runtime(self.env)
        self.assertFalse(self.database.exists())
        self.env["LAUNCHPAD_INITIALIZE_DEMO"] = "1"
        self.assertEqual(prepare_runtime(self.env), self.database)
        mark_module_complete(1, "hardware_basics", True, self.database)
        self.env["LAUNCHPAD_INITIALIZE_DEMO"] = "0"
        prepare_runtime(self.env)
        self.assertTrue(module_is_complete(1, "hardware_basics", self.database))

    def test_missing_initialized_database_is_not_silently_recreated(self):
        self.env["LAUNCHPAD_INITIALIZE_DEMO"] = "1"
        prepare_runtime(self.env)
        quarantine = self.root / "preserved.sqlite"
        self.database.rename(quarantine)
        with self.assertRaisesRegex(DemoDataError, "restore rather than reseed"):
            prepare_runtime(self.env)
        self.assertTrue(quarantine.exists())
        self.assertFalse(self.database.exists())

    def test_render_requires_actual_mount_before_initialization(self):
        self.env.update(RENDER="true", LAUNCHPAD_INITIALIZE_DEMO="1")
        with patch("scripts.start_pilot.os.path.ismount", return_value=False):
            with self.assertRaisesRegex(DemoDataError, "mounted persistent disk"):
                prepare_runtime(self.env)
        self.assertFalse(self.database.exists())
        with patch("scripts.start_pilot.os.path.ismount", return_value=True):
            prepare_runtime(self.env)
        self.assertTrue(self.database.exists())

    def test_missing_or_unsafe_security_settings_fail_before_database_creation(self):
        for key, value in (
            ("LAUNCHPAD_PILOT_MODE", "0"),
            ("LAUNCHPAD_DEMO_MODE", "0"),
            ("LAUNCHPAD_SECRET_KEY", "short"),
            ("LAUNCHPAD_PILOT_USERNAME", ""),
            ("LAUNCHPAD_PILOT_USERNAME", "bad:username"),
            ("LAUNCHPAD_TRUSTED_HOSTS", ""),
            ("LAUNCHPAD_TRUSTED_HOSTS", "*"),
            ("LAUNCHPAD_PILOT_PASSWORD_HASH", "plaintext-password"),
            ("LAUNCHPAD_PILOT_PASSWORD_HASH", "scrypt:32768:8:1$bad$bad"),
            ("LAUNCHPAD_TRUSTED_HOSTS", "https://example.invalid"),
        ):
            with self.subTest(setting=key):
                env = dict(self.env, LAUNCHPAD_INITIALIZE_DEMO="1")
                env[key] = value
                with self.assertRaises(DemoDataError):
                    prepare_runtime(env)
                self.assertFalse(self.database.exists())
                self.assertFalse((self.root / ".launchpad-initialized").exists())

    def test_existing_valid_database_requires_no_reseed(self):
        prepare_demo_database(self.database)
        before = self.database.read_bytes()
        prepare_runtime(self.env)
        self.assertEqual(before, self.database.read_bytes())
        self.assertTrue((self.root / ".launchpad-initialized").is_file())

    def test_database_outside_configured_directory_is_refused(self):
        nested = self.root / "nested"
        nested.mkdir()
        self.env["LAUNCHPAD_DB_PATH"] = str(nested / "pilot.sqlite")
        self.env["LAUNCHPAD_INITIALIZE_DEMO"] = "1"
        with self.assertRaisesRegex(DemoDataError, "directly inside"):
            prepare_runtime(self.env)
        self.assertFalse((nested / "pilot.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
