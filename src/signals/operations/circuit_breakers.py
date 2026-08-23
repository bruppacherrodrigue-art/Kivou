"""Acquisition-specific circuit breaker decisions and execution guard."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from signals.operations.contracts import (
    BreakerScope,
    IncidentSeverity,
    IncidentTrigger,
    IncidentType,
    SafeCode,
    SafeRef,
)
from signals.operations.store import OperationsStore, SaveResult

BOUNCE_BREAKER_VERSION = "step1-bounce-breaker-v1"
BOUNCE_MINIMUM_SAMPLE = 20
BOUNCE_MAXIMUM_RATE = Decimal("0.05")
PROVIDER_FAILURE_BREAKER_VERSION = "provider-failure-breaker-v1"
PROVIDER_FAILURE_THRESHOLD = 3


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observation time must be timezone-aware")
    return value.astimezone(dt.UTC)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class BounceObservation(_FrozenModel):
    scope: BreakerScope
    authoritative_step1_members: tuple[SafeRef, ...] = Field(max_length=100_000)
    bounced_step1_members: tuple[SafeRef, ...] = Field(max_length=100_000)
    source_state_ref: SafeRef
    observed_at: dt.datetime
    campaign_ref: SafeRef | None = None
    mailbox_ref: SafeRef | None = None
    wedge: SafeRef | None = None
    country: str | None = Field(default=None, pattern=r"^(CH|FR)$")
    _observed = field_validator("observed_at")(_aware)

    @model_validator(mode="after")
    def authoritative_sets(self) -> BounceObservation:
        sent = set(self.authoritative_step1_members)
        bounced = set(self.bounced_step1_members)
        if len(sent) != len(self.authoritative_step1_members):
            raise ValueError("Step-1 sent members must be unique")
        if len(bounced) != len(self.bounced_step1_members):
            raise ValueError("Step-1 bounced members must be unique")
        if not bounced.issubset(sent):
            raise ValueError("bounce member must belong to authoritative Step-1 sample")
        return self


class ProviderFailureObservation(_FrozenModel):
    scope: BreakerScope
    failure_refs: tuple[SafeRef, ...] = Field(max_length=100)
    failure_codes: tuple[SafeCode, ...] = Field(max_length=100)
    source_state_ref: SafeRef
    observed_at: dt.datetime
    campaign_ref: SafeRef | None = None
    mailbox_ref: SafeRef | None = None
    _observed = field_validator("observed_at")(_aware)

    @model_validator(mode="after")
    def aligned(self) -> ProviderFailureObservation:
        if len(self.failure_refs) != len(self.failure_codes):
            raise ValueError("provider failure refs and codes must align")
        if len(set(self.failure_refs)) != len(self.failure_refs):
            raise ValueError("provider failure refs must be unique")
        return self


class LearningDegradationThresholds(_FrozenModel):
    version: SafeRef = "UNCONFIGURED"
    minimum_sample: int = Field(default=1, ge=1, le=1_000_000)
    minimum_conversion_rate: Decimal | None = Field(default=None, ge=0, le=1)
    minimum_retention_rate: Decimal | None = Field(default=None, ge=0, le=1)

    @property
    def configured(self) -> bool:
        return self.minimum_conversion_rate is not None or self.minimum_retention_rate is not None


class DegradationObservation(_FrozenModel):
    incident_type: IncidentType
    scope: BreakerScope
    authoritative_sample_count: int = Field(ge=0)
    observed_rate: Decimal = Field(ge=0, le=1)
    source_state_ref: SafeRef
    observed_at: dt.datetime
    _observed = field_validator("observed_at")(_aware)

    @model_validator(mode="after")
    def degradation_type(self) -> DegradationObservation:
        if self.incident_type not in {
            IncidentType.CONVERSION_DEGRADATION,
            IncidentType.RETENTION_DEGRADATION,
        }:
            raise ValueError("degradation observation requires conversion or retention type")
        return self


class AcquisitionCircuitOpen(RuntimeError):
    pass


class AcquisitionExecutionGuard:
    """Fail closed when an unresolved HIGH/CRITICAL incident blocks a scope."""

    def __init__(self, store: OperationsStore) -> None:
        self._store = store

    def require_allowed(self, *scopes: BreakerScope) -> None:
        if not scopes:
            raise ValueError("at least one execution scope is required")
        for scope in scopes:
            if self._store.has_open_breaker(scope):
                raise AcquisitionCircuitOpen("acquisition execution circuit is open")


class CircuitBreakerService:
    def __init__(self, store: OperationsStore) -> None:
        self._store = store

    def observe_bounces(self, observation: BounceObservation) -> SaveResult | None:
        sent_count = len(observation.authoritative_step1_members)
        if sent_count < BOUNCE_MINIMUM_SAMPLE:
            return None
        rate = Decimal(len(observation.bounced_step1_members)) / Decimal(sent_count)
        if rate <= BOUNCE_MAXIMUM_RATE:
            return None
        return self._store.open_incident(
            IncidentTrigger(
                incident_type=IncidentType.BOUNCE_RATE,
                severity=IncidentSeverity.HIGH,
                scope=observation.scope,
                source_state_ref=observation.source_state_ref,
                triggered_at=observation.observed_at,
                observed_value=rate,
                threshold_value=BOUNCE_MAXIMUM_RATE,
                metric_version=BOUNCE_BREAKER_VERSION,
                campaign_ref=observation.campaign_ref,
                mailbox_ref=observation.mailbox_ref,
                wedge=observation.wedge,
                country=observation.country,
                reason_codes=("STEP1_BOUNCE_RATE_ABOVE_LIMIT",),
                human_review_required=True,
                pause_required=True,
            )
        )

    def observe_complaint(
        self,
        *,
        campaign_ref: str,
        response_evaluation_ref: str,
        observed_at: dt.datetime,
    ) -> SaveResult:
        return self._store.open_incident(
            IncidentTrigger(
                incident_type=IncidentType.COMPLAINT,
                severity=IncidentSeverity.HIGH,
                scope=BreakerScope(scope_type="CAMPAIGN", scope_ref=campaign_ref),
                source_state_ref=response_evaluation_ref,
                triggered_at=observed_at,
                reason_codes=("AUTHORITATIVE_COMPLAINT",),
                human_review_required=True,
                pause_required=True,
            )
        )

    def observe_provider_failures(
        self, observation: ProviderFailureObservation
    ) -> SaveResult | None:
        ignored = {"RATE_LIMITED", "SEND_WINDOW_CLOSED", "NORMAL_WAITING"}
        qualifying = tuple(
            ref
            for ref, code in zip(
                observation.failure_refs, observation.failure_codes, strict=True
            )
            if code not in ignored
        )
        if len(qualifying) < PROVIDER_FAILURE_THRESHOLD:
            return None
        return self._store.open_incident(
            IncidentTrigger(
                incident_type=IncidentType.PROVIDER_FAILURE,
                severity=IncidentSeverity.HIGH,
                scope=observation.scope,
                source_state_ref=observation.source_state_ref,
                triggered_at=observation.observed_at,
                observed_value=Decimal(len(qualifying)),
                threshold_value=Decimal(PROVIDER_FAILURE_THRESHOLD),
                metric_version=PROVIDER_FAILURE_BREAKER_VERSION,
                campaign_ref=observation.campaign_ref,
                mailbox_ref=observation.mailbox_ref,
                reason_codes=("CONSECUTIVE_PROVIDER_FAILURES", "RECONCILE_BEFORE_RETRY"),
                human_review_required=True,
                pause_required=True,
            )
        )

    def observe_degradation(
        self,
        observation: DegradationObservation,
        *,
        thresholds: LearningDegradationThresholds,
    ) -> SaveResult | None:
        threshold = (
            thresholds.minimum_conversion_rate
            if observation.incident_type is IncidentType.CONVERSION_DEGRADATION
            else thresholds.minimum_retention_rate
        )
        if (
            not thresholds.configured
            or threshold is None
            or observation.authoritative_sample_count < thresholds.minimum_sample
            or observation.observed_rate >= threshold
        ):
            return None
        return self._store.open_incident(
            IncidentTrigger(
                incident_type=observation.incident_type,
                severity=IncidentSeverity.HIGH,
                scope=observation.scope,
                source_state_ref=observation.source_state_ref,
                triggered_at=observation.observed_at,
                observed_value=observation.observed_rate,
                threshold_value=threshold,
                metric_version=thresholds.version,
                reason_codes=(f"{observation.incident_type.value}_BELOW_OPERATOR_THRESHOLD",),
                human_review_required=True,
                pause_required=True,
            )
        )

    def observe_critical_transport(
        self,
        *,
        campaign_ref: str,
        provider_event_ref: str,
        incident_code: str,
        observed_at: dt.datetime,
    ) -> SaveResult:
        allowed_codes = {
            "UNEXPECTED_EMAIL_SENT_AFTER_STOP",
            "CONFLICTING_STEP1_TRANSPORT_TRUTH",
            "DUPLICATE_BUSINESS_SEND",
            "TRANSPORT_STATE_CONFLICT",
        }
        if incident_code not in allowed_codes:
            raise ValueError("transport incident is not critical")
        return self._store.open_incident(
            IncidentTrigger(
                incident_type=IncidentType.UNEXPECTED_TRANSPORT_TRUTH,
                severity=IncidentSeverity.CRITICAL,
                scope=BreakerScope(scope_type="CAMPAIGN", scope_ref=campaign_ref),
                source_state_ref=provider_event_ref,
                triggered_at=observed_at,
                reason_codes=(incident_code, "AUTHORITATIVE_SENT_TRUTH_PRESERVED"),
                human_review_required=True,
                pause_required=True,
            )
        )
