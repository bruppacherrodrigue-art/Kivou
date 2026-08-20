"""Strict Kivou-owned contracts for durable acquisition state and events."""

from __future__ import annotations

import datetime as dt
import json
import re
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

STATE_MACHINE_VERSION = "acquisition-state-v1"
EVENT_SCHEMA_VERSION = 1
MAX_EVENT_PAYLOAD_BYTES = 65_536
MAX_REASON_CODES = 50
MAX_EVIDENCE_REFS = 100

ShortCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
StableRef = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
Identifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class AcquisitionState(StrEnum):
    DISCOVERED = "DISCOVERED"
    ENRICHING = "ENRICHING"
    READY_FOR_DECISION = "READY_FOR_DECISION"
    HOLD = "HOLD"
    NO_SEND = "NO_SEND"
    REVIEW = "REVIEW"
    SEND = "SEND"
    QUEUED = "QUEUED"
    SENT = "SENT"
    REPLIED = "REPLIED"
    ACTIVATED = "ACTIVATED"
    PAID = "PAID"
    RETAINED = "RETAINED"
    CHURNED = "CHURNED"


class Decision(StrEnum):
    SEND = "SEND"
    HOLD = "HOLD"
    ENRICH = "ENRICH"
    NO_SEND = "NO_SEND"
    REVIEW = "REVIEW"


class ActorType(StrEnum):
    SYSTEM = "SYSTEM"
    HERMES = "HERMES"
    HUMAN = "HUMAN"
    EXTERNAL = "EXTERNAL"


class EventType(StrEnum):
    OPPORTUNITY_CREATED = "OPPORTUNITY_CREATED"
    STATE_TRANSITIONED = "STATE_TRANSITIONED"
    DECISION_RECORDED = "DECISION_RECORDED"
    NEXT_ACTION_SET = "NEXT_ACTION_SET"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    SUPERVISOR_PLAN_OBSERVED = "SUPERVISOR_PLAN_OBSERVED"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    CONTACT_SELECTED = "CONTACT_SELECTED"
    OUTCOME_RECORDED = "OUTCOME_RECORDED"


class ProjectionVerification(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"


class AcquisitionError(RuntimeError):
    """Base class for typed acquisition-domain failures."""


class InvalidTransition(AcquisitionError):
    pass


class IdempotencyConflict(AcquisitionError):
    pass


class AcquisitionIdentityConflict(AcquisitionError):
    pass


class OpportunityConcurrencyConflict(AcquisitionError):
    pass


class UnsupportedStateMachineVersion(AcquisitionError):
    pass


class SupervisorAuditMappingError(AcquisitionError):
    pass


class ProjectionNotFound(AcquisitionError):
    pass


class AcquisitionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("datetime must be timezone-aware")
    return value


def _normalized_key(value: str) -> str:
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", value)
    return re.sub(r"[^a-z0-9]+", "_", snake.lower()).strip("_")


_SECRET_KEYS = frozenset(
    {
        "password",
        "secret",
        "api_key",
        "authorization",
        "access_token",
        "refresh_token",
        "session_token",
        "private_key",
        "client_secret",
        "bearer_token",
    }
)
_HIDDEN_REASONING_KEYS = frozenset(
    {
        "chain_of_thought",
        "reasoning_trace",
        "scratchpad",
        "internal_reasoning",
        "hidden_reasoning",
    }
)


def _guard_payload(value: object) -> None:
    if isinstance(value, dict):
        for raw_key, nested in value.items():
            key = _normalized_key(str(raw_key))
            if key in _SECRET_KEYS:
                raise ValueError(f"prohibited payload key: {key}")
            if key in _HIDDEN_REASONING_KEYS:
                raise ValueError(f"hidden reasoning payload key: {key}")
            _guard_payload(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _guard_payload(nested)


def _validate_payload(value: dict[str, Any]) -> dict[str, Any]:
    _guard_payload(value)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("payload must contain finite JSON values") from exc
    if len(encoded) > MAX_EVENT_PAYLOAD_BYTES:
        raise ValueError(
            f"event payload exceeds {MAX_EVENT_PAYLOAD_BYTES} serialized bytes"
        )
    return value


class AcquisitionEvent(AcquisitionContract):
    event_id: Identifier
    acquisition_opportunity_id: Identifier
    stream_sequence: int = Field(ge=1)
    event_type: EventType
    schema_version: int = Field(default=EVENT_SCHEMA_VERSION, ge=1)
    state_machine_version: ShortCode = STATE_MACHINE_VERSION
    occurred_at: dt.datetime
    recorded_at: dt.datetime
    actor_type: ActorType
    actor_ref: StableRef | None = None
    idempotency_key: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ]
    semantic_fingerprint: Fingerprint
    correlation_id: Identifier | None = None
    causation_id: Identifier | None = None
    reason_codes: tuple[ShortCode, ...] = Field(default=(), max_length=MAX_REASON_CODES)
    evidence_refs: tuple[ShortCode, ...] = Field(default=(), max_length=MAX_EVIDENCE_REFS)
    policy_version: ShortCode | None = None
    skill_version: ShortCode | None = None
    supervisor_version: ShortCode | None = None
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    estimated_cost: Decimal | None = Field(default=None, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)

    _validate_occurred_at = field_validator("occurred_at")(_aware)
    _validate_recorded_at = field_validator("recorded_at")(_aware)
    _validate_payload = field_validator("payload")(_validate_payload)


class AcquisitionOpportunity(AcquisitionContract):
    acquisition_opportunity_id: Identifier
    identity_key: StableRef
    state: AcquisitionState
    stream_version: int = Field(ge=1)
    state_machine_version: ShortCode
    signal_ref: StableRef
    supplier_ref: StableRef | None = None
    contact_ref: StableRef | None = None
    campaign_ref: StableRef | None = None
    decision: Decision | None = None
    reason_codes: tuple[ShortCode, ...] = Field(default=(), max_length=MAX_REASON_CODES)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    evidence_refs: tuple[ShortCode, ...] = Field(default=(), max_length=MAX_EVIDENCE_REFS)
    next_action: ShortCode | None = None
    next_review_at: dt.datetime | None = None
    retry_count: int = Field(default=0, ge=0)
    retry_at: dt.datetime | None = None
    last_error_category: ShortCode | None = None
    policy_version: ShortCode | None = None
    skill_version: ShortCode | None = None
    supervisor_version: ShortCode | None = None
    estimated_cost: Decimal | None = Field(default=None, ge=0)
    last_event_id: Identifier
    created_at: dt.datetime
    updated_at: dt.datetime

    _validate_next_review_at = field_validator("next_review_at")(_aware)
    _validate_retry_at = field_validator("retry_at")(_aware)
    _validate_created_at = field_validator("created_at")(_aware)
    _validate_updated_at = field_validator("updated_at")(_aware)
