"""Authenticated attribution tokens. They attribute; they never authorize."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from signals.conversion.contracts import ATTRIBUTION_TOKEN_VERSION, AttributionTokenPayload

_TOKEN_PREFIX = "kat1"
_SIGNING_DOMAIN = b"kivou:conversion-attribution-token:v1\0"
_FINGERPRINT_DOMAIN = b"kivou:conversion-attribution-fingerprint:v1\0"


class AttributionTokenError(ValueError):
    code = "invalid_attribution_token"


class AttributionTokenInvalid(AttributionTokenError):
    pass


class AttributionTokenExpired(AttributionTokenError):
    code = "expired_attribution_token"


@dataclass(frozen=True)
class IssuedAttributionToken:
    raw_token: str = field(repr=False)
    token_fingerprint: str
    token_version: str
    key_version: str
    payload: AttributionTokenPayload


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise AttributionTokenInvalid("attribution token encoding is invalid") from error


def _canonical(payload: AttributionTokenPayload) -> bytes:
    return json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True)
class AttributionTokenKeyring:
    current_key_version: str
    keys: Mapping[str, bytes] = field(repr=False)

    def __post_init__(self) -> None:
        copied = dict(self.keys)
        if (
            not self.current_key_version
            or self.current_key_version not in copied
            or len(copied) > 8
            or any(not version or len(version) > 100 for version in copied)
            or any(not isinstance(secret, bytes) or len(secret) < 16 for secret in copied.values())
        ):
            raise ValueError("invalid attribution token keyring")
        object.__setattr__(self, "keys", MappingProxyType(copied))

    def issue(self, payload: AttributionTokenPayload) -> IssuedAttributionToken:
        keyed = payload.model_copy(update={"key_version": self.current_key_version})
        canonical = _canonical(keyed)
        secret = self.keys[self.current_key_version]
        signature = hmac.new(secret, _SIGNING_DOMAIN + canonical, hashlib.sha256).digest()
        raw_token = f"{_TOKEN_PREFIX}.{_b64(canonical)}.{_b64(signature)}"
        return IssuedAttributionToken(
            raw_token=raw_token,
            token_fingerprint=hmac.new(
                secret, _FINGERPRINT_DOMAIN + canonical, hashlib.sha256
            ).hexdigest(),
            token_version=ATTRIBUTION_TOKEN_VERSION,
            key_version=self.current_key_version,
            payload=keyed,
        )

    def verify(self, raw_token: str, *, at: dt.datetime) -> IssuedAttributionToken:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("verification time must be timezone-aware")
        if not isinstance(raw_token, str) or len(raw_token) > 4096:
            raise AttributionTokenInvalid("attribution token is invalid")
        parts = raw_token.split(".")
        if len(parts) != 3 or parts[0] != _TOKEN_PREFIX:
            raise AttributionTokenInvalid("attribution token is invalid")
        canonical = _unb64(parts[1])
        signature = _unb64(parts[2])
        try:
            decoded = json.loads(canonical)
            payload = AttributionTokenPayload.model_validate(decoded)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            raise AttributionTokenInvalid("attribution token payload is invalid") from error
        if _canonical(payload) != canonical or payload.key_version not in self.keys:
            raise AttributionTokenInvalid("attribution token payload is invalid")
        secret = self.keys[payload.key_version]
        expected = hmac.new(secret, _SIGNING_DOMAIN + canonical, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise AttributionTokenInvalid("attribution token signature is invalid")
        observed = at.astimezone(dt.UTC)
        if observed < payload.issued_at:
            raise AttributionTokenInvalid("attribution token is not active")
        if observed >= payload.expires_at:
            raise AttributionTokenExpired("attribution token expired")
        return IssuedAttributionToken(
            raw_token=raw_token,
            token_fingerprint=hmac.new(
                secret, _FINGERPRINT_DOMAIN + canonical, hashlib.sha256
            ).hexdigest(),
            token_version=payload.token_version,
            key_version=payload.key_version,
            payload=payload,
        )


__all__ = [
    "AttributionTokenExpired",
    "AttributionTokenInvalid",
    "AttributionTokenKeyring",
    "IssuedAttributionToken",
]
