"""Authenticated attribution tokens. They attribute; they never authorize."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import re
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


@dataclass(frozen=True)
class AttributionTokenLookup:
    key_version: str
    member_ref: str
    signature: bytes = field(repr=False)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as error:
        raise AttributionTokenInvalid("attribution token encoding is invalid") from error


def _canonical(payload: AttributionTokenPayload) -> bytes:
    """La forme signée. Un champ facultatif ABSENT n'y figure pas.

    C'est la seule chose qui rend un nouveau champ compatible avec les jetons
    déjà partis en cold mail : la charge n'est pas dans le lien, elle est
    reconstruite en base à la vérification. Si un champ ajouté aujourd'hui
    apparaissait avec `null` dans la forme canonique, chaque jeton signé hier
    deviendrait invalide du jour au lendemain.
    """
    body = payload.model_dump(mode="json")
    if body.get("opportunity_key") is None:
        body.pop("opportunity_key", None)
    return json.dumps(
        body,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _signable_forms(payload: AttributionTokenPayload) -> tuple[bytes, ...]:
    """Les formes canoniques acceptables, de la plus récente à la plus ancienne.

    La seconde est la forme d'AVANT `opportunity_key` : un jeton émis avant
    PR2b reste vérifiable même si le résolveur, lui, connaît désormais
    l'opportunité. L'empreinte du jeton est alors calculée sur la forme qui a
    RÉELLEMENT signé — sans quoi un clic d'hier et une inscription de demain ne
    se rejoindraient plus.
    """
    current = _canonical(payload)
    if payload.opportunity_key is None:
        return (current,)
    return (current, _canonical(payload.model_copy(update={"opportunity_key": None})))


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
            or any(
                re.fullmatch(r"[A-Za-z0-9_-]{1,100}", version) is None
                for version in copied
            )
            or any(not isinstance(secret, bytes) or len(secret) < 16 for secret in copied.values())
        ):
            raise ValueError("invalid attribution token keyring")
        object.__setattr__(self, "keys", MappingProxyType(copied))

    def issue(self, payload: AttributionTokenPayload) -> IssuedAttributionToken:
        keyed = payload.model_copy(update={"key_version": self.current_key_version})
        canonical = _canonical(keyed)
        secret = self.keys[self.current_key_version]
        signature = hmac.new(secret, _SIGNING_DOMAIN + canonical, hashlib.sha256).digest()
        if re.fullmatch(r"[0-9a-f]{64}", keyed.member_ref) is None:
            raise ValueError("attribution member ref must be an opaque fingerprint")
        raw_token = (
            f"{_TOKEN_PREFIX}.{self.current_key_version}."
            f"{keyed.member_ref}.{_b64(signature)}"
        )
        return IssuedAttributionToken(
            raw_token=raw_token,
            token_fingerprint=hmac.new(
                secret, _FINGERPRINT_DOMAIN + canonical, hashlib.sha256
            ).hexdigest(),
            token_version=ATTRIBUTION_TOKEN_VERSION,
            key_version=self.current_key_version,
            payload=keyed,
        )

    def parse(self, raw_token: str) -> AttributionTokenLookup:
        if not isinstance(raw_token, str) or len(raw_token) > 512:
            raise AttributionTokenInvalid("attribution token is invalid")
        parts = raw_token.split(".")
        if (
            len(parts) != 4
            or parts[0] != _TOKEN_PREFIX
            or re.fullmatch(r"[A-Za-z0-9_-]{1,100}", parts[1]) is None
            or re.fullmatch(r"[0-9a-f]{64}", parts[2]) is None
        ):
            raise AttributionTokenInvalid("attribution token is invalid")
        signature = _unb64(parts[3])
        if len(signature) != hashlib.sha256().digest_size:
            raise AttributionTokenInvalid("attribution token signature is invalid")
        return AttributionTokenLookup(
            key_version=parts[1], member_ref=parts[2], signature=signature
        )

    def verify(
        self,
        raw_token: str,
        *,
        payload: AttributionTokenPayload,
        at: dt.datetime,
    ) -> IssuedAttributionToken:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("verification time must be timezone-aware")
        lookup = self.parse(raw_token)
        if payload.member_ref != lookup.member_ref:
            raise AttributionTokenInvalid("attribution token payload is invalid")
        if payload.key_version not in (None, lookup.key_version):
            raise AttributionTokenInvalid("attribution token key binding is invalid")
        if lookup.key_version not in self.keys:
            raise AttributionTokenInvalid("attribution token key is unavailable")
        payload = payload.model_copy(update={"key_version": lookup.key_version})
        secret = self.keys[lookup.key_version]
        canonical: bytes | None = None
        matched_payload = payload
        for candidate in _signable_forms(payload):
            expected = hmac.new(secret, _SIGNING_DOMAIN + candidate, hashlib.sha256).digest()
            if hmac.compare_digest(lookup.signature, expected):
                canonical = candidate
                if candidate != _canonical(payload):
                    matched_payload = payload.model_copy(update={"opportunity_key": None})
                break
        if canonical is None:
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
            payload=matched_payload,
        )


__all__ = [
    "AttributionTokenExpired",
    "AttributionTokenInvalid",
    "AttributionTokenKeyring",
    "AttributionTokenLookup",
    "IssuedAttributionToken",
]
