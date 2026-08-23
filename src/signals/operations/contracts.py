"""Strict, PII-minimal contracts for SPEC-031 operations."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
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

from signals.policy.contracts import AutonomyMode

OPERATIONS_VERSION = "acquisition-operations-v1"
BREAKER_VERSION = "acquisition-circuit-breaker-v1"
RETRY_POLICY_VERSION = "acquisition-retry-policy-v1"
HEALTH_VERSION = "acquisition-operational-health-v1"
READINESS_VERSION = "autonomous-readiness-v1"

SafeRef = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
SafeCode = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z0-9][A-Z0-9_:-]{0,99}$")
]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(dt.UTC)


def _finite(value: Decimal | None) -> Decimal | None:
    if value is not None and not value.is_finite():
        raise ValueError("metric must be finite")
    return value


def _internal_ref(value: str | None) -> str | None:
    if value is not None and ("@" in value or "://" in value or any(ch.isspace() for ch in value)):
        raise ValueError("operational references must be opaque Kivou refs, not PII or URLs")
    return value


def canonical_fingerprint(domain: str, value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode()
    return hashlib.sha256(domain.encode() + b"\0" + encoded).hexdigest()


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ScopeType(StrEnum):
    GLOBAL = "GLOBAL"
    COUNTRY = "COUNTRY"
    WEDGE = "WEDGE"
    CAMPAIGN = "CAMPAIGN"
    MAILBOX = "MAILBOX"


class IncidentType(StrEnum):
    BOUNCE_RATE = "BOUNCE_RATE"
    COMPLAINT = "COMPLAINT"
    COMPLIANCE_FAILURE = "COMPLIANCE_FAILURE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    UNEXPECTED_TRANSPORT_TRUTH = "UNEXPECTED_TRANSPORT_TRUTH"
    BUDGET_BREACH = "BUDGET_BREACH"
    COST_DRIFT = "COST_DRIFT"
    CONVERSION_DEGRADATION = "CONVERSION_DEGRADATION"
    RETENTION_DEGRADATION = "RETENTION_DEGRADATION"
    MAILBOX_UNAVAILABLE = "MAILBOX_UNAVAILABLE"


class IncidentSeverity(StrEnum):
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentState(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class DeadLetterStatus(StrEnum):
    OPEN = "OPEN"
    REQUEUED = "REQUEUED"
    RESOLVED = "RESOLVED"


class WorkType(StrEnum):
    SUPERVISOR_CYCLE = "SUPERVISOR_CYCLE"
    SUPPLIER_DISCOVERY = "SUPPLIER_DISCOVERY"
    CONTACT_DISCOVERY = "CONTACT_DISCOVERY"
    COMPANY_RESEARCH = "COMPANY_RESEARCH"
    CAMPAIGN_PROVIDER_OPERATION = "CAMPAIGN_PROVIDER_OPERATION"
    RESPONSE_RESOLUTION = "RESPONSE_RESOLUTION"
    CONVERSION_RECONCILIATION = "CONVERSION_RECONCILIATION"
    LEARNING_CYCLE = "LEARNING_CYCLE"


class HealthStatus(StrEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    NOT_READY = "NOT_READY"


class GateStatus(StrEnum):
    READY = "READY"
    NOT_READY = "NOT_READY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class RetryDisposition(StrEnum):
    RETRY = "RETRY"
    DLQ = "DLQ"
    RECONCILE_FIRST = "RECONCILE_FIRST"


class BreakerScope(_FrozenModel):
    scope_type: ScopeType
    scope_ref: SafeRef
    _safe_scope = field_validator("scope_ref")(_internal_ref)


class IncidentTrigger(_FrozenModel):
    incident_type: IncidentType
    severity: IncidentSeverity
    scope: BreakerScope
    source_state_ref: SafeRef
    triggered_at: dt.datetime
    reason_codes: tuple[SafeCode, ...] = Field(min_length=1, max_length=16)
    observed_value: Decimal | None = None
    threshold_value: Decimal | None = None
    metric_version: SafeRef | None = None
    campaign_ref: SafeRef | None = None
    mailbox_ref: SafeRef | None = None
    wedge: SafeRef | None = None
    country: str | None = Field(default=None, pattern=r"^(CH|FR)$")
    human_review_required: bool = False
    pause_required: bool = False
    policy_control_before: SafeRef | None = None
    policy_control_after: SafeRef | None = None
    _time = field_validator("triggered_at")(_aware)
    _metric = field_validator("observed_value", "threshold_value")(_finite)
    _safe_refs = field_validator(
        "source_state_ref", "campaign_ref", "mailbox_ref", "wedge"
    )(_internal_ref)

    @property
    def trigger_fingerprint(self) -> str:
        return canonical_fingerprint(
            "acquisition-operational-incident:v1",
            {
                "version": BREAKER_VERSION,
                "type": self.incident_type.value,
                "scope": self.scope.model_dump(mode="json"),
                "source_state_ref": self.source_state_ref,
                "metric_version": self.metric_version,
            },
        )

    @property
    def incident_ref(self) -> str:
        return canonical_fingerprint("acquisition-operational-incident-ref:v1", self.trigger_fingerprint)


class DeadLetterExhaustion(_FrozenModel):
    work_type: WorkType
    work_ref: SafeRef
    scope: BreakerScope
    attempt_count: int = Field(ge=1, le=100)
    first_failed_at: dt.datetime
    last_failed_at: dt.datetime
    failure_code: SafeCode
    retry_policy_version: SafeRef
    source_component: Annotated[
        str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    ]
    source_state_ref: SafeRef
    _first = field_validator("first_failed_at")(_aware)
    _last = field_validator("last_failed_at")(_aware)
    _safe_refs = field_validator(
        "work_ref", "retry_policy_version", "source_state_ref"
    )(_internal_ref)

    @model_validator(mode="after")
    def failure_window(self) -> DeadLetterExhaustion:
        if self.last_failed_at < self.first_failed_at:
            raise ValueError("last failure cannot precede first failure")
        return self

    @property
    def exhaustion_fingerprint(self) -> str:
        return canonical_fingerprint(
            "acquisition-dead-letter-exhaustion:v1",
            {
                "work_type": self.work_type.value,
                "work_ref": self.work_ref,
                "scope": self.scope.model_dump(mode="json"),
                "retry_policy_version": self.retry_policy_version,
                "source_component": self.source_component,
                "source_state_ref": self.source_state_ref,
            },
        )

    @property
    def dead_letter_ref(self) -> str:
        return canonical_fingerprint("acquisition-dead-letter-ref:v1", self.exhaustion_fingerprint)


class RetryDecision(_FrozenModel):
    disposition: RetryDisposition
    retry_at: dt.datetime | None = None
    _retry = field_validator("retry_at")(_aware)


class RetryPolicy(_FrozenModel):
    version: SafeRef
    maximum_attempts: int = Field(ge=1, le=20)
    delays_seconds: tuple[int, ...]

    @model_validator(mode="after")
    def delays_match_attempts(self) -> RetryPolicy:
        if len(self.delays_seconds) != self.maximum_attempts:
            raise ValueError("one delay is required per allowed attempt")
        if any(item <= 0 for item in self.delays_seconds):
            raise ValueError("retry delays must be positive")
        return self

    def decide(
        self,
        attempt: int,
        *,
        failed_at: dt.datetime,
        external_outcome_unknown: bool = False,
    ) -> RetryDecision:
        failed_at = _aware(failed_at)
        if external_outcome_unknown:
            return RetryDecision(disposition=RetryDisposition.RECONCILE_FIRST)
        if attempt >= self.maximum_attempts:
            return RetryDecision(disposition=RetryDisposition.DLQ)
        if attempt < 1:
            raise ValueError("attempt must be positive")
        return RetryDecision(
            disposition=RetryDisposition.RETRY,
            retry_at=failed_at + dt.timedelta(seconds=self.delays_seconds[attempt - 1]),
        )


DEFAULT_RETRY_POLICY = RetryPolicy(
    version=RETRY_POLICY_VERSION,
    maximum_attempts=5,
    delays_seconds=(60, 120, 240, 480, 960),
)


class HermesRuntimeIdentity(_FrozenModel):
    repository: SafeRef
    tag: SafeRef
    commit: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
    version: SafeRef
    python_contract: SafeRef


class HealthComponent(_FrozenModel):
    status: HealthStatus
    reason_codes: tuple[SafeCode, ...] = Field(default=(), max_length=16)


class HealthEvidence(_FrozenModel):
    observed_at: dt.datetime
    api: HealthStatus
    database: HealthStatus
    hermes_runtime: HealthStatus
    supervisor_loop: HealthStatus
    policy_control: HealthStatus
    campaign_execution: HealthStatus
    dlq: HealthStatus
    circuit_breakers: HealthStatus
    reason_codes: tuple[SafeCode, ...] = Field(default=(), max_length=32)
    _observed = field_validator("observed_at")(_aware)


class AcquisitionOperationalHealth(_FrozenModel):
    version: str = HEALTH_VERSION
    observed_at: dt.datetime
    api: HealthStatus
    database: HealthStatus
    hermes_runtime: HealthStatus
    supervisor_loop: HealthStatus
    policy_control: HealthStatus
    campaign_execution: HealthStatus
    dlq: HealthStatus
    circuit_breakers: HealthStatus
    status: HealthStatus
    reason_codes: tuple[SafeCode, ...]
    _observed = field_validator("observed_at")(_aware)


class GateEvidence(_FrozenModel):
    status: GateStatus
    reason_codes: tuple[SafeCode, ...] = Field(default=(), max_length=16)
    evidence_refs: tuple[SafeRef, ...] = Field(default=(), max_length=32)


class ReadinessEvidence(_FrozenModel):
    evaluated_at: dt.datetime
    h_a_runtime: GateEvidence
    h_b_state: GateEvidence
    h_c_policy: GateEvidence
    h_d_shadow: GateEvidence
    h_e_capped: GateEvidence
    h_f_closed_loop: GateEvidence
    h_g_scale: GateEvidence
    _evaluated = field_validator("evaluated_at")(_aware)

    @classmethod
    def repository_default(cls, *, evaluated_at: dt.datetime) -> ReadinessEvidence:
        return cls(
            evaluated_at=evaluated_at,
            h_a_runtime=GateEvidence(
                status=GateStatus.NOT_READY,
                reason_codes=("HERMES_RUNTIME_UNCONFIGURED", "ENVIRONMENT_UNCONFIGURED"),
            ),
            h_b_state=GateEvidence(
                status=GateStatus.READY,
                reason_codes=("DURABLE_REPLAY_CONTRACTS_PRESENT",),
                evidence_refs=("acquisition-state-v1",),
            ),
            h_c_policy=GateEvidence(
                status=GateStatus.READY,
                reason_codes=("POLICY_COMMAND_COVERAGE_PRESENT",),
                evidence_refs=("acquisition-policy-v1",),
            ),
            h_d_shadow=GateEvidence(
                status=GateStatus.INSUFFICIENT_EVIDENCE,
                reason_codes=("HUMAN_REVIEW_TRUTH_UNAVAILABLE",),
            ),
            h_e_capped=GateEvidence(
                status=GateStatus.NOT_READY,
                reason_codes=(
                    "PRODUCTION_MAILBOX_UNCONFIGURED",
                    "COST_COVERAGE_INCOMPLETE",
                ),
            ),
            h_f_closed_loop=GateEvidence(
                status=GateStatus.READY,
                reason_codes=("CLOSED_LOOP_IDENTITIES_PRESENT",),
                evidence_refs=("weekly-commercial-cockpit-v1",),
            ),
            h_g_scale=GateEvidence(
                status=GateStatus.NOT_READY,
                reason_codes=("ALLOCATION_ENVELOPE_UNCONFIGURED",),
                evidence_refs=("wedge-economic-value-v1",),
            ),
        )


class AutonomousReadiness(_FrozenModel):
    version: str = READINESS_VERSION
    evaluated_at: dt.datetime
    h_a_runtime: GateEvidence
    h_b_state: GateEvidence
    h_c_policy: GateEvidence
    h_d_shadow: GateEvidence
    h_e_capped: GateEvidence
    h_f_closed_loop: GateEvidence
    h_g_scale: GateEvidence
    highest_safe_mode: AutonomyMode
    blockers: tuple[SafeCode, ...]
    evidence_refs: tuple[SafeRef, ...]
    _evaluated = field_validator("evaluated_at")(_aware)
