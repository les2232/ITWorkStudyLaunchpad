"""Exercise the prepared VM vhost with disposable non-root Nginx/Gunicorn.

Only high loopback ports, a NEW test database, a temporary Unix socket and a
locally generated TLS certificate are used. Nothing under /etc or the existing
certificate directory is read or changed. No identity provider is contacted;
OIDC is exercised separately by test_real_login_flow.
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from flask import Flask
import requests

import test_real_login_flow as tls_fixture
from launchpad.accounts import create_auth_session, enroll_account
from launchpad.demo import synthetic_beginner_responses
from launchpad.quizzes import get_module_quiz
from launchpad.real_data import initialize_real_database
from launchpad.storage import latest_assessment_result, latest_module_quiz_result, module_is_complete


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Exercise the proposed cutover hostname without resolving or contacting it.
# Requests connect only to the disposable fixture's high loopback TLS port.
CANONICAL_HOST = "lesliec.ccaurora.edu"


class VMProxyIntegrationTests(unittest.TestCase):
    def setUp(self):
        if not sys.platform.startswith("linux") or not Path("/proc/self/fd").is_dir():
            self.skipTest("The VM proxy/socket check requires Linux process metadata.")
        if os.geteuid() == 0:
            self.skipTest("Refusing to run the application or temporary Nginx as root.")
        self.nginx_binary = shutil.which("nginx")
        if not self.nginx_binary:
            self.skipTest("Nginx is unavailable; the prepared VM proxy remains unverified here.")
        temporary = tempfile.TemporaryDirectory(prefix="launchpad-vm-proxy-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.directory.chmod(0o700)
        # Reuse only certificate generation; no servers or existing paths from
        # the independent complete-login fixture are used.
        self.certificate, self.private_key = tls_fixture.RealLoginProcessTests.make_certificate(self)
        self.socket_path = self.directory / "gunicorn.sock"
        self.database = self.directory / "isolated.sqlite"
        initialize_real_database(self.database)
        self.issuer = "https://isolated-identity.example.invalid"
        self.account = enroll_account(self.issuer, "isolated-proxy-subject", "Isolated Proxy Learner", db_path=self.database)
        self.other = enroll_account(self.issuer, "isolated-other-subject", "Isolated Other Learner", db_path=self.database)
        self.csrf = secrets.token_urlsafe(32)
        self.signing_secret = secrets.token_urlsafe(48)
        self.session_handle = create_auth_session(self.account["id"], self.database)
        signer_app = Flask("isolated-cookie-fixture")
        signer_app.secret_key = self.signing_secret
        self.cookie = signer_app.session_interface.get_signing_serializer(signer_app).dumps({
            "auth_session": self.session_handle, "csrf_token": self.csrf,
        })
        self.http_port, self.https_port = self.reserve_test_ports()
        self.base_url = f"https://127.0.0.1:{self.https_port}"
        self.client = requests.Session()
        self.client.trust_env = False
        self.client.verify = str(self.certificate)
        self.addCleanup(self.client.close)
        self.app_logs = tempfile.TemporaryFile(mode="w+t")
        self.nginx_logs = tempfile.TemporaryFile(mode="w+t")
        self.addCleanup(self.app_logs.close)
        self.addCleanup(self.nginx_logs.close)
        self.environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("LAUNCHPAD_", "FLASK_", "RENDER", "GUNICORN"))
            and key.upper() not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"}
        }
        self.environment.update({
            "LAUNCHPAD_REAL_MODE": "1", "LAUNCHPAD_DEMO_MODE": "0", "LAUNCHPAD_PILOT_MODE": "0",
            "LAUNCHPAD_DATA_DIR": str(self.directory), "LAUNCHPAD_DB_PATH": str(self.database),
            "LAUNCHPAD_SECRET_KEY": self.signing_secret, "LAUNCHPAD_TRUSTED_HOSTS": CANONICAL_HOST,
            "LAUNCHPAD_OIDC_ISSUER": self.issuer, "LAUNCHPAD_OIDC_CLIENT_ID": "isolated-proxy-client",
            "LAUNCHPAD_OIDC_CLIENT_SECRET": secrets.token_urlsafe(32),
            "LAUNCHPAD_OIDC_REDIRECT_URI": f"https://{CANONICAL_HOST}/auth/callback",
            "GUNICORN_CMD_ARGS": f"--bind=unix:{self.socket_path} --umask=0o117 --worker-tmp-dir={self.directory} --graceful-timeout=5",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        self.prepare_nginx_configuration()
        validation = subprocess.run(
            [self.nginx_binary, "-t", "-p", str(self.directory) + "/", "-c", str(self.nginx_config)],
            env=self.environment, stdout=self.nginx_logs, stderr=self.nginx_logs,
            check=False, timeout=10,
        )
        self.assertEqual(validation.returncode, 0, "The prepared vhost failed isolated Nginx validation.")
        self.app_process = subprocess.Popen(
            [sys.executable, "-B", "scripts/start_real.py"], cwd=PROJECT_ROOT, env=self.environment,
            stdout=self.app_logs, stderr=self.app_logs, start_new_session=True,
        )
        self.addCleanup(self.stop_process, self.app_process)
        self.wait_for_socket()
        self.nginx_process = subprocess.Popen(
            [self.nginx_binary, "-p", str(self.directory) + "/", "-c", str(self.nginx_config), "-g", "daemon off;"],
            env=self.environment, stdout=self.nginx_logs, stderr=self.nginx_logs, start_new_session=True,
        )
        self.addCleanup(self.stop_process, self.nginx_process)
        self.wait_for_proxy()

    @staticmethod
    def reserve_test_ports():
        with socket.socket() as first, socket.socket() as second:
            first.bind(("127.0.0.1", 0))
            second.bind(("127.0.0.1", 0))
            return first.getsockname()[1], second.getsockname()[1]

    def prepare_nginx_configuration(self):
        # Preserve every proxy/security directive. Only listener addresses/ports,
        # certificate, log and socket paths change for the isolated fixture.
        source = (PROJECT_ROOT / "deploy/vm/launchpad.nginx.conf").read_text()
        substitutions = {
            "    listen 80;": f"    listen 127.0.0.1:{self.http_port};",
            "    listen [::]:80;\n": "",
            "    listen 443 ssl http2;": f"    listen 127.0.0.1:{self.https_port} ssl http2;",
            "    listen [::]:443 ssl http2;\n": "",
            "/opt/project/certs/fullchain.pem": str(self.certificate),
            "/opt/project/certs/ccaurora.key": str(self.private_key),
            "/var/log/nginx/launchpad.access.log": str(self.directory / "access.log"),
            "/run/launchpad/gunicorn.sock": str(self.socket_path),
        }
        for original, replacement in substitutions.items():
            self.assertIn(original, source, "Review test isolation when prepared vhost paths/listeners change.")
            source = source.replace(original, replacement)
        vhost = self.directory / "vhost.conf"
        vhost.write_text(source)
        self.nginx_config = self.directory / "nginx.conf"
        self.nginx_config.write_text(
            "worker_processes 1;\n"
            f"pid {self.directory}/nginx.pid;\n"
            f"error_log {self.directory}/main-error.log crit;\n"
            "events { worker_connections 64; }\n"
            "http {\n"
            f"  client_body_temp_path {self.directory}/body;\n"
            f"  proxy_temp_path {self.directory}/proxy;\n"
            f"  fastcgi_temp_path {self.directory}/fastcgi;\n"
            f"  uwsgi_temp_path {self.directory}/uwsgi;\n"
            f"  scgi_temp_path {self.directory}/scgi;\n"
            f"  include {vhost};\n"
            "}\n"
        )

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)

    def wait_for_socket(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.app_process.poll() is not None:
                self.fail("The isolated real-user Unix-socket process failed to start.")
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(0.2)
                    connection.connect(str(self.socket_path))
                    return
            except OSError:
                time.sleep(0.05)
        self.fail("The isolated Gunicorn socket did not become ready.")

    def wait_for_proxy(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.nginx_process.poll() is not None:
                self.fail("The isolated Nginx process failed to start.")
            try:
                response = self.request("GET", "/student", authenticated=False)
                if response.status_code == 401:
                    return
            except requests.RequestException:
                time.sleep(0.05)
        self.fail("The isolated TLS proxy did not become ready.")

    def request(self, method, path, *, authenticated=True, headers=None, data=None):
        final_headers = {"Host": CANONICAL_HOST}
        final_headers["Cookie"] = "__Host-launchpad_session=" + self.cookie if authenticated else ""
        if headers:
            final_headers.update(headers)
        # Never follow a redirect or resolve/contact the actual canonical host.
        return self.client.request(method, self.base_url + path, headers=final_headers,
                                   data=data, timeout=10, allow_redirects=False)

    def assert_backend_has_no_tcp_listener(self):
        pids = {self.app_process.pid}
        pending = list(pids)
        while pending:
            pid = pending.pop()
            children = Path(f"/proc/{pid}/task/{pid}/children")
            for value in children.read_text().split():
                child = int(value)
                if child not in pids:
                    pids.add(child)
                    pending.append(child)
        socket_inodes = set()
        for pid in pids:
            for descriptor in Path(f"/proc/{pid}/fd").iterdir():
                try:
                    target = os.readlink(descriptor)
                except FileNotFoundError:
                    continue
                if target.startswith("socket:["):
                    socket_inodes.add(target[8:-1])
        self.assertTrue(socket_inodes, "Expected the running WSGI Unix listener.")
        for source in ("/proc/net/tcp", "/proc/net/tcp6"):
            for line in Path(source).read_text().splitlines()[1:]:
                fields = line.split()
                self.assertFalse(fields[3] == "0A" and fields[9] in socket_inodes,
                                 "The application unexpectedly opened a TCP listening socket.")
        self.assertEqual(self.socket_path.stat().st_mode & 0o777, 0o660)

    def test_prepared_proxy_enforces_https_host_identity_and_private_backend(self):
        sensitive_query = "isolated-query-value-must-not-be-logged"
        written_answer = "isolated-training-answer-must-not-be-logged"
        redirect = self.client.get(
            f"http://127.0.0.1:{self.http_port}/student?code={sensitive_query}",
            headers={"Host": "foreign.example.invalid"}, timeout=10, allow_redirects=False,
        )
        self.assertEqual(redirect.status_code, 308)
        self.assertEqual(redirect.headers["Location"], f"https://{CANONICAL_HOST}/student?code={sensitive_query}")
        denied = self.request("GET", "/student", authenticated=False)
        self.assertEqual(denied.status_code, 401)
        self.assertNotIn("Isolated Proxy Learner", denied.text)
        cookie_header = denied.headers.get("Set-Cookie", "")
        for flag in ("__Host-launchpad_session=", "Secure", "HttpOnly", "SameSite=Lax", "Path=/"):
            self.assertIn(flag, cookie_header)
        self.assertNotIn("Domain=", cookie_header)
        foreign = self.request("GET", "/student", headers={"Host": "foreign.example.invalid"})
        self.assertEqual(foreign.status_code, 421)
        self.assertNotIn("Isolated Proxy Learner", foreign.text)
        page = self.request("GET", "/student")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Isolated Proxy Learner", page.text)
        self.assertNotIn("Isolated Other Learner", page.text)
        spoofed = self.request("GET", "/modules//hardware_basics?code=" + sensitive_query, headers={
            "X-Forwarded-Proto": "http", "X-Forwarded-Protocol": "http", "X-Forwarded-Ssl": "off",
            "X-Forwarded-Host": "foreign.example.invalid", "X-Forwarded-Port": "80",
            "X-Forwarded-Prefix": "/forged", "Forwarded": "proto=http;host=foreign.example.invalid",
            "SCRIPT_NAME": "/forged", "PATH_INFO": "/supervisor",
        })
        self.assertEqual(spoofed.status_code, 308)
        self.assertEqual(spoofed.headers["Location"], f"https://{CANONICAL_HOST}/modules/hardware_basics?code={sensitive_query}")
        self.assert_backend_has_no_tcp_listener()
        bad_csrf = self.request("POST", "/modules/hardware_basics", data={"completed": "1"})
        self.assertEqual(bad_csrf.status_code, 400)
        self.assertFalse(module_is_complete(self.account["learner_id"], "hardware_basics", self.database))
        fields = {**synthetic_beginner_responses(), "q3": written_answer, "csrf_token": self.csrf}
        self.assertEqual(self.request("POST", "/pre-assessment", data=fields,
                                      headers={"Origin": f"https://{CANONICAL_HOST}"}).status_code, 302)
        self.assertEqual(self.request("POST", "/modules/hardware_basics", data={"completed": "1", "csrf_token": self.csrf}).status_code, 302)
        quiz = get_module_quiz("hardware_basics")
        fields = {question["id"]: question["answer"] for question in quiz["questions"]}
        result = self.request("POST", "/modules/hardware_basics/quiz", data={**fields, "csrf_token": self.csrf})
        self.assertEqual(result.status_code, 200)
        self.assertIn("3 / 3 correct (100%)", result.text)
        self.assertEqual(latest_assessment_result(self.account["learner_id"], "pre", self.database)["technical_score"], 18)
        self.assertEqual(latest_module_quiz_result(self.account["learner_id"], "hardware_basics", self.database)["score"], 100)
        self.assertTrue(module_is_complete(self.account["learner_id"], "hardware_basics", self.database))
        self.assertFalse(module_is_complete(self.other["learner_id"], "hardware_basics", self.database))
        self.assertIsNone(latest_assessment_result(self.other["learner_id"], "pre", self.database))
        self.stop_process(self.app_process)
        unavailable = self.request("GET", "/auth/callback?code=" + sensitive_query)
        self.assertEqual(unavailable.status_code, 502)
        self.stop_process(self.nginx_process)
        self.app_logs.flush()
        self.app_logs.seek(0)
        self.nginx_logs.flush()
        self.nginx_logs.seek(0)
        access = (self.directory / "access.log").read_text()
        logs = {"access": access, "application": self.app_logs.read(), "nginx-process": self.nginx_logs.read()}
        for name in ("error.log", "main-error.log"):
            path = self.directory / name
            if path.exists():
                logs[name] = path.read_text()
        self.assertIn("GET 502", access)
        protected = {
            "query": sensitive_query, "answer": written_answer, "session-handle": self.session_handle,
            "cookie": self.cookie, "csrf": self.csrf, "signing-key": self.signing_secret,
            "client-secret": self.environment["LAUNCHPAD_OIDC_CLIENT_SECRET"], "subject": self.account["subject"],
        }
        for label, private in protected.items():
            for destination, text in logs.items():
                self.assertTrue(private not in text, f"Protected {label} reached isolated {destination} log.")


if __name__ == "__main__":
    unittest.main()
