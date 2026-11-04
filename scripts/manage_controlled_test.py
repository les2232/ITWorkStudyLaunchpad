"""Explicit operator provisioning for an isolated AD work-study test."""
from __future__ import annotations

import argparse
from getpass import GetPassWarning, getpass
import os
from pathlib import Path
import sqlite3
import sys
import warnings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launchpad.controlled_test import enroll_controlled_account, initialize_controlled_run, load_run_config  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("initialize", "verify", "enroll"):
        item = commands.add_parser(name)
        item.add_argument("--run", required=True, help="new non-personal run label; never a path")
        if name == "enroll":
            item.add_argument("--role", choices=("learner", "mentor"), default="learner")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        if args.command == "initialize":
            initialize_controlled_run(args.run)
            print("New empty controlled-test storage prepared. Complete private config.json before startup; no accounts were enrolled.")
        elif args.command == "verify":
            load_run_config(args.run)
            print("Isolated storage and account mappings verified offline. Directory settings, credentials and browser HTTPS are not verified.")
        else:
            load_run_config(args.run)
            if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
                raise ValueError("Enrollment requires a trusted interactive terminal.")
            with warnings.catch_warnings():
                warnings.simplefilter("error", GetPassWarning)
                subject = getpass("Student/mentor's independently verified canonical objectGUID (not Pilot A): ")
                label = getpass("Invented test display label (no real name): ")
            account = enroll_controlled_account(args.run, subject, label, args.role)
            print(f"Explicit enrollment completed. Internal account ID: {account['id']}; learner ID: {account['learner_id'] or 'none'}.")
    except (ValueError, OSError, sqlite3.DatabaseError, GetPassWarning, EOFError, KeyboardInterrupt):
        print("Controlled test operation refused. Check isolated run inputs; no existing dataset was replaced.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
