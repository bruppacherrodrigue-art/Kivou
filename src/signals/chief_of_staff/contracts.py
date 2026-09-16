"""Strict immutable contracts for the read-only Chief of Staff boundary."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

CONTEXT_VERSION = "chief-of-staff-context-v2"
REPORT_VERSION = "chief-of-staff-report-v1"
BUSINESS_MEMORY_VERSION = "business-memory-v1"
PROFILE_VERSION = "1.1.0"
CHIEF_OF_STAFF_TIMEZONE = "Europe/Zurich"

ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
StableRef = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
ReasonCode = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z][A-Z0-9_]{1,99}$")
]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Cadence = Literal["DAILY", "WEEKLY", "ON_DEMAND"]
Domain = Literal[
    "BUSINESS",
    "PRODUCT",
    "DATA",
    "OPERATIONS",
    "ACQUISITION",
    "ROADMAP_RELEASE",
    "STRATEGY",
]
DataStatus = Literal["KNOWN", "UNKNOWN", "INSUFFICIENT_EVIDENCE", "STALE"]
Owner = Literal["FOUNDER", "ENGINEERING", "ACQUISITION", "PRODUCT", "DATA", "NONE"]
Capability = Literal[
    "BUSINESS_REVIEW",
    "PRODUCT_JOURNEY_REVIEW",
    "DATA_HEALTH_REVIEW",
    "OPERATIONS_REVIEW",
    "ACQUISITION_REVIEW",
    "ROADMAP_RELEASE_REVIEW",
    "STRATEGIC_SYNTHESIS",
]
CapabilityStatus = Literal["AVAILABLE", "UNAVAILABLE", "INSUFFICIENT_EVIDENCE"]
CAPABILITY_ORDER: tuple[Capability, ...] = (
    "BUSINESS_REVIEW",
    "PRODUCT_JOURNEY_REVIEW",
    "DATA_HEALTH_REVIEW",
    "OPERATIONS_REVIEW",
    "ACQUISITION_REVIEW",
    "ROADMAP_RELEASE_REVIEW",
    "STRATEGIC_SYNTHESIS",
)
FactValue = int | Decimal | str | bool | None


class ChiefOfStaffModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class BusinessDecision(ChiefOfStaffModel):
    decision_key: StableRef
    category: Literal[
        "POSITIONING",
        "PRODUCT",
        "PRICING",
        "ACQUISITION",
        "SECURITY",
        "AUTONOMY",
        "QUALITY",
        "BUSINESS_OBJECTIVES",
        "GOVERNANCE",
    ]
    statement: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000)
    ]
    status: Literal["ACTIVE", "SUPERSEDED", "CONTRADICTED"]
    effective_from: dt.date
    version: Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    source_ref: StableRef


class BusinessMemory(ChiefOfStaffModel):
    memory_version: Literal["business-memory-v1"] = BUSINESS_MEMORY_VERSION
    updated_at: dt.date
    decisions: tuple[BusinessDecision, ...] = Field(min_length=1, max_length=100)

    @field_validator("decisions")
    @classmethod
    def unique_decisions(
        cls, value: tuple[BusinessDecision, ...]
    ) -> tuple[BusinessDecision, ...]:
        keys = tuple(item.decision_key for item in value)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("business decisions must have unique sorted keys")
        return value


class ChiefOfStaffFact(ChiefOfStaffModel):
    fact_ref: StableRef
    domain: Domain
    metric_key: StableRef
    value: FactValue
    unit: Literal[
        "COUNT",
        "MINOR_UNITS",
        "BASIS_POINTS",
        "RATIO",
        "BOOLEAN",
        "STATUS",
        "TEXT",
        "TIMESTAMP",
        "VERSION",
    ]
    currency: Literal["CHF", "EUR", "USD"] | None = None
    period_start: dt.datetime
    period_end: dt.datetime
    captured_at: dt.datetime
    source_contract: StableRef
    source_version: StableRef
    data_status: DataStatus

    _times = field_validator("period_start", "period_end", "captured_at")(_aware)

    @model_validator(mode="after")
    def validate_semantics(self) -> ChiefOfStaffFact:
        if self.period_end <= self.period_start:
            raise ValueError("fact period end must follow start")
        if self.data_status in {"UNKNOWN", "INSUFFICIENT_EVIDENCE"} and self.value is not None:
            raise ValueError("unknown facts cannot carry a value")
        if self.data_status in {"KNOWN", "STALE"} and self.value is None:
            raise ValueError("known or stale facts require a value")
        if self.unit == "MINOR_UNITS" and self.data_status in {"KNOWN", "STALE"}:
            if isinstance(self.value, bool) or not isinstance(self.value, int):
                raise ValueError("money facts require integer minor units")
            if self.currency is None:
                raise ValueError("money facts require an explicit currency")
        elif self.unit != "MINOR_UNITS" and self.currency is not None:
            raise ValueError("currency is allowed only for money facts")
        return self


class ActiveGate(ChiefOfStaffModel):
    gate_ref: StableRef
    status: Literal["OPEN", "BLOCKED", "UNKNOWN"]
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1, max_length=20)
    fact_refs: tuple[StableRef, ...] = Field(default=(), max_length=20)


class KnownIncident(ChiefOfStaffModel):
    incident_ref: StableRef
    severity: Literal["WARNING", "HIGH", "CRITICAL", "UNKNOWN"]
    status: StableRef
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1, max_length=20)
    fact_refs: tuple[StableRef, ...] = Field(default=(), max_length=20)


class DataQualitySummary(ChiefOfStaffModel):
    reason_codes: tuple[ReasonCode, ...] = Field(default=(), max_length=50)
    fact_refs: tuple[StableRef, ...] = Field(default=(), max_length=100)


class CapabilityAvailability(ChiefOfStaffModel):
    capability: Capability
    status: CapabilityStatus
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1, max_length=10)
    fact_refs: tuple[StableRef, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_evidence(self) -> CapabilityAvailability:
        if self.status == "AVAILABLE" and not self.fact_refs:
            raise ValueError("available capabilities require fact references")
        if self.status == "UNAVAILABLE" and self.fact_refs:
            raise ValueError("unavailable capabilities cannot claim fact references")
        return self


class ChiefOfStaffContext(ChiefOfStaffModel):
    context_version: Literal["chief-of-staff-context-v2"] = CONTEXT_VERSION
    generated_at: dt.datetime
    timezone: Literal["Europe/Zurich"] = CHIEF_OF_STAFF_TIMEZONE
    runtime_mode: Literal["SHADOW"] = "SHADOW"
    cadence: Cadence
    period_start: dt.datetime
    period_end: dt.datetime
    business_memory_version: Literal["business-memory-v1"]
    business_memory: tuple[BusinessDecision, ...] = Field(min_length=1, max_length=100)
    profile_version: Literal["1.1.0"]
    facts: tuple[ChiefOfStaffFact, ...] = Field(max_length=200)
    active_gates: tuple[ActiveGate, ...] = Field(max_length=50)
    known_incidents: tuple[KnownIncident, ...] = Field(max_length=50)
    data_quality: DataQualitySummary
    capabilities: tuple[CapabilityAvailability, ...] = Field(min_length=7, max_length=7)
    content_boundary: Literal["UNTRUSTED_DATA"] = "UNTRUSTED_DATA"

    _times = field_validator("generated_at", "period_start", "period_end")(_aware)

    @model_validator(mode="after")
    def validate_period_and_facts(self) -> ChiefOfStaffContext:
        if self.period_end <= self.period_start:
            raise ValueError("context period end must follow start")
        refs = tuple(item.fact_ref for item in self.facts)
        if refs != tuple(sorted(set(refs))):
            raise ValueError("facts must have unique sorted references")
        capabilities = tuple(item.capability for item in self.capabilities)
        if capabilities != CAPABILITY_ORDER:
            raise ValueError("capabilities must use the complete canonical order")
        return self


class ChiefOfStaffObservation(ChiefOfStaffModel):
    observation_id: StableRef
    domain: Domain
    kind: Literal["CHANGE", "ANOMALY", "RISK", "STATUS", "UNKNOWN"]
    summary: ShortText
    impact: ShortText
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1, max_length=20)
    fact_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=20)
    confidence: Decimal = Field(ge=0, le=1)


class ChiefOfStaffPriority(ChiefOfStaffModel):
    priority: int = Field(ge=1, le=3)
    owner: Owner
    recommended_action: ShortText
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1, max_length=20)
    fact_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=20)
    approval_required: bool


class ChiefOfStaffDecisionRequest(ChiefOfStaffModel):
    decision_id: StableRef
    owner: Literal["FOUNDER"] = "FOUNDER"
    question: ShortText
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1, max_length=20)
    fact_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=20)
    human_decision_required: Literal[True] = True


class ChiefOfStaffUnknown(ChiefOfStaffModel):
    unknown_id: StableRef
    domain: Domain
    summary: ShortText
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1, max_length=20)
    fact_refs: tuple[StableRef, ...] = Field(default=(), max_length=20)


class ChiefOfStaffReport(ChiefOfStaffModel):
    report_version: Literal["chief-of-staff-report-v1"] = REPORT_VERSION
    report_ref: StableRef
    context_fingerprint: Fingerprint
    cadence: Cadence
    period_start: dt.datetime
    period_end: dt.datetime
    created_at: dt.datetime
    executive_status: Literal["HEALTHY", "WATCH", "CRITICAL", "UNKNOWN"]
    executive_summary: ShortText
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1, max_length=20)
    observations: tuple[ChiefOfStaffObservation, ...] = Field(max_length=20)
    priorities: tuple[ChiefOfStaffPriority, ...] = Field(max_length=3)
    decision_requests: tuple[ChiefOfStaffDecisionRequest, ...] = Field(max_length=5)
    unknowns: tuple[ChiefOfStaffUnknown, ...] = Field(max_length=20)
    source_refs: tuple[StableRef, ...] = Field(max_length=100)
    confidence: Decimal = Field(ge=0, le=1)
    supervisor_version: StableRef
    profile_version: Literal["1.1.0"]

    _times = field_validator("period_start", "period_end", "created_at")(_aware)

    @model_validator(mode="after")
    def validate_shape(self) -> ChiefOfStaffReport:
        if self.period_end <= self.period_start:
            raise ValueError("report period end must follow start")
        ranks = tuple(item.priority for item in self.priorities)
        if ranks != tuple(range(1, len(ranks) + 1)):
            raise ValueError("priorities must be consecutively ranked")
        sources = tuple(self.source_refs)
        if sources != tuple(sorted(set(sources))):
            raise ValueError("source refs must be unique and sorted")
        return self


__all__ = [
    "BUSINESS_MEMORY_VERSION",
    "CAPABILITY_ORDER",
    "CHIEF_OF_STAFF_TIMEZONE",
    "CONTEXT_VERSION",
    "PROFILE_VERSION",
    "REPORT_VERSION",
    "ActiveGate",
    "BusinessDecision",
    "BusinessMemory",
    "CapabilityAvailability",
    "ChiefOfStaffContext",
    "ChiefOfStaffDecisionRequest",
    "ChiefOfStaffFact",
    "ChiefOfStaffObservation",
    "ChiefOfStaffPriority",
    "ChiefOfStaffReport",
    "ChiefOfStaffUnknown",
    "DataQualitySummary",
    "KnownIncident",
]
