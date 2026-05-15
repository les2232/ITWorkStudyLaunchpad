import sys
import subprocess
from pathlib import Path

from validate_content import main as validate_content

PROJECT_ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    validation_status = validate_content()
    if validation_status != 0:
        sys.exit(validation_status)

    test_result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=PROJECT_ROOT,
        check=False,
    )
    sys.exit(test_result.returncode)
