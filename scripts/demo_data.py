"""Prepare or safely reset the isolated July 30 synthetic demo database."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launchpad.demo import (  # noqa: E402 - project root is added for direct execution
    DEMO_LEARNER_NAMES,
    DemoDataError,
    prepare_demo_database,
    reset_demo_database,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create a guarded synthetic-only Launchpad database below /tmp. "
            "This command never targets the normal instance database."
        )
    )
    parser.add_argument("command", choices=("prepare", "reset"))
    parser.add_argument(
        "--db",
        required=True,
        type=Path,
        help="required canonical absolute .sqlite path below /tmp",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            prepared = prepare_demo_database(args.db)
            print(f"Prepared synthetic demo database: {prepared}")
        else:
            prepared, quarantined = reset_demo_database(args.db)
            print(f"Quarantined previous synthetic demo database: {quarantined}")
            print(f"Prepared fresh synthetic demo database: {prepared}")
    except DemoDataError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2

    print("Synthetic learners:")
    for name in DEMO_LEARNER_NAMES:
        print(f"  - {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
