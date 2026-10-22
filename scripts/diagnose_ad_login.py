"""One human-operated AD bind and eligibility check, without app enrollment.

The default is an offline preflight. Only --execute requests a password or
contacts AD. Use a private, unrecorded terminal; never pipe a password here.
There is no retry loop or persisted throttle: the operator must control reruns.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from getpass import GetPassWarning, getpass
import hashlib
import json
import logging
import os
from pathlib import Path
import resource
import signal
import stat
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4
import warnings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launchpad.ad import authenticate_ad, configure_ad, normalized_attempt_key  # noqa: E402

DIRECTORY_HOST = "CCCDC01.ccc.ccofc.edu"
GROUP_DN = "CN=CCA_Leslie_Project,OU=CCA_Groups_Security_User,OU=CCA,DC=ccc,DC=ccofc,DC=edu"
BUNDLE_SHA256 = "3FCA2B4261A70C682C5A52399A910D8DCB04EEDC4159F4254222AB51094A3A8E"
DEADLINE_SECONDS = 30
IDENTITY_KEYS = frozenset({
    "purpose", "label", "role", "upn", "object_guid", "upn_suffix",
    "identity_source", "reported_date", "reported_date_timezone", "enrollment_status",
    "use_as_lookup_account", "progress_policy", "test_namespace",
    "planned_database_path", "directory_search_base", "lookup_account_upn",
})


class Refused(Exception):
    """Public output must not include input values or directory diagnostics."""


class DeadlineExpired(BaseException):
    """Escape library handlers and interrupt bounded directory operations."""


class AttemptStopped(BaseException):
    """Prevent ldap3 from trying another DNS address after a failed transport."""


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refused()
        result[key] = value
    return result


def _private_directory(path: Path) -> None:
    if not path.is_absolute() or path.resolve() != path:
        raise Refused()
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise Refused()


def _read_file(path: Path, *, private: bool, limit: int) -> bytes:
    if not path.is_absolute() or path.resolve() != path:
        raise Refused()
    # O_NONBLOCK avoids blocking on an unexpected FIFO before fstat rejects it.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise Refused()
        if private and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
            raise Refused()
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise Refused()
        return data


def preflight(base_dn: str, group_policy: str):
    """Read approved inputs and configure TLS locally; no database or network."""
    folder = PROJECT_ROOT / "work" / "ad-login-test"
    _private_directory(folder)
    raw = _read_file(folder / "pilot-a-identity.local.json", private=True, limit=16 * 1024)
    identity = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(identity, dict) or set(identity) != IDENTITY_KEYS:
        raise Refused()
    if (identity["label"] != "Pilot A" or identity["role"] != "learner"
            or identity["enrollment_status"] != "prepared_not_enrolled"
            or identity["use_as_lookup_account"] is not False
            or identity["progress_policy"] != "new_isolated_dataset_only"
            or any(identity[key] is not None for key in (
                "test_namespace", "planned_database_path", "directory_search_base", "lookup_account_upn"))):
        raise Refused()
    for key in IDENTITY_KEYS - {
        "test_namespace", "planned_database_path", "directory_search_base", "lookup_account_upn", "use_as_lookup_account",
    }:
        value = identity[key]
        if not isinstance(value, str) or not value or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise Refused()
    subject = identity["object_guid"]
    if str(UUID(subject)) != subject or not UUID(subject).int:
        raise Refused()
    upn = identity["upn"]
    if upn.count("@") != 1 or upn.rsplit("@", 1)[1].lower() != identity["upn_suffix"].lower():
        raise Refused()
    bundle = PROJECT_ROOT / "work" / "ad-ca-review" / "launchpad-ad-ca.pem"
    bundle_bytes = _read_file(bundle, private=False, limit=64 * 1024)
    if hashlib.sha256(bundle_bytes).hexdigest().upper() != BUNDLE_SHA256:
        raise Refused()
    # A throwaway namespace satisfies the adapter's immutable identity contract.
    # It is never stored, used for enrollment, or substituted for OIDC identity.
    holder = SimpleNamespace(config={
        "LAUNCHPAD_AD_HOST": DIRECTORY_HOST,
        "LAUNCHPAD_AD_PORT": "636",
        "LAUNCHPAD_AD_CA_FILE": str(bundle),
        "LAUNCHPAD_AD_DOMAIN": identity["upn_suffix"],
        "LAUNCHPAD_AD_BASE_DN": base_dn,
        "LAUNCHPAD_AD_GROUP_DN": GROUP_DN,
        "LAUNCHPAD_AD_GROUP_POLICY": group_policy,
        "LAUNCHPAD_AD_IDENTITY_NAMESPACE": str(uuid4()),
    }, extensions={})
    configured = configure_ad(holder)
    if normalized_attempt_key(upn, configured).startswith("invalid:"):
        raise Refused()
    return configured, upn, subject


def require_tty() -> None:
    if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
        raise Refused()


def private_password() -> str:
    require_tty()
    with warnings.catch_warnings():
        warnings.simplefilter("error", GetPassWarning)
        password = getpass("Pilot A AD password (hidden; one attempt): ", stream=sys.stderr)
    if not password or len(password) > 4096 or "\x00" in password:
        raise Refused()
    return password


@contextmanager
def bounded_execution():
    def expired(_number, _frame):
        raise DeadlineExpired()

    if not hasattr(signal, "setitimer") or signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise Refused()
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, DEADLINE_SECONDS, 1)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)



@contextmanager
def single_connection():
    """Confine even ldap3's transport fallback to one socket attempt.

    This process-local guard changes no application adapter behavior. The
    command is single-threaded and restores both library entry points on exit.
    """
    import ldap3
    from ldap3.strategy.base import BaseStrategy

    original_connection = ldap3.Connection
    original_open = BaseStrategy._open_socket
    connections = []
    connection_calls = socket_calls = 0

    def tracked_connection(*args, **kwargs):
        nonlocal connection_calls
        connection_calls += 1
        if connection_calls != 1:
            raise AttemptStopped()
        connection = original_connection(*args, **kwargs)
        connections.append(connection)
        return connection

    def once_open(strategy, *args, **kwargs):
        nonlocal socket_calls
        socket_calls += 1
        if socket_calls != 1:
            raise AttemptStopped()
        try:
            return original_open(strategy, *args, **kwargs)
        except Exception:
            # BaseStrategy.open catches Exception and tries the next address.
            # Escape that loop immediately on the first TCP/TLS failure.
            raise AttemptStopped() from None

    ldap3.Connection = tracked_connection
    BaseStrategy._open_socket = once_open
    try:
        yield
    finally:
        ldap3.Connection = original_connection
        BaseStrategy._open_socket = original_open
        for connection in connections:
            connection.password = None
            transport = getattr(connection, "socket", None)
            if transport is not None:
                transport.close()


def main(argv=None) -> int:
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--base-dn", required=True, help="Owner-approved search base DN; no default.")
    parser.add_argument("--group-policy", required=True, choices=("direct", "nested"), help="Explicit membership check for this test.")
    parser.add_argument("--execute", action="store_true", help="Prompt privately and make one credentialed directory attempt.")
    previous_logging = logging.root.manager.disable
    logging.disable(sys.maxsize)
    password = username = subject = configured = returned = None
    try:
        args = parser.parse_args(argv)
        configured, username, subject = preflight(args.base_dn, args.group_policy)
        if not args.execute:
            print("PREFLIGHT PASS: private identity and pinned CA bundle accepted; no password, network, enrollment or session used.")
            return 0
        require_tty()
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        password = private_password()
        with bounded_execution(), single_connection():
            # Exactly one call; the existing adapter opens verified TLS, binds,
            # performs one enabled-account/group/GUID query and unbinds finally.
            returned = authenticate_ad(username, password, configured)
        if returned != {"issuer": configured.issuer, "subject": subject}:
            raise Refused()
        print("PASS: verified LDAPS, credentials, enabled-account/group eligibility and expected GUID. No application session or enrollment created.")
        return 0
    except DeadlineExpired:
        print("FAILED: directory attempt exceeded its time limit; stopped without retry.")
        return 1
    except (Exception, KeyboardInterrupt, AttemptStopped):
        print("FAILED: input checks or the single diagnostic attempt did not pass; stopped without retry. No directory details are displayed.")
        return 1
    finally:
        # Drop references; Python does not guarantee physical string zeroization.
        password = username = subject = configured = returned = None
        logging.disable(previous_logging)


if __name__ == "__main__":
    raise SystemExit(main())
