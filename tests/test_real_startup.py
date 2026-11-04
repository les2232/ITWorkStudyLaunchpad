import contextlib
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from launchpad.accounts import enroll_account
from launchpad.real_data import RealDataError, initialize_real_database
from launchpad.storage import mark_module_complete, module_is_complete
from scripts.start_real import main, prepare_runtime


class RealStartupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.root = Path(self.directory.name)
        self.database = self.root / "real.sqlite"
        initialize_real_database(self.database)
        self.env = {
            "LAUNCHPAD_REAL_MODE": "1", "LAUNCHPAD_DEMO_MODE": "0", "LAUNCHPAD_PILOT_MODE": "0",
            "LAUNCHPAD_SECRET_KEY": "isolated-only-signing-key-over-32-characters",
            "LAUNCHPAD_TRUSTED_HOSTS": "launchpad.example.invalid",
            "LAUNCHPAD_OIDC_ISSUER": "https://identity.example.invalid",
            "LAUNCHPAD_OIDC_CLIENT_ID": "isolated-client",
            "LAUNCHPAD_OIDC_CLIENT_SECRET": "isolated-only-client-secret",
            "LAUNCHPAD_OIDC_REDIRECT_URI": "https://launchpad.example.invalid/auth/callback",
            "LAUNCHPAD_DATA_DIR": str(self.root), "LAUNCHPAD_DB_PATH": str(self.database),
        }

    def tearDown(self):
        self.directory.cleanup()

    def test_missing_identity_dependency_refuses_before_database_access(self):
        with patch("scripts.start_real.importlib.util.find_spec", side_effect=lambda name: None if name == "authlib" else object()), patch("scripts.start_real.prepare_runtime") as prepare, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(), 2)
        prepare.assert_not_called()

    def test_production_startup_never_accepts_controlled_or_unknown_session_policy(self):
        before = self.database.read_bytes()
        for policy in ("controlled_test", "", "optional", "REVALIDATE"):
            with self.subTest(policy=policy), patch("scripts.start_real.configure_real_security") as configure:
                with self.assertRaises(RealDataError):
                    prepare_runtime(dict(self.env, LAUNCHPAD_AD_SESSION_POLICY=policy))
                configure.assert_not_called()
                self.assertEqual(self.database.read_bytes(), before)

    def test_valid_startup_does_not_change_records_or_schema(self):
        learner = enroll_account("https://identity.example.invalid", "isolated-subject", "Invented learner", db_path=self.database)
        mark_module_complete(learner["learner_id"], "hardware_basics", True, self.database)
        before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        self.assertEqual(prepare_runtime(self.env), self.database)
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), before)
        self.assertTrue(module_is_complete(learner["learner_id"], "hardware_basics", self.database))

    def test_missing_database_never_initialized_even_with_demo_bootstrap_flag(self):
        missing = self.root / "missing.sqlite"
        env = dict(self.env, LAUNCHPAD_DB_PATH=str(missing), LAUNCHPAD_INITIALIZE_DEMO="1")
        with self.assertRaises(RealDataError):
            prepare_runtime(env)
        self.assertFalse(missing.exists())
        self.assertFalse((self.root / ".launchpad-initialized").exists())

    def test_identity_and_mode_validation_precedes_database_access(self):
        for key, value in (
            ("LAUNCHPAD_REAL_MODE", "0"), ("LAUNCHPAD_DEMO_MODE", "1"), ("LAUNCHPAD_PILOT_MODE", "1"),
            ("LAUNCHPAD_SECRET_KEY", "short"), ("LAUNCHPAD_TRUSTED_HOSTS", "*"),
            ("LAUNCHPAD_OIDC_ISSUER", ""), ("LAUNCHPAD_OIDC_ISSUER", "http://identity.example.invalid"),
            ("LAUNCHPAD_OIDC_CLIENT_ID", ""), ("LAUNCHPAD_OIDC_CLIENT_SECRET", ""),
            ("LAUNCHPAD_OIDC_REDIRECT_URI", "http://launchpad.example.invalid/auth/callback"),
        ):
            with self.subTest(key=key, value=value), patch("scripts.start_real.validate_real_database") as validate:
                with self.assertRaises(ValueError):
                    prepare_runtime(dict(self.env, **{key: value}))
                validate.assert_not_called()

    def test_database_outside_data_directory_and_symlink_directory_refused(self):
        nested = self.root / "nested"
        nested.mkdir()
        with self.assertRaises(RealDataError):
            prepare_runtime(dict(self.env, LAUNCHPAD_DATA_DIR=str(nested)))
        link = self.root / "linked"
        link.symlink_to(nested, target_is_directory=True)
        with self.assertRaises(RealDataError):
            prepare_runtime(dict(self.env, LAUNCHPAD_DATA_DIR=str(link)))

    def test_render_mount_required_and_startup_never_infers_durability(self):
        env = dict(self.env, RENDER="true")
        with patch("scripts.start_real.os.path.ismount", return_value=False):
            with self.assertRaisesRegex(RealDataError, "mounted persistent disk"):
                prepare_runtime(env)
        with patch("scripts.start_real.os.path.ismount", return_value=True):
            self.assertEqual(prepare_runtime(env), self.database)


if __name__ == "__main__":
    unittest.main()
