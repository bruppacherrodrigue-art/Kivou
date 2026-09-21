"""Opaque program tokens and minimal signed Milo Mail conversion ingress.

Conversion facts are appended to Kivou's existing acquisition event journal;
the receipt table only prevents replay across opportunities.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.engine import Engine

from signals.acquisition.contracts import EventType
from signals.acquisition.store import AcquisitionStore
from signals.compliance.suppression import (
    MILOMAIL_SUPPRESSION_SCOPE,
    SuppressionIdentityKeyring,
)
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import (
    acquisition_contact,
    acquisition_program,
    acquisition_program_attribution,
    acquisition_program_conversion_receipt,
    acquisition_program_eligibility,
)
from signals.prospection_actions.suppression import EmailSuppressionChecker

_TOKEN_DOMAIN = b"milomail:program-attribution-token:v1\0"
_WEBHOOK_DOMAIN = b"milomail-conversion-v1\0"
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_OPAQUE_EVENT = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


@dataclass(frozen=True)
class ProgramAttributionKeyring:
    current_key_version: str
    keys: Mapping[str, bytes] = field(repr=False)

    def __post_init__(self) -> None:
        copied = dict(self.keys)
        if (
            self.current_key_version not in copied
            or len(copied) > 8
            or any(not _OPAQUE_EVENT.fullmatch(version) for version in copied)
            or any(not isinstance(secret, bytes) or len(secret) < 16 for secret in copied.values())
        ):
            raise ValueError("invalid program attribution keyring")
        object.__setattr__(self, "keys", MappingProxyType(copied))


class ProgramAttributionService:
    def __init__(
        self,
        engine: Engine,
        keyring: ProgramAttributionKeyring,
        suppression_keyring: SuppressionIdentityKeyring,
        *,
        clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._engine = engine
        self._keys = keyring
        self._suppression_keys = suppression_keyring
        self._clock = clock
        self._suppression = EmailSuppressionChecker(
            suppression_keyring,
            scope=MILOMAIL_SUPPRESSION_SCOPE,
        )

    def issue(
        self,
        *,
        program_id: str,
        opportunity_id: str,
        campaign_ref: str,
        issued_at: dt.datetime,
        expires_at: dt.datetime,
        recipient_email: str,
    ) -> str:
        if (
            issued_at.tzinfo is None
            or expires_at.tzinfo is None
            or not issued_at < expires_at <= issued_at + dt.timedelta(days=62)
        ):
            raise ValueError("attribution lifetime is invalid")
        version = self._keys.current_key_version
        seed = f"{program_id}\0{opportunity_id}\0{campaign_ref}\0{version}".encode()
        token = (
            base64.urlsafe_b64encode(
                hmac.new(self._keys.keys[version], _TOKEN_DOMAIN + seed, hashlib.sha256).digest()
            )
            .rstrip(b"=")
            .decode()
        )
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        attribution_id = hashlib.sha256(b"milomail:attribution:v1\0" + seed).hexdigest()
        identities = self._suppression_keys.identities_for_email(
            recipient_email,
            scope=MILOMAIL_SUPPRESSION_SCOPE,
        )
        recipient_version = self._suppression_keys.current_key_version
        values = {
            "attribution_id": attribution_id,
            "program_id": program_id,
            "acquisition_opportunity_id": opportunity_id,
            "campaign_ref": campaign_ref,
            "opaque_token_hash": token_hash,
            "key_version": version,
            "recipient_identity_hmac": identities[recipient_version],
            "recipient_identity_key_version": recipient_version,
            "issued_at": issued_at,
            "expires_at": expires_at,
        }
        with self._engine.begin() as connection:
            checked_at = max(_utc(issued_at), _utc(self._clock()))
            if expires_at <= checked_at:
                raise ValueError("attribution token has expired")
            if self._suppression.is_suppressed(connection, email=recipient_email, at=checked_at):
                raise ValueError("suppressed recipient cannot receive attribution")
            program = (
                connection.execute(
                    sa.select(acquisition_program).where(
                        acquisition_program.c.program_id == program_id
                    )
                )
                .mappings()
                .one()
            )
            if (
                program["program_key"] != "milomail"
                or program["mode"] != "SHADOW"
                or not campaign_ref.startswith("milomail:")
            ):
                raise ValueError("Milo Mail attribution program binding mismatch")
            latest = connection.execute(
                sa.select(
                    acquisition_program_eligibility.c.decision,
                    acquisition_program_eligibility.c.contact_ref,
                    acquisition_program_eligibility.c.professional_evidence,
                    acquisition_contact.c.business_email,
                )
                .select_from(acquisition_program_eligibility.outerjoin(
                    acquisition_contact,
                    acquisition_program_eligibility.c.contact_ref == acquisition_contact.c.contact_ref,
                ))
                .where(
                    acquisition_program_eligibility.c.program_id == program_id,
                    acquisition_program_eligibility.c.acquisition_opportunity_id == opportunity_id,
                )
                .order_by(
                    acquisition_program_eligibility.c.evaluated_at.desc(),
                    acquisition_program_eligibility.c.eligibility_id.desc(),
                )
                .limit(1)
            ).mappings().one_or_none()
            if latest is None or latest["decision"] != "SEND":
                raise ValueError("attribution requires a theoretical SEND assessment")
            if not latest["contact_ref"] or not latest["business_email"]:
                raise ValueError("attribution requires a selected contact")
            selected_identity = self._suppression_keys.identities_for_email(
                latest["business_email"], scope=MILOMAIL_SUPPRESSION_SCOPE,
            )[recipient_version]
            if not hmac.compare_digest(selected_identity, identities[recipient_version]):
                raise ValueError("attribution recipient differs from selected contact")
            assessed_identity = latest["professional_evidence"]
            assessed_version = assessed_identity.get("recipient_identity_key_version")
            if (
                not isinstance(assessed_version, str)
                or assessed_version not in self._suppression_keys.keys
                or not isinstance(assessed_identity.get("recipient_identity_hmac"), str)
                or not hmac.compare_digest(
                    assessed_identity["recipient_identity_hmac"],
                    identities[assessed_version],
                )
            ):
                raise ValueError("attribution recipient differs from assessed recipient")
            inserted = insert_if_absent(
                connection,
                acquisition_program_attribution,
                values,
                index_elements=[acquisition_program_attribution.c.attribution_id],
            )
            if not inserted:
                row = (
                    connection.execute(
                        sa.select(acquisition_program_attribution).where(
                            acquisition_program_attribution.c.attribution_id == attribution_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None or any(
                    _compare_value(row[key]) != _compare_value(value)
                    for key, value in values.items()
                ):
                    raise ValueError("attribution issuance idempotency conflict")
        return token


def _compare_value(value):
    return _utc(value) if isinstance(value, dt.datetime) else value


class ProductConversionEventType(StrEnum):
    LANDING_CLICKED = "landing_clicked"
    AUDIT_STARTED = "audit_started"
    GOOGLE_OAUTH_COMPLETED = "google_oauth_completed"
    AUDIT_COMPLETED = "audit_completed"
    MILO_CLEAN_CHECKOUT_STARTED = "milo_clean_checkout_started"
    MILO_CLEAN_PAID = "milo_clean_paid"
    M1_RETAINED = "m1_retained"
    M2_RETAINED = "m2_retained"


class ProductConversionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    event_id: str = Field(min_length=1, max_length=128)
    event_type: ProductConversionEventType
    attribution_token: str = Field(min_length=43, max_length=43, repr=False)
    occurred_at: dt.datetime
    mrr_chf: Decimal | None = Field(default=None, ge=0)

    @field_validator("event_id")
    @classmethod
    def opaque_id(cls, value: str) -> str:
        if not _OPAQUE_EVENT.fullmatch(value):
            raise ValueError("conversion event ID must be opaque")
        return value

    @field_validator("attribution_token")
    @classmethod
    def opaque_token(cls, value: str) -> str:
        if not _TOKEN_PATTERN.fullmatch(value):
            raise ValueError("invalid program attribution token")
        return value

    @field_validator("occurred_at")
    @classmethod
    def aware(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("conversion time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def money_only_for_paid_or_retained(self) -> ProductConversionEvent:
        if self.mrr_chf is not None and self.event_type not in {
            ProductConversionEventType.MILO_CLEAN_PAID,
            ProductConversionEventType.M1_RETAINED,
            ProductConversionEventType.M2_RETAINED,
        }:
            raise ValueError("MRR is not valid on an earlier funnel milestone")
        return self


class MilomailConversionIngress:
    def __init__(
        self,
        engine: Engine,
        acquisition: AcquisitionStore,
        *,
        program_id: str,
        webhook_secret: bytes,
    ) -> None:
        if not isinstance(webhook_secret, bytes) or len(webhook_secret) < 16:
            raise ValueError("Milo Mail webhook key is unavailable")
        self._engine = engine
        self._acquisition = acquisition
        self._program_id = program_id
        self._secret = webhook_secret

    def ingest(
        self,
        raw_body: bytes,
        *,
        headers: Mapping[str, str],
        received_at: dt.datetime,
    ) -> str:
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("webhook reception time must be timezone-aware")
        if not isinstance(raw_body, bytes) or len(raw_body) > 4096:
            raise ValueError("Milo Mail event body exceeds bound")
        stamp = headers.get("X-MiloMail-Timestamp", "")
        signature = headers.get("X-MiloMail-Signature", "")
        if not stamp.isdigit() or len(stamp) > 12:
            raise ValueError("invalid Milo Mail webhook timestamp")
        if abs(int(stamp) - int(received_at.timestamp())) > 300:
            raise ValueError("Milo Mail webhook timestamp is outside replay window")
        expected = hmac.new(
            self._secret,
            _WEBHOOK_DOMAIN + stamp.encode() + b"\0" + raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not re.fullmatch(r"[0-9a-f]{64}", signature) or not hmac.compare_digest(
            signature, expected
        ):
            raise ValueError("invalid Milo Mail webhook signature")
        try:

            def unique_pairs(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate event key")
                    result[key] = value
                return result

            decoded = json.loads(raw_body, object_pairs_hook=unique_pairs)
            event = ProductConversionEvent.model_validate(decoded)
        except (ValueError, TypeError):
            raise ValueError("invalid minimal Milo Mail conversion payload") from None
        if not (
            received_at - dt.timedelta(days=7)
            <= event.occurred_at
            <= received_at + dt.timedelta(minutes=5)
        ):
            raise ValueError("conversion occurrence is outside accepted bound")
        token_hash = hashlib.sha256(event.attribution_token.encode()).hexdigest()
        event_id_hash = hmac.new(
            self._secret,
            b"milomail:conversion-event-id:v1\0" + event.event_id.encode(),
            hashlib.sha256,
        ).hexdigest()
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type.value,
                    "token_hash": token_hash,
                    "occurred_at": event.occurred_at.isoformat(),
                    "mrr_chf": str(event.mrr_chf) if event.mrr_chf is not None else None,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        receipt_id = hashlib.sha256(
            f"milomail:conversion-receipt:v1\0{self._program_id}\0{event_id_hash}".encode()
        ).hexdigest()
        with self._engine.begin() as connection:
            binding = (
                connection.execute(
                    sa.select(acquisition_program_attribution).where(
                        acquisition_program_attribution.c.program_id == self._program_id,
                        acquisition_program_attribution.c.opaque_token_hash == token_hash,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if binding is None:
                raise ValueError("unknown Milo Mail attribution binding")
            if not (_utc(binding["issued_at"]) <= event.occurred_at < _utc(binding["expires_at"])):
                raise ValueError("Milo Mail attribution token outside validity")
            existing = (
                connection.execute(
                    sa.select(acquisition_program_conversion_receipt).where(
                        acquisition_program_conversion_receipt.c.program_id == self._program_id,
                        acquisition_program_conversion_receipt.c.event_id_hash == event_id_hash,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if existing["payload_fingerprint"] != fingerprint:
                    raise ValueError("conversion event idempotency conflict")
                return existing["receipt_id"]
            opportunity_id = binding["acquisition_opportunity_id"]
            current = self._acquisition.get_opportunity_in_transaction(
                connection,
                opportunity_id,
                for_update=True,
            )
            appended = self._acquisition.append_in_transaction(
                connection,
                opportunity_id,
                event_type=EventType.POLICY_EVALUATED,
                expected_version=current.stream_version,
                idempotency_key=receipt_id,
                payload={
                    "kind": "program_conversion_event",
                    "program_id": self._program_id,
                    "attribution_id": binding["attribution_id"],
                    "event_type": event.event_type.value,
                    "mrr_chf": str(event.mrr_chf) if event.mrr_chf is not None else None,
                },
                reason_codes=(event.event_type.value.upper(),),
                policy_version=None,
                occurred_at=event.occurred_at,
            )
            connection.execute(
                sa.insert(acquisition_program_conversion_receipt).values(
                    receipt_id=receipt_id,
                    program_id=self._program_id,
                    attribution_id=binding["attribution_id"],
                    event_id_hash=event_id_hash,
                    payload_fingerprint=fingerprint,
                    event_type=event.event_type.value,
                    recorded_event_id=appended.event.event_id,
                    received_at=received_at,
                )
            )
        return receipt_id


__all__ = [
    "MilomailConversionIngress",
    "ProductConversionEvent",
    "ProductConversionEventType",
    "ProgramAttributionKeyring",
    "ProgramAttributionService",
]
