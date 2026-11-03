"""Operator-only provisioning, explicit account mapping and new-file recovery.

This CLI is never called from a web endpoint. Run only in an approved restricted
operator environment; identifiers are read without echo, not from shell history.
"""
from __future__ import annotations

import argparse
from getpass import getpass
import os
from pathlib import Path
import sqlite3
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launchpad.accounts import (  # noqa: E402
    assign_mentor, bind_existing_learner, enroll_account, revoke_all_sessions,
    set_account_active, unassign_mentor,
)
from launchpad.real_data import (  # noqa: E402
    RealDataError, copy_real_snapshot, initialize_real_database, migrate_real_database,
    validate_real_database,
)
from launchpad.ad_state import initialize_ad_state, validate_ad_state  # noqa: E402


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("initialize-ad-state", "verify-ad-state"):
        item = commands.add_parser(name, help="explicitly provision or verify separate AD login-throttle storage")
        item.add_argument("--path", required=True, type=Path)
    provision = commands.add_parser("initialize", help="create a NEW empty real-user dataset")
    provision.add_argument("--db", required=True, type=Path)
    verify = commands.add_parser("verify", help="validate schema, account mappings and database integrity")
    verify.add_argument("--db", required=True, type=Path)
    for name in ("backup", "restore"):
        item = commands.add_parser(name, help="create a new snapshot; never overwrite")
        item.add_argument("--source", required=True, type=Path)
        item.add_argument("--destination", required=True, type=Path)
    migrate = commands.add_parser("migrate", help="write a NEW schema-version-3 copy of a version-1 or version-2 dataset; never overwrite")
    migrate.add_argument("--source", required=True, type=Path)
    migrate.add_argument("--destination", required=True, type=Path)
    for name in ("enroll", "bind-existing"):
        item = commands.add_parser(name, help="provision an explicitly verified identity")
        item.add_argument("--db", required=True, type=Path)
        item.add_argument("--issuer", required=True, help="exact OIDC issuer or urn:launchpad:ad:<directory UUID>; verified subject is prompted privately")
        if name == "enroll":
            item.add_argument("--role", choices=("learner", "mentor", "admin"), default="learner")
        else:
            item.add_argument("--learner-id", type=int, required=True)
            item.add_argument("--migration-reviewed", action="store_true", help="confirm the restricted mapping has been independently verified")
    for name in ("grant-mentor", "revoke-mentor"):
        item = commands.add_parser(name, help="change an explicit read-only learner-review assignment")
        item.add_argument("--db", required=True, type=Path)
        item.add_argument("--account-id", type=int, required=True)
        item.add_argument("--learner-id", type=int, required=True)
    disable = commands.add_parser("disable-account", help="revoke account access and its sessions")
    disable.add_argument("--db", required=True, type=Path)
    disable.add_argument("--account-id", type=int, required=True)
    revoke = commands.add_parser("revoke-sessions", help="invalidate all local sessions, or one account's sessions")
    revoke.add_argument("--db", required=True, type=Path)
    revoke.add_argument("--account-id", type=int)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    os.umask(0o077)
    try:
        if args.command == "initialize-ad-state":
            initialize_ad_state(args.path)
        elif args.command == "verify-ad-state":
            validate_ad_state(args.path)
        elif args.command == "initialize":
            initialize_real_database(args.db)
        elif args.command == "migrate":
            migrate_real_database(args.source, args.destination)
        elif args.command in {"backup", "restore"}:
            copy_real_snapshot(args.source, args.destination, restore=args.command == "restore")
        else:
            validate_real_database(args.db)
            if args.command in {"enroll", "bind-existing"}:
                if args.command == "bind-existing" and not args.migration_reviewed:
                    raise RealDataError("existing records require a reviewed identity-to-learner mapping")
                subject = getpass("Verified immutable identity subject (not email/display name): ")
                if args.command == "enroll":
                    label = getpass("Approved display label: ")
                    account = enroll_account(args.issuer, subject, label, args.role, db_path=args.db)
                else:
                    account = bind_existing_learner(args.issuer, subject, args.learner_id,
                                                    db_path=args.db, migration_reviewed=True)
                print(f"Account provisioned. Internal account ID: {account['id']}")
            elif args.command == "grant-mentor":
                assign_mentor(args.account_id, args.learner_id, args.db)
            elif args.command == "revoke-mentor":
                unassign_mentor(args.account_id, args.learner_id, args.db)
            elif args.command == "disable-account":
                set_account_active(args.account_id, False, args.db)
            elif args.command == "revoke-sessions":
                revoke_all_sessions(args.db, account_id=args.account_id)
    except (ValueError, OSError, sqlite3.DatabaseError):
        # Errors must not echo submitted identities, paths, row data or secrets.
        print("Operation refused. Check the approved configuration, mapping and new-file requirements; existing data was not replaced.", file=sys.stderr)
        return 2
    print("Operation completed; record the authorized change in the restricted operations log.")
    if args.command == "migrate":
        print("Migrated version-3 copy written; the source was not changed. Version-1 help requests start as Open; version-2 status is preserved. Day 1 answers start empty. Keep learner traffic stopped until the NEW release points at the NEW database, then run smoke checks.")
    if args.command == "restore":
        print("Restored sessions were revoked. Keep traffic closed, rotate the signing key, review account/grant changes since the snapshot, select the NEW database path and run smoke checks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
