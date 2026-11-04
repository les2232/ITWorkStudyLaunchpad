"""Bounded Gunicorn diagnostics for the supervised controlled test only.

Never format Gunicorn's message, arguments or exceptions: parser failures can
embed submitted headers in them. Application login reasons use their own
fixed-schema logger. These records identify the server boundary without
pretending that an unparsed request has an established method or path.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
import re
import ssl
import sys

from gunicorn.glogging import Logger
from gunicorn.http import errors


_PARSER_REASONS = {
    errors.InvalidRequestLine: (400, "parser_request_line"),
    errors.InvalidRequestMethod: (400, "parser_method"),
    errors.InvalidHTTPVersion: (400, "parser_http_version"),
    errors.InvalidHeader: (400, "parser_header"),
    errors.InvalidHeaderName: (400, "parser_header_name"),
    errors.LimitRequestLine: (400, "parser_line_limit"),
    errors.LimitRequestHeaders: (431, "parser_header_limit"),
    errors.InvalidProxyLine: (400, "parser_proxy_line"),
    errors.ForbiddenProxyRequest: (403, "parser_proxy_forbidden"),
    errors.InvalidSchemeHeaders: (400, "parser_scheme_headers"),
    errors.UnsupportedTransferCoding: (501, "parser_transfer_coding"),
    errors.ConfigurationProblem: (500, "parser_configuration"),
    errors.ObsoleteFolding: (400, "parser_header_folding"),
    errors.ExpectationFailed: (417, "parser_expectation"),
}
# This exception was added in later Gunicorn versions. Keep the logging
# adapter usable with earlier supported versions without changing parsing.
if hasattr(errors, "InvalidH2CPreface"):
    _PARSER_REASONS[errors.InvalidH2CPreface] = (400, "parser_http2_preface")

_METHODS = frozenset({"GET", "POST", "HEAD", "OPTIONS", "PUT", "PATCH", "DELETE"})
_LIFECYCLE = {
    "Starting gunicorn %s": "server_starting",
    "Listening at: %s (%s)": "server_listening",
    "Using worker: %s": "server_worker_type",
    "Booting worker with pid: %s": "worker_starting",
    "Worker exiting (pid: %s)": "worker_exiting",
    "Handling signal: %s": "server_signal",
    "Shutting down: %s": "server_shutdown",
    "WORKER TIMEOUT (pid:%s)": "worker_timeout",
}


def _parser_reason():
    exception = sys.exc_info()[1]
    if isinstance(exception, ssl.SSLError):
        return 403, "parser_tls"
    return _PARSER_REASONS.get(type(exception))


class _DiagnosticHandler(logging.Handler):
    """Do not expose the file stream through Gunicorn's wsgi.errors wrapper.

    Gunicorn otherwise gives WSGI applications direct access to every error
    handler's stream, bypassing logger methods and potentially writing raw
    exception details. Only marked, constructed records reach this sink.
    """

    def __init__(self, delegate):
        super().__init__()
        self._delegate = delegate
        self._gunicorn = True

    def emit(self, record):
        if not getattr(record, "_launchpad_safe", False):
            record = logging.LogRecord(
                record.name, record.levelno, "", 0,
                SafeControlledLogger._record(reason="server_log_suppressed"), (), None,
            )
        self._delegate.handle(record)

    def close(self):
        self._delegate.close()
        super().close()


class SafeControlledLogger(Logger):
    """Replace raw server diagnostics with a small fixed vocabulary.

    Configure private errorlog/accesslog destinations through Gunicorn. Raw
    stdout/stderr capture must stay off; it bypasses these sanitizers.
    """

    error_fmt = "%(message)s"

    def setup(self, cfg):
        if cfg.capture_output:
            raise ValueError("Controlled diagnostics require capture_output=False.")
        super().setup(cfg)
        for logger in (self.error_log, self.access_log):
            for handler in list(logger.handlers):
                logger.removeHandler(handler)
                logger.addHandler(_DiagnosticHandler(handler))

    @staticmethod
    def _record(*, method="unavailable", path="unavailable", status=0, reason):
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return (f"timestamp={timestamp} pid={os.getpid()} method={method} "
                f"path={path} status={status} reason={reason}")

    def _server(self, level, msg, fallback):
        parsed = _parser_reason()
        if parsed is not None:
            status, reason = parsed
        else:
            status = 0
            # Only exact built-in template matches are inspected. No string
            # conversion, interpolation, exception repr or traceback logging.
            reason = _LIFECYCLE.get(msg, fallback) if type(msg) is str else fallback
        self.error_log.log(level, self._record(status=status, reason=reason), extra={"_launchpad_safe": True})

    def critical(self, msg, *args, **kwargs):
        self._server(logging.CRITICAL, msg, "server_critical")

    def error(self, msg, *args, **kwargs):
        self._server(logging.ERROR, msg, "server_error")

    def warning(self, msg, *args, **kwargs):
        self._server(logging.WARNING, msg, "server_warning")

    def info(self, msg, *args, **kwargs):
        self._server(logging.INFO, msg, "server_info")

    def debug(self, msg, *args, **kwargs):
        self._server(logging.DEBUG, msg, "server_debug")

    def exception(self, msg, *args, **kwargs):
        self._server(logging.ERROR, msg, "server_exception")

    def log(self, lvl, msg, *args, **kwargs):
        if type(lvl) is str:
            lvl = self.LOG_LEVELS.get(lvl.lower(), logging.INFO)
        if lvl not in self.LOG_LEVELS.values():
            lvl = logging.INFO
        self._server(lvl, msg, "server_event")

    def access(self, resp, req, environ, request_time):
        if not self.access_log_enabled:
            return
        method = environ.get("REQUEST_METHOD")
        if method not in _METHODS:
            method = "unavailable"
        path = "/auth/login" if environ.get("PATH_INFO") == "/auth/login" else "other"
        raw_status = resp.status
        if type(raw_status) is int and 100 <= raw_status <= 599:
            status = raw_status
        elif type(raw_status) is str and re.fullmatch(r"[1-5][0-9]{2}(?: [^\r\n]*)?", raw_status):
            status = int(raw_status[:3])
        else:
            status = 0
        parsed = _parser_reason()
        reason = parsed[1] if parsed is not None else "application_response"
        # Do not call atoms(): it enumerates request/response headers and the
        # environment, none of which this diagnostic needs.
        self.access_log.info(self._record(method=method, path=path, status=status, reason=reason),
                             extra={"_launchpad_safe": True})
