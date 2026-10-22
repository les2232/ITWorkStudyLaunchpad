import sys
import os
import subprocess
from pathlib import Path
import importlib.util

from validate_content import main as validate_content

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_python() -> str:
    if importlib.util.find_spec("flask") is not None:
        return sys.executable

    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)

    return sys.executable


def main() -> int:
    validation_status = validate_content()
    if validation_status != 0:
        return validation_status

    test_result = subprocess.run(
        [test_python(), "-m", "unittest", "discover", "-s", "tests"],
        cwd=PROJECT_ROOT,
        check=False,
        # Hosting config belongs to the running pilot, never the isolated suite.
        env={
            key: value for key, value in os.environ.items()
            if not key.startswith("LAUNCHPAD_")
            and key not in {"FLASK_APP", "FLASK_DEBUG", "FLASK_ENV"}
        },
    )
    return test_result.returncode


if __name__ == "__main__":
    sys.exit(main())
