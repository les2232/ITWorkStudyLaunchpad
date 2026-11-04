"""Exercise controlled-test proxy candidates using only disposable local TLS.

No application, directory connection, system service, existing certificate or
learner database is used. Nginx and the synthetic backend listen on high
loopback ports; certificate and log files exist only in a private /tmp fixture.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

import requests

import test_real_login_flow as tls_fixture
import test_vm_proxy as proxy_fixture


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_HOST = "lesliec.ccaurora.edu"
BACKEND_NAME = "launchpad-controlled.invalid"


class ControlledProxyTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("Disposable Nginx must run as a non-root test user.")
        self.nginx = shutil.which("nginx")
        if not self.nginx or not shutil.which("openssl"):
            self.skipTest("Controlled TLS proxy verification requires Nginx and OpenSSL.")
        temporary = tempfile.TemporaryDirectory(prefix="launchpad-controlled-proxy-", dir="/tmp")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.directory.chmod(0o700)
        self.certificate, self.private_key = tls_fixture.RealLoginProcessTests.make_certificate(self)
        self.http_port, self.https_port = proxy_fixture.VMProxyIntegrationTests.reserve_test_ports()
        self.client = requests.Session()
        self.client.trust_env = False
        self.client.verify = str(self.certificate)
        self.addCleanup(self.client.close)
        self.received = []
        self.server_names = []
        self.diagnostics = tempfile.TemporaryFile(mode="w+t")
        self.addCleanup(self.diagnostics.close)

    def start_backend(self, *, name=BACKEND_NAME):
        directory = self.directory / "backend"
        directory.mkdir(mode=0o700)
        ca, ca_key = tls_fixture.RealLoginProcessTests.make_certificate(SimpleNamespace(directory=directory))
        key, request, certificate = (directory / filename for filename in ("key.pem", "request.csr", "leaf.pem"))
        # Exercise the prepared server certificate extensions. Change only its
        # DNS SAN for the deliberate hostname-mismatch case.
        extensions = directory / "extensions.cnf"
        extensions.write_text((PROJECT_ROOT / "deploy/vm/controlled-backend.ext").read_text().replace(BACKEND_NAME, name))
        for command in (
            ["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
             "-out", str(request), "-subj", "/CN=" + name],
            ["openssl", "x509", "-req", "-in", str(request), "-CA", str(ca), "-CAkey", str(ca_key),
             "-set_serial", "17", "-days", "1", "-extfile", str(extensions), "-out", str(certificate)],
        ):
            subprocess.run(command, check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        key.chmod(0o600)
        received = self.received

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                entry = {
                    "path": self.path, "headers": dict(self.headers),
                    "body": self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode(),
                    "tls": self.connection.version(),
                }
                received.append(entry)
                body = json.dumps(entry).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_POST = do_GET

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(certificate, key)
        context.set_servername_callback(lambda _socket, name, _context: self.server_names.append(name))
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop_backend():
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        self.addCleanup(stop_backend)
        return server.server_port, ca

    def start_proxy(self, *, backend_port=None, trusted_ca=None, maintenance=False):
        candidate = "launchpad-controlled-maintenance.nginx.conf" if maintenance else "launchpad-controlled.nginx.conf"
        source = (PROJECT_ROOT / "deploy/vm" / candidate).read_text()
        substitutions = {
            "    listen 80;": f"    listen 127.0.0.1:{self.http_port};",
            "    listen [::]:80;\n": "",
            "    listen 443 ssl http2;": f"    listen 127.0.0.1:{self.https_port} ssl http2;",
            "    listen [::]:443 ssl http2;\n": "",
            "/opt/project/certs/fullchain.pem": str(self.certificate),
            "/opt/project/certs/ccaurora.key": str(self.private_key),
        }
        if not maintenance:
            substitutions.update({
                "https://127.0.0.1:8443": f"https://127.0.0.1:{backend_port}",
                "/etc/nginx/launchpad-controlled/backend-ca.pem": str(trusted_ca),
                "/var/log/nginx/launchpad-controlled.access.log": str(self.directory / "access.log"),
            })
        for original, replacement in substitutions.items():
            self.assertIn(original, source, "Review fixture isolation after candidate paths/listeners change.")
            source = source.replace(original, replacement)
        vhost = self.directory / "vhost.conf"
        vhost.write_text(source)
        configuration = self.directory / "nginx.conf"
        configuration.write_text(
            "worker_processes 1;\n"
            f"pid {self.directory}/nginx.pid;\n"
            f"error_log {self.directory}/main-error.log crit;\n"
            "events { worker_connections 32; }\nhttp {\n"
            + "".join(f"  {kind}_temp_path {self.directory}/{kind};\n" for kind in ("client_body", "proxy", "fastcgi", "uwsgi", "scgi"))
            + f"  include {vhost};\n}}\n"
        )
        command = [self.nginx, "-p", str(self.directory) + "/", "-c", str(configuration)]
        result = subprocess.run(command + ["-t"], stdout=self.diagnostics, stderr=self.diagnostics, timeout=10)
        self.assertEqual(result.returncode, 0, "Isolated candidate failed Nginx syntax validation.")
        process = subprocess.Popen(command + ["-g", "daemon off;"], stdout=self.diagnostics,
                                   stderr=self.diagnostics, start_new_session=True)
        self.proxy_process = process
        self.addCleanup(proxy_fixture.VMProxyIntegrationTests.stop_process, process)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.assertIsNone(process.poll(), "Disposable Nginx exited before readiness.")
            try:
                with socket.create_connection(("127.0.0.1", self.https_port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.05)
        self.fail("Disposable Nginx never became ready.")

    def request(self, path="/auth/login", *, method="GET", headers=None, data=None):
        return self.client.request(method, f"https://127.0.0.1:{self.https_port}" + path,
                                   headers={"Host": PUBLIC_HOST, **(headers or {})}, data=data,
                                   timeout=5, allow_redirects=False)

    def assert_private_logs(self, *private_values):
        # Drain log writes before checking absence of sensitive values.
        proxy_fixture.VMProxyIntegrationTests.stop_process(self.proxy_process)
        self.diagnostics.flush()
        self.diagnostics.seek(0)
        text = self.diagnostics.read()
        for path in self.directory.glob("*.log"):
            text += path.read_text()
        for value in private_values:
            self.assertNotIn(value, text, "A synthetic sensitive value reached proxy logs.")
        self.assertTrue((self.directory / "access.log").read_text().strip(), "Expected sanitized access evidence.")

    def test_verified_tls_forwarding_headers_and_private_logging(self):
        port, ca = self.start_backend()
        self.start_proxy(backend_port=port, trusted_ca=ca)
        secret_query, secret_cookie, secret_body = "synthetic-query-private", "synthetic-cookie-private", "synthetic-answer-private"
        redirect = self.client.get(f"http://127.0.0.1:{self.http_port}/auth/login", headers={"Host": "foreign.invalid"},
                                   timeout=5, allow_redirects=False)
        self.assertEqual(redirect.status_code, 308)
        self.assertEqual(redirect.headers["Location"], f"https://{PUBLIC_HOST}/auth/login")
        denied = self.request(headers={"Host": "foreign.invalid"})
        self.assertEqual(denied.status_code, 421)
        self.assertEqual(self.received, [])
        response = self.request("/auth/login?code=" + secret_query, method="POST", data=secret_body, headers={
            "Cookie": secret_cookie, "X-Forwarded-Proto": "http", "X-Forwarded-Protocol": "http",
            "X-Forwarded-Ssl": "off", "Forwarded": "proto=http;host=foreign.invalid",
            "X-Forwarded-Host": "foreign.invalid", "X-Forwarded-Port": "80", "X-Forwarded-Prefix": "/forged",
            "X-Forwarded-For": "192.0.2.200", "X-Real-IP": "192.0.2.200", "SCRIPT_NAME": "/forged", "PATH_INFO": "/supervisor",
        })
        self.assertEqual(response.status_code, 200)
        entry = response.json()
        self.assertIn(entry["tls"], ("TLSv1.2", "TLSv1.3"))
        self.assertEqual(self.server_names, [BACKEND_NAME])
        self.assertEqual(len(self.received), 1)
        self.assertEqual(entry["body"], secret_body)
        self.assertEqual(entry["path"], "/auth/login?code=" + secret_query)
        self.assertEqual(entry["headers"]["Host"], PUBLIC_HOST)
        self.assertEqual(entry["headers"]["X-Forwarded-Proto"], "https")
        self.assertEqual(entry["headers"]["X-Forwarded-For"], "127.0.0.1")
        self.assertEqual(entry["headers"]["X-Real-IP"], "127.0.0.1")
        for name in ("Forwarded", "X-Forwarded-Protocol", "X-Forwarded-Ssl", "X-Forwarded-Host", "X-Forwarded-Port",
                     "X-Forwarded-Prefix", "SCRIPT_NAME", "PATH_INFO"):
            self.assertNotIn(name, entry["headers"])
        self.assert_private_logs(secret_query, secret_cookie, secret_body)
        # Streaming credentials must not spill to a request-body temporary file.
        self.assertEqual(list((self.directory / "client_body").glob("**/*")), [])

    def test_wrong_backend_certificate_hostname_fails_closed(self):
        port, ca = self.start_backend(name="wrong-backend.invalid")
        self.start_proxy(backend_port=port, trusted_ca=ca)
        sentinel = "wrong-host-query-private"
        self.assertEqual(self.request("/auth/login?code=" + sentinel).status_code, 502)
        self.assertEqual(self.received, [])
        self.assert_private_logs(sentinel)

    def test_untrusted_backend_certificate_fails_closed(self):
        port, _ca = self.start_backend()
        self.start_proxy(backend_port=port, trusted_ca=self.certificate)
        sentinel = "untrusted-ca-query-private"
        self.assertEqual(self.request("/auth/login?code=" + sentinel).status_code, 502)
        self.assertEqual(self.received, [])
        self.assert_private_logs(sentinel)

    def test_maintenance_candidate_closes_access_without_backend(self):
        self.start_proxy(maintenance=True)
        response = self.request()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Retry-After"], "300")
        self.assertIn("controlled test is closed", response.text)
        self.assertEqual(self.request(headers={"Host": "foreign.invalid"}).status_code, 421)


if __name__ == "__main__":
    unittest.main()
