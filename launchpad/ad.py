"""Explicit, verified LDAPS authentication without directory provisioning.

An AD login proves identity and group eligibility only. The caller must still
resolve the immutable identity against an explicitly enrolled local account.
No user password, bind credential, or directory response is persisted here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import ipaddress
import logging
import os
from pathlib import Path
import re
import ssl
from uuid import UUID

from flask import Flask, current_app


class ADLoginError(Exception):
    """Safe public failure with no directory response or credential detail."""


_FAILURE = "Sign-in could not be completed. Check your credentials or contact IT."
_CONFIG_FAILURE = "AD configuration is invalid; review the approved directory and CA settings."
_DNS_LABEL = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\Z")
_ACCOUNT = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._'-]{0,63}\Z")
_SETTINGS = ("HOST", "PORT", "CA_FILE", "DOMAIN", "BASE_DN", "GROUP_DN", "GROUP_POLICY", "IDENTITY_NAMESPACE")


@dataclass(frozen=True)
class ADConfig:
    host: str
    domain: str
    base_dn: str
    group_dn: str
    group_policy: str
    namespace: str
    context: ssl.SSLContext = field(repr=False, compare=False)

    @property
    def issuer(self) -> str:
        return "urn:launchpad:ad:" + self.namespace


def _ldap():
    try:
        import ldap3
        from ldap3.utils.log import OFF, set_library_log_detail_level
    except ImportError:
        raise ValueError("AD mode requires the dependencies in requirements-real.txt.") from None
    # Library diagnostic output can contain requests or bind details. The
    # application records bounded outcome categories outside this adapter.
    logging.getLogger("ldap3").disabled = True
    set_library_log_detail_level(OFF)
    return ldap3


def _dns_name(value: object) -> str:
    if not isinstance(value, str) or len(value) > 253 or value != value.strip():
        raise ValueError(_CONFIG_FAILURE)
    if len(value.split(".")) < 2 or any(not _DNS_LABEL.fullmatch(part) for part in value.split(".")):
        raise ValueError(_CONFIG_FAILURE)
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value.lower()
    raise ValueError(_CONFIG_FAILURE)


def configure_ad(app: Flask) -> ADConfig:
    """Validate explicit settings and CA certificates; never contact AD."""
    _ldap()
    from ldap3.utils.dn import parse_dn

    for name in _SETTINGS:
        key = "LAUNCHPAD_AD_" + name
        app.config.setdefault(key, os.environ.get(key, ""))
    try:
        host = _dns_name(app.config["LAUNCHPAD_AD_HOST"])
        domain = _dns_name(app.config["LAUNCHPAD_AD_DOMAIN"])
        port = app.config["LAUNCHPAD_AD_PORT"]
        if isinstance(port, bool) or str(port) != "636":
            raise ValueError(_CONFIG_FAILURE)
        namespace = app.config["LAUNCHPAD_AD_IDENTITY_NAMESPACE"]
        if not isinstance(namespace, str) or str(UUID(namespace)) != namespace or not UUID(namespace).int:
            raise ValueError(_CONFIG_FAILURE)
        group_policy = app.config["LAUNCHPAD_AD_GROUP_POLICY"]
        if group_policy not in {"direct", "nested"}:
            raise ValueError(_CONFIG_FAILURE)
        dns = []
        for key in ("LAUNCHPAD_AD_BASE_DN", "LAUNCHPAD_AD_GROUP_DN"):
            value = app.config[key]
            if (not isinstance(value, str) or not 1 <= len(value) <= 2048 or value != value.strip()
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                raise ValueError(_CONFIG_FAILURE)
            parse_dn(value, escape=False, strip=False)
            dns.append(value)
        ca_path = Path(app.config["LAUNCHPAD_AD_CA_FILE"])
        if not ca_path.is_absolute() or not ca_path.is_file() or not os.access(ca_path, os.R_OK):
            raise ValueError(_CONFIG_FAILURE)
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca_path))
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        if context.cert_store_stats()["x509_ca"] < 1:
            raise ValueError(_CONFIG_FAILURE)
    except Exception:
        raise ValueError(_CONFIG_FAILURE) from None
    configured = ADConfig(host, domain, dns[0], dns[1], group_policy, namespace, context)
    app.extensions["launchpad_ad"] = configured
    return configured


def _config(config: ADConfig | None) -> ADConfig:
    configured = config if config is not None else current_app.extensions["launchpad_ad"]
    if not isinstance(configured, ADConfig):
        raise ADLoginError(_FAILURE)
    return configured


def _principal(username: object, config: ADConfig) -> tuple[str, str]:
    # Bind, search and throttling share this boundary; passwords never pass here.
    if not isinstance(username, str) or len(username) > 320:
        raise ADLoginError(_FAILURE)
    parts = username.strip().split("@")
    if len(parts) > 2 or (len(parts) == 2 and parts[1].lower() != config.domain):
        raise ADLoginError(_FAILURE)
    account = parts[0]
    if not _ACCOUNT.fullmatch(account):
        raise ADLoginError(_FAILURE)
    # The supported short-name convention is the local part of an approved
    # domain UPN. A different institutional login convention needs review.
    return account.lower() + "@" + config.domain, "userPrincipalName"


def normalized_attempt_key(username: object, config: ADConfig | None = None) -> str:
    """Canonical throttle input; callers hash it before persistence/logging."""
    configured = _config(config)
    try:
        principal, _attribute = _principal(username, configured)
        return principal.casefold()
    except ADLoginError:
        return "invalid:" + (username.casefold()[:128] if isinstance(username, str) else "")


def _tls(config: ADConfig):
    ldap3 = _ldap()

    class VerifiedTLS(ldap3.Tls):
        def __init__(self):
            super().__init__(validate=ssl.CERT_REQUIRED)

        def wrap_socket(self, connection, do_handshake=False):
            # SSLContext supplies certificate/hostname verification, SNI and
            # minimum TLS version. No library fallback TLS context is used.
            connection.socket = config.context.wrap_socket(
                connection.socket, server_hostname=config.host,
                do_handshake_on_connect=True,
            )

    return VerifiedTLS()


def _subject(value: object) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value or not UUID(value).int:
        raise ADLoginError(_FAILURE)
    return value


def _query(identity_filter: str, bind_username: str, password: str, config: ADConfig) -> dict[str, str]:
    ldap3 = _ldap()
    from ldap3.utils.conv import escape_filter_chars

    connection = None
    try:
        if not isinstance(password, str) or not password or len(password) > 4096 or "\x00" in password:
            raise ADLoginError(_FAILURE)
        if config.context.verify_mode != ssl.CERT_REQUIRED or not config.context.check_hostname or config.context.minimum_version < ssl.TLSVersion.TLSv1_2:
            raise ADLoginError(_FAILURE)
        server = ldap3.Server(
            config.host, port=636, use_ssl=True, tls=_tls(config),
            allowed_referral_hosts=[], connect_timeout=3, get_info=ldap3.NONE,
        )
        # Assert the parsed server as well as configuration: ldap3's Server
        # otherwise allows URI syntax to override the SSL and port arguments.
        if server.host != config.host or server.port != 636 or server.ssl is not True or server.allowed_referral_hosts:
            raise ADLoginError(_FAILURE)
        connection = ldap3.Connection(
            server, user=bind_username, password=password,
            authentication=ldap3.SIMPLE, auto_bind=False, auto_referrals=False,
            read_only=True, receive_timeout=5, raise_exceptions=True,
            check_names=False, auto_range=False,
        )
        connection.open(read_server_info=False)
        if connection.closed or not connection.bind(read_server_info=False) or not connection.bound:
            raise ADLoginError(_FAILURE)
        membership = "memberOf" if config.group_policy == "direct" else "memberOf:1.2.840.113556.1.4.1941:"
        query = (
            "(&(objectCategory=person)(objectClass=user)"
            "(!(userAccountControl:1.2.840.113556.1.4.803:=2))"
            + identity_filter + "(" + membership + "=" + escape_filter_chars(config.group_dn) + "))"
        )
        found = connection.search(
            search_base=config.base_dn, search_filter=query,
            search_scope=ldap3.SUBTREE, dereference_aliases=ldap3.DEREF_NEVER,
            attributes=["objectGUID"], size_limit=2, time_limit=3,
        )
        if not found or not isinstance(connection.result, dict) or connection.result.get("result") != 0:
            raise ADLoginError(_FAILURE)
        responses = connection.response
        if not isinstance(responses, list) or len(responses) != 1 or responses[0].get("type") != "searchResEntry":
            raise ADLoginError(_FAILURE)
        raw = responses[0].get("raw_attributes", {})
        values = [value for key, value in raw.items() if key.lower() == "objectguid"]
        if len(values) != 1 or not isinstance(values[0], list) or len(values[0]) != 1:
            raise ADLoginError(_FAILURE)
        guid = values[0][0]
        if not isinstance(guid, bytes) or len(guid) != 16:
            raise ADLoginError(_FAILURE)
        subject = _subject(str(UUID(bytes_le=guid)))
        return {"issuer": config.issuer, "subject": subject}
    except Exception:
        raise ADLoginError(_FAILURE) from None
    finally:
        if connection is not None:
            try:
                connection.unbind()
            except Exception:
                pass
            # Avoid retaining a submitted password on a connection object.
            connection.password = None


def authenticate_ad(username: str, password: str, config: ADConfig | None = None) -> dict[str, str]:
    """Verify credentials, enabled account and group, returning immutable identity."""
    from ldap3.utils.conv import escape_filter_chars

    try:
        configured = _config(config)
        principal, attribute = _principal(username, configured)
        return _query("(" + attribute + "=" + escape_filter_chars(principal) + ")", principal, password, configured)
    except Exception:
        raise ADLoginError(_FAILURE) from None


def revalidate_ad(subject: str, config: ADConfig | None = None, *, bind_username: str, bind_password: str) -> dict[str, str]:
    """Recheck immutable account/group using supplied approved lookup credentials.

    This does not provision a service account or persist its credentials. The
    caller must choose and enforce the approved session-revalidation policy.
    """
    try:
        configured = _config(config)
        principal, _attribute = _principal(bind_username, configured)
        subject = _subject(subject)
        escaped_guid = "".join("\\" + format(byte, "02x") for byte in UUID(subject).bytes_le)
        identity = _query("(objectGUID=" + escaped_guid + ")", principal, bind_password, configured)
        if identity["subject"] != subject:
            raise ADLoginError(_FAILURE)
        return identity
    except Exception:
        raise ADLoginError(_FAILURE) from None
