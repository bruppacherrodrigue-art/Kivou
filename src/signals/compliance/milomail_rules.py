"""Separate, deterministic France B2B policy for Milo Mail's Gmail audit pilot.

Legal anchors: CNIL electronic prospecting guidance, CPCE L34-5, GDPR 6/14/21.
This is a theoretical eligibility decision. Execution remains under Policy Gateway
and the program's SHADOW export guard.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from decimal import Decimal
from typing import Final, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from signals.acquisition_programs.activity_evidence import (
    ActivityAssessment,
    ActivityEvidenceInput,
    WebsiteIdentityProof,
    activity_input_from_b0,
    evaluate_activity_evidence,
)
from signals.acquisition_programs.contracts import AcquisitionProgramConfig
from signals.acquisition_programs.mail_provider import (
    MailProvider,
    MailProviderDetector,
    MailProviderEvidence,
    ProviderConfidence,
    normalize_domain,
)
from signals.acquisition_programs.qualification import (
    CapacityAssessment,
    FitAssessment,
    ProfessionalEvidenceInput,
    RecipientCapacity,
    classify_recipient,
)

MILOMAIL_PURPOSE: Final = "MILOMAIL_GMAIL_AUDIT_B2B"
POLICY_VERSION: Final = "milomail-fr-b2b-v1"
POLICY_VERSION_V2: Final = "milomail-fr-b2b-v2"
LEGAL_SOURCES = (
    "https://www.cnil.fr/fr/communication-electronique-quelles-regles",
    "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000042155961/",
    "https://eur-lex.europa.eu/eli/reg/2016/679/oj?locale=fr",
)


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class MilomailPolicyInput(_ClosedModel):
    acquisition_purpose: Literal["MILOMAIL_GMAIL_AUDIT_B2B"]
    program: AcquisitionProgramConfig
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    sector: str | None = None
    employee_count: int | None = Field(default=None, ge=0)
    employee_count_range: tuple[int, int] | None = None
    company_active: bool | None = None
    company_active_source_url: str | None = None
    company_active_source_type: str | None = None
    company_active_observed_at: dt.datetime | None = None
    company_active_evidence_id: str | None = None
    activity_evidence: ActivityEvidenceInput | None = None
    business_relevance_confirmed: bool = False
    provider: MailProviderEvidence
    capacity: CapacityAssessment
    fit: FitAssessment
    email_verified: bool = False
    collection_source_url: str | None = None
    collected_at: dt.datetime | None = None
    suppressed: bool = False
    suppression_coverage_safe: bool = False
    is_minor: bool = False
    is_private_individual: bool = False
    sender_identity_ready: bool = False
    opt_out_ready: bool = False
    privacy_notice_ready: bool = False
    source_notice_ready: bool = False
    sender_domain: str | None = None
    sender_healthy: bool = False
    spf_ready: bool = False
    dkim_ready: bool = False
    dmarc_ready: bool = False
    warmup_ready: bool = False
    landing_active: bool = False
    landing_french: bool = False
    daily_remaining: int = Field(default=0, ge=0)
    monthly_remaining: int = Field(default=0, ge=0)
    cost_remaining_chf: Decimal = Field(default=Decimal(0), ge=0)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=16)
    assessed_at: dt.datetime

    @field_validator("assessed_at", "collected_at", "company_active_observed_at")
    @classmethod
    def aware(cls, value: dt.datetime | None) -> dt.datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("policy datetimes must be timezone-aware")
        return value

    @field_validator("collection_source_url", "company_active_source_url")
    @classmethod
    def public_collection_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("collection source must be a public HTTP URL")
        normalize_domain(parsed.hostname)
        return value

    @model_validator(mode="after")
    def bound_versions(self) -> MilomailPolicyInput:
        if self.program.program_key != "milomail" or self.program.policy_version not in {
            POLICY_VERSION, POLICY_VERSION_V2
        }:
            raise ValueError("Milo Mail policy and program version mismatch")
        if self.fit.score_version != self.program.score_version:
            raise ValueError("Milo Mail score version mismatch")
        return self


class MilomailPolicyDecision(_ClosedModel):
    decision: Literal["SEND", "HOLD", "NO_SEND"]
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=32)
    policy_country: Literal["FR"] = "FR"
    policy_version: Literal["milomail-fr-b2b-v1", "milomail-fr-b2b-v2"] = POLICY_VERSION
    score_version: str
    evidence_ids: tuple[str, ...]
    decided_at: dt.datetime


def evaluate_milomail(value: MilomailPolicyInput) -> MilomailPolicyDecision:
    """Separate exclusions from remediable gaps; never infer permission from Apollo."""
    excluded: list[str] = []
    hold: list[str] = []
    activity_result = None
    if value.program.policy_version == POLICY_VERSION_V2:
        if value.activity_evidence is None:
            hold.append("ACTIVITY_EVIDENCE_MISSING")
        else:
            activity_result = evaluate_activity_evidence(
                value.activity_evidence,
                provider=value.provider,
                allowed_roles=value.program.target_roles,
                at=value.assessed_at,
            )
            if activity_result.status == "OFFICIAL_CEASED":
                excluded.append("OFFICIAL_CEASED")
            elif activity_result.status == "UNKNOWN":
                hold.extend(activity_result.reason_codes)
            if not set(activity_result.evidence_ids).issubset(value.evidence_ids):
                hold.append("ACTIVITY_EVIDENCE_NOT_RECORDED")

    if value.is_minor or value.is_private_individual:
        excluded.append("PERSONAL_OR_MINOR")
    if value.capacity.capacity is RecipientCapacity.PERSONAL:
        excluded.append("PERSONAL_RECIPIENT")
    if value.suppressed:
        excluded.append("SUPPRESSION_MATCH")
    if value.country is not None and value.country != "FR":
        excluded.append("COUNTRY_OUT_OF_SCOPE")
    if value.sector is not None and value.sector not in value.program.target_sectors:
        excluded.append("SECTOR_OUT_OF_SCOPE")
    if value.employee_count_range is not None and not (
        value.program.target_company_size_min <= value.employee_count_range[0] <=
        value.employee_count_range[1] <= value.program.target_company_size_max
    ):
        excluded.append("COMPANY_SIZE_OUT_OF_SCOPE")
    if value.employee_count is not None and not (
        value.program.target_company_size_min
        <= value.employee_count
        <= value.program.target_company_size_max
    ):
        excluded.append("COMPANY_SIZE_OUT_OF_SCOPE")
    if value.program.policy_version == POLICY_VERSION and value.company_active is False:
        excluded.append("COMPANY_INACTIVE")
    if value.provider.provider in {
        MailProvider.MICROSOFT_365,
        MailProvider.OTHER,
        MailProvider.GMAIL_CONSUMER,
    }:
        excluded.append("MAIL_PROVIDER_OUT_OF_SCOPE")
    unresolved_score_facts = (
        value.provider.provider is MailProvider.UNKNOWN
        or value.sector is None
        or (value.employee_count is None and value.employee_count_range is None)
        or value.capacity.capacity
        in {RecipientCapacity.UNKNOWN, RecipientCapacity.LIKELY_PROFESSIONAL}
    )
    if value.fit.total < value.program.hold_threshold:
        if unresolved_score_facts:
            hold.append("FIT_BELOW_MINIMUM_PENDING_FACTS")
        else:
            excluded.append("FIT_BELOW_MINIMUM")

    if value.country is None:
        hold.append("COUNTRY_UNRESOLVED")
    if value.sector is None or (value.employee_count is None and value.employee_count_range is None):
        hold.append("COMPANY_FACTS_INCOMPLETE")
    if value.program.policy_version == POLICY_VERSION and value.company_active is None:
        hold.append("COMPANY_ACTIVE_STATUS_UNRESOLVED")
    if value.program.policy_version == POLICY_VERSION and value.company_active is True and (
        not all(
            (
                value.company_active_source_url,
                value.company_active_source_type,
                value.company_active_observed_at,
                value.company_active_evidence_id,
            )
        )
        or value.company_active_evidence_id not in value.evidence_ids
        or (
            value.company_active_observed_at is not None
            and (
                value.company_active_observed_at > value.assessed_at
                or value.company_active_observed_at
                + dt.timedelta(days=value.program.professional_evidence_ttl_days)
                <= value.assessed_at
            )
        )
    ):
        hold.append("COMPANY_ACTIVE_EVIDENCE_INSUFFICIENT")
    if not value.business_relevance_confirmed:
        hold.append("BUSINESS_RELEVANCE_UNCONFIRMED")
    if value.provider.provider is MailProvider.UNKNOWN:
        hold.append("MAIL_PROVIDER_UNKNOWN")
    if value.provider.provider is MailProvider.GOOGLE_WORKSPACE and (
        value.provider.confidence is not ProviderConfidence.CONFIRMED
        or not value.provider.mx_records
        or value.provider.source != "DNS_MX"
        or MailProviderDetector._classify(value.provider.mx_records)
        is not MailProvider.GOOGLE_WORKSPACE
    ):
        hold.append("GOOGLE_WORKSPACE_EVIDENCE_INSUFFICIENT")
    if value.provider.observed_at > value.assessed_at:
        hold.append("PROVIDER_EVIDENCE_FROM_FUTURE")
    if value.provider.expires_at <= value.assessed_at:
        hold.append("PROVIDER_EVIDENCE_EXPIRED")
    if value.capacity.capacity in {
        RecipientCapacity.UNKNOWN,
        RecipientCapacity.LIKELY_PROFESSIONAL,
    }:
        hold.append("RECIPIENT_CAPACITY_UNCONFIRMED")
    if value.capacity.capacity is RecipientCapacity.CONFIRMED_PROFESSIONAL and not all(
        (
            value.capacity.professional_source_url,
            value.capacity.professional_source_type,
            value.capacity.professional_evidence_observed_at,
            value.capacity.company_id,
            value.capacity.role in value.program.target_roles,
        )
    ):
        hold.append("PROFESSIONAL_EVIDENCE_INCOMPLETE")
    if (
        value.capacity.evidence_expires_at is None
        or value.capacity.evidence_expires_at <= value.assessed_at
    ):
        hold.append("PROFESSIONAL_EVIDENCE_EXPIRED")
    if not value.email_verified:
        hold.append("EMAIL_NOT_VERIFIED")
    if (
        not value.collection_source_url
        or not value.collected_at
        or (value.collected_at is not None and value.collected_at > value.assessed_at)
    ):
        hold.append("COLLECTION_PROVENANCE_MISSING")
    if not value.suppression_coverage_safe:
        hold.append("SUPPRESSION_COVERAGE_UNSAFE")
    if value.program.hold_threshold <= value.fit.total < value.program.send_review_threshold:
        if unresolved_score_facts:
            hold.append("FIT_BELOW_REVIEW_THRESHOLD_PENDING_FACTS")
        else:
            excluded.append("FIT_BELOW_REVIEW_THRESHOLD")
    if not value.evidence_ids:
        hold.append("EVIDENCE_MISSING")
    if not value.sender_identity_ready or not all(
        (
            value.program.sender_legal_name,
            value.program.sender_postal_address,
        )
    ):
        hold.append("SENDER_IDENTITY_MISSING")
    if not value.opt_out_ready or not value.program.opt_out_url:
        hold.append("OPT_OUT_MISSING")
    if not value.privacy_notice_ready or not value.program.privacy_url:
        hold.append("PRIVACY_NOTICE_MISSING")
    if not value.source_notice_ready:
        hold.append("SOURCE_NOTICE_MISSING")
    if not value.sender_domain or value.sender_domain not in value.program.sender_domains:
        hold.append("SENDER_DOMAIN_NOT_ALLOWED")
    if not all(
        (
            value.sender_healthy,
            value.spf_ready,
            value.dkim_ready,
            value.dmarc_ready,
            value.warmup_ready,
            value.program.sender_configuration_ref,
            value.program.instantly_workspace_ref,
        )
    ):
        hold.append("SENDER_NOT_READY")
    if not value.program.landing_url or not value.landing_active or not value.landing_french:
        hold.append("FRENCH_LANDING_UNAVAILABLE")
    if value.daily_remaining <= 0 or value.monthly_remaining <= 0 or value.cost_remaining_chf <= 0:
        hold.append("BUDGET_EXHAUSTED")

    decision: Literal["SEND", "HOLD", "NO_SEND"]
    reasons: tuple[str, ...]
    if excluded:
        decision, reasons = "NO_SEND", tuple(dict.fromkeys(excluded))
    elif hold:
        decision, reasons = "HOLD", tuple(dict.fromkeys(hold))
    else:
        decision, reasons = "SEND", (
            "FR_B2B_GMAIL_AUDIT_ELIGIBLE",
            *((activity_result.reason_codes) if activity_result is not None else ()),
        )
    return MilomailPolicyDecision(
        decision=decision,
        reason_codes=reasons,
        score_version=value.fit.score_version,
        evidence_ids=value.evidence_ids,
        policy_version=value.program.policy_version,
        decided_at=value.assessed_at,
    )


class B0ActivityReplay(_ClosedModel):
    activity: ActivityAssessment
    policy: MilomailPolicyDecision


def evaluate_b0_activity_replay(
    b0_result: Mapping[str, object],
    candidate_snapshot: Mapping[str, object],
    *,
    policy_input: MilomailPolicyInput,
    website_proof: WebsiteIdentityProof | None = None,
) -> B0ActivityReplay:
    """Replay persisted B0 evidence through policy v2 with no provider calls."""
    if policy_input.program.policy_version != POLICY_VERSION_V2:
        raise ValueError("B0 activity replay requires Milo Mail policy v2")
    activity_input = activity_input_from_b0(
        b0_result,
        candidate_snapshot,
        role=policy_input.capacity.role,
        website_proof=website_proof,
    )
    activity = evaluate_activity_evidence(
        activity_input,
        provider=policy_input.provider,
        allowed_roles=policy_input.program.target_roles,
        at=policy_input.assessed_at,
    )
    evidence_ids = tuple(dict.fromkeys((*policy_input.evidence_ids, *activity.evidence_ids)))
    capacity = policy_input.capacity
    leader = activity_input.leader
    candidate = candidate_snapshot.get("snapshot", candidate_snapshot)
    if (
        activity.status in {"OFFICIAL_ACTIVE", "OPERATIONALLY_ACTIVE"}
        and leader is not None
        and capacity.capacity in {RecipientCapacity.UNKNOWN, RecipientCapacity.LIKELY_PROFESSIONAL}
        and isinstance(candidate, Mapping)
        and isinstance(candidate.get("provider_organization_id"), str)
        and isinstance(b0_result.get("email"), str)
    ):
        capacity = classify_recipient(
            ProfessionalEvidenceInput(
                email=b0_result["email"],
                company_domain=activity_input.company_domain,
                company_id=candidate["provider_organization_id"],
                company_active=True,
                role=leader.role,
                email_verified=leader.email_verified,
                professional_source_url="https://api.apollo.io/api/v1/people/match",
                professional_source_type=leader.source_type,
                professional_evidence_observed_at=leader.observed_at,
                is_minor=policy_input.is_minor,
                is_private_individual=policy_input.is_private_individual,
            ),
            config=policy_input.program,
            at=policy_input.assessed_at,
        )
    decision = evaluate_milomail(policy_input.model_copy(update={
        "activity_evidence": activity_input,
        "evidence_ids": evidence_ids,
        "capacity": capacity,
        "suppressed": policy_input.suppressed or b0_result.get("classification") == "SUPPRESSED",
    }))
    return B0ActivityReplay(activity=activity, policy=decision)


__all__ = [
    "LEGAL_SOURCES",
    "MILOMAIL_PURPOSE",
    "POLICY_VERSION",
    "POLICY_VERSION_V2",
    "B0ActivityReplay",
    "MilomailPolicyDecision",
    "MilomailPolicyInput",
    "evaluate_b0_activity_replay",
    "evaluate_milomail",
]
