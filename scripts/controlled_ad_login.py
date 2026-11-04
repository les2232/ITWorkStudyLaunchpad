"""Human-operated, explicitly authorized AD integration check; never a web server.

Nothing executes without --execute. This helper never provisions accounts or
storage, and accepts no passwords in its JSON configuration or command line.
An authorized operator must supply secrets through a trusted, unrecorded TTY.
It exercises real Flask views in process; this is not browser/hosting acceptance.
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
import secrets
import signal
import stat
import sys
from uuid import UUID
import warnings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask  # noqa: E402

from launchpad import create_app  # noqa: E402
from launchpad import real_auth  # noqa: E402
from launchpad.accounts import get_session_account, revoke_auth_session  # noqa: E402
from launchpad.ad import configure_ad, normalized_attempt_key  # noqa: E402
from launchpad.ad_state import validate_ad_state  # noqa: E402
from launchpad.real_data import validate_real_database  # noqa: E402

TEST_HOST = "launchpad-controlled.invalid"
DIRECTORY_HOST = "CCCDC01.ccc.ccofc.edu"
GROUP_DN = "CN=CCA_Leslie_Project,OU=CCA_Groups_Security_User,OU=CCA,DC=ccc,DC=ccofc,DC=edu"
BUNDLE_SHA256 = "3FCA2B4261A70C682C5A52399A910D8DCB04EEDC4159F4254222AB51094A3A8E"
DEADLINE_SECONDS = 30
CONFIG_KEYS = frozenset({
    "LAUNCHPAD_REAL_MODE", "LAUNCHPAD_DEMO_MODE", "LAUNCHPAD_PILOT_MODE",
    "LAUNCHPAD_AUTH_BACKEND", "LAUNCHPAD_DATA_DIR", "LAUNCHPAD_DB_PATH",
    "LAUNCHPAD_TRUSTED_HOSTS", "LAUNCHPAD_AD_HOST", "LAUNCHPAD_AD_PORT",
    "LAUNCHPAD_AD_CA_FILE", "LAUNCHPAD_AD_DOMAIN", "LAUNCHPAD_AD_BASE_DN",
    "LAUNCHPAD_AD_GROUP_DN", "LAUNCHPAD_AD_GROUP_POLICY",
    "LAUNCHPAD_AD_IDENTITY_NAMESPACE", "LAUNCHPAD_AD_LOOKUP_USERNAME",
    "LAUNCHPAD_AD_REVALIDATE_SECONDS", "LAUNCHPAD_AD_STATE_PATH",
})


class Refused(Exception):
    pass


class CheckFailed(Exception):
    def __init__(self, step: str, status: int | None):
        self.step = step
        self.status = status


class DeadlineExpired(BaseException):
    """Do not let an LDAP/library or Flask Exception handler swallow the limit."""


class AttemptBudgetExceeded(BaseException):
    """The helper permits one learner bind and at most one eligibility lookup."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refused()
        result[key] = value
    return result


def _private_path(path: Path, *, directory: bool) -> None:
    if not path.is_absolute() or path.resolve() != path:
        raise Refused()
    info = path.stat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise Refused()
    if not directory and info.st_nlink != 1:
        raise Refused()


def load_config(path: Path) -> dict:
    """Read and validate allowlisted non-secret input; no writes or AD requests."""
    if path.stat().st_size > 16 * 1024:
        raise Refused()
    config = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if not isinstance(config, dict) or set(config) != CONFIG_KEYS:
        raise Refused()
    if (config["LAUNCHPAD_REAL_MODE"] is not True
            or config["LAUNCHPAD_DEMO_MODE"] is not False
            or config["LAUNCHPAD_PILOT_MODE"] is not False
            or config["LAUNCHPAD_AUTH_BACKEND"] != "ad"
            or config["LAUNCHPAD_TRUSTED_HOSTS"] != TEST_HOST
            or config["LAUNCHPAD_AD_HOST"] != DIRECTORY_HOST
            or str(config["LAUNCHPAD_AD_PORT"]) != "636"
            or config["LAUNCHPAD_AD_GROUP_DN"] != GROUP_DN):
        raise Refused()
    interval = config["LAUNCHPAD_AD_REVALIDATE_SECONDS"]
    if type(interval) is not int or not 1 <= interval <= 300:
        raise Refused()
    for key in CONFIG_KEYS - {
        "LAUNCHPAD_REAL_MODE", "LAUNCHPAD_DEMO_MODE", "LAUNCHPAD_PILOT_MODE",
        "LAUNCHPAD_AD_REVALIDATE_SECONDS", "LAUNCHPAD_AD_PORT",
    }:
        if not isinstance(config[key], str) or not config[key] or config[key] != config[key].strip():
            raise Refused()
    staging_root = PROJECT_ROOT / "work" / "ad-login-test"
    directory = Path(config["LAUNCHPAD_DATA_DIR"])
    if directory.parent != staging_root:
        raise Refused()
    _private_path(directory, directory=True)
    database = Path(config["LAUNCHPAD_DB_PATH"])
    state = Path(config["LAUNCHPAD_AD_STATE_PATH"])
    if database.parent != directory or state.parent != directory or database == state:
        raise Refused()
    for store in (database, state):
        _private_path(store, directory=False)
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(str(store) + suffix)
            if os.path.lexists(sidecar):
                _private_path(sidecar, directory=False)
    bundle = PROJECT_ROOT / "work" / "ad-ca-review" / "launchpad-ad-ca.pem"
    if Path(config["LAUNCHPAD_AD_CA_FILE"]) != bundle or bundle.resolve() != bundle:
        raise Refused()
    if hashlib.sha256(bundle.read_bytes()).hexdigest().upper() != BUNDLE_SHA256:
        raise Refused()
    validator = Flask("controlled-ad-config")
    validator.config.update(config)
    directory_config = configure_ad(validator)
    lookup = config["LAUNCHPAD_AD_LOOKUP_USERNAME"]
    if "@" not in lookup or normalized_attempt_key(lookup, directory_config).startswith("invalid:"):
        raise Refused()
    validate_real_database(database)
    validate_ad_state(state)
    return config


def require_tty() -> None:
    if not all(stream.isatty() for stream in (sys.stdin, sys.stdout, sys.stderr)):
        raise Refused()


def private_input(prompt: str) -> str:
    require_tty()
    with warnings.catch_warnings():
        warnings.simplefilter("error", GetPassWarning)
        value = getpass(prompt, stream=sys.stderr)
    if not value or len(value) > 1024 or "\x00" in value:
        raise Refused()
    return value


@contextmanager
def bounded_execution():
    def expired(_number, _frame):
        raise DeadlineExpired()

    if not hasattr(signal, "setitimer") or signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
        raise Refused()
    previous = signal.signal(signal.SIGALRM, expired)
    # Repeated alarm prevents a library's blocking cleanup from indefinitely
    # postponing the outer deadline after the first interruption.
    signal.setitimer(signal.ITIMER_REAL, DEADLINE_SECONDS, 1)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@contextmanager
def one_attempt_each():
    original_login = real_auth.authenticate_ad
    original_lookup = real_auth.revalidate_ad
    calls = {"login": 0, "lookup": 0}

    def limited(kind, function, *args, **kwargs):
        calls[kind] += 1
        if calls[kind] > 1:
            raise AttemptBudgetExceeded()
        return function(*args, **kwargs)

    real_auth.authenticate_ad = lambda *args, **kwargs: limited("login", original_login, *args, **kwargs)
    real_auth.revalidate_ad = lambda *args, **kwargs: limited("lookup", original_lookup, *args, **kwargs)
    try:
        yield
    finally:
        real_auth.authenticate_ad = original_login
        real_auth.revalidate_ad = original_lookup


def _expect(step: str, response, expected: int) -> None:
    status = response.status_code
    if status != expected:
        raise CheckFailed(step, status)
    print(f"{step}: PASS (HTTP {status})")


def _csrf(client) -> str:
    with client.session_transaction(base_url="https://" + TEST_HOST) as session:
        value = session.get("csrf_token")
    if not isinstance(value, str) or not value:
        raise Refused()
    return value


def exercise(config: dict, username: str, password: str, expected_subject: str) -> None:
    """Only identity/session writes in an already provisioned isolated dataset."""
    apps = []
    client = restarted = replay = cookie = None
    try:
        app = create_app(config)
        apps.append(app)
        client = app.test_client()
        base_url = "https://" + TEST_HOST
        _expect("anonymous-denied", client.get("/student", base_url=base_url), 401)
        _expect("login-form", client.get("/auth/login", base_url=base_url), 200)
        response = client.post("/auth/login", base_url=base_url, data={
            "csrf_token": _csrf(client), "username": username, "password": password,
        })
        password = username = None
        try:
            _expect("enrolled-login", response, 302)
        finally:
            response = None
        with client.session_transaction(base_url=base_url) as session:
            token = session.get("auth_session")
        account = get_session_account(token, config["LAUNCHPAD_DB_PATH"])
        if not account or account["issuer"] != "urn:launchpad:ad:" + config["LAUNCHPAD_AD_IDENTITY_NAMESPACE"] \
                or account["subject"] != expected_subject or account["role"] != "learner":
            revoke_auth_session(token, config["LAUNCHPAD_DB_PATH"])
            raise CheckFailed("designated-identity", None)
        print("designated-identity: PASS")
        account = token = expected_subject = None
        _expect("own-learner", client.get("/student", base_url=base_url), 200)
        _expect("learner-staff-denied", client.get("/supervisor", base_url=base_url), 403)
        cookie = client.get_cookie("__Host-launchpad_session", domain=TEST_HOST)
        if cookie is None:
            raise Refused()
        # Recreating the app empties its AD eligibility cache. This next request
        # must use the approved lookup account, not the learner's password.
        recreated = create_app(config)
        apps.append(recreated)
        restarted = recreated.test_client()
        restarted.set_cookie(cookie.key, cookie.value, domain=TEST_HOST, secure=True)
        _expect("lookup-after-recreation", restarted.get("/student", base_url=base_url), 200)
        replay = recreated.test_client()
        replay.set_cookie(cookie.key, cookie.value, domain=TEST_HOST, secure=True)
        _expect("logout", restarted.post("/auth/logout", base_url=base_url,
                                         data={"csrf_token": _csrf(restarted)}), 302)
        _expect("old-cookie-denied", replay.get("/student", base_url=base_url), 401)
    finally:
        for application in apps:
            application.config.pop("LAUNCHPAD_AD_LOOKUP_PASSWORD", None)
            application.config.pop("SECRET_KEY", None)
        # Drop references; Python strings cannot promise in-memory zeroization.
        client = restarted = replay = cookie = password = username = expected_subject = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="non-secret JSON; strict allowlist")
    parser.add_argument("--execute", action="store_true", help="operator confirms explicit authorization and trusted TTY")
    args = parser.parse_args(argv)
    if not args.execute:
        print("REFUSED: --execute is required; no configuration, credentials or storage were used.")
        return 2
    config = {}
    password = username = expected_subject = None
    previous_logging = logging.root.manager.disable
    try:
        require_tty()
        # This human-only helper never emits library diagnostics or tracebacks.
        logging.disable(logging.CRITICAL)
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        config = load_config(args.config)
        username = private_input("Designated learner UPN (not recorded): ")
        validator = Flask("controlled-ad-learner-name")
        validator.config.update(config)
        directory = configure_ad(validator)
        # This operator diagnostic requires the exact verified UPN; the web
        # sign-in's whitespace tolerance must not relax this pre-prompt check.
        if username != username.strip() or "@" not in username or normalized_attempt_key(username, directory).startswith("invalid:"):
            raise Refused()
        # The designated learner must never supply the background lookup
        # identity. Compare canonical UPNs before collecting either password.
        # Distinct aliases still require independent directory-owner review.
        if normalized_attempt_key(username, directory) == normalized_attempt_key(
                config["LAUNCHPAD_AD_LOOKUP_USERNAME"], directory):
            raise Refused()
        expected_subject = private_input("Independently verified learner objectGUID (not recorded): ")
        if str(UUID(expected_subject)) != expected_subject or not UUID(expected_subject).int:
            raise Refused()
        config["LAUNCHPAD_AD_LOOKUP_PASSWORD"] = private_input("Approved lookup-account password (not recorded): ")
        password = private_input("Designated learner password (not recorded): ")
        config["SECRET_KEY"] = secrets.token_urlsafe(48)
        with bounded_execution(), one_attempt_each():
            exercise(config, username, password, expected_subject)
        print("PASS: controlled AD integration checks; browser and hosting checks remain separate.")
        return 0
    except CheckFailed as error:
        detail = f" (HTTP {error.status})" if error.status is not None else ""
        print(f"{error.step}: FAIL{detail}; no automatic retry.")
        return 1
    except DeadlineExpired:
        print("FAIL: controlled test deadline reached; no automatic retry.")
        return 124
    except AttemptBudgetExceeded:
        print("FAIL: directory attempt budget reached; no additional directory request.")
        return 1
    except (Exception, KeyboardInterrupt):
        print("REFUSED: check the approved configuration, isolated storage and trusted terminal; no automatic retry.")
        return 2
    finally:
        config.pop("LAUNCHPAD_AD_LOOKUP_PASSWORD", None)
        config.pop("SECRET_KEY", None)
        password = username = expected_subject = None
        logging.disable(previous_logging)


if __name__ == "__main__":
    sys.exit(main())
