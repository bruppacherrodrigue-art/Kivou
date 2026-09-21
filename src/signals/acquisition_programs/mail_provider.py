"""Bounded public MX classification; no SMTP connection or mailbox access."""

from __future__ import annotations

import datetime as dt
import ipaddress
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import dns.exception
import dns.resolver
import idna
from email_validator import EmailNotValidError, validate_email

DETECTOR_VERSION = "public-mx-provider-v1"
_GOOGLE_LEGACY = re.compile(r"(?:alt[1-4]\.)?aspmx\.l\.google\.com")
_MICROSOFT = re.compile(r"[a-z0-9-]+\.mail\.protection\.outlook\.com")
_ASCII_DOMAIN = re.compile(
    r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?"
)


class MailProvider(StrEnum):
    GOOGLE_WORKSPACE = "GOOGLE_WORKSPACE"
    GMAIL_CONSUMER = "GMAIL_CONSUMER"
    MICROSOFT_365 = "MICROSOFT_365"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class ProviderConfidence(StrEnum):
    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    UNKNOWN = "UNKNOWN"


def normalize_domain(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("domain must be a string")
    candidate = value.strip().removesuffix(".")
    if not candidate or any(char in candidate for char in "/:@[]\\?\x00"):
        raise ValueError("domain is not a bare DNS name")
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        pass
    else:
        raise ValueError("IP addresses are not mail domains")
    try:
        ascii_domain = idna.encode(candidate, uts46=True, std3_rules=True).decode("ascii").lower()
    except idna.IDNAError as error:
        raise ValueError("domain is invalid") from error
    if not _ASCII_DOMAIN.fullmatch(ascii_domain):
        raise ValueError("domain is invalid")
    return ascii_domain


@dataclass(frozen=True)
class MailProviderEvidence:
    domain: str
    provider: MailProvider
    confidence: ProviderConfidence
    mx_records: tuple[str, ...]
    source: str
    observed_at: dt.datetime
    expires_at: dt.datetime
    detector_version: str = DETECTOR_VERSION


class MXResolver(Protocol):
    def mx(self, domain: str, *, timeout: float) -> tuple[str, ...]: ...


class DnsMXResolver:
    """dnspython adapter; bounded DNS lookups only."""

    def mx(self, domain: str, *, timeout: float) -> tuple[str, ...]:
        resolver = dns.resolver.Resolver(configure=True)
        resolver.timeout = timeout
        resolver.lifetime = timeout
        response = resolver.resolve(domain, "MX", lifetime=timeout)
        return tuple(str(answer.exchange) for answer in response)


class MailProviderDetector:
    def __init__(
        self,
        resolver: MXResolver,
        *,
        ttl_seconds: int = 86_400,
        timeout_seconds: float = 2.0,
        attempts: int = 2,
    ) -> None:
        if (
            not 60 <= ttl_seconds <= 604_800
            or not 0 < timeout_seconds <= 10
            or not 1 <= attempts <= 3
        ):
            raise ValueError("DNS limits outside bounded range")
        self._resolver = resolver
        self._ttl = dt.timedelta(seconds=ttl_seconds)
        self._timeout = timeout_seconds
        self._attempts = attempts
        self._cache: dict[str, MailProviderEvidence] = {}

    def detect_email(self, email: str, *, observed_at: dt.datetime) -> MailProviderEvidence:
        try:
            domain = validate_email(email, check_deliverability=False).domain
        except EmailNotValidError as error:
            raise ValueError("invalid email") from error
        return self.detect_domain(domain, observed_at=observed_at)

    def detect_domain(self, domain: str, *, observed_at: dt.datetime) -> MailProviderEvidence:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("observation must be timezone-aware")
        name = normalize_domain(domain)
        cached = self._cache.get(name)
        if cached is not None and cached.observed_at <= observed_at < cached.expires_at:
            return cached
        if name in {"gmail.com", "googlemail.com"}:
            evidence = MailProviderEvidence(
                name,
                MailProvider.GMAIL_CONSUMER,
                ProviderConfidence.CONFIRMED,
                (),
                "EMAIL_DOMAIN",
                observed_at,
                observed_at + self._ttl,
            )
            self._cache[name] = evidence
            return evidence
        records: tuple[str, ...] = ()
        for _ in range(self._attempts):
            try:
                raw_records = self._resolver.mx(name, timeout=self._timeout)
                records = tuple(sorted({normalize_domain(value) for value in raw_records}))
                break
            except (dns.exception.DNSException, TimeoutError, OSError, ValueError):
                records = ()
        provider = self._classify(records)
        confidence = (
            ProviderConfidence.CONFIRMED
            if provider is not MailProvider.UNKNOWN
            else ProviderConfidence.UNKNOWN
        )
        evidence = MailProviderEvidence(
            name,
            provider,
            confidence,
            records,
            "DNS_MX",
            observed_at,
            observed_at + self._ttl,
        )
        self._cache[name] = evidence
        return evidence

    @staticmethod
    def _classify(records: tuple[str, ...]) -> MailProvider:
        if not records:
            return MailProvider.UNKNOWN
        google = tuple(
            value == "smtp.google.com" or _GOOGLE_LEGACY.fullmatch(value) is not None
            for value in records
        )
        microsoft = tuple(_MICROSOFT.fullmatch(value) is not None for value in records)
        if all(google):
            return MailProvider.GOOGLE_WORKSPACE
        if all(microsoft):
            return MailProvider.MICROSOFT_365
        if any(google) or any(microsoft):
            return MailProvider.UNKNOWN
        return MailProvider.OTHER


__all__ = [
    "DnsMXResolver",
    "MXResolver",
    "MailProvider",
    "MailProviderDetector",
    "MailProviderEvidence",
    "ProviderConfidence",
    "normalize_domain",
]
