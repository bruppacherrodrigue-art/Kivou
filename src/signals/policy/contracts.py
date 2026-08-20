"""Immutable, bounded contracts for Policy Gateway evaluation."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

POLICY_VERSION = "acquisition-policy-v1"
MAX_APPROVAL_GRANTS = 4
MAX_REASON_CODES = 32
MAX_EVIDENCE_REFS = 100
MAX_ARGUMENT_BYTES = 16_384

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
EvaluationIdentifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]
StableRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
ShortCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
CommandName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class PolicyStatus(StrEnum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    COMPLIANCE_BLOCKED = "COMPLIANCE_BLOCKED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    RATE_LIMITED = "RATE_LIMITED"


class AutonomyMode(StrEnum):
    SHADOW = "SHADOW"
    ASSISTED = "ASSISTED"
    AUTONOMOUS_CAPPED = "AUTONOMOUS_CAPPED"
    ADAPTIVE_SCALE = "ADAPTIVE_SCALE"


class ApprovalPurpose(StrEnum):
    ACTION = "ACTION"
    COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"


class ComplianceState(StrEnum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNKNOWN = "UNKNOWN"


class EvidenceStatus(StrEnum):
    READY = "READY"
    INSUFFICIENT = "INSUFFICIENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class ReadinessState(StrEnum):
    READY = "READY"
    EXHAUSTED = "EXHAUSTED"
    UNKNOWN = "UNKNOWN"


class AvailabilityState(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class WindowState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class PolicyError(RuntimeError):
    pass


class PolicyControlUnavailable(PolicyError):
    pass


class PolicyEvaluationIdempotencyConflict(PolicyError):
    pass


class PolicyAuditUnavailable(PolicyError):
    pass


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("datetime must be timezone-aware")
    return value


def _finite_nonnegative(value: Decimal | None) -> Decimal | None:
    if value is not None and (not value.is_finite() or value < 0):
        raise ValueError("value must be finite and non-negative")
    return value


def _guard_structure(value: object) -> None:
    if isinstance(value, dict):
        for raw_key, nested in value.items():
            key = re.sub(r"(?<!^)(?=[A-Z])", "_", str(raw_key))
            key = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
            if key in {
                "password", "secret", "api_key", "authorization", "access_token",
                "refresh_token", "session_token", "private_key", "chain_of_thought",
                "reasoning_trace", "scratchpad", "hidden_reasoning",
            }:
                raise ValueError(f"prohibited policy argument key: {key}")
            _guard_structure(nested)
    elif isinstance(value, list):
        for nested in value:
            _guard_structure(nested)


def _guard_text(value: str) -> str:
    if len(value.encode()) > MAX_ARGUMENT_BYTES:
        raise ValueError("canonical arguments too large")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("canonical arguments must be valid JSON") from exc
    _guard_structure(parsed)
    return value


class Scope(Contract):
    country: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")] | None = None
    language: Annotated[str, StringConstraints(pattern=r"^[a-z]{2}$")] | None = None
    wedge: ShortCode | None = None

    def fingerprint(self) -> str:
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()


class ApprovalGrant(Contract):
    approval_id: Identifier
    purpose: ApprovalPurpose
    command: CommandName
    target_ref: StableRef
    acquisition_opportunity_id: Identifier | None = None
    action_fingerprint: Fingerprint
    policy_version: ShortCode
    policy_snapshot_id: Identifier
    control_revision: int = Field(ge=1)
    scope_fingerprint: Fingerprint
    issued_at: dt.datetime
    expires_at: dt.datetime
    one_shot: bool = True
    consumed_at: dt.datetime | None = None
    approved_by_actor_ref: StableRef

    _issued = field_validator("issued_at")(_aware)
    _expires = field_validator("expires_at")(_aware)
    _consumed = field_validator("consumed_at")(_aware)

    @model_validator(mode="after")
    def valid_interval(self) -> ApprovalGrant:
        if self.expires_at <= self.issued_at:
            raise ValueError("approval expiry must follow issue time")
        return self


class ApprovalRef(Contract):
    """Safe durable proof that one bound approval satisfied a policy gate."""

    approval_id: Identifier
    purpose: ApprovalPurpose
    binding_fingerprint: Fingerprint


def approval_binding_fingerprint(grant: ApprovalGrant) -> str:
    """Hash only the canonical safe binding fields enforced by the evaluator."""
    binding = {
        "purpose": grant.purpose.value,
        "command": grant.command,
        "target_ref": grant.target_ref,
        "acquisition_opportunity_id": grant.acquisition_opportunity_id,
        "action_fingerprint": grant.action_fingerprint,
        "policy_version": grant.policy_version,
        "policy_snapshot_id": grant.policy_snapshot_id,
        "control_revision": grant.control_revision,
        "scope_fingerprint": grant.scope_fingerprint,
        "issued_at": grant.issued_at.isoformat(),
        "expires_at": grant.expires_at.isoformat(),
        "one_shot": grant.one_shot,
        "consumed_at": grant.consumed_at.isoformat() if grant.consumed_at else None,
    }
    encoded = json.dumps(binding, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class EvidenceReadiness(Contract):
    status: EvidenceStatus
    claims: tuple[ShortCode, ...] = Field(default=(), max_length=32)
    assessment_version: ShortCode
    observed_at: dt.datetime
    valid_until: dt.datetime | None = None
    _observed = field_validator("observed_at")(_aware)
    _valid = field_validator("valid_until")(_aware)


class ComplianceAssessment(Contract):
    state: ComplianceState
    assessment_version: ShortCode
    observed_at: dt.datetime
    valid_until: dt.datetime | None = None
    _observed = field_validator("observed_at")(_aware)
    _valid = field_validator("valid_until")(_aware)


class OperationalReadiness(Contract):
    runtime_revision: ShortCode
    provider_quota: ReadinessState = ReadinessState.READY
    mailbox_quota: ReadinessState = ReadinessState.READY
    send_window: WindowState = WindowState.OPEN
    provider_control_plane: AvailabilityState = AvailabilityState.AVAILABLE
    retry_after: dt.datetime | None = None
    valid_until: dt.datetime | None = None
    _retry = field_validator("retry_after")(_aware)
    _valid = field_validator("valid_until")(_aware)


class BudgetEnvelope(Contract):
    period_start: dt.datetime
    period_end: dt.datetime | None
    currency: Currency
    cost_cap: Decimal
    cost_used: Decimal
    volume_cap: int = Field(ge=0)
    volume_used: int = Field(ge=0)
    _start = field_validator("period_start")(_aware)
    _end = field_validator("period_end")(_aware)
    _money = field_validator("cost_cap", "cost_used")(_finite_nonnegative)

    @model_validator(mode="after")
    def bounds(self) -> BudgetEnvelope:
        if self.period_end is not None and self.period_end <= self.period_start:
            raise ValueError("budget period end must follow start")
        return self


class BudgetUsage(Contract):
    cost_used: Decimal = Decimal("0")
    volume_used: int = Field(default=0, ge=0)
    _cost = field_validator("cost_used")(_finite_nonnegative)


class PolicyControlSnapshot(Contract):
    policy_snapshot_id: Identifier
    control_revision: int = Field(ge=1)
    policy_version: ShortCode = POLICY_VERSION
    autonomy_mode: AutonomyMode
    shadow_target_mode: AutonomyMode | None = None
    read_only: bool
    kill_switch: bool
    allowed_commands: tuple[CommandName, ...] = Field(max_length=32)
    allowed_countries: tuple[ShortCode, ...] = Field(default=(), max_length=64)
    allowed_languages: tuple[ShortCode, ...] = Field(default=(), max_length=64)
    allowed_wedges: tuple[ShortCode, ...] = Field(default=(), max_length=64)
    currency: Currency
    daily_cost_cap: Decimal
    daily_volume_cap: int = Field(ge=0)
    effective_at: dt.datetime
    expires_at: dt.datetime | None = None
    snapshot_fingerprint: Fingerprint
    created_at: dt.datetime
    created_by_actor_type: Annotated[str, StringConstraints(pattern=r"^(SYSTEM|HUMAN)$")]
    created_by_actor_ref: StableRef
    reason_codes: tuple[ShortCode, ...] = Field(default=(), max_length=MAX_REASON_CODES)
    _cost = field_validator("daily_cost_cap")(_finite_nonnegative)
    _effective = field_validator("effective_at")(_aware)
    _expires = field_validator("expires_at")(_aware)
    _created = field_validator("created_at")(_aware)

    @model_validator(mode="after")
    def validity(self) -> PolicyControlSnapshot:
        if self.expires_at is not None and self.expires_at <= self.effective_at:
            raise ValueError("expires_at must follow effective_at")
        if self.autonomy_mode is AutonomyMode.SHADOW:
            if self.shadow_target_mode not in {
                AutonomyMode.ASSISTED,
                AutonomyMode.AUTONOMOUS_CAPPED,
                AutonomyMode.ADAPTIVE_SCALE,
            }:
                raise ValueError("SHADOW requires a non-SHADOW target mode")
        elif self.shadow_target_mode is not None:
            raise ValueError("shadow_target_mode is only valid in SHADOW")
        return self


class PolicySnapshot(Contract):
    policy_snapshot_id: Identifier
    control_revision: int = Field(ge=1)
    policy_version: ShortCode
    captured_at: dt.datetime
    expires_at: dt.datetime | None = None
    autonomy_mode: AutonomyMode
    shadow_target_mode: AutonomyMode | None = None
    read_only: bool
    kill_switch: bool
    allowed_commands: tuple[CommandName, ...] = Field(max_length=32)
    allowed_countries: tuple[ShortCode, ...] = Field(default=(), max_length=64)
    allowed_languages: tuple[ShortCode, ...] = Field(default=(), max_length=64)
    allowed_wedges: tuple[ShortCode, ...] = Field(default=(), max_length=64)
    budget: BudgetEnvelope
    runtime_revision: ShortCode
    _captured = field_validator("captured_at")(_aware)
    _expires = field_validator("expires_at")(_aware)

    @model_validator(mode="after")
    def shadow_contract(self) -> PolicySnapshot:
        if self.autonomy_mode is AutonomyMode.SHADOW:
            if self.shadow_target_mode not in {
                AutonomyMode.ASSISTED,
                AutonomyMode.AUTONOMOUS_CAPPED,
                AutonomyMode.ADAPTIVE_SCALE,
            }:
                raise ValueError("SHADOW requires a non-SHADOW target mode")
        elif self.shadow_target_mode is not None:
            raise ValueError("shadow_target_mode is only valid in SHADOW")
        return self


class PolicyRequest(Contract):
    evaluation_id: EvaluationIdentifier
    request_id: Identifier
    command: CommandName
    target_ref: StableRef
    acquisition_opportunity_id: Identifier | None = None
    expected_opportunity_version: int | None = Field(default=None, ge=1)
    actor_type: Annotated[str, StringConstraints(pattern=r"^(SYSTEM|HERMES|HUMAN|EXTERNAL)$")]
    actor_ref: StableRef | None = None
    canonical_arguments: str
    action_fingerprint: Fingerprint
    scope: Scope
    proposed_cost: Decimal = Decimal("0")
    currency: Currency
    proposed_volume: int = Field(default=0, ge=0)
    reason_codes: tuple[ShortCode, ...] = Field(default=(), max_length=MAX_REASON_CODES)
    evidence_refs: tuple[StableRef, ...] = Field(default=(), max_length=MAX_EVIDENCE_REFS)
    evidence: EvidenceReadiness
    compliance: ComplianceAssessment
    operational: OperationalReadiness
    expected_policy_version: ShortCode
    approval_grants: tuple[ApprovalGrant, ...] = Field(default=(), max_length=MAX_APPROVAL_GRANTS)
    supervisor_plan_id: Identifier | None = None
    supervisor_action_index: int | None = Field(default=None, ge=0)
    supervisor_version: ShortCode | None = None
    skill_version: ShortCode | None = None
    _arguments = field_validator("canonical_arguments")(_guard_text)
    _cost = field_validator("proposed_cost")(_finite_nonnegative)


class PolicyDecision(Contract):
    evaluation_id: EvaluationIdentifier
    request_id: Identifier
    status: PolicyStatus
    counterfactual_status: PolicyStatus | None = None
    executable: bool
    command: CommandName
    target_ref: StableRef
    acquisition_opportunity_id: Identifier | None = None
    action_fingerprint: Fingerprint
    reason_codes: tuple[ShortCode, ...]
    policy_version: ShortCode
    policy_snapshot_id: Identifier
    control_revision: int
    runtime_revision: ShortCode
    evaluated_at: dt.datetime
    valid_until: dt.datetime | None = None
    requires_revalidation: bool = True
    currency: Currency
    estimated_cost: Decimal
    proposed_volume: int
    cost_remaining: Decimal
    volume_remaining: int
    retry_after: dt.datetime | None = None
    approval_refs: tuple[ApprovalRef, ...] = Field(default=(), max_length=MAX_APPROVAL_GRANTS)
    evidence_refs: tuple[StableRef, ...] = Field(default=(), max_length=MAX_EVIDENCE_REFS)
    _evaluated = field_validator("evaluated_at")(_aware)
    _valid = field_validator("valid_until")(_aware)
    _retry = field_validator("retry_after")(_aware)

    @property
    def allowed(self) -> bool:
        return self.status is PolicyStatus.APPROVED and self.executable
