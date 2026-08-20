"""Strict bounded contracts for company-only supplier discovery."""

from __future__ import annotations

import datetime as dt
import re
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

PROFILE_VERSION = "supplier-search-v1"
PROVIDER = "apollo"
MAX_RESPONSE_BYTES = 1_048_576
_DOMAIN = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)

StableRef = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
ShortText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)
]
ProviderId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class DiscoveryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SupplierIdentityStatus(StrEnum):
    PROVIDER_IDENTIFIED = "PROVIDER_IDENTIFIED"
    DOMAIN_CONFLICT = "DOMAIN_CONFLICT"


class DiscoveryRunStatus(StrEnum):
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SEARCH_TOO_BROAD = "SEARCH_TOO_BROAD"


class DiscoveryAlreadyStarted(RuntimeError):
    pass


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class SupplierTargetingConfig(DiscoveryContract):
    organization_locations: tuple[ShortText, ...] = Field(default=(), max_length=32)
    organization_not_locations: tuple[ShortText, ...] = Field(default=(), max_length=32)
    employee_ranges: tuple[
        Annotated[str, StringConstraints(pattern=r"^[0-9]+,[0-9]+$")], ...
    ] = Field(default=(), max_length=16)
    excluded_domains: tuple[
        Annotated[str, StringConstraints(min_length=1, max_length=253)], ...
    ] = Field(default=(), max_length=100)
    max_pages: int = Field(default=1, ge=1, le=5)
    per_page: int = Field(default=100, ge=1, le=100)
    candidate_cap: int = Field(default=100, ge=1, le=500)
    search_too_broad_threshold: int = Field(default=10_000, ge=100, le=50_000)

    @field_validator("employee_ranges")
    @classmethod
    def ordered_employee_ranges(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            low, high = (int(part) for part in value.split(","))
            if low > high:
                raise ValueError("employee range lower bound exceeds upper bound")
        return tuple(sorted(set(values)))

    @field_validator(
        "organization_locations",
        "organization_not_locations",
    )
    @classmethod
    def sorted_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values), key=str.casefold))

    @field_validator("excluded_domains")
    @classmethod
    def normalized_domains(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.casefold().rstrip(".") for value in values)
        if any(not _DOMAIN.fullmatch(value) for value in normalized):
            raise ValueError("excluded_domains contains an invalid domain")
        return tuple(sorted(set(normalized)))


class SupplierSearchProfile(DiscoveryContract):
    profile_version: ShortText = PROFILE_VERSION
    signal_ref: StableRef
    representative_award_key: StableRef
    need_categories: tuple[ShortText, ...] = Field(max_length=7)
    keyword_tags: tuple[ShortText, ...] = Field(max_length=32)
    organization_locations: tuple[ShortText, ...] = Field(default=(), max_length=32)
    organization_not_locations: tuple[ShortText, ...] = Field(default=(), max_length=32)
    employee_ranges: tuple[ShortText, ...] = Field(default=(), max_length=16)
    excluded_domains: tuple[ShortText, ...] = Field(default=(), max_length=100)
    max_pages: int = Field(ge=1, le=5)
    per_page: int = Field(ge=1, le=100)
    candidate_cap: int = Field(ge=1, le=500)
    search_too_broad_threshold: int = Field(ge=100, le=50_000)
    profile_fingerprint: Fingerprint

    @field_validator("signal_ref")
    @classmethod
    def public_seed_reference(cls, value: str) -> str:
        if not value.startswith("procurement-opportunity:"):
            raise ValueError("supplier discovery requires a public procurement seed")
        return value

    @field_validator("excluded_domains")
    @classmethod
    def canonical_excluded_domains(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.casefold().rstrip(".") for value in values)
        if any(not _DOMAIN.fullmatch(value) for value in normalized):
            raise ValueError("excluded_domains contains an invalid domain")
        return tuple(sorted(set(normalized)))


class ApolloOrganizationCandidate(DiscoveryContract):
    provider: Literal["apollo"] = PROVIDER
    provider_organization_id: ProviderId
    display_name: ShortText
    normalized_name: ShortText
    primary_domain: Annotated[str, StringConstraints(max_length=253)] | None = None
    website_url: Annotated[str, StringConstraints(max_length=2048)] | None = None
    linkedin_company_url: Annotated[str, StringConstraints(max_length=2048)] | None = None
    country_code: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")] | None = None
    location: Annotated[str, StringConstraints(max_length=512)] | None = None
    industry: Annotated[str, StringConstraints(max_length=256)] | None = None
    provider_observed_at: dt.datetime
    source_fingerprint: Fingerprint

    _observed = field_validator("provider_observed_at")(_aware)


class SupplierRecord(DiscoveryContract):
    supplier_ref: StableRef
    provider: Literal["apollo"]
    provider_organization_id: ProviderId
    display_name: ShortText
    normalized_name: ShortText
    primary_domain: Annotated[str, StringConstraints(max_length=253)] | None = None
    website_url: Annotated[str, StringConstraints(max_length=2048)] | None = None
    linkedin_company_url: Annotated[str, StringConstraints(max_length=2048)] | None = None
    country_code: Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")] | None = None
    location: Annotated[str, StringConstraints(max_length=512)] | None = None
    industry: Annotated[str, StringConstraints(max_length=256)] | None = None
    identity_status: SupplierIdentityStatus
    identity_conflict_fingerprint: Fingerprint | None = None
    provider_observed_at: dt.datetime
    source_fingerprint: Fingerprint
    created_at: dt.datetime
    updated_at: dt.datetime

    _times = field_validator("provider_observed_at", "created_at", "updated_at")(_aware)


class CandidateRejection(DiscoveryContract):
    item_index: int = Field(ge=0)
    provider_organization_id: ProviderId | None = None
    reason_code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,99}$")]


class SupplierSearchPage(DiscoveryContract):
    page: int = Field(ge=1)
    per_page: int = Field(ge=1, le=100)
    total_entries: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    partial_results_only: bool | None = None
    candidates: tuple[ApolloOrganizationCandidate, ...] = Field(max_length=100)
    rejections: tuple[CandidateRejection, ...] = Field(max_length=100)


class DiscoveryRunStart(DiscoveryContract):
    discovery_run_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    policy_evaluation_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    profile: SupplierSearchProfile
    provider_request_fingerprint: Fingerprint
    started_at: dt.datetime
    correlation_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]

    _started = field_validator("started_at")(_aware)


class DiscoveryRunRecord(DiscoveryContract):
    discovery_run_id: str
    signal_ref: StableRef
    policy_evaluation_id: str
    provider: str
    search_profile_version: str
    search_profile_fingerprint: Fingerprint
    search_profile: dict[str, object]
    provider_request_fingerprint: Fingerprint
    requested_max_pages: int
    per_page: int
    candidate_cap: int
    planned_provider_credit_units: int
    pages_requested: int
    provider_credit_units_observed: int | None = Field(default=None, ge=0)
    provider_total_entries: int | None = Field(default=None, ge=0)
    partial_results_only: bool | None = None
    records_returned: int
    records_accepted: int
    records_rejected: int
    rejection_reason_counts: dict[str, int]
    duplicates: int
    opportunities_created: int
    started_at: dt.datetime
    completed_at: dt.datetime | None = None
    status: DiscoveryRunStatus
    error_category: str | None = None
    error_detail: str | None = None
    retry_after: dt.datetime | None = None
    correlation_id: str

    _run_times = field_validator("started_at", "completed_at", "retry_after")(
        lambda value: _aware(value) if value is not None else None
    )


class DiscoveryAuthorizationInput(DiscoveryContract):
    evaluation_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    request_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
    ]
    actor_type: Annotated[str, StringConstraints(pattern=r"^(SYSTEM|HERMES|HUMAN)$")]
    actor_ref: StableRef | None = None
    scope: Scope
    proposed_cost: Decimal = Field(ge=0)
    currency: Currency
    reason_codes: tuple[ShortText, ...] = Field(default=(), max_length=MAX_REASON_CODES)
    evidence_refs: tuple[StableRef, ...] = Field(default=(), max_length=MAX_EVIDENCE_REFS)
    evidence: EvidenceReadiness
    compliance: ComplianceAssessment
    operational: OperationalReadiness
    expected_policy_version: ShortText
    approval_grants: tuple[ApprovalGrant, ...] = Field(
        default=(), max_length=MAX_APPROVAL_GRANTS
    )
    supervisor_plan_id: str | None = None
    supervisor_action_index: int | None = Field(default=None, ge=0)
    supervisor_version: str | None = None
    skill_version: str | None = None


class DiscoveryServiceResult(DiscoveryContract):
    decision: PolicyDecision
    run: DiscoveryRunRecord | None = None
    opportunity_ids: tuple[str, ...] = ()
    provider_called: bool = False


class ApolloProviderError(RuntimeError):
    def __init__(
        self,
        category: str,
        *,
        retry_after: dt.datetime | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(detail or category)
        self.category = category
        self.retry_after = retry_after
        self.detail = detail
