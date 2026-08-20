"""Strict contracts for SPEC-023 deterministic acquisition decisions."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from signals.acquisition.contracts import Decision
from signals.company_research.contracts import CompanySizeBand, ResearchCompleteness
from signals.policy.contracts import (
    MAX_APPROVAL_GRANTS,
    ApprovalGrant,
    ComplianceAssessment,
    Currency,
    EvidenceReadiness,
    OperationalReadiness,
    PolicyDecision,
    PolicyStatus,
    Scope,
)
from signals.supplier_discovery.contracts import SupplierIdentityStatus

INPUT_VERSION = "acquisition-decision-input-v1"
RECENCY_VERSION = "acquisition-recency-v1"
POLICY_VERSION = "decision-policy-v1"
REASON_CODE_VERSION = "decision-reasons-v1"
MAX_DECISION_REASONS = 8
MAX_DECISION_EVIDENCE = 16

StableRef = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
ShortCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class DecisionEngineContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RecencyBasis(StrEnum):
    AWARD_DATE = "AWARD_DATE"
    CONTRACT_NOTIFICATION_DATE = "CONTRACT_NOTIFICATION_DATE"
    PUBLICATION_DATE = "PUBLICATION_DATE"
    UNRESOLVED = "UNRESOLVED"


class DecisionAuditDisposition(StrEnum):
    POLICY_BLOCKED = "POLICY_BLOCKED"
    RECORDED = "RECORDED"


class DecisionPolicyConfig(DecisionEngineContract):
    policy_version: Literal["decision-policy-v1"] = POLICY_VERSION
    recency_version: Literal["acquisition-recency-v1"] = RECENCY_VERSION
    max_send_age_days: int = Field(ge=1, le=3650)
    future_date_tolerance_days: int = Field(ge=0, le=30)
    award_publication_tolerance_days: int = Field(ge=0, le=30)
    domain_conflict_behavior: Literal["REVIEW"] = "REVIEW"
    supplier_snapshot_mismatch_behavior: Literal["REVIEW"] = "REVIEW"
    limited_research_behavior: Literal["CONTINUE"] = "CONTINUE"
    size_band_behavior: Literal["CONTEXT_ONLY"] = "CONTEXT_ONLY"
    contact_role_tier_behavior: Literal["CONTEXT_ONLY"] = "CONTEXT_ONLY"
    hold_enabled: Literal[False] = False
    enrich_enabled: Literal[False] = False
    reason_code_version: Literal["decision-reasons-v1"] = REASON_CODE_VERSION
    config_fingerprint: Fingerprint


class PublicDecisionContext(DecisionEngineContract):
    opportunity_key: StableRef
    representative_award_key: StableRef
    source_event_key: StableRef
    award_date: dt.date | None = None
    contract_notification_date: dt.date | None = None
    publication_date: dt.date | None = None
    public_evidence_refs: tuple[StableRef, ...] = Field(
        min_length=1, max_length=MAX_DECISION_EVIDENCE
    )
    public_context_fingerprint: Fingerprint

    @field_validator("public_evidence_refs")
    @classmethod
    def evidence_is_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("public evidence refs must be unique")
        return value


class AcquisitionDecisionInput(DecisionEngineContract):
    input_version: Literal["acquisition-decision-input-v1"] = INPUT_VERSION
    acquisition_opportunity_id: StableRef
    signal_ref: StableRef
    supplier_ref: StableRef
    contact_ref: StableRef
    company_prebuild_version: StableRef
    company_prebuild_fingerprint: Fingerprint
    size_band_version: StableRef
    profile_supplier_identity_status: SupplierIdentityStatus
    current_supplier_identity_status: SupplierIdentityStatus
    profile_contact_role_profile_version: StableRef
    profile_contact_role_tier: int = Field(ge=1, le=4)
    current_contact_role_profile_version: StableRef
    current_contact_role_tier: int = Field(ge=1, le=4)
    current_contact_verification_state: Literal["PROVIDER_VERIFIED"]
    current_contact_verification_provider: Literal["apollo"]
    current_contact_provider_email_status: Literal["verified"]
    representative_award_key: StableRef
    source_event_key: StableRef
    public_evidence_refs: tuple[StableRef, ...] = Field(
        min_length=1, max_length=MAX_DECISION_EVIDENCE
    )
    public_context_fingerprint: Fingerprint
    award_date: dt.date | None = None
    contract_notification_date: dt.date | None = None
    publication_date: dt.date | None = None
    recency_basis: RecencyBasis
    recency_date: dt.date | None = None
    as_of_date: dt.date
    age_days: int | None = None
    public_timing_inconsistent: bool
    research_completeness: ResearchCompleteness
    research_gaps: tuple[ShortCode, ...] = Field(default=(), max_length=32)
    size_band: CompanySizeBand
    decision_policy_version: Literal["decision-policy-v1"] = POLICY_VERSION
    decision_policy_config_fingerprint: Fingerprint
    decision_input_fingerprint: Fingerprint

    @field_validator("research_gaps")
    @classmethod
    def gaps_are_sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        expected = tuple(sorted(set(value)))
        if value != expected:
            raise ValueError("research gaps must be sorted and unique")
        return value

    @model_validator(mode="after")
    def recency_is_internally_consistent(self) -> AcquisitionDecisionInput:
        if self.recency_basis is RecencyBasis.UNRESOLVED:
            if self.recency_date is not None or self.age_days is not None:
                raise ValueError("unresolved recency cannot have a date or age")
            return self
        if self.recency_date is None or self.age_days is None:
            raise ValueError("resolved recency requires both a date and an age")
        if self.age_days != (self.as_of_date - self.recency_date).days:
            raise ValueError("age_days must match as_of_date minus recency_date")
        return self


class AcquisitionDecisionProposal(DecisionEngineContract):
    proposed_decision: Decision
    reason_codes: tuple[ShortCode, ...] = Field(
        min_length=1, max_length=MAX_DECISION_REASONS
    )
    evidence_refs: tuple[StableRef, ...] = Field(
        min_length=1, max_length=MAX_DECISION_EVIDENCE
    )
    next_action: StableRef | None = None
    next_review_at: dt.datetime | None = None
    decision_input_fingerprint: Fingerprint
    decision_policy_version: Literal["decision-policy-v1"] = POLICY_VERSION
    proposal_fingerprint: Fingerprint
    confidence: None = None

    @field_validator("proposed_decision")
    @classmethod
    def v1_decision_set(cls, value: Decision) -> Decision:
        if value not in {Decision.SEND, Decision.REVIEW, Decision.NO_SEND}:
            raise ValueError("decision-policy-v1 emits only SEND, REVIEW, or NO_SEND")
        return value

    @field_validator("reason_codes", "evidence_refs")
    @classmethod
    def audit_refs_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("decision audit values must be unique")
        return value

    @field_validator("next_review_at")
    @classmethod
    def v1_has_no_review_clock(cls, value: dt.datetime | None) -> None:
        if value is not None:
            raise ValueError("decision-policy-v1 does not emit HOLD")
        return value

    @model_validator(mode="after")
    def next_action_matches_decision(self) -> AcquisitionDecisionProposal:
        expected = {
            Decision.SEND: "prepare_campaign",
            Decision.REVIEW: "request_human_review",
            Decision.NO_SEND: None,
        }
        if self.next_action != expected[self.proposed_decision]:
            raise ValueError("next_action does not match decision-policy-v1 output")
        return self


class DecisionAuthorizationInput(DecisionEngineContract):
    """Caller identity/readiness only; commercial time and decision stay Kivou-owned."""

    evaluation_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    request_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ]
    actor_type: Annotated[str, StringConstraints(pattern=r"^(SYSTEM|HERMES|HUMAN)$")]
    actor_ref: StableRef | None = None
    scope: Scope
    currency: Currency
    evidence: EvidenceReadiness
    compliance: ComplianceAssessment
    operational: OperationalReadiness
    expected_policy_version: ShortCode
    approval_grants: tuple[ApprovalGrant, ...] = Field(default=(), max_length=MAX_APPROVAL_GRANTS)
    supervisor_plan_id: str | None = None
    supervisor_action_index: int | None = Field(default=None, ge=0)
    supervisor_version: str | None = None
    skill_version: str | None = None


class DecisionEvaluationWrite(DecisionEngineContract):
    decision_evaluation_id: StableRef
    acquisition_opportunity_id: StableRef
    policy_evaluation_id: StableRef
    decision_input: AcquisitionDecisionInput
    proposal: AcquisitionDecisionProposal
    policy_status: PolicyStatus
    policy_counterfactual_status: PolicyStatus | None = None
    expected_post_policy_version: int = Field(ge=2)
    disposition: DecisionAuditDisposition
    recorded_event_id: StableRef | None = None
    created_at: dt.datetime

    @field_validator("created_at")
    @classmethod
    def created_is_aware(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @field_validator("recorded_event_id")
    @classmethod
    def event_matches_disposition(cls, value: str | None, info):
        disposition = info.data.get("disposition")
        if disposition is DecisionAuditDisposition.RECORDED and value is None:
            raise ValueError("RECORDED audit requires recorded_event_id")
        if disposition is DecisionAuditDisposition.POLICY_BLOCKED and value is not None:
            raise ValueError("POLICY_BLOCKED audit cannot reference an event")
        return value


class DecisionEvaluationRecord(DecisionEngineContract):
    decision_evaluation_id: StableRef
    acquisition_opportunity_id: StableRef
    policy_evaluation_id: StableRef
    decision_input_version: StableRef
    decision_input_fingerprint: Fingerprint
    decision_input: dict[str, object]
    company_prebuild_fingerprint: Fingerprint
    representative_award_key: StableRef
    recency_basis: RecencyBasis
    recency_date: dt.date | None = None
    as_of_date: dt.date
    age_days: int | None = None
    decision_policy_version: StableRef
    decision_policy_config_fingerprint: Fingerprint
    proposed_decision: Decision
    reason_codes: tuple[ShortCode, ...] = Field(min_length=1, max_length=MAX_DECISION_REASONS)
    evidence_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=MAX_DECISION_EVIDENCE)
    proposed_next_action: StableRef | None = None
    proposed_next_review_at: dt.datetime | None = None
    proposal_fingerprint: Fingerprint
    policy_status: PolicyStatus
    policy_counterfactual_status: PolicyStatus | None = None
    expected_post_policy_version: int = Field(ge=2)
    disposition: DecisionAuditDisposition
    recorded_event_id: StableRef | None = None
    created_at: dt.datetime

    @field_validator("created_at", "proposed_next_review_at")
    @classmethod
    def record_times_are_aware(cls, value: dt.datetime | None) -> dt.datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("datetime must be timezone-aware")
        return value


class DecisionServiceResult(DecisionEngineContract):
    decision: PolicyDecision | None = None
    audit: DecisionEvaluationRecord
    proposal: AcquisitionDecisionProposal


class DecisionEngineError(RuntimeError):
    """Base class for typed decision-engine orchestration failures."""


class DecisionNotActionable(DecisionEngineError):
    pass


class DecisionCompanyProfileMissing(DecisionEngineError):
    pass


class DecisionInputVersionUnsupported(DecisionEngineError):
    pass


class DecisionBindingConflict(DecisionEngineError):
    pass


class DecisionPublicContextNotResolvable(DecisionEngineError):
    pass


class DecisionEvaluationRequiresFreshAttempt(DecisionEngineError):
    pass


class DecisionEvaluationIdempotencyConflict(DecisionEngineError):
    pass


class DecisionInputChanged(DecisionEngineError):
    pass
