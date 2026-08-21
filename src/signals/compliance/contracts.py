"""Immutable, PII-minimized contracts for SPEC-025 compliance."""

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

from signals.decision_engine.policy import semantic_fingerprint
from signals.policy.contracts import (
    MAX_APPROVAL_GRANTS,
    ApprovalGrant,
    ComplianceState,
    Currency,
    EvidenceReadiness,
    OperationalReadiness,
    Scope,
)

INPUT_VERSION = "acquisition-compliance-input-v1"
RULESET_VERSION = "acquisition-compliance-ruleset-v1"
JURISDICTION_VERSION = "compliance-jurisdiction-v1"
SENDER_CONFIG_VERSION = "sender-compliance-v1"

StableRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
ShortCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ComplianceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("datetime must be timezone-aware")
    return value


class ComplianceJurisdiction(StrEnum):
    CH = "CH"
    FR = "FR"
    EU_MEMBER_STATE_UNCONFIGURED = "EU_MEMBER_STATE_UNCONFIGURED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    UNRESOLVED = "UNRESOLVED"


class SuppressionMatchState(StrEnum):
    CLEAR = "CLEAR"
    MATCHED = "MATCHED"
    COVERAGE_UNSAFE = "COVERAGE_UNSAFE"


class BusinessContextState(StrEnum):
    PROFESSIONAL_CONTEXT_VERIFIED = "PROFESSIONAL_CONTEXT_VERIFIED"
    BUSINESS_CONTEXT_INSUFFICIENT = "BUSINESS_CONTEXT_INSUFFICIENT"


class EmailProvenance(StrEnum):
    PROVIDER_VERIFIED_BUSINESS_CONTACT = "PROVIDER_VERIFIED_BUSINESS_CONTACT"
    UNKNOWN = "UNKNOWN"


class CHLegalBasis(StrEnum):
    CONSENT_PROVEN = "CONSENT_PROVEN"
    EXISTING_CUSTOMER_SIMILAR_PROVEN = "EXISTING_CUSTOMER_SIMILAR_PROVEN"
    UNPROVEN = "UNPROVEN"


class ComplianceDisposition(StrEnum):
    RECORDED = "RECORDED"
    POLICY_BLOCKED = "POLICY_BLOCKED"


class SuppressionSource(StrEnum):
    UNSUBSCRIBE = "UNSUBSCRIBE"
    RECIPIENT_OBJECTION = "RECIPIENT_OBJECTION"
    MANUAL_VERIFIED = "MANUAL_VERIFIED"
    SYSTEM_IMPORT = "SYSTEM_IMPORT"


class SuppressionReasonCode(StrEnum):
    UNSUBSCRIBED = "UNSUBSCRIBED"
    RECIPIENT_OBJECTED = "RECIPIENT_OBJECTED"
    MANUAL_DO_NOT_CONTACT = "MANUAL_DO_NOT_CONTACT"
    IMPORTED_SUPPRESSION = "IMPORTED_SUPPRESSION"
    IDENTITY_REKEY_PROOF = "IDENTITY_REKEY_PROOF"


class SuppressionMatch(ComplianceContract):
    state: SuppressionMatchState
    key_versions_considered: tuple[ShortCode, ...] = Field(min_length=1, max_length=8)
    suppression_refs: tuple[StableRef, ...] = Field(default=(), max_length=16)


class JurisdictionResolution(ComplianceContract):
    jurisdiction: ComplianceJurisdiction
    country_code: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")] | None = None
    resolvable: bool
    evidence_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=8)
    resolver_version: Literal["compliance-jurisdiction-v1"] = JURISDICTION_VERSION


class SenderComplianceConfig(ComplianceContract):
    config_version: ShortCode = SENDER_CONFIG_VERSION
    sender_profile_ref: StableRef
    sender_identity_ready: bool
    opt_out_ready: bool
    privacy_notice_ready: bool
    source_notice_ready: bool
    valid_until: dt.datetime | None = None
    config_fingerprint: Fingerprint | None = None

    _valid = field_validator("valid_until")(_aware)

    @model_validator(mode="after")
    def derive_fingerprint(self) -> SenderComplianceConfig:
        values = self.model_dump(mode="json", exclude={"config_fingerprint"})
        expected = semantic_fingerprint({"kind": "sender-compliance-config-v1", **values})
        if self.config_fingerprint not in (None, expected):
            raise ValueError("sender config fingerprint mismatch")
        object.__setattr__(self, "config_fingerprint", expected)
        return self


class ComplianceRulesetConfig(ComplianceContract):
    ruleset_version: Literal["acquisition-compliance-ruleset-v1"] = RULESET_VERSION
    allowed_ttl_hours: Literal[24] = 24
    configured_country_rulesets: tuple[Literal["CH", "FR"], ...] = ("CH", "FR")
    reason_code_version: Literal["compliance-reasons-v1"] = "compliance-reasons-v1"
    config_fingerprint: Fingerprint | None = None

    @model_validator(mode="after")
    def derive_fingerprint(self) -> ComplianceRulesetConfig:
        values = self.model_dump(mode="json", exclude={"config_fingerprint"})
        expected = semantic_fingerprint({"kind": "compliance-ruleset-config-v1", **values})
        if self.config_fingerprint not in (None, expected):
            raise ValueError("ruleset config fingerprint mismatch")
        object.__setattr__(self, "config_fingerprint", expected)
        return self


class ComplianceInput(ComplianceContract):
    acquisition_opportunity_id: StableRef
    supplier_ref: StableRef
    contact_ref: StableRef
    personalization_artifact_id: StableRef
    personalization_artifact_fingerprint: Fingerprint
    personalization_input_fingerprint: Fingerprint
    personalization_proposal_fingerprint: Fingerprint
    personalization_policy_action_fingerprint: Fingerprint
    language: Literal["fr", "en"]
    supplier_identity_status: Literal["PROVIDER_IDENTIFIED", "DOMAIN_CONFLICT"]
    contact_verification_state: Literal["PROVIDER_VERIFIED"]
    contact_verification_provider: Literal["apollo"]
    contact_provider_email_status: Literal["verified"]
    contact_source_fingerprint: Fingerprint
    contact_role_profile_version: ShortCode
    contact_role_tier: int = Field(ge=1, le=4)
    jurisdiction: JurisdictionResolution
    business_context_state: BusinessContextState
    email_provenance: EmailProvenance
    sender_config: SenderComplianceConfig
    acquisition_purpose: Literal["KIVOU_ACQUISITION_SIGNAL_RELEVANCE"]
    ch_legal_basis: CHLegalBasis
    suppression_match_state: SuppressionMatchState
    suppression_key_versions_considered: tuple[ShortCode, ...] = Field(min_length=1, max_length=8)
    evidence_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=16)
    ruleset_version: Literal["acquisition-compliance-ruleset-v1"] = RULESET_VERSION
    ruleset_config_fingerprint: Fingerprint
    assessed_at: dt.datetime
    as_of_date: dt.date
    input_version: Literal["acquisition-compliance-input-v1"] = INPUT_VERSION
    compliance_input_fingerprint: Fingerprint

    _assessed = field_validator("assessed_at")(_aware)


class ComplianceProposal(ComplianceContract):
    state: ComplianceState
    reason_codes: tuple[ShortCode, ...] = Field(min_length=1, max_length=8)
    evidence_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=16)
    next_action: Literal["schedule_campaign", "request_human_review"] | None
    valid_until: dt.datetime | None = None
    input_fingerprint: Fingerprint
    ruleset_version: Literal["acquisition-compliance-ruleset-v1"] = RULESET_VERSION
    ruleset_config_fingerprint: Fingerprint
    proposal_fingerprint: Fingerprint

    _valid = field_validator("valid_until")(_aware)


class ComplianceAuthorizationInput(ComplianceContract):
    """Caller authorization context; compliance itself is always Kivou-owned."""

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
    operational: OperationalReadiness
    expected_policy_version: ShortCode
    approval_grants: tuple[ApprovalGrant, ...] = Field(default=(), max_length=MAX_APPROVAL_GRANTS)
    supervisor_plan_id: str | None = None
    supervisor_action_index: int | None = Field(default=None, ge=0)
    supervisor_version: str | None = None
    skill_version: str | None = None


class ComplianceAssessmentWrite(ComplianceContract):
    compliance_assessment_id: StableRef
    acquisition_opportunity_id: StableRef
    personalization_artifact_id: StableRef
    supplier_ref: StableRef
    contact_ref: StableRef
    policy_evaluation_id: StableRef
    jurisdiction: ComplianceJurisdiction
    jurisdiction_resolver_version: Literal["compliance-jurisdiction-v1"] = JURISDICTION_VERSION
    ruleset_version: Literal["acquisition-compliance-ruleset-v1"] = RULESET_VERSION
    ruleset_config_fingerprint: Fingerprint
    input_version: Literal["acquisition-compliance-input-v1"] = INPUT_VERSION
    input_fingerprint: Fingerprint
    proposal_fingerprint: Fingerprint
    policy_action_fingerprint: Fingerprint
    state: ComplianceState
    reason_codes: tuple[ShortCode, ...] = Field(min_length=1, max_length=8)
    evidence_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=16)
    input_snapshot: dict[str, object]
    valid_until: dt.datetime | None = None
    policy_status: ShortCode
    policy_counterfactual_status: ShortCode | None = None
    expected_post_policy_version: int = Field(ge=2)
    disposition: ComplianceDisposition
    next_action: Literal["schedule_campaign", "request_human_review"] | None
    recorded_event_id: StableRef | None = None
    created_at: dt.datetime

    _times = field_validator("valid_until", "created_at")(_aware)

    @model_validator(mode="after")
    def coherent_result(self) -> ComplianceAssessmentWrite:
        expected_action = {
            ComplianceState.ALLOWED: "schedule_campaign",
            ComplianceState.REVIEW_REQUIRED: "request_human_review",
            ComplianceState.BLOCKED: None,
        }
        if self.state in expected_action and self.next_action != expected_action[self.state]:
            raise ValueError("assessment state/next_action mismatch")
        if self.state is ComplianceState.ALLOWED and self.valid_until is None:
            raise ValueError("ALLOWED assessment requires valid_until")
        if self.state is not ComplianceState.ALLOWED and self.valid_until is not None:
            raise ValueError("non-ALLOWED assessment cannot carry authorization validity")
        if self.disposition is ComplianceDisposition.RECORDED:
            if self.recorded_event_id is None:
                raise ValueError("RECORDED assessment requires workflow event")
        elif self.recorded_event_id is not None:
            raise ValueError("POLICY_BLOCKED assessment cannot bind workflow event")
        return self
