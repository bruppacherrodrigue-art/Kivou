"""Bounded MX and SMTP-RCPT verification. This module never submits SMTP DATA."""

from __future__ import annotations

import smtplib
from collections.abc import Callable

import dns.resolver


class EmailDeliverabilityVerifier:
    def __init__(
        self,
        *,
        resolver=None,
        smtp_factory: Callable[..., object] = smtplib.SMTP,
        timeout: float = 8.0,
    ) -> None:
        self._resolver = resolver or dns.resolver.Resolver()
        self._smtp_factory = smtp_factory
        self._timeout = timeout

    def verify(self, email: str) -> bool:
        try:
            local, domain = email.rsplit("@", 1)
            if not local or not domain:
                return False
            records = sorted(
                self._resolver.resolve(domain, "MX"),
                key=lambda record: int(record.preference),
            )
            if not records:
                return False
            host = str(records[0].exchange).rstrip(".")
            with self._smtp_factory(host, 25, timeout=self._timeout) as smtp:
                smtp.ehlo()
                mail_code, _ = smtp.mail("verification@kivou.eu")
                if not 200 <= int(mail_code) < 300:
                    return False
                rcpt_code, _ = smtp.rcpt(email)
                return 200 <= int(rcpt_code) < 300
        except (OSError, ValueError, dns.exception.DNSException, smtplib.SMTPException):
            return False


class EmailMxVerifier:
    """Verify that a published professional address has a routable MX domain."""

    def __init__(self, *, resolver=None) -> None:
        self._resolver = resolver or dns.resolver.Resolver()

    def verify(self, email: str) -> bool:
        try:
            local, domain = email.rsplit("@", 1)
            return bool(local and domain and tuple(self._resolver.resolve(domain, "MX")))
        except (OSError, ValueError, dns.exception.DNSException):
            return False


__all__ = ["EmailDeliverabilityVerifier", "EmailMxVerifier"]
