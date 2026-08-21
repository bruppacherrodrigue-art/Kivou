"""Versioned HMAC identity for the hard acquisition-email suppression boundary."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

SUPPRESSION_SCOPE = "KIVOU_ACQUISITION_EMAIL"
_DOMAIN = b"kivou:acquisition-suppression:v1\0"
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_EVIDENCE_DOMAIN = b"kivou:acquisition-suppression-evidence:v1\0"


class SuppressionIdentityUnavailable(RuntimeError):
    """A suppression identity cannot be evaluated safely."""


def normalize_business_email(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized or len(normalized) > 320 or not _EMAIL.fullmatch(normalized):
        raise SuppressionIdentityUnavailable("business email is unusable for suppression")
    return normalized


def suppression_evidence_ref(source_kind: str, durable_identity: str) -> str:
    """Return an opaque audit reference without persisting source payload text."""
    if (
        not isinstance(source_kind, str)
        or not source_kind.strip()
        or len(source_kind) > 64
        or not isinstance(durable_identity, str)
        or not durable_identity.strip()
        or len(durable_identity) > 256
    ):
        raise ValueError("suppression evidence identity must be bounded")
    digest = hashlib.sha256(
        _EVIDENCE_DOMAIN + source_kind.strip().encode() + b"\0" + durable_identity.strip().encode()
    ).hexdigest()
    return f"suppression-evidence:{digest}"


@dataclass(frozen=True)
class SuppressionIdentityKeyring:
    current_key_version: str
    keys: Mapping[str, bytes] = field(repr=False)

    def __post_init__(self) -> None:
        copied = dict(self.keys)
        if (
            not self.current_key_version
            or self.current_key_version not in copied
            or len(copied) > 8
            or any(not version or len(version) > 64 for version in copied)
            or any(not isinstance(secret, bytes) or len(secret) < 8 for secret in copied.values())
        ):
            raise ValueError("invalid suppression keyring")
        object.__setattr__(self, "keys", MappingProxyType(copied))

    def identities_for_email(self, email: str) -> dict[str, str]:
        normalized = normalize_business_email(email).encode()
        return {
            version: hmac.new(secret, _DOMAIN + normalized, hashlib.sha256).hexdigest()
            for version, secret in sorted(self.keys.items())
        }

    def require_versions_covered(self, retained_versions: tuple[str, ...]) -> None:
        missing = sorted(set(retained_versions).difference(self.keys))
        if missing:
            raise SuppressionIdentityUnavailable(
                f"suppression key coverage unavailable: {','.join(missing)}"
            )


def minimum_retention_until(received_at: dt.datetime) -> dt.datetime:
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    try:
        return received_at.replace(year=received_at.year + 3)
    except ValueError:
        return received_at.replace(year=received_at.year + 3, day=28)


__all__ = [
    "SUPPRESSION_SCOPE",
    "SuppressionIdentityKeyring",
    "SuppressionIdentityUnavailable",
    "minimum_retention_until",
    "normalize_business_email",
    "suppression_evidence_ref",
]
