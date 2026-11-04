"""Prove the build check command cannot inherit a hosted pilot's database."""

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


class CheckEnvironmentTests(unittest.TestCase):
    def test_check_subprocess_ignores_hosted_application_settings(self):
        project = Path(__file__).resolve().parents[1]
        # Direct script imports resolve their sibling validator from scripts/.
        with patch.object(sys, "path", [str(project / "scripts"), *sys.path]):
            spec = importlib.util.spec_from_file_location("isolated_check_command", project / "scripts/check_all.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            rehearsal = Path(directory)
            sentinel = rehearsal / "must-stay-untouched.sqlite"
            sentinel.write_bytes(b"not a database; never initialize me")
            (rehearsal / "tests").mkdir()
            (rehearsal / "tests/test_host_environment.py").write_text(
                "import os, unittest\n"
                "class IsolatedEnvironment(unittest.TestCase):\n"
                " def test_no_host_configuration(self):\n"
                "  self.assertFalse(any(key.startswith('LAUNCHPAD_') for key in os.environ))\n"
                "  self.assertNotIn('FLASK_DEBUG', os.environ)\n"
                "  self.assertNotIn('FLASK_APP', os.environ)\n"
                "  self.assertIn('PATH', os.environ)\n"
            )
            before = sentinel.read_bytes()
            with patch.dict(os.environ, {
                "LAUNCHPAD_PILOT_MODE": "1",
                "LAUNCHPAD_DEMO_MODE": "1",
                "LAUNCHPAD_DB_PATH": str(sentinel),
                "LAUNCHPAD_SECRET_KEY": "never-print-this-synthetic-secret",
                "LAUNCHPAD_PILOT_PASSWORD_HASH": "invalid-hash-must-not-load",
                "FLASK_DEBUG": "1",
                "FLASK_APP": "app",
            }), patch.object(module, "PROJECT_ROOT", rehearsal), patch.object(module, "validate_content", return_value=0):
                self.assertEqual(module.main(), 0)
                self.assertEqual(os.environ["LAUNCHPAD_DB_PATH"], str(sentinel))
            self.assertEqual(before, sentinel.read_bytes())
            self.assertFalse((rehearsal / "instance").exists())


if __name__ == "__main__":
    unittest.main()
