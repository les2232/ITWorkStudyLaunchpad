"""Actual local HTTPS OIDC and WSGI restart; no browser or live identity claims.

The temporary IdP signs synthetic tokens, checks one-use codes and PKCE, and
serves discovery/JWKS over a locally trusted TLS certificate. The application
runs through the real startup entrypoint and Gunicorn against a NEW database.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

try:
    import requests
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from joserfc import jwt
    from joserfc.jwk import RSAKey
except ImportError as error:
    raise ImportError("Real-login checks require requirements-real.txt in the isolated validation environment.") from error

from launchpad.accounts import enroll_account
from launchpad.demo import synthetic_beginner_responses
from launchpad.quizzes import get_module_quiz
from launchpad.real_data import initialize_real_database
from launchpad.storage import latest_assessment_result, latest_module_quiz_result, module_is_complete


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RealLoginProcessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="launchpad-real-login-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.directory.chmod(0o700)
        self.database = self.directory / "isolated-real.sqlite"
        self.certificate, self.private_key = self.make_certificate()
        self.signing_key = RSAKey.generate_key(parameters={"kid": "isolated-integration-key"})
        self.client_id = "isolated-real-client"
        self.client_secret = secrets.token_urlsafe(32)
        self.subject = "isolated-learner-subject"
        self.authorization_codes = {}
        self.idp_events = {"authorization": 0, "token": 0, "jwks": 0}
        self.app_process = None
        self.logs = tempfile.TemporaryFile(mode="w+t")
        self.addCleanup(self.logs.close)
        self.idp = self.start_tls_server(self.identity_handler())
        self.issuer = f"https://localhost:{self.idp.server_port}"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.wsgi_port = listener.getsockname()[1]
        self.proxy = self.start_tls_server(self.proxy_handler())
        self.base_url = f"https://127.0.0.1:{self.proxy.server_port}"
        self.callback = self.base_url + "/auth/callback"
        initialize_real_database(self.database)
        self.account = enroll_account(self.issuer, self.subject, "Isolated Learner", db_path=self.database)
        self.other_account = enroll_account(self.issuer, "other-isolated-subject", "Isolated Learner", db_path=self.database)
        self.environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("LAUNCHPAD_", "FLASK_", "RENDER", "GUNICORN"))
            and key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"}
        }
        self.environment.update({
            "LAUNCHPAD_REAL_MODE": "1", "LAUNCHPAD_DEMO_MODE": "0", "LAUNCHPAD_PILOT_MODE": "0",
            "LAUNCHPAD_DATA_DIR": str(self.directory), "LAUNCHPAD_DB_PATH": str(self.database),
            "LAUNCHPAD_SECRET_KEY": secrets.token_urlsafe(48),
            "LAUNCHPAD_TRUSTED_HOSTS": "127.0.0.1",
            "LAUNCHPAD_OIDC_ISSUER": self.issuer,
            "LAUNCHPAD_OIDC_CLIENT_ID": self.client_id,
            "LAUNCHPAD_OIDC_CLIENT_SECRET": self.client_secret,
            "LAUNCHPAD_OIDC_REDIRECT_URI": self.callback,
            "REQUESTS_CA_BUNDLE": str(self.certificate),
            "NO_PROXY": "localhost,127.0.0.1",
            "GUNICORN_CMD_ARGS": f"--bind=127.0.0.1:{self.wsgi_port} --graceful-timeout=5",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        self.browser = self.new_http_session()
        self.addCleanup(self.stop_app)

    def make_certificate(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Isolated Launchpad TLS")])
        now = datetime.now(timezone.utc)
        certificate = (
            x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]), critical=False)
            .sign(key, hashes.SHA256())
        )
        certificate_path = self.directory / "isolated-ca.pem"
        key_path = self.directory / "isolated-tls-key.pem"
        certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        key_path.chmod(0o600)
        return certificate_path, key_path

    def start_tls_server(self, handler):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.certificate, self.private_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()

        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.addCleanup(close)
        return server

    def new_http_session(self):
        client = requests.Session()
        client.trust_env = False
        client.verify = str(self.certificate)
        self.addCleanup(client.close)
        return client

    def identity_handler(self):
        test = self

        class IdentityHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def output(self, payload, status=200):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                address = urlsplit(self.path)
                if address.path == "/.well-known/openid-configuration":
                    return self.output({
                        "issuer": test.issuer,
                        "authorization_endpoint": test.issuer + "/authorize",
                        "token_endpoint": test.issuer + "/token",
                        "jwks_uri": test.issuer + "/keys",
                        "code_challenge_methods_supported": ["S256"],
                        "id_token_signing_alg_values_supported": ["RS256"],
                        "token_endpoint_auth_methods_supported": ["client_secret_basic"],
                    })
                if address.path == "/keys":
                    test.idp_events["jwks"] += 1
                    return self.output({"keys": [test.signing_key.as_dict()]})
                if address.path != "/authorize":
                    return self.output({"error": "not_found"}, 404)
                params = parse_qs(address.query)
                expected = {
                    "client_id": [test.client_id], "redirect_uri": [test.callback],
                    "response_type": ["code"], "scope": ["openid"], "code_challenge_method": ["S256"],
                }
                if any(params.get(name) != value for name, value in expected.items()) or any(
                    len(params.get(name, [])) != 1 or len(params[name][0]) < 32
                    for name in ("state", "nonce", "code_challenge")
                ):
                    return self.output({"error": "invalid_request"}, 400)
                test.idp_events["authorization"] += 1
                code = secrets.token_urlsafe(32)
                test.authorization_codes[code] = {"nonce": params["nonce"][0], "challenge": params["code_challenge"][0]}
                location = test.callback + "?" + urlencode({"code": code, "state": params["state"][0]})
                self.send_response(302)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self):
                if self.path != "/token":
                    return self.output({"error": "not_found"}, 404)
                auth = "Basic " + base64.b64encode(f"{test.client_id}:{test.client_secret}".encode()).decode()
                if not secrets.compare_digest(self.headers.get("Authorization", ""), auth):
                    return self.output({"error": "invalid_client"}, 401)
                form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode())
                if form.get("grant_type") != ["authorization_code"] or form.get("redirect_uri") != [test.callback]:
                    return self.output({"error": "invalid_request"}, 400)
                code = form.get("code", [""])[0]
                grant = test.authorization_codes.pop(code, None)
                verifier = form.get("code_verifier", [""])[0]
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                if grant is None or not secrets.compare_digest(grant["challenge"], challenge):
                    return self.output({"error": "invalid_grant"}, 400)
                test.idp_events["token"] += 1
                now = int(time.time())
                signed = jwt.encode({"alg": "RS256", "kid": "isolated-integration-key"}, {
                    "iss": test.issuer, "sub": test.subject, "aud": test.client_id,
                    "iat": now, "exp": now + 300, "nonce": grant["nonce"],
                    "roles": ["admin"], "name": "This claim cannot select a learner",
                }, test.signing_key)
                self.output({"access_token": "isolated-unused-access-token", "token_type": "Bearer", "id_token": signed})

        return IdentityHandler

    def proxy_handler(self):
        test = self

        class ProxyHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.forward()

            def do_POST(self):
                self.forward()

            def forward(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                connection = http.client.HTTPConnection("127.0.0.1", test.wsgi_port, timeout=10)
                try:
                    connection.request(self.command, self.path, body=body, headers=dict(self.headers))
                    response = connection.getresponse()
                    payload = response.read()
                    self.send_response(response.status)
                    for name, value in response.getheaders():
                        if name.lower() not in {"connection", "transfer-encoding", "server", "date", "content-length"}:
                            self.send_header(name, value)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                finally:
                    connection.close()

        return ProxyHandler

    def start_app(self):
        self.app_process = subprocess.Popen(
            [sys.executable, "-B", "scripts/start_real.py"], cwd=PROJECT_ROOT,
            env=self.environment, stdout=self.logs, stderr=self.logs,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.app_process.poll() is not None:
                self.fail("Isolated real-user startup failed; no production data or credentials were used.")
            connection = http.client.HTTPConnection("127.0.0.1", self.wsgi_port, timeout=0.2)
            try:
                connection.request("GET", "/")
                response = connection.getresponse()
                response.read()
                if response.status == 401:
                    return
            except (OSError, http.client.HTTPException):
                time.sleep(0.05)
            finally:
                connection.close()
        self.fail("Isolated real-user startup did not become ready within 10 seconds.")

    def stop_app(self):
        if self.app_process is not None:
            if self.app_process.poll() is None:
                self.app_process.terminate()
                try:
                    self.app_process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    self.app_process.kill()
                    self.app_process.wait(timeout=5)
            self.app_process = None

    def page(self, route, expected=200, client=None):
        response = (client or self.browser).get(self.base_url + route, timeout=10)
        self.assertEqual(response.status_code, expected, route)
        return response

    def csrf(self, route="/student"):
        response = self.page(route)
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
        self.assertIsNotNone(match, "Expected a protected form")
        return match.group(1)

    def post(self, route, fields, expected=200):
        response = self.browser.post(self.base_url + route, data=fields, headers={"Origin": self.base_url}, timeout=10)
        self.assertEqual(response.status_code, expected, route)
        return response

    def sign_in(self):
        token = self.csrf("/auth/login")
        # Follow the real HTTPS redirects through the isolated IdP and callback.
        response = self.post("/auth/login", {"csrf_token": token})
        self.assertEqual(response.url, self.base_url + "/")
        self.assertIn("Isolated Learner", self.page("/student").text)
        cookies = [cookie for cookie in self.browser.cookies if cookie.name == "__Host-launchpad_session"]
        self.assertEqual(len(cookies), 1)
        self.assertTrue(cookies[0].secure)
        self.assertEqual(cookies[0].path, "/")

    def assert_saved_progress(self):
        self.assertIn("Auto-scored starting point: 18%", self.page("/assessment-results").text)
        module = self.page("/modules/hardware_basics").text
        self.assertIn("Reading recorded as complete.", module)
        self.assertIn("3 / 3 correct (100%)", module)
        learner = self.account["learner_id"]
        self.assertEqual(latest_assessment_result(learner, "pre", self.database)["technical_score"], 18)
        result = latest_module_quiz_result(learner, "hardware_basics", self.database)
        self.assertEqual((result["score"], result["earned"], result["possible"]), (100, 3, 3))
        self.assertTrue(module_is_complete(learner, "hardware_basics", self.database))
        other = self.other_account["learner_id"]
        self.assertIsNone(latest_assessment_result(other, "pre", self.database))
        self.assertIsNone(latest_module_quiz_result(other, "hardware_basics", self.database))
        self.assertFalse(module_is_complete(other, "hardware_basics", self.database))

    def test_signed_login_scores_restart_and_logout_rejects_copied_cookie(self):
        self.start_app()
        self.page("/student", expected=401)
        self.sign_in()
        self.assertEqual(self.idp_events, {"authorization": 1, "token": 1, "jwks": 1})
        self.page("/supervisor", expected=403)  # A signed admin claim grants no app role.
        token = self.csrf()
        assessment = {**synthetic_beginner_responses(), "csrf_token": token}
        self.post("/pre-assessment", assessment)
        self.post("/modules/hardware_basics", {"completed": "1", "csrf_token": token})
        quiz = get_module_quiz("hardware_basics")
        self.post("/modules/hardware_basics/quiz", {**{question["id"]: question["answer"] for question in quiz["questions"]}, "csrf_token": token})
        self.page("/learn")
        self.assert_saved_progress()
        self.stop_app()
        self.start_app()
        self.assert_saved_progress()  # Same secure cookie and DB survive process restart.
        self.assertEqual(self.idp_events["token"], 1)
        copied_cookies = deepcopy(self.browser.cookies)
        self.post("/auth/logout", {"csrf_token": self.csrf()})
        self.page("/student", expected=401)
        replay = self.new_http_session()
        replay.cookies = copied_cookies
        self.page("/student", expected=401, client=replay)
        self.sign_in()  # New IdP flow can reopen only the same explicitly bound record.
        self.assert_saved_progress()
        self.assertEqual(self.idp_events["token"], 2)
        self.stop_app()
        self.logs.flush()
        self.logs.seek(0)
        log_text = self.logs.read()
        for value in (self.client_secret, self.environment["LAUNCHPAD_SECRET_KEY"], "isolated-unused-access-token", self.subject, "csrf_token="):
            self.assertNotIn(value, log_text)
        self.assertIn("Listening at: http://127.0.0.1:", log_text)


if __name__ == "__main__":
    unittest.main()
