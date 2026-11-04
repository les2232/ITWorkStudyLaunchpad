"""Server diagnostics never serialize submitted data or exception details."""
from __future__ import annotations

from datetime import timedelta
import logging
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from gunicorn.config import Config
from gunicorn.http import errors
from gunicorn.http.parser import RequestParser
from gunicorn.http.wsgi import WSGIErrorsWrapper
from gunicorn.workers.base import Worker

from launchpad.controlled_logging import SafeControlledLogger


class ControlledLoggingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="launchpad-safe-log-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "diagnostics.log"
        cfg = Config()
        cfg.set("errorlog", str(self.path))
        cfg.set("accesslog", str(self.path))
        cfg.set("capture_output", False)
        self.cfg = cfg
        self.logger = SafeControlledLogger(cfg)
        self.addCleanup(self.close_handlers)

    def close_handlers(self):
        for logger in (self.logger.error_log, self.logger.access_log):
            for handler in list(logger.handlers):
                if getattr(handler, "_gunicorn", False):
                    logger.removeHandler(handler)
                    handler.close()

    def contents(self):
        return self.path.read_text()

    def test_parser_failure_names_boundary_without_logging_header_or_address(self):
        secret = "password=never-record Cookie=session-secret Authorization=token-secret"
        try:
            raise errors.InvalidHeader(secret)
        except errors.InvalidHeader as exception:
            self.logger.warning("Invalid request from ip=10.0.0.1: " + str(exception))
        text = self.contents()
        self.assertIn("method=unavailable path=unavailable status=400 reason=parser_header", text)
        self.assertNotIn(secret, text)
        self.assertNotIn("10.0.0.1", text)
        self.assertRegex(text, r"timestamp=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z pid=\d+")

    def test_parser_access_only_identifies_exact_known_login_path(self):
        secret = "never-record-this-query-or-cookie"
        request = SimpleNamespace(headers={"Cookie": secret})
        try:
            raise errors.LimitRequestHeaders(secret)
        except errors.LimitRequestHeaders:
            self.logger.access(SimpleNamespace(status="431 ignored secret status text"), request,
                               {"REQUEST_METHOD": "POST", "PATH_INFO": "/auth/login",
                                "QUERY_STRING": secret, "HTTP_COOKIE": secret, "RAW_URI": "/auth/login?" + secret},
                               timedelta())
        text = self.contents()
        self.assertIn("method=POST path=/auth/login status=431 reason=parser_header_limit", text)
        self.assertNotIn(secret, text)
        self.assertNotIn("secret status", text)

    def test_access_never_reads_body_headers_or_unapproved_paths(self):
        class Request:
            @property
            def headers(self):
                raise AssertionError("Diagnostics must not enumerate headers")

        self.logger.access(SimpleNamespace(status="400 Bad Request"), Request(),
                           {"REQUEST_METHOD": "POST", "PATH_INFO": "/private-personal-path",
                            "wsgi.input": object()}, timedelta())
        self.assertIn("method=POST path=other status=400 reason=application_response", self.contents())
        self.assertNotIn("private-personal-path", self.contents())

    def test_untrusted_method_status_and_exception_are_not_formatted(self):
        class Dangerous:
            def __str__(self):
                raise AssertionError("Do not format an exception or log argument")

        secret = "must-never-appear"
        self.logger.access(SimpleNamespace(status="400\n" + secret), None,
                           {"REQUEST_METHOD": secret, "PATH_INFO": "/auth/login?" + secret}, timedelta())
        try:
            raise RuntimeError(secret)
        except RuntimeError:
            self.logger.exception(Dangerous(), Dangerous(), exc_info=True, extra={"private": secret})
        self.logger.error("raw %s " + secret, Dangerous(), exc_info=True, stack_info=True)
        self.assertIn("method=unavailable path=other status=0 reason=application_response", self.contents())
        self.assertIn("reason=server_exception", self.contents())
        self.assertIn("reason=server_error", self.contents())
        self.assertNotIn(secret, self.contents())
        self.assertNotIn("Traceback", self.contents())

    def test_lifecycle_remains_useful_without_raw_arguments(self):
        self.logger.info("Booting worker with pid: %s", "not-a-safe-argument")
        self.assertIn("reason=worker_starting", self.contents())
        self.assertNotIn("not-a-safe-argument", self.contents())

    def test_raw_stdio_capture_is_rejected(self):
        cfg = Config()
        cfg.set("capture_output", True)
        with self.assertRaisesRegex(ValueError, "capture_output=False"):
            SafeControlledLogger(cfg)

    def test_wsgi_errors_and_direct_logger_calls_cannot_bypass_sanitizer(self):
        secret = "raw traceback containing a submitted credential"
        stream = WSGIErrorsWrapper(self.cfg)
        self.assertEqual(stream.streams, [])
        stream.write(secret)
        logging.getLogger("gunicorn.error").error(secret, exc_info=True)
        self.assertIn("reason=server_log_suppressed", self.contents())
        self.assertNotIn(secret, self.contents())

    def test_actual_parser_and_worker_reject_without_raw_header_diagnostics(self):
        secret = b"private-password-cookie-token"
        source = [b"POST /auth/login HTTP/1.1\r\nHost: localhost\r\nBad " + secret + b": no\r\n\r\n"]
        parser = RequestParser(self.cfg, source, ("127.0.0.1", 10))

        class Client:
            def gettimeout(self):
                return 0.0

            def sendall(self, data):
                self.response = data

        client = Client()
        worker = SimpleNamespace(log=self.logger, cfg=self.cfg)
        try:
            next(parser)
        except errors.InvalidHeaderName as exception:
            Worker.handle_error(worker, None, client, ("127.0.0.1", 10), exception)
        else:
            self.fail("Malformed synthetic header unexpectedly passed parser")
        self.assertTrue(client.response.startswith(b"HTTP/1.1 400"))
        self.assertIn("reason=parser_header_name", self.contents())
        self.assertNotIn(secret.decode(), self.contents())


if __name__ == "__main__":
    unittest.main()
