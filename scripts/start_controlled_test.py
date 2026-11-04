"""Manual HTTPS loopback startup for the isolated short-session AD test.

No listener is opened by preflight. --serve opens only 127.0.0.1:8443.
The prepared Nginx route verifies this backend's separate certificate and
serves the browser over approved public HTTPS; it is not installed here.
AD's CA bundle is separate from both website and backend TLS certificates.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import resource
import ssl
import stat
import sys
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launchpad.controlled_test import _private, runtime_config  # noqa: E402
from launchpad.ad import normalized_attempt_key  # noqa: E402
from launchpad.web import create_app  # noqa: E402


def prepare_runtime(run_id: str, certfile: str | Path, keyfile: str | Path):
    """Offline app and TLS validation; no initialization or directory connection."""
    config = runtime_config(run_id)
    if not isinstance(config["LAUNCHPAD_TRUSTED_HOSTS"], str) or not config["LAUNCHPAD_TRUSTED_HOSTS"].strip():
        raise ValueError("Controlled tests require an explicit approved browser hostname.")
    certificate = Path(certfile)
    key = Path(keyfile)
    _private(key)
    if (not certificate.is_absolute() or certificate.resolve() != certificate or not certificate.is_file()
            or certificate.stat().st_size > 65536):
        raise ValueError("Approved website certificate path is invalid.")
    data = certificate.read_bytes()
    certificate_pattern = rb"(?:\s*-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*)+"
    if re.fullmatch(certificate_pattern, data) is None:
        raise ValueError("Website chain file must contain public certificate PEM blocks only.")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    # Password callback refuses encrypted keys without a hidden OpenSSL prompt.
    def refuse_key_password():
        raise ValueError("Use an operator-owned private server key without a passphrase prompt.")
    context.load_cert_chain(str(certificate), str(key), password=refuse_key_password)
    app = create_app(config)
    return app, context


def source_fingerprint() -> str:
    """Identify reviewed source only; never hash private run/configuration files."""
    digest = hashlib.sha256()
    files = [PROJECT_ROOT / "scripts" / "start_controlled_test.py", PROJECT_ROOT / "deploy" / "gunicorn.conf.py"]
    for directory in ("launchpad", "templates", "static"):
        files.extend(path for path in (PROJECT_ROOT / directory).rglob("*")
                     if path.is_file() and path.suffix in {".py", ".html", ".js", ".css"})
    for path in sorted(files):
        digest.update(str(path.relative_to(PROJECT_ROOT)).encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def prepare_diagnostics(app) -> tuple[Path, logging.Logger]:
    """Create private, durable diagnostics only when serving the controlled run."""
    directory = Path(app.config["LAUNCHPAD_DATA_DIR"]) / "logs"
    directory.mkdir(mode=0o700, exist_ok=True)
    _private(directory, directory=True)
    for name in ("login-diagnostics.log", "backend-access.log", "backend-events.log"):
        path = directory / name
        # Refuse symlinks/hardlinks or another owner's/open file before attaching
        # handlers. The enclosing private run prevents access by other users.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                raise ValueError("Controlled diagnostic files must be private and operator-owned.")
        finally:
            os.close(descriptor)
        _private(path)
    for suffix in (".1", ".2"):
        backup = directory / ("login-diagnostics.log" + suffix)
        if os.path.lexists(backup):
            _private(backup)
    logger = logging.getLogger("launchpad.login_diagnostic")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    handler = RotatingFileHandler(directory / "login-diagnostics.log", maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return directory, logger


def serve(app, context: ssl.SSLContext, certfile: str, keyfile: str) -> None:
    """Reuse the deployment logging/worker defaults, fixing listener and TLS."""
    from gunicorn.app.base import BaseApplication
    from launchpad.controlled_logging import SafeControlledLogger
    import runpy

    directory, diagnostic = prepare_diagnostics(app)
    source_id = source_fingerprint()

    def worker_ready(worker):
        # Evaluate the actual inherited callable without a password, database
        # operation or directory connection. A worker recycle is not a reload.
        with app.app_context():
            domain = app.extensions["launchpad_ad"].domain
            canonical = normalized_attempt_key("w00000000@" + domain)
            if normalized_attempt_key(" W00000000 ") != canonical:
                raise ValueError("Controlled worker username normalization is stale.")
        diagnostic.info(
            "timestamp=%s event=worker_ready master_pid=%d worker_pid=%d source_sha256=%s username_normalization=verified",
            datetime.now(timezone.utc).isoformat(timespec="seconds"), os.getppid(), os.getpid(), source_id,
        )

    class ControlledServer(BaseApplication):
        def load_config(self):
            for key, value in runpy.run_path(str(PROJECT_ROOT / "deploy" / "gunicorn.conf.py")).items():
                if key in self.cfg.settings:
                    self.cfg.set(key, value)
            self.cfg.set("bind", "127.0.0.1:8443")
            self.cfg.set("certfile", certfile)
            self.cfg.set("keyfile", keyfile)
            self.cfg.set("ssl_context", lambda _config, _factory: context)
            self.cfg.set("reload", False)
            self.cfg.set("forwarded_allow_ips", "")
            self.cfg.set("secure_scheme_headers", {})
            self.cfg.set("proxy_protocol", "off")
            self.cfg.set("logger_class", SafeControlledLogger)
            self.cfg.set("capture_output", False)
            self.cfg.set("accesslog", str(directory / "backend-access.log"))
            self.cfg.set("errorlog", str(directory / "backend-events.log"))
            self.cfg.set("post_worker_init", worker_ready)

        def load(self):
            return app

    ControlledServer().run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--certfile", required=True)
    parser.add_argument("--keyfile", required=True)
    parser.add_argument("--serve", action="store_true", help="open manual loopback HTTPS listener after successful preflight")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        app, context = prepare_runtime(args.run, args.certfile, args.keyfile)
        if args.serve:
            print("Starting controlled test on HTTPS loopback port 8443; use only the approved browser hostname/tunnel and invented training answers.")
            serve(app, context, args.certfile, args.keyfile)
        else:
            print("Offline startup preflight passed. No listener or directory connection opened; browser trust/hostname and actual AD login remain unverified.")
    except (OSError, ValueError, ImportError):
        print("Controlled test startup refused. Review private run configuration, isolated storage and approved browser HTTPS files; no fallback mode was selected.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
