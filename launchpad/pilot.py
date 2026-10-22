"""Opt-in controls for a facilitated, synthetic-only hosted pilot.

This shared invitation gate is deliberately not learner identity or role-based
access. All invitees can select any synthetic persona and view mentor evidence.
"""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
from datetime import timedelta
from html import escape
from urllib.parse import urlsplit

from flask import Flask, Response, abort, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash

from .assessment import all_questions, load_assessment
from .quizzes import get_module_quiz
from .scenarios import get_scenario, is_guided_scenario


def configure_pilot(app: Flask) -> None:
    """Validate before opening a database; register gate before other hooks."""
    app.config.setdefault("LAUNCHPAD_PILOT_MODE", os.environ.get(
        "LAUNCHPAD_PILOT_MODE", ""
    ).lower() in {"1", "true", "yes"})
    for key in ("LAUNCHPAD_PILOT_USERNAME", "LAUNCHPAD_PILOT_PASSWORD_HASH"):
        app.config.setdefault(key, os.environ.get(key, ""))
    hosts = os.environ.get("LAUNCHPAD_TRUSTED_HOSTS") or os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
    app.config.setdefault("LAUNCHPAD_TRUSTED_HOSTS", hosts)
    if not app.config["LAUNCHPAD_PILOT_MODE"]:
        return
    if not app.config["LAUNCHPAD_DEMO_MODE"]:
        raise ValueError("Hosted pilot requires guarded synthetic demo mode.")
    secret = app.config.get("SECRET_KEY")
    if not isinstance(secret, str) or len(secret.strip()) < 32:
        raise ValueError("Hosted pilot requires a random secret of at least 32 characters.")
    username = app.config["LAUNCHPAD_PILOT_USERNAME"]
    password_hash = app.config["LAUNCHPAD_PILOT_PASSWORD_HASH"]
    if not isinstance(username, str) or not username or len(username) > 128 or ":" in username:
        raise ValueError("Hosted pilot requires a valid invitation username.")
    if not isinstance(password_hash, str) or not re.fullmatch(
        r"scrypt:32768:8:1\$[A-Za-z0-9]{16}\$[a-f0-9]{128}", password_hash
    ):
        raise ValueError("Hosted pilot requires a Werkzeug default scrypt password hash.")
    hosts = app.config["LAUNCHPAD_TRUSTED_HOSTS"]
    if not isinstance(hosts, str):
        raise ValueError("Hosted pilot requires exact trusted host names.")
    allowed_hosts = [host.strip() for host in hosts.split(",") if host.strip()]
    if not allowed_hosts or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*(?::[0-9]+)?", host) for host in allowed_hosts):
        raise ValueError("Hosted pilot requires exact trusted host names.")
    app.config.update(
        DEBUG=False,
        SESSION_COOKIE_NAME="launchpad_pilot_session",
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        TRUSTED_HOSTS=allowed_hosts,
        MAX_CONTENT_LENGTH=64 * 1024,
        MAX_FORM_MEMORY_SIZE=64 * 1024,
        MAX_FORM_PARTS=128,
    )

    @app.before_request
    def require_invitation():
        auth = request.authorization
        if not (
            auth and auth.type == "basic"
            and secrets.compare_digest((auth.username or "").encode(), username.encode())
            and check_password_hash(password_hash, auth.password or "")
        ):
            return Response(
                "Invitation required for this synthetic pilot.", 401,
                {"WWW-Authenticate": 'Basic realm="Launchpad pilot", charset="UTF-8"'},
                mimetype="text/plain",
            )
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            token = request.form.get("csrf_token", "")
            expected = session.get("csrf_token", "")
            if not expected or not secrets.compare_digest(token.encode(), expected.encode()):
                abort(400, "This form has expired. Return to the form, reload it, and try again.")
            origin = request.headers.get("Origin")
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme != "https" or parsed.netloc != request.host:
                    abort(400, "Submit the form from this pilot site.")
            validate_pilot_submission()

    @app.after_request
    def protect_pilot_response(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Strict-Transport-Security"] = "max-age=86400"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @app.errorhandler(sqlite3.OperationalError)
    def storage_unavailable(error):
        # Never include SQLite messages, request bodies, cookies or credentials.
        app.logger.error("pilot_storage_unavailable endpoint=%s", request.endpoint)
        return error_page(
            503, "Progress could not be saved or loaded",
            "Keep any written answers on the previous page. Ask the facilitator to check storage before retrying. Do not assume this attempt was saved.",
        )

    @app.errorhandler(Exception)
    def safe_error(error):
        if isinstance(error, HTTPException):
            return error_page(error.code or 500, error.name, error.description)
        incident = secrets.token_hex(6)
        app.logger.error("pilot_error reference=%s type=%s endpoint=%s", incident, type(error).__name__, request.endpoint)
        return error_page(500, "This action could not be completed", f"Ask the facilitator for help and give reference {incident}. Do not assume this attempt was saved.")


def error_page(status: int, title: str, message: str) -> Response:
    # Standalone: rendering the app shell would try to read the failing database.
    return Response(
        '<!doctype html><html lang="en"><meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{escape(title)}</title><main><h1>{escape(title)}</h1>'
        f'<p>{escape(message)}</p><p><a href="/">Return to Launchpad</a></p></main></html>',
        status=status, mimetype="text/html",
    )


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_pilot_submission(*, synthetic_only: bool = True) -> None:
    """Match existing form requirements without changing scoring rules."""
    form = request.form
    endpoint = request.endpoint
    if any(len(value) > 8000 for _, values in form.lists() for value in values):
        abort(400, "An answer is too long. Use at most 8,000 characters per field." + (" Use invented details only." if synthetic_only else ""))
    if endpoint in {"pre_assessment", "post_assessment"}:
        if endpoint == "pre_assessment" and form.get("synthetic_preset"):
            return  # Route enforces the fixed persona and preset value.
        assessment = load_assessment("pre_assessment_v1" if endpoint == "pre_assessment" else "post_assessment_v1")
        for question in all_questions(assessment):
            values = form.getlist(question["id"])
            kind = question["type"]
            if kind == "select_all":
                allowed = {str(option["value"]) for option in question["options"]}
                if len(values) != len(set(values)) or not set(values) <= allowed:
                    abort(400, "Choose only the listed assessment options.")
                none_value = question.get("scoring", {}).get("none_value")
                if none_value in values and len(values) > 1:
                    abort(400, "Choose either none or the applicable assessment options.")
            elif len(values) != 1 or not values[0].strip():
                abort(400, "Complete every required assessment question before submitting.")
            elif kind in {"multiple_choice", "rating"}:
                allowed = set("12345") if kind == "rating" else {str(option["value"]) for option in question["options"]}
                if values[0] not in allowed:
                    abort(400, "Choose one of the listed assessment options.")
    elif endpoint == "module_quiz":
        quiz = get_module_quiz(request.view_args["slug"])
        if quiz:
            for question in quiz["questions"]:
                values = form.getlist(question["id"])
                if len(values) != 1 or values[0] not in {str(choice["value"]) for choice in question["choices"]}:
                    abort(400, "Answer each knowledge-check question using the listed choices.")
    elif endpoint in {"stuck", "ask", "scenario_detail"}:
        fields = {"stuck": ("trying_to_do", "what_happened", "already_checked", "current_blocker"), "ask": ("question",), "scenario_detail": ("student_response",)}[endpoint]
        if endpoint == "scenario_detail":
            scenario = get_scenario(request.view_args["scenario_id"])
            if scenario is None or is_guided_scenario(scenario):
                return
        if any(len(form.getlist(key)) != 1 or not form.get(key, "").strip() for key in fields):
            abort(400, "Complete the required fields before submitting." + (" Use invented details only." if synthetic_only else ""))
    elif endpoint == "update_help_request_status" and form.getlist("status") not in (["open"], ["resolved"]):
        abort(400, "Choose a valid help-request status.")
    elif endpoint == "module_reader" and form.getlist("completed") not in (["0"], ["1"]):
        abort(400, "Choose a valid completion action.")
