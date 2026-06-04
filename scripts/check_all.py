import sys
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


if __name__ == "__main__":
    validation_status = validate_content()
    if validation_status != 0:
        sys.exit(validation_status)

    test_result = subprocess.run(
        [test_python(), "-m", "unittest", "discover", "-s", "tests"],
        cwd=PROJECT_ROOT,
        check=False,
    )
    sys.exit(test_result.returncode)
