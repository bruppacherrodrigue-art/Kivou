"""Domain-separated recipe tokens with no commercial attribution authority."""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from signals.conversion.token import AttributionTokenKeyring

_DOMAIN = b"kivou:qa-attribution:v1\0"
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]


class QaTokenPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    qa: Literal[True] = True
    opportunity_key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    wedge: Text
    country: Literal["FR", "CH"]
    sector: Text
    need: Text
    issued_at: dt.datetime
    expires_at: dt.datetime
    nonce: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")] = Field(
        default_factory=lambda: secrets.token_hex(16)
    )

    @model_validator(mode="after")
    def valid_window(self):
        if any(value.tzinfo is None or value.utcoffset() is None
               for value in (self.issued_at, self.expires_at)):
            raise ValueError("QA timestamps must be timezone-aware")
        if not dt.timedelta(0) < self.expires_at - self.issued_at <= dt.timedelta(days=7):
            raise ValueError("QA lifetime must be positive and at most seven days")
        return self


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _b64(decoded) != value:
        raise ValueError("Noncanonical QA token encoding")
    return decoded


def keyring_from_environment() -> AttributionTokenKeyring:
    secret = os.environ.get("KIVOU_ATTRIBUTION_HMAC_KEY")
    version = os.environ.get("KIVOU_ATTRIBUTION_HMAC_KEY_VERSION")
    if not secret or not version:
        raise ValueError("KIVOU_ATTRIBUTION_HMAC_KEY and its version must be loaded")
    return AttributionTokenKeyring(current_key_version=version, keys={version: secret.encode()})


def issue(payload: QaTokenPayload, *, keyring: AttributionTokenKeyring) -> str:
    body = json.dumps(payload.model_dump(mode="json"), sort_keys=True,
                      ensure_ascii=True, separators=(",", ":")).encode()
    signed = f"kqa1.{keyring.current_key_version}.{_b64(body)}"
    signature = hmac.digest(keyring.keys[keyring.current_key_version],
                            _DOMAIN + signed.encode("ascii"), "sha256")
    return f"{signed}.{_b64(signature)}"


def verify(raw: str, *, keyring: AttributionTokenKeyring, at: dt.datetime) -> QaTokenPayload:
    if len(raw) > 4096 or at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Invalid QA token")
    parts = raw.split(".")
    if len(parts) != 4 or parts[0] != "kqa1" or parts[1] not in keyring.keys:
        raise ValueError("Invalid QA token")
    try:
        signed = ".".join(parts[:3]).encode("ascii")
        expected = hmac.digest(keyring.keys[parts[1]], _DOMAIN + signed, "sha256")
        if not hmac.compare_digest(_decode(parts[3]), expected):
            raise ValueError("Invalid QA signature")
        payload = QaTokenPayload.model_validate_json(_decode(parts[2]))
    except (ValueError, UnicodeError) as error:
        raise ValueError("Invalid QA token") from error
    if not payload.issued_at <= at < payload.expires_at:
        raise ValueError("QA token expired or not active")
    return payload


def fingerprint(raw: str) -> str:
    return hashlib.sha256(_DOMAIN + raw.encode("ascii")).hexdigest()
