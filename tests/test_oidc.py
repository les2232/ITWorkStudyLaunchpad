"""Offline IdP transport with real Authlib/JWT validation, never a live account."""
import base64
import hashlib
import json
import time
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from flask import Flask, jsonify

try:
    from joserfc import jwt
    from joserfc.jwk import RSAKey
    from requests import Response
except ImportError as error:
    raise ImportError("OIDC checks require requirements-real.txt; run the full suite in its isolated environment.") from error

from launchpad.oidc import OIDCLoginError, begin_login, complete_login, configure_oidc


class OIDCClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.signing_key = RSAKey.generate_key(parameters={"kid": "isolated-key"})
        cls.wrong_key = RSAKey.generate_key(parameters={"kid": "isolated-key"})

    def setUp(self):
        self.config = {
            "TESTING": True,
            "SECRET_KEY": "isolated-oidc-test-secret-at-least-32-chars",
            "LAUNCHPAD_OIDC_ISSUER": "https://identity.example/tenant",
            "LAUNCHPAD_OIDC_CLIENT_ID": "isolated-client",
            "LAUNCHPAD_OIDC_CLIENT_SECRET": "isolated-client-secret",
            "LAUNCHPAD_OIDC_REDIRECT_URI": "https://launchpad.example/auth/callback",
        }
        self.metadata = {
            "issuer": self.config["LAUNCHPAD_OIDC_ISSUER"],
            "authorization_endpoint": "https://identity.example/authorize",
            "token_endpoint": "https://identity.example/token",
            "jwks_uri": "https://identity.example/keys",
            "code_challenge_methods_supported": ["S256"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic"],
        }
        self.claim_changes = {}
        self.omit_claims = []
        self.use_wrong_key = False
        self.omit_id_token = False
        self.token_override = None
        self.calls = []
        self.authorization = None
        self.code_used = False
        self.app = self.make_app()
        self.client = self.app.test_client()
        transport = patch("requests.sessions.Session.send", autospec=True, side_effect=self.transport)
        transport.start()
        self.addCleanup(transport.stop)

    def make_app(self, **changes):
        app = Flask(__name__)
        app.config.update({**self.config, **changes})
        configure_oidc(app)

        @app.post("/auth/login")
        def login():
            try:
                return begin_login()
            except OIDCLoginError as error:
                return str(error), 401

        @app.get("/auth/callback")
        def callback():
            try:
                return jsonify(complete_login())
            except OIDCLoginError as error:
                return str(error), 401

        return app

    def response(self, request, payload, status=200):
        response = Response()
        response.status_code = status
        response._content = json.dumps(payload).encode()
        response.headers["Content-Type"] = "application/json"
        response.request = request
        response.url = request.url
        return response

    def transport(self, transport_session, request, **kwargs):
        self.calls.append((request.method, request.url))
        self.assertEqual(kwargs.get("timeout"), 10)
        if request.url.endswith("/.well-known/openid-configuration"):
            return self.response(request, self.metadata)
        if request.url == self.metadata["jwks_uri"]:
            return self.response(request, {"keys": [self.signing_key.as_dict()]})
        if request.url == self.metadata["token_endpoint"]:
            self.assertEqual(request.method, "POST")
            body = request.body.decode() if isinstance(request.body, bytes) else request.body
            form = parse_qs(body)
            self.assertEqual(form["grant_type"], ["authorization_code"])
            self.assertEqual(form["redirect_uri"], [self.config["LAUNCHPAD_OIDC_REDIRECT_URI"]])
            self.assertEqual(form["code"], ["isolated-code"])
            self.assertIn("Basic ", request.headers["Authorization"])
            verifier = form["code_verifier"][0]
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            self.assertEqual(challenge, self.authorization["code_challenge"][0])
            if self.code_used:
                return self.response(request, {"error": "invalid_grant"}, 400)
            self.code_used = True
            now = int(time.time())
            claims = {
                "iss": self.config["LAUNCHPAD_OIDC_ISSUER"], "sub": "isolated-subject",
                "aud": self.config["LAUNCHPAD_OIDC_CLIENT_ID"], "iat": now, "exp": now + 300,
                "nonce": self.authorization["nonce"][0],
                "name": "Untrusted display name", "email": "invented@example.invalid",
                "roles": ["admin"],
                **self.claim_changes,
            }
            for claim in self.omit_claims:
                claims.pop(claim, None)
            key = self.wrong_key if self.use_wrong_key else self.signing_key
            encoded = jwt.encode({"alg": "RS256", "kid": "isolated-key"}, claims, key)
            payload = {"access_token": "isolated-access-token", "token_type": "Bearer", "id_token": encoded}
            if self.omit_id_token:
                payload.pop("id_token")
            if self.token_override is not None:
                payload = self.token_override
            return self.response(request, payload)
        self.fail("Unexpected external request in isolated OIDC check")

    def start(self):
        response = self.client.post("/auth/login?next=https://attacker.invalid/", base_url="https://launchpad.example")
        self.assertEqual(response.status_code, 302)
        self.authorization = parse_qs(urlsplit(response.location).query)
        return response

    def finish(self, **query):
        values = {"code": "isolated-code", "state": self.authorization["state"][0], **query}
        return self.client.get("/auth/callback", query_string=values, base_url="https://launchpad.example")

    def test_code_flow_validates_signed_identity_and_limits_claims(self):
        response = self.start()
        self.assertEqual(urlsplit(response.location).netloc, "identity.example")
        self.assertEqual(self.authorization["response_type"], ["code"])
        self.assertEqual(self.authorization["scope"], ["openid"])
        self.assertEqual(self.authorization["redirect_uri"], [self.config["LAUNCHPAD_OIDC_REDIRECT_URI"]])
        self.assertEqual(self.authorization["code_challenge_method"], ["S256"])
        self.assertNotIn("client_secret", self.authorization)
        response = self.finish()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"issuer": self.config["LAUNCHPAD_OIDC_ISSUER"], "subject": "isolated-subject"})
        with self.client.session_transaction(base_url="https://launchpad.example") as saved:
            serialized = json.dumps(dict(saved))
            self.assertNotIn("isolated-access-token", serialized)
            self.assertNotIn("Untrusted display name", serialized)
            self.assertNotIn("roles", serialized)
            self.assertNotIn("oidc", serialized)

    def test_state_is_bound_to_the_browser_and_rejected_before_token_exchange(self):
        self.start()
        before = len(self.calls)
        stranger = self.app.test_client()
        response = stranger.get("/auth/callback", query_string={"code": "isolated-code", "state": self.authorization["state"][0]}, base_url="https://launchpad.example")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(len(self.calls), before)
        self.assertEqual(self.finish(state="wrong-state").status_code, 401)
        self.assertEqual(len(self.calls), before)

    def test_valid_callback_is_single_use(self):
        self.start()
        self.assertEqual(self.finish().status_code, 200)
        calls = len(self.calls)
        self.assertEqual(self.finish().status_code, 401)
        self.assertEqual(len(self.calls), calls)

    def test_pending_transaction_expires(self):
        self.start()
        with self.client.session_transaction(base_url="https://launchpad.example") as saved:
            transaction = dict(saved["launchpad_oidc_transaction"])
            transaction["created"] -= 601
            saved["launchpad_oidc_transaction"] = transaction
        self.assertEqual(self.finish().status_code, 401)
        self.assertFalse(self.code_used)

    def test_new_sign_in_replaces_old_pending_state_and_nonce(self):
        self.start()
        previous = self.authorization
        self.start()
        self.assertNotEqual(previous["state"], self.authorization["state"])
        self.assertNotEqual(previous["nonce"], self.authorization["nonce"])
        self.assertNotEqual(previous["code_challenge"], self.authorization["code_challenge"])
        self.assertEqual(self.finish(state=previous["state"][0]).status_code, 401)
        self.assertFalse(self.code_used)

    def test_rejects_bad_issuer_audience_nonce_expiry_and_authorized_party(self):
        cases = (
            {"iss": "https://other.example/tenant"},
            {"aud": "other-client"},
            {"nonce": "other-nonce"},
            {"exp": int(time.time()) - 60},
            {"iat": int(time.time()) + 120},
            {"azp": "other-client"},
            {"aud": ["isolated-client", "other-client"]},
            {"sub": ""},
            {"sub": 123},
            {"sub": " "},
            {"nonce_supported": False, "nonce": "other-nonce"},
        )
        for claims in cases:
            with self.subTest(claims=claims):
                self.code_used = False
                self.claim_changes = claims
                self.start()
                self.assertEqual(self.finish().status_code, 401)

    def test_rejects_missing_identity_claims(self):
        for claim in ("iss", "sub", "aud", "exp", "iat", "nonce"):
            with self.subTest(claim=claim):
                self.code_used = False
                self.omit_claims = [claim]
                self.start()
                self.assertEqual(self.finish().status_code, 401)

    def test_multi_audience_token_requires_this_clients_authorized_party(self):
        self.claim_changes = {"aud": ["isolated-client", "other-client"], "azp": "isolated-client"}
        self.start()
        self.assertEqual(self.finish().status_code, 200)

    def test_rejects_invalid_signature(self):
        self.use_wrong_key = True
        self.start()
        self.assertEqual(self.finish().status_code, 401)

    def test_rejects_oauth_response_without_an_id_token(self):
        self.omit_id_token = True
        self.start()
        self.assertEqual(self.finish().status_code, 401)

    def test_provider_error_is_safe_and_ends_pending_login(self):
        self.start()
        response = self.finish(error="access_denied", error_description="synthetic-private-provider-detail")
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(b"synthetic-private-provider-detail", response.data)
        self.assertFalse(self.code_used)
        self.assertEqual(self.finish().status_code, 401)

    def test_metadata_issuer_mismatch_fails_before_redirect(self):
        self.metadata["issuer"] = "https://different.example/"
        response = self.client.post("/auth/login", base_url="https://launchpad.example")
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("Location", response.headers)

    def test_requires_advertised_pkce_and_safe_provider_endpoints(self):
        for field, value in (
            ("code_challenge_methods_supported", ["plain"]),
            ("id_token_signing_alg_values_supported", ["HS256"]),
            ("token_endpoint_auth_methods_supported", ["none"]),
            ("authorization_endpoint", "https://other.example/authorize"),
            ("authorization_endpoint", "https://identity.example:8443/authorize"),
            ("token_endpoint", "http://identity.example/token"),
            ("jwks_uri", "https://user:password@identity.example/keys"),
        ):
            with self.subTest(field=field):
                self.app = self.make_app()
                self.client = self.app.test_client()
                previous = self.metadata[field]
                self.metadata[field] = value
                response = self.client.post("/auth/login", base_url="https://launchpad.example")
                self.assertEqual(response.status_code, 401)
                self.metadata[field] = previous

    def test_configuration_is_required_before_network_access(self):
        for key, value in (
            ("LAUNCHPAD_OIDC_ISSUER", ""),
            ("LAUNCHPAD_OIDC_ISSUER", "http://identity.example"),
            ("LAUNCHPAD_OIDC_ISSUER", "https://identity.example?tenant=example"),
            ("LAUNCHPAD_OIDC_REDIRECT_URI", "https://launchpad.example/other-route"),
            ("LAUNCHPAD_OIDC_REDIRECT_URI", "https://launchpad.example/auth/callback#fragment"),
            ("LAUNCHPAD_OIDC_CLIENT_ID", ""),
            ("LAUNCHPAD_OIDC_CLIENT_SECRET", ""),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.make_app(**{key: value})
        self.assertFalse(self.calls)

    def test_injected_client_is_never_accepted_in_production(self):
        with self.assertRaisesRegex(ValueError, "only during isolated tests"):
            self.make_app(TESTING=False, LAUNCHPAD_OIDC_CLIENT=object())

    def test_duplicate_callback_parameters_are_rejected(self):
        self.start()
        response = self.client.get("/auth/callback", query_string=[("state", self.authorization["state"][0]), ("state", "other-state"), ("code", "isolated-code")], base_url="https://launchpad.example")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(self.code_used)


if __name__ == "__main__":
    unittest.main()
