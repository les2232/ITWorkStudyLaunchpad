"""Provider-neutral OIDC client; identity verification never grants app roles.

No identity provider is selected here. A deployment must supply an approved,
fixed issuer and client registration. Tokens remain request-local and never
enter Flask's signed, client-readable session cookie.
"""
from __future__ import annotations

import logging
import os
import secrets
import time
from collections.abc import Mapping
from urllib.parse import urlsplit

from flask import Flask, current_app, request, session


class OIDCLoginError(Exception):
    """Safe public error; upstream responses and token contents are omitted."""


_SETTINGS = ("ISSUER", "CLIENT_ID", "CLIENT_SECRET", "REDIRECT_URI")
_TRANSACTION_KEY = "launchpad_oidc_transaction"
_CLIENT_NAME = "launchpad_identity"
_FAILURE = "Sign-in could not be completed. Start sign-in again."


def _https_url(value: object, *, allow_query: bool = False) -> bool:
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if any(character.isspace() or ord(character) < 32 for character in value):
        return False
    try:
        parsed = urlsplit(value)
        return bool(
            parsed.scheme == "https" and parsed.hostname and parsed.port != 0
            and parsed.username is None and parsed.password is None
            and not parsed.fragment and (allow_query or not parsed.query)
            and "\\" not in value
        )
    except ValueError:
        return False


def configure_oidc(app: Flask) -> None:
    """Validate fixed settings without contacting an IdP or opening a database."""
    for name in _SETTINGS:
        key = f"LAUNCHPAD_OIDC_{name}"
        app.config.setdefault(key, os.environ.get(key, ""))
    issuer = app.config["LAUNCHPAD_OIDC_ISSUER"]
    callback = app.config["LAUNCHPAD_OIDC_REDIRECT_URI"]
    if not _https_url(issuer) or not _https_url(callback):
        raise ValueError("OIDC requires fixed HTTPS issuer and callback URLs without query strings or fragments.")
    if urlsplit(callback).path != "/auth/callback":
        raise ValueError("OIDC callback must use the configured /auth/callback route.")
    for name in ("CLIENT_ID", "CLIENT_SECRET"):
        value = app.config[f"LAUNCHPAD_OIDC_{name}"]
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise ValueError(f"OIDC requires LAUNCHPAD_OIDC_{name}.")
    injected_client = app.config.get("LAUNCHPAD_OIDC_CLIENT")
    if injected_client is not None:
        if not app.testing:
            raise ValueError("Injected OIDC clients are allowed only during isolated tests.")
        app.extensions["launchpad_oidc"] = injected_client
        return
    try:
        from authlib.integrations.flask_client import OAuth
    except ImportError:
        raise ValueError("Real-user mode requires the dependencies in requirements-real.txt.") from None
    # Authlib debug messages can include transient PKCE values. Never enable
    # those messages through an unrelated application's root debug log level.
    logging.getLogger("authlib").setLevel(logging.WARNING)
    oauth = OAuth(app)
    client = oauth.register(
        _CLIENT_NAME,
        client_id=app.config["LAUNCHPAD_OIDC_CLIENT_ID"],
        client_secret=app.config["LAUNCHPAD_OIDC_CLIENT_SECRET"],
        server_metadata_url=issuer.rstrip("/") + "/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid",
            "code_challenge_method": "S256",
            "token_endpoint_auth_method": "client_secret_basic",
            "default_timeout": 10,
        },
    )
    app.extensions["launchpad_oidc"] = client


def _client():
    return current_app.extensions["launchpad_oidc"]


def _validated_metadata(client) -> None:
    metadata = client.load_server_metadata()
    if metadata.get("issuer") != current_app.config["LAUNCHPAD_OIDC_ISSUER"]:
        raise OIDCLoginError(_FAILURE)
    for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not _https_url(metadata.get(name), allow_query=True):
            raise OIDCLoginError(_FAILURE)
    issuer_origin = urlsplit(current_app.config["LAUNCHPAD_OIDC_ISSUER"])
    authorization_origin = urlsplit(metadata["authorization_endpoint"])
    if (
        issuer_origin.scheme, issuer_origin.hostname, issuer_origin.port or 443
    ) != (
        authorization_origin.scheme, authorization_origin.hostname, authorization_origin.port or 443
    ):
        # Login form CSP permits only the explicitly configured issuer origin.
        # A provider using a different authorization origin requires review.
        raise OIDCLoginError(_FAILURE)
    if "S256" not in metadata.get("code_challenge_methods_supported", []):
        raise OIDCLoginError(_FAILURE)
    if "RS256" not in metadata.get("id_token_signing_alg_values_supported", []):
        raise OIDCLoginError(_FAILURE)
    if "client_secret_basic" not in metadata.get("token_endpoint_auth_methods_supported", ["client_secret_basic"]):
        raise OIDCLoginError(_FAILURE)
    # RS256 is the standard OIDC signing algorithm. An approved provider using
    # another algorithm needs an explicit reviewed integration change.
    metadata["id_token_signing_alg_values_supported"] = ["RS256"]


def clear_login_transaction() -> None:
    session.pop(_TRANSACTION_KEY, None)
    for key in list(session):
        if key.startswith(f"_state_{_CLIENT_NAME}_"):
            session.pop(key, None)


def begin_login():
    """Start a single pending code flow with fresh state, nonce and PKCE."""
    clear_login_transaction()
    try:
        client = _client()
        _validated_metadata(client)
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        session[_TRANSACTION_KEY] = {"state": state, "nonce": nonce, "created": time.time()}
        return client.authorize_redirect(
            current_app.config["LAUNCHPAD_OIDC_REDIRECT_URI"],
            state=state, nonce=nonce,
        )
    except Exception:
        clear_login_transaction()
        raise OIDCLoginError(_FAILURE) from None


def complete_login() -> dict[str, str]:
    """Return only validated issuer/subject; roles and record binding are local."""
    transaction = session.pop(_TRANSACTION_KEY, None)
    try:
        if not isinstance(transaction, dict):
            raise OIDCLoginError(_FAILURE)
        state = request.args.getlist("state")
        code = request.args.getlist("code")
        created = transaction.get("created")
        if (
            request.method != "GET" or len(state) != 1 or len(code) != 1 or not code[0]
            or request.args.get("error")
            or not isinstance(created, (int, float))
            or not 0 <= time.time() - created <= 600
            or not secrets.compare_digest(state[0], transaction.get("state", ""))
        ):
            raise OIDCLoginError(_FAILURE)
        client = _client()
        _validated_metadata(client)
        token = client.authorize_access_token(
            claims_options={
                "iss": {"essential": True, "value": current_app.config["LAUNCHPAD_OIDC_ISSUER"]},
                "aud": {"essential": True, "value": current_app.config["LAUNCHPAD_OIDC_CLIENT_ID"]},
            },
            leeway=30,
        )
        claims = token.get("userinfo")
        if not token.get("id_token") or not isinstance(claims, Mapping):
            raise OIDCLoginError(_FAILURE)
        issuer, subject = claims.get("iss"), claims.get("sub")
        audience = claims.get("aud")
        client_id = current_app.config["LAUNCHPAD_OIDC_CLIENT_ID"]
        if isinstance(audience, str):
            audience = [audience]
        if (
            issuer != current_app.config["LAUNCHPAD_OIDC_ISSUER"]
            or not isinstance(subject, str) or not subject or len(subject) > 255
            or any(ord(character) < 33 or ord(character) > 126 for character in subject)
            or not isinstance(audience, list) or client_id not in audience
            or not all(isinstance(value, str) for value in audience)
            or (len(audience) > 1 and claims.get("azp") != client_id)
            or ("azp" in claims and claims["azp"] != client_id)
            # Some providers advertise nonce_supported=false; that must never
            # bypass the transaction binding required by this application.
            or claims.get("nonce") != transaction.get("nonce")
        ):
            raise OIDCLoginError(_FAILURE)
        return {"issuer": issuer, "subject": subject}
    except Exception:
        raise OIDCLoginError(_FAILURE) from None
    finally:
        clear_login_transaction()
