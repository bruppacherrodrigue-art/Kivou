"""Strict Kivou-owned contracts for contact discovery."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

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

PROFILE_VERSION = "decision-maker-search-v1"
PROVIDER = "apollo"
MAX_RESPONSE_BYTES = 1_048_576
MAX_SEARCH_PAGES = 1
MAX_SEARCH_RESULTS = 25
MAX_ENRICHMENT_ATTEMPTS = 3
SEARCH_TOO_BROAD_THRESHOLD = 250

StableRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
ProviderId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ContactDiscoveryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _aware_optional(value: dt.datetime | None) -> dt.datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("datetime must be timezone-aware")
    return value


class DecisionMakerSearchProfile(ContactDiscoveryContract):
    profile_version: ShortText = PROFILE_VERSION
    acquisition_opportunity_id: StableRef
    supplier_ref: StableRef
    provider_organization_id: ProviderId
    person_titles: tuple[ShortText, ...] = Field(min_length=1, max_length=32)
    person_seniorities: tuple[ShortText, ...] = Field(min_length=1, max_length=16)
    contact_email_statuses: tuple[ShortText, ...] = ("verified",)
    include_similar_titles: bool = False
    max_pages: int = Field(default=MAX_SEARCH_PAGES, ge=1, le=MAX_SEARCH_PAGES)
    per_page: int = Field(default=MAX_SEARCH_RESULTS, ge=1, le=MAX_SEARCH_RESULTS)
    max_enrichment_attempts: int = Field(
        default=MAX_ENRICHMENT_ATTEMPTS, ge=1, le=MAX_ENRICHMENT_ATTEMPTS
    )
    search_too_broad_threshold: int = Field(
        default=SEARCH_TOO_BROAD_THRESHOLD,
        ge=MAX_SEARCH_RESULTS,
        le=SEARCH_TOO_BROAD_THRESHOLD,
    )
    profile_fingerprint: Fingerprint


class PeopleSearchCandidate(ContactDiscoveryContract):
    provider_person_id: ProviderId
    first_name: ShortText | None = None
    last_name_obfuscated: ShortText | None = None
    title: ShortText
    provider_position: int = Field(ge=0, le=MAX_SEARCH_RESULTS - 1)
    organization_name: ShortText | None = None
    provider_refreshed_at: dt.datetime | None = None
    has_email: bool

    _refreshed = field_validator("provider_refreshed_at")(_aware_optional)


class RankedCandidate(ContactDiscoveryContract):
    candidate: PeopleSearchCandidate
    normalized_title: ShortText
    role_tier: int = Field(ge=1, le=4)
    exact_title_match: bool
    seniority_priority: int = Field(ge=1, le=20)


class ContactCandidateRejection(ContactDiscoveryContract):
    item_index: int = Field(ge=0, le=MAX_SEARCH_RESULTS - 1)
    provider_person_id: ProviderId | None = None
    reason_code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,99}$")]


class PeopleSearchPage(ContactDiscoveryContract):
    total_entries: int = Field(ge=0)
    candidates: tuple[PeopleSearchCandidate, ...] = Field(max_length=MAX_SEARCH_RESULTS)
    rejections: tuple[ContactCandidateRejection, ...] = Field(max_length=MAX_SEARCH_RESULTS)
    observed_at: dt.datetime

    _observed = field_validator("observed_at")(_aware_optional)


class ApolloEnrichedPerson(ContactDiscoveryContract):
    provider_person_id: ProviderId
    provider_organization_id: ProviderId | None = None
    first_name: ShortText | None = None
    last_name: ShortText | None = None
    display_name: ShortText | None = None
    title: ShortText | None = None
    business_email: Annotated[str, StringConstraints(max_length=320)] | None = None
    provider_email_status: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)] | None
    ) = None
    provider_observed_at: dt.datetime
    source_fingerprint: Fingerprint

    _observed = field_validator("provider_observed_at")(_aware_optional)


class ApolloContactProviderError(RuntimeError):
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
        super().__init__(f"apollo contact provider: {category}")


class ContactRunStatus(StrEnum):
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    NO_CANDIDATE = "NO_CANDIDATE"
    NO_VERIFIED_CONTACT = "NO_VERIFIED_CONTACT"
    CONTACT_SEARCH_TOO_BROAD = "CONTACT_SEARCH_TOO_BROAD"
    FAILED = "FAILED"


class ContactObservationConflict(RuntimeError):
    pass


class ContactRunIdentityConflict(RuntimeError):
    pass


class ContactRunAlreadyStarted(RuntimeError):
    pass


class ContactDiscoveryNotActionable(RuntimeError):
    pass


class ContactDiscoveryEvaluationRequiresFreshAttempt(RuntimeError):
    pass


_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ContactObservation(ContactDiscoveryContract):
    supplier_ref: StableRef
    provider: str = PROVIDER
    provider_person_id: ProviderId
    provider_organization_id: ProviderId
    first_name: ShortText | None = None
    last_name: ShortText | None = None
    display_name: ShortText | None = None
    title: ShortText | None = None
    normalized_title: ShortText
    role_profile_version: ShortText = PROFILE_VERSION
    role_tier: int = Field(ge=1, le=4)
    business_email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320)]
    provider_email_status: str = "verified"
    verification_state: str = "PROVIDER_VERIFIED"
    verification_provider: str = PROVIDER
    provider_observed_at: dt.datetime
    email_observed_at: dt.datetime
    source_fingerprint: Fingerprint

    _times = field_validator("provider_observed_at", "email_observed_at")(_aware_optional)

    @field_validator("business_email")
    @classmethod
    def valid_business_email(cls, value: str) -> str:
        if not _EMAIL.fullmatch(value):
            raise ValueError("invalid business email")
        return value

    @field_validator("provider", "verification_provider")
    @classmethod
    def apollo_only(cls, value: str) -> str:
        if value != PROVIDER:
            raise ValueError("only Apollo provider observations are supported")
        return value

    @field_validator("provider_email_status")
    @classmethod
    def verified_status(cls, value: str) -> str:
        if value != "verified":
            raise ValueError("provider email status must be verified")
        return value

    @field_validator("verification_state")
    @classmethod
    def provider_verified_state(cls, value: str) -> str:
        if value != "PROVIDER_VERIFIED":
            raise ValueError("contact must be provider verified")
        return value


class ContactRecord(ContactObservation):
    contact_ref: Fingerprint
    created_at: dt.datetime
    updated_at: dt.datetime

    _record_times = field_validator("created_at", "updated_at")(_aware_optional)


class ContactRunStart(ContactDiscoveryContract):
    contact_discovery_run_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    acquisition_opportunity_id: StableRef
    supplier_ref: StableRef
    policy_evaluation_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]
    profile: DecisionMakerSearchProfile
    provider_request_fingerprint: Fingerprint
    expected_post_policy_version: int = Field(ge=2)
    started_at: dt.datetime
    correlation_id: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]

    _started = field_validator("started_at")(_aware_optional)


class ContactRunRecord(ContactDiscoveryContract):
    contact_discovery_run_id: str
    acquisition_opportunity_id: StableRef
    supplier_ref: StableRef
    policy_evaluation_id: str
    provider: str
    search_profile_version: str
    search_profile_fingerprint: Fingerprint
    search_profile: dict[str, object]
    provider_request_fingerprint: Fingerprint
    expected_post_policy_version: int = Field(ge=2)
    requested_max_pages: int
    per_page: int
    max_enrichment_attempts: int
    people_search_requests: int = Field(ge=0)
    recovery_provider_calls: int = Field(ge=0, le=1)
    provider_total_entries: int | None = Field(default=None, ge=0)
    search_results_returned: int = Field(ge=0)
    search_results_truncated: bool
    candidates_eligible: int = Field(ge=0)
    candidates_rejected: int = Field(ge=0)
    enrichment_attempts: int = Field(ge=0)
    planned_provider_credit_units: int = Field(ge=0)
    observed_provider_credit_units: int | None = Field(default=None, ge=0)
    attempted_contact_refs: tuple[Fingerprint, ...] = Field(default=(), max_length=3)
    selected_contact_ref: Fingerprint | None = None
    started_at: dt.datetime
    completed_at: dt.datetime | None = None
    status: ContactRunStatus
    error_category: str | None = None
    error_detail: str | None = None
    retry_after: dt.datetime | None = None
    correlation_id: str

    _run_times = field_validator("started_at", "completed_at", "retry_after")(_aware_optional)


class ContactAuthorizationInput(ContactDiscoveryContract):
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


class ContactDiscoveryServiceResult(ContactDiscoveryContract):
    decision: PolicyDecision | None = None
    run: ContactRunRecord | None = None
    contact: ContactRecord | None = None
    provider_called: bool = False
