"""Real-user request identity and least-privilege authorization.

The institutional provider authenticates a subject. Explicit local account
bindings and grants determine what that subject can access; claims, names,
form fields and request headers never grant learner or mentor authority.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from flask import Flask, abort, current_app, g, redirect, render_template, request, session, url_for
from werkzeug.exceptions import BadRequest, HTTPException, RequestEntityTooLarge, SecurityError

from .accounts import (
    create_auth_session,
    get_account_for_identity,
    get_session_account,
    revoke_auth_session,
    revoke_all_sessions,
)
from .ad import ADLoginError, authenticate_ad, configure_ad, normalized_attempt_key, revalidate_ad
from .ad_state import ADStateError, reserve_login_attempt, validate_ad_state
from .controlled_test import validate_controlled_storage
from .oidc import OIDCLoginError, begin_login, complete_login, configure_oidc
from .pilot import error_page, validate_pilot_submission


_PUBLIC_ENDPOINTS = frozenset({"auth_login", "auth_callback", "auth_logout", "static"})
_IDENTITY_FIELDS = frozenset({"student", "student_id", "learner_id", "account_id", "display_name", "role", "issuer", "subject"})
_PERSONAL_ENDPOINTS = frozenset({"student_identity", "assessment_results", "pre_assessment", "post_assessment", "help_requests"})
_CONTROLLED_SESSION_SECONDS = 900
_IDLE_SESSION_SECONDS = 1800
_SESSION_POLICIES = frozenset({"revalidate", "signin", "controlled_test"})
_LOGIN_REJECTION_REASONS = frozenset({
    "csrf_session_absent", "csrf_after_session_invalid", "csrf_token_count",
    "csrf_mismatch", "origin_rejected", "login_fields_invalid",
    "login_identity_invalid", "login_throttled", "ad_denied_or_unavailable",
    "identity_issuer_mismatch", "enrollment_denied", "ad_state_unavailable",
    "trusted_host_rejected", "request_too_large", "request_bad_request",
    "storage_unavailable", "internal_error", "http_rejected",
})
_CONTROLLED_SIGN_IN_NOTICE = (
    "Sign in again with your CCA account. Test sessions end 15 minutes after sign-in. "
    "Previously submitted progress is retained. Unsaved answers and this request were not saved; "
    "they will not be submitted automatically after sign-in. Unfinished guided practice must be restarted."
)


def session_ended_notice(hours: int) -> str:
    """Accurate re-sign-in guidance for regular (non-test) sessions."""
    return (
        f"Your sign-in ended. Sessions end after 30 minutes without activity or {hours} hours after sign-in. "
        "Progress you already submitted is saved. Anything you typed but did not submit, including this request, "
        "was not saved and will not be submitted automatically. Unfinished guided practice must be restarted."
    )


def configure_real_security(app: Flask) -> None:
    """Validate identity settings before learner access; AD state is read-only here."""
    app.config.setdefault("LAUNCHPAD_REAL_MODE", os.environ.get("LAUNCHPAD_REAL_MODE", "").strip().lower() in {"1", "true", "yes"})
    policy = app.config.setdefault("LAUNCHPAD_AD_SESSION_POLICY", os.environ.get("LAUNCHPAD_AD_SESSION_POLICY", "revalidate"))
    if not isinstance(policy, str) or policy not in _SESSION_POLICIES:
        raise ValueError("Choose an explicit supported AD session policy.")
    controlled = policy == "controlled_test"
    signin_only = policy == "signin"
    if controlled and not app.config["LAUNCHPAD_REAL_MODE"]:
        raise ValueError("Controlled AD testing requires real-user authentication.")
    if not app.config["LAUNCHPAD_REAL_MODE"]:
        return
    if app.config.get("LAUNCHPAD_DEMO_MODE") or app.config.get("LAUNCHPAD_PILOT_MODE"):
        raise ValueError("Real-user mode cannot use demo or shared-invitation mode.")
    secret = app.config.get("SECRET_KEY")
    if not isinstance(secret, str) or len(secret.strip()) < 32:
        raise ValueError("Real-user mode requires a stable random signing key of at least 32 characters.")
    hosts = app.config.get("LAUNCHPAD_TRUSTED_HOSTS") or os.environ.get("LAUNCHPAD_TRUSTED_HOSTS") or os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
    if not isinstance(hosts, str):
        raise ValueError("Real-user mode requires exact trusted host names.")
    allowed_hosts = [host.strip() for host in hosts.split(",") if host.strip()]
    if not allowed_hosts or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*(?::[0-9]+)?", host) for host in allowed_hosts):
        raise ValueError("Real-user mode requires exact trusted host names.")
    backend = app.config.setdefault("LAUNCHPAD_AUTH_BACKEND", os.environ.get("LAUNCHPAD_AUTH_BACKEND", "oidc"))
    if backend not in {"oidc", "ad"}:
        raise ValueError("Choose an explicit supported authentication backend.")
    if (controlled or signin_only) and backend != "ad":
        raise ValueError("This AD session policy requires the AD authentication backend.")
    authorization_origin = ""
    if backend == "ad":
        directory = configure_ad(app)
        for name in ("LOOKUP_USERNAME", "LOOKUP_PASSWORD", "STATE_PATH", "REVALIDATE_SECONDS"):
            key = f"LAUNCHPAD_AD_{name}"
            app.config.setdefault(key, os.environ.get(key, ""))
        if controlled or signin_only:
            # Without a lookup account, eligibility is verified only at sign-in.
            # Configured credentials signal that revalidate was intended.
            if any(app.config[f"LAUNCHPAD_AD_{name}"] != "" for name in ("LOOKUP_USERNAME", "LOOKUP_PASSWORD")):
                raise ValueError("Sign-in-only session policies must not configure background lookup credentials; use revalidate.")
            if controlled:
                validate_controlled_storage(app.config, directory.issuer)
        else:
            for name in ("LOOKUP_USERNAME", "LOOKUP_PASSWORD"):
                value = app.config[f"LAUNCHPAD_AD_{name}"]
                if not isinstance(value, str) or not value or len(value) > 1024 or "\x00" in value:
                    raise ValueError("AD session verification requires approved lookup credentials.")
            if normalized_attempt_key(app.config["LAUNCHPAD_AD_LOOKUP_USERNAME"], directory).startswith("invalid:"):
                raise ValueError("AD session verification requires an approved lookup sign-in name.")
            try:
                interval = int(app.config["LAUNCHPAD_AD_REVALIDATE_SECONDS"])
            except (ValueError, TypeError):
                interval = 0
            if not 1 <= interval <= 300:
                raise ValueError("AD session revalidation must be from 1 to 300 seconds.")
            app.config["LAUNCHPAD_AD_REVALIDATE_SECONDS"] = interval
        validate_ad_state(app.config["LAUNCHPAD_AD_STATE_PATH"])
        app.config["LAUNCHPAD_IDENTITY_ISSUER"] = directory.issuer
        app.extensions["launchpad_ad_checks"] = {}
    else:
        authorization_origin = _configure_oidc_settings(app, allowed_hosts)
        app.config["LAUNCHPAD_IDENTITY_ISSUER"] = app.config["LAUNCHPAD_OIDC_ISSUER"]
    if controlled:
        session_seconds = _CONTROLLED_SESSION_SECONDS
    elif signin_only:
        hours = app.config.setdefault("LAUNCHPAD_SESSION_MAX_HOURS", os.environ.get("LAUNCHPAD_SESSION_MAX_HOURS", "4"))
        try:
            hours = int(hours)
        except (TypeError, ValueError):
            hours = 0
        if not 1 <= hours <= 8:
            raise ValueError("LAUNCHPAD_SESSION_MAX_HOURS must be a whole number from 1 to 8.")
        session_seconds = hours * 3600
    else:
        session_seconds = 28800
    app.config["LAUNCHPAD_SESSION_SECONDS"] = session_seconds
    app.config.update(
        DEBUG=False,
        SESSION_COOKIE_NAME="__Host-launchpad_session",
        SESSION_COOKIE_DOMAIN=None,
        SESSION_COOKIE_PATH="/",
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(seconds=session_seconds),
        TRUSTED_HOSTS=allowed_hosts,
        MAX_CONTENT_LENGTH=64 * 1024,
        MAX_FORM_MEMORY_SIZE=64 * 1024,
        MAX_FORM_PARTS=128,
    )
    if controlled:
        app.config["SESSION_REFRESH_EACH_REQUEST"] = False

    @app.after_request
    def protect_real_response(response):
        # The path is a constant, not request.path or the query string. The
        # reason is bounded to this allowlist, never an exception description,
        # header, form value, account identifier, cookie, or directory result.
        if controlled and request.method == "POST" and request.path == "/auth/login" and response.status_code >= 400:
            reason = getattr(g, "login_rejection_reason", "http_rejected")
            if reason == "http_rejected" and isinstance(request.routing_exception, SecurityError):
                # Anonymous access can return 401 before dispatch raises the
                # pending host-routing error. Record it without changing that
                # established authorization response or trusting request.host.
                reason = "trusted_host_rejected"
            if reason not in _LOGIN_REJECTION_REASONS:
                reason = "http_rejected"
            logging.getLogger("launchpad.login_diagnostic").warning(
                "timestamp=%s method=POST path=/auth/login status=%d reason=%s",
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                response.status_code, reason,
            )
        form_sources = "'self'"
        if authorization_origin and (request.endpoint == "auth_login" or current_account() is None):
            form_sources += " " + authorization_origin
        response.headers.update({
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            # Native form POSTs under no-referrer send Origin: null. Preserve
            # their same-origin value without relaxing CSRF/origin checks or
            # sending referrers to other sites. OIDC callback URLs may contain
            # code/state; keep those out of same-origin resource referrers too.
            "Referrer-Policy": "no-referrer" if request.endpoint == "auth_callback" else "same-origin",
            "Strict-Transport-Security": "max-age=86400",
            "Content-Security-Policy": "default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action " + form_sources,
        })
        return response

    @app.errorhandler(sqlite3.OperationalError)
    def unavailable_storage(error):
        g.login_rejection_reason = "storage_unavailable"
        app.logger.error("real_storage_unavailable endpoint=%s", request.endpoint)
        return error_page(503, "Training records are unavailable", "Keep any written answer on the previous page. Contact the service owner before retrying; do not assume this action was saved.")

    @app.errorhandler(Exception)
    def safe_error(error):
        if isinstance(error, HTTPException):
            if not getattr(g, "login_rejection_reason", None):
                if isinstance(error, SecurityError):
                    g.login_rejection_reason = "trusted_host_rejected"
                elif isinstance(error, RequestEntityTooLarge):
                    g.login_rejection_reason = "request_too_large"
                elif isinstance(error, BadRequest):
                    g.login_rejection_reason = "request_bad_request"
                else:
                    g.login_rejection_reason = "http_rejected"
            return error_page(error.code or 500, error.name, error.description)
        g.login_rejection_reason = "internal_error"
        reference = secrets.token_hex(6)
        app.logger.error("real_request_failed reference=%s type=%s endpoint=%s", reference, type(error).__name__, request.endpoint)
        return error_page(500, "This action could not be completed", f"Contact the service owner with reference {reference}. Do not assume this action was saved.")


def _configure_oidc_settings(app: Flask, allowed_hosts: list[str]) -> str:
    """Preserve the existing OIDC contract when that backend is selected."""
    for name in ("ISSUER", "CLIENT_ID", "CLIENT_SECRET", "REDIRECT_URI"):
        key = f"LAUNCHPAD_OIDC_{name}"
        app.config.setdefault(key, os.environ.get(key, ""))
        if not isinstance(app.config[key], str) or not app.config[key].strip():
            raise ValueError(f"Real-user mode requires {key}.")
    for name in ("ISSUER", "REDIRECT_URI"):
        value = app.config[f"LAUNCHPAD_OIDC_{name}"]
        try:
            parsed = urlsplit(value)
            valid = parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and parsed.port != 0
        except ValueError:
            valid = False
        if not valid or any(character.isspace() for character in value) or "\\" in value:
            raise ValueError("Identity URLs must use fixed HTTPS addresses without credentials, query or fragment.")
    issuer = urlsplit(app.config["LAUNCHPAD_OIDC_ISSUER"])
    authorization_origin = f"{issuer.scheme}://{issuer.netloc}"
    callback = urlsplit(app.config["LAUNCHPAD_OIDC_REDIRECT_URI"])
    if callback.path != "/auth/callback" or not any(callback.netloc == host or callback.hostname == host for host in allowed_hosts):
        raise ValueError("OIDC callback must be /auth/callback on a trusted application host.")
    if app.config.get("LAUNCHPAD_OIDC_CLIENT") is not None and not app.testing:
        raise ValueError("Injected identity clients are allowed only during isolated tests.")
    return authorization_origin


def _db_path() -> str:
    return str(current_app.config["LAUNCHPAD_DB_PATH"])


def _require_csrf() -> None:
    expected = session.get("csrf_token")
    tokens = request.form.getlist("csrf_token")
    if not isinstance(expected, str) or len(tokens) != 1 or not secrets.compare_digest(expected.encode(), tokens[0].encode()):
        if not isinstance(expected, str):
            g.login_rejection_reason = "csrf_after_session_invalid" if getattr(g, "login_session_invalid", False) else "csrf_session_absent"
        elif len(tokens) != 1:
            g.login_rejection_reason = "csrf_token_count"
        else:
            g.login_rejection_reason = "csrf_mismatch"
        abort(400, "This form expired. Reload the form and try again.")
    origin = request.headers.get("Origin")
    if origin:
        try:
            source = urlsplit(origin)
            valid = source.scheme == "https" and source.netloc == request.host and not source.username and not source.password
        except ValueError:
            valid = False
        if not valid:
            g.login_rejection_reason = "origin_rejected"
            abort(400, "Submit the form from this application.")


def current_account():
    return getattr(g, "account", None)


def require_staff_account():
    account = current_account()
    if not account or account["role"] not in {"mentor", "admin"}:
        abort(403)
    return account


def require_learner_account():
    account = current_account()
    if not account or account["role"] != "learner" or not account["learner_id"]:
        abort(403)
    return account


def install_real_auth(app: Flask) -> None:
    """Install identity verification and authorization only after DB validation."""
    ad_mode = app.config["LAUNCHPAD_AUTH_BACKEND"] == "ad"
    controlled = app.config["LAUNCHPAD_AD_SESSION_POLICY"] == "controlled_test"
    revalidating = ad_mode and app.config["LAUNCHPAD_AD_SESSION_POLICY"] == "revalidate"
    session_seconds = app.config["LAUNCHPAD_SESSION_SECONDS"]
    ended_notice = _CONTROLLED_SIGN_IN_NOTICE if controlled else session_ended_notice(session_seconds // 3600)
    if not ad_mode:
        configure_oidc(app)

    def verify_directory_session(account) -> bool:
        # Positive checks are short-lived, process-local, and empty on restart.
        # A directory failure never refreshes the cache or authorizes a write.
        checks = app.extensions["launchpad_ad_checks"]
        checked_at = time.monotonic()
        if checks.get(account["id"], 0) > checked_at:
            return True
        try:
            identity = revalidate_ad(
                account["subject"],
                bind_username=app.config["LAUNCHPAD_AD_LOOKUP_USERNAME"],
                bind_password=app.config["LAUNCHPAD_AD_LOOKUP_PASSWORD"],
            )
            if identity != {"issuer": account["issuer"], "subject": account["subject"]}:
                raise ADLoginError()
        except ADLoginError:
            checks.pop(account["id"], None)
            revoke_all_sessions(_db_path(), account_id=account["id"])
            return False
        if len(checks) >= 1024:
            checks.clear()  # Eviction requires another verified lookup, never admission.
        checks[account["id"]] = checked_at + app.config["LAUNCHPAD_AD_REVALIDATE_SECONDS"]
        return True

    @app.before_request
    def enforce_account_access():
        if controlled and session.permanent:
            session.permanent = False
        # Never restore attribution from a prior demo cookie or posted identity.
        for key in ("student_id", "student_display_name", "demo_student_token"):
            session.pop(key, None)
        g.account = None
        token = session.get("auth_session")
        if token:
            g.account = get_session_account(token, _db_path(), max_lifetime_seconds=session_seconds)
            if g.account and g.account["issuer"] != current_app.config["LAUNCHPAD_IDENTITY_ISSUER"]:
                revoke_auth_session(token, _db_path())
                g.account = None
            if g.account is None:
                g.login_session_invalid = True
                session.clear()
        if request.endpoint in _PUBLIC_ENDPOINTS:
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                _require_csrf()
            return
        if g.account is not None and revalidating and not verify_directory_session(g.account):
            g.account = None
            session.clear()
            return error_page(503, "Access could not be verified", "Sign in again later or contact IT. This request did not save training changes.")
        if g.account is None:
            # Only a session that existed and ended gets the "ended" notice.
            ended = controlled or getattr(g, "login_session_invalid", False)
            if request.method in {"GET", "HEAD"}:
                return render_template("login.html", login_notice=ended_notice if ended else None), 401
            if controlled:
                return error_page(401, "Sign in to continue the controlled test", _CONTROLLED_SIGN_IN_NOTICE)
            if ended:
                return error_page(401, "Sign in again to continue", ended_notice)
            abort(401)
        if _IDENTITY_FIELDS.intersection(request.args) or (
            request.method not in {"GET", "HEAD", "OPTIONS"} and _IDENTITY_FIELDS.intersection(request.form)
        ):
            abort(403, "Learner identity and permissions cannot be selected in a request.")
        if request.endpoint in {"supervisor", "supervisor_learner"}:
            require_staff_account()
        elif request.endpoint in _PERSONAL_ENDPOINTS:
            require_learner_account()
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            require_learner_account()
            if request.endpoint == "student_identity":
                abort(403, "Your training record is linked to your sign-in account.")
            _require_csrf()
            validate_pilot_submission(synthetic_only=controlled)

    @app.route("/auth/login", methods=["GET", "POST"])
    def auth_login():
        if request.method == "GET":
            return render_template("login.html")
        # A new sign-in cannot inherit progress state or a prior account session.
        revoke_auth_session(session.get("auth_session", ""), _db_path())
        session.clear()
        if ad_mode:
            try:
                usernames = request.form.getlist("username")
                passwords = request.form.getlist("password")
                if len(usernames) != 1 or len(passwords) != 1 or len(passwords[0]) > 1024:
                    g.login_rejection_reason = "login_fields_invalid"
                    raise ADLoginError()
                key = normalized_attempt_key(usernames[0])
                if not reserve_login_attempt(app.config["LAUNCHPAD_AD_STATE_PATH"], key, app.secret_key):
                    g.login_rejection_reason = "login_throttled"
                    response = error_page(429, "Sign-in is temporarily unavailable", "Wait a few minutes before trying again or contact IT.")
                    response.headers["Retry-After"] = "300"
                    return response
                if key.startswith("invalid:"):
                    g.login_rejection_reason = "login_identity_invalid"
                identity = authenticate_ad(usernames[0], passwords[0])
                if identity.get("issuer") != app.config["LAUNCHPAD_IDENTITY_ISSUER"]:
                    g.login_rejection_reason = "identity_issuer_mismatch"
                    raise ADLoginError()
                account = get_account_for_identity(identity["issuer"], identity["subject"], _db_path())
                if not account or not account["active"] or (account["role"] == "learner" and not account["learner_id"]):
                    g.login_rejection_reason = "enrollment_denied"
                    raise ADLoginError()
            except (ADLoginError, ADStateError) as error:
                if isinstance(error, ADStateError):
                    g.login_rejection_reason = "ad_state_unavailable"
                elif not getattr(g, "login_rejection_reason", None):
                    g.login_rejection_reason = "ad_denied_or_unavailable"
                return render_template("login.html", login_error="Sign-in could not be completed. Check your details or contact IT."), 401
            if controlled:
                session.permanent = False
                session["auth_session"] = create_auth_session(account["id"], _db_path(), lifetime_seconds=_CONTROLLED_SESSION_SECONDS, idle_timeout_seconds=_CONTROLLED_SESSION_SECONDS)
            elif not revalidating:
                session["auth_session"] = create_auth_session(account["id"], _db_path(), lifetime_seconds=session_seconds, idle_timeout_seconds=_IDLE_SESSION_SECONDS)
            else:
                session["auth_session"] = create_auth_session(account["id"], _db_path())
                checks = app.extensions["launchpad_ad_checks"]
                if len(checks) >= 1024:
                    checks.clear()
                checks[account["id"]] = time.monotonic() + app.config["LAUNCHPAD_AD_REVALIDATE_SECONDS"]
            return redirect(url_for("home"))
        try:
            return begin_login()
        except OIDCLoginError:
            app.logger.warning("real_signin_unavailable")
            return error_page(503, "Sign-in is unavailable", "Contact the service owner or start sign-in again later.")

    @app.get("/auth/callback")
    def auth_callback():
        if ad_mode:
            abort(404)
        try:
            identity = complete_login()
        except OIDCLoginError:
            session.clear()
            app.logger.warning("real_signin_rejected")
            return error_page(401, "Sign-in could not be verified", "Start sign-in again from the application.")
        if identity.get("issuer") != current_app.config["LAUNCHPAD_OIDC_ISSUER"]:
            session.clear()
            return error_page(401, "Sign-in could not be verified", "Start sign-in again from the application.")
        account = get_account_for_identity(identity["issuer"], identity["subject"], _db_path())
        if not account or not account["active"] or (account["role"] == "learner" and not account["learner_id"]):
            session.clear()
            app.logger.warning("real_signin_not_enrolled")
            return error_page(403, "Access has not been granted", "Contact the service owner about enrollment. Signing in does not create or claim a training record.")
        revoke_auth_session(session.get("auth_session", ""), _db_path())
        session.clear()
        session["auth_session"] = create_auth_session(account["id"], _db_path())
        return redirect(url_for("home"))

    @app.post("/auth/logout")
    def auth_logout():
        revoke_auth_session(session.get("auth_session", ""), _db_path())
        session.clear()
        return redirect(url_for("auth_login"))
