"""Strict immutable contracts for SPEC-022 company research."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from signals.policy.contracts import (
    MAX_APPROVAL_GRANTS,
    MAX_EVIDENCE_REFS,
    MAX_REASON_CODES,
    ApprovalGrant,
    ComplianceAssessment,
    Currency,
    EvidenceReadiness,
    OperationalReadiness,
    PolicyDecision,
    Scope,
)
from signals.supplier_discovery.contracts import SupplierIdentityStatus

PROFILE_VERSION = "company-research-v1"
RESPONSE_CONTRACT_VERSION = "apollo-organization-info-v1"
NORMALIZATION_VERSION = "company-normalization-v1"
PREBUILD_VERSION = "acquisition-prospect-prebuild-v1"
SIZE_BAND_VERSION = "company-size-v1"
PROVIDER = "apollo"
ENDPOINT_KIND = "exact_organization_id"
MAX_RESPONSE_BYTES = 1_048_576
MAX_KEYWORDS = 32
MAX_KEYWORD_LENGTH = 128
MAX_DESCRIPTION_LENGTH = 2_000
MAX_RESEARCH_GAPS = 32
MAX_EMPLOYEE_COUNT = 10_000_000

StableRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
ProviderId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
    ),
]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class CompanyResearchContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CompanySizeBand(StrEnum):
    UNKNOWN = "UNKNOWN"
    MICRO = "MICRO"
    SMB = "SMB"
    MID_MARKET = "MID_MARKET"
    ENTERPRISE = "ENTERPRISE"


class ResearchCompleteness(StrEnum):
    COMPLETE = "COMPLETE"
    LIMITED = "LIMITED"


class ProviderResearchStatus(StrEnum):
    CURRENT_PROVIDER_RECORD = "CURRENT_PROVIDER_RECORD"


class CompanyResearchRunStatus(StrEnum):
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    LIMITED = "LIMITED"
    FAILED = "FAILED"


class CompanyResearchObservationConflict(RuntimeError):
    pass


class CompanyResearchRunIdentityConflict(RuntimeError):
    pass


class CompanyResearchRunAlreadyStarted(RuntimeError):
    pass


class CompanyResearchNotActionable(RuntimeError):
    pass


class CompanyResearchEvaluationRequiresFreshAttempt(RuntimeError):
    pass


class ResearchGap(StrEnum):
    MISSING_DOMAIN_OR_WEBSITE = "MISSING_DOMAIN_OR_WEBSITE"
    MISSING_COUNTRY = "MISSING_COUNTRY"
    MISSING_INDUSTRY = "MISSING_INDUSTRY"
    MISSING_EMPLOYEE_COUNT = "MISSING_EMPLOYEE_COUNT"
    INVALID_PRIMARY_DOMAIN = "INVALID_PRIMARY_DOMAIN"
    INVALID_WEBSITE_URL = "INVALID_WEBSITE_URL"
    INVALID_COUNTRY = "INVALID_COUNTRY"
    INVALID_INDUSTRY = "INVALID_INDUSTRY"
    INVALID_EMPLOYEE_COUNT = "INVALID_EMPLOYEE_COUNT"
    INVALID_FOUNDED_YEAR = "INVALID_FOUNDED_YEAR"
    INVALID_DESCRIPTION = "INVALID_DESCRIPTION"
    TRUNCATED_DESCRIPTION = "TRUNCATED_DESCRIPTION"
    INVALID_KEYWORDS = "INVALID_KEYWORDS"
    TRUNCATED_KEYWORDS = "TRUNCATED_KEYWORDS"


class CompanyResearchProviderError(RuntimeError):
    def __init__(
        self,
        category: str,
        *,
        detail: str | None = None,
        retry_after: dt.datetime | None = None,
    ) -> None:
        self.category = category
        self.detail = detail or category
        self.retry_after = retry_after
        super().__init__(f"Apollo company research: {category}")


ALLOWED_PROVIDER_FIELDS = (
    "id",
    "name",
    "primary_domain",
    "website_url",
    "country",
    "industry",
    "estimated_num_employees",
    "founded_year",
    "short_description",
    "keywords",
)


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class CompanyResearchProfile(CompanyResearchContract):
    profile_version: ShortText = PROFILE_VERSION
    provider: Literal["apollo"] = PROVIDER
    provider_organization_id: ProviderId
    endpoint_kind: Literal["exact_organization_id"] = ENDPOINT_KIND
    response_contract_version: ShortText = RESPONSE_CONTRACT_VERSION
    allowed_provider_fields: tuple[ShortText, ...] = ALLOWED_PROVIDER_FIELDS
    max_response_bytes: int = Field(default=MAX_RESPONSE_BYTES, ge=1, le=MAX_RESPONSE_BYTES)
    max_keywords: int = Field(default=MAX_KEYWORDS, ge=1, le=MAX_KEYWORDS)
    max_keyword_length: int = Field(default=MAX_KEYWORD_LENGTH, ge=1, le=MAX_KEYWORD_LENGTH)
    max_description_length: int = Field(
        default=MAX_DESCRIPTION_LENGTH, ge=1, le=MAX_DESCRIPTION_LENGTH
    )
    normalization_version: ShortText = NORMALIZATION_VERSION
    profile_fingerprint: Fingerprint


class ApolloOrganizationObservation(CompanyResearchContract):
    provider: Literal["apollo"] = PROVIDER
    provider_organization_id: ProviderId
    provider_company_name: ShortText
    provider_primary_domain: Annotated[str, StringConstraints(max_length=253)] | None = None
    provider_website_url: Annotated[str, StringConstraints(max_length=2048)] | None = None
    provider_country: Annotated[str, StringConstraints(max_length=128)] | None = None
    provider_industry: Annotated[str, StringConstraints(max_length=256)] | None = None
    provider_employee_count: int | None = Field(default=None, ge=0, le=MAX_EMPLOYEE_COUNT)
    provider_founded_year: int | None = Field(default=None, ge=1000, le=9999)
    provider_short_description: (
        Annotated[str, StringConstraints(max_length=MAX_DESCRIPTION_LENGTH)] | None
    ) = None
    provider_keywords: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=MAX_KEYWORD_LENGTH)], ...
    ] = Field(default=(), max_length=MAX_KEYWORDS)
    provider_observed_at: dt.datetime
    provider_source_fingerprint: Fingerprint
    research_gaps: tuple[ResearchGap, ...] = Field(default=(), max_length=MAX_RESEARCH_GAPS)

    _observed = field_validator("provider_observed_at")(_aware)

    @field_validator("research_gaps")
    @classmethod
    def sorted_unique_gaps(cls, value: tuple[ResearchGap, ...]) -> tuple[ResearchGap, ...]:
        return tuple(sorted(set(value), key=lambda item: item.value))


class AcquisitionProspectPrebuild(CompanyResearchContract):
    acquisition_opportunity_id: StableRef
    signal_ref: StableRef
    supplier_ref: StableRef
    contact_ref: StableRef
    supplier_identity_status: SupplierIdentityStatus
    provider: Literal["apollo"] = PROVIDER
    provider_organization_id: ProviderId
    provider_company_name: ShortText
    provider_primary_domain: Annotated[str, StringConstraints(max_length=253)] | None = None
    provider_website_url: Annotated[str, StringConstraints(max_length=2048)] | None = None
    provider_country: Annotated[str, StringConstraints(max_length=128)] | None = None
    provider_industry: Annotated[str, StringConstraints(max_length=256)] | None = None
    provider_employee_count: int | None = Field(default=None, ge=0, le=MAX_EMPLOYEE_COUNT)
    provider_founded_year: int | None = Field(default=None, ge=1000, le=9999)
    provider_short_description: (
        Annotated[str, StringConstraints(max_length=MAX_DESCRIPTION_LENGTH)] | None
    ) = None
    provider_keywords: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=MAX_KEYWORD_LENGTH)], ...
    ] = Field(default=(), max_length=MAX_KEYWORDS)
    provider_observed_at: dt.datetime
    provider_source_fingerprint: Fingerprint
    contact_role_profile_version: ShortText
    contact_role_tier: int = Field(ge=1, le=4)
    provider_research_status: ProviderResearchStatus = (
        ProviderResearchStatus.CURRENT_PROVIDER_RECORD
    )
    research_completeness: ResearchCompleteness
    research_gaps: tuple[ResearchGap, ...] = Field(default=(), max_length=MAX_RESEARCH_GAPS)
    size_band: CompanySizeBand
    size_band_version: ShortText = SIZE_BAND_VERSION
    prebuild_version: ShortText = PREBUILD_VERSION
    prebuild_fingerprint: Fingerprint

    _observed = field_validator("provider_observed_at")(_aware)


class AcquisitionCompanyProfile(AcquisitionProspectPrebuild):
    created_at: dt.datetime
    updated_at: dt.datetime

    _record_times = field_validator("created_at", "updated_at")(_aware)


class CompanyResearchContactBinding(CompanyResearchContract):
    contact_ref: StableRef
    supplier_ref: StableRef
    verification_state: Literal["PROVIDER_VERIFIED"]
    verification_provider: Literal["apollo"]
    provider_email_status: Literal["verified"]
    role_profile_version: ShortText
    role_tier: int = Field(ge=1, le=4)


class CompanyResearchRunStart(CompanyResearchContract):
    company_research_run_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    acquisition_opportunity_id: StableRef
    supplier_ref: StableRef
    contact_ref: StableRef
    policy_evaluation_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    profile: CompanyResearchProfile
    provider_request_fingerprint: Fingerprint
    expected_post_policy_version: int = Field(ge=2)
    started_at: dt.datetime
    correlation_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]

    _started = field_validator("started_at")(_aware)


class CompanyResearchRunRecord(CompanyResearchContract):
    company_research_run_id: str
    acquisition_opportunity_id: StableRef
    supplier_ref: StableRef
    contact_ref: StableRef
    policy_evaluation_id: str
    research_profile_version: str
    research_profile_fingerprint: Fingerprint
    research_profile: dict[str, object]
    provider: Literal["apollo"]
    provider_endpoint_kind: Literal["exact_organization_id"]
    provider_request_fingerprint: Fingerprint
    expected_post_policy_version: int = Field(ge=2)
    planned_provider_credit_units: Literal[1]
    observed_provider_credit_units: int | None = Field(default=None, ge=0)
    provider_calls: int = Field(ge=0, le=1)
    started_at: dt.datetime
    completed_at: dt.datetime | None = None
    status: CompanyResearchRunStatus
    error_category: str | None = None
    error_detail: str | None = None
    retry_after: dt.datetime | None = None
    correlation_id: str

    @field_validator("started_at", "completed_at", "retry_after")
    @classmethod
    def aware_run_times(cls, value: dt.datetime | None) -> dt.datetime | None:
        return _aware(value) if value is not None else None


class CompanyResearchAuthorizationInput(CompanyResearchContract):
    evaluation_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    request_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ]
    actor_type: Annotated[str, StringConstraints(pattern=r"^(SYSTEM|HERMES|HUMAN)$")]
    actor_ref: StableRef | None = None
    qa_signal_ref: StableRef | None = None
    scope: Scope
    proposed_cost: Decimal = Field(ge=0)
    currency: Currency
    reason_codes: tuple[ShortText, ...] = Field(default=(), max_length=MAX_REASON_CODES)
    evidence_refs: tuple[StableRef, ...] = Field(default=(), max_length=MAX_EVIDENCE_REFS)
    evidence: EvidenceReadiness
    compliance: ComplianceAssessment
    operational: OperationalReadiness
    expected_policy_version: ShortText
    approval_grants: tuple[ApprovalGrant, ...] = Field(default=(), max_length=MAX_APPROVAL_GRANTS)
    supervisor_plan_id: str | None = None
    supervisor_action_index: int | None = Field(default=None, ge=0)
    supervisor_version: str | None = None
    skill_version: str | None = None


class CompanyResearchServiceResult(CompanyResearchContract):
    decision: PolicyDecision | None = None
    run: CompanyResearchRunRecord | None = None
    profile: AcquisitionCompanyProfile | None = None
    provider_called: bool = False


__all__ = [
    "ALLOWED_PROVIDER_FIELDS",
    "AcquisitionCompanyProfile",
    "AcquisitionProspectPrebuild",
    "ApolloOrganizationObservation",
    "CompanyResearchAuthorizationInput",
    "CompanyResearchContactBinding",
    "CompanyResearchEvaluationRequiresFreshAttempt",
    "CompanyResearchNotActionable",
    "CompanyResearchObservationConflict",
    "CompanyResearchProfile",
    "CompanyResearchProviderError",
    "CompanyResearchRunAlreadyStarted",
    "CompanyResearchRunIdentityConflict",
    "CompanyResearchRunRecord",
    "CompanyResearchRunStart",
    "CompanyResearchRunStatus",
    "CompanyResearchServiceResult",
    "CompanySizeBand",
    "ProviderResearchStatus",
    "ResearchCompleteness",
    "ResearchGap",
    "SupplierIdentityStatus",
]
