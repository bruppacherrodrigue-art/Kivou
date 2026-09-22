"""Deterministic professional-capacity and public-proxy fit calculations."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from urllib.parse import urlsplit

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, field_validator

from signals.acquisition_programs.contracts import AcquisitionProgramConfig
from signals.acquisition_programs.mail_provider import MailProvider, normalize_domain

CLASSIFIER_VERSION = "professional-capacity-v1"


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RecipientCapacity(StrEnum):
    CONFIRMED_PROFESSIONAL = "CONFIRMED_PROFESSIONAL"
    LIKELY_PROFESSIONAL = "LIKELY_PROFESSIONAL"
    PERSONAL = "PERSONAL"
    UNKNOWN = "UNKNOWN"


class ProfessionalEvidenceInput(_ClosedModel):
    email: str = Field(min_length=3, max_length=320, repr=False)
    company_domain: str | None = None
    company_id: str | None = None
    company_active: bool = False
    role: str | None = None
    email_verified: bool = False
    professional_source_url: str | None = None
    professional_source_type: str | None = None
    professional_evidence_observed_at: dt.datetime | None = None
    email_explicitly_published: bool = False
    is_minor: bool = False
    is_private_individual: bool = False

    @field_validator("professional_source_url")
    @classmethod
    def public_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if (
            parts.scheme not in {"https", "http"}
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.fragment
        ):
            raise ValueError("professional source URL is invalid")
        normalize_domain(parts.hostname)
        return value

    @field_validator("professional_evidence_observed_at")
    @classmethod
    def aware_observation(cls, value: dt.datetime | None) -> dt.datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("professional observation must be timezone-aware")
        return value


class CapacityAssessment(_ClosedModel):
    capacity: RecipientCapacity
    reasons: tuple[str, ...]
    classifier_version: str = CLASSIFIER_VERSION
    professional_source_url: str | None = None
    professional_source_type: str | None = None
    professional_evidence_observed_at: dt.datetime | None = None
    evidence_expires_at: dt.datetime | None = None
    role: str | None = None
    company_id: str | None = None


def classify_recipient(
    value: ProfessionalEvidenceInput,
    *,
    config: AcquisitionProgramConfig,
    at: dt.datetime,
) -> CapacityAssessment:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("classification time must be timezone-aware")
    try:
        domain = normalize_domain(validate_email(value.email, check_deliverability=False).domain)
    except EmailNotValidError as error:
        raise ValueError("recipient email is invalid") from error
    source_complete = all(
        (
            value.professional_source_url,
            value.professional_source_type,
            value.professional_evidence_observed_at,
        )
    )
    expires_at = (
        value.professional_evidence_observed_at
        + dt.timedelta(days=config.professional_evidence_ttl_days)
        if value.professional_evidence_observed_at is not None
        else None
    )
    source_fresh = (
        source_complete
        and value.professional_evidence_observed_at is not None
        and value.professional_evidence_observed_at <= at
        and expires_at is not None
        and at < expires_at
    )
    role_allowed = value.role in config.target_roles
    company_confirmed = value.company_active and bool(value.company_id)
    is_consumer = domain in {"gmail.com", "googlemail.com"}
    reasons: tuple[str, ...]
    if value.is_minor or value.is_private_individual:
        capacity, reasons = RecipientCapacity.PERSONAL, ("PERSONAL_OR_MINOR",)
    elif is_consumer and not (
        source_fresh and value.email_explicitly_published and role_allowed and company_confirmed
    ):
        capacity, reasons = RecipientCapacity.PERSONAL, ("GMAIL_PROFESSIONAL_SOURCE_MISSING",)
    elif not value.email_verified:
        capacity, reasons = RecipientCapacity.UNKNOWN, ("EMAIL_NOT_VERIFIED",)
    elif not role_allowed or not company_confirmed:
        capacity, reasons = RecipientCapacity.UNKNOWN, ("PROFESSIONAL_ROLE_OR_COMPANY_MISSING",)
    elif is_consumer:
        capacity, reasons = (
            RecipientCapacity.CONFIRMED_PROFESSIONAL,
            ("GMAIL_PROFESSIONALLY_PUBLISHED",),
        )
    elif value.company_domain and normalize_domain(value.company_domain) == domain and source_fresh:
        capacity, reasons = (
            RecipientCapacity.CONFIRMED_PROFESSIONAL,
            ("COMPANY_DOMAIN_AND_SOURCE_VERIFIED",),
        )
    elif (
        value.company_domain
        and normalize_domain(value.company_domain) == domain
        and source_complete
    ):
        capacity, reasons = RecipientCapacity.LIKELY_PROFESSIONAL, ("PROFESSIONAL_SOURCE_EXPIRED",)
    elif value.company_domain and normalize_domain(value.company_domain) == domain:
        capacity, reasons = RecipientCapacity.LIKELY_PROFESSIONAL, ("PROFESSIONAL_SOURCE_MISSING",)
    else:
        capacity, reasons = RecipientCapacity.UNKNOWN, ("EMAIL_COMPANY_DOMAIN_MISMATCH",)
    return CapacityAssessment(
        capacity=capacity,
        reasons=reasons,
        professional_source_url=value.professional_source_url,
        professional_source_type=value.professional_source_type,
        professional_evidence_observed_at=value.professional_evidence_observed_at,
        evidence_expires_at=expires_at,
        role=value.role,
        company_id=value.company_id,
    )


class FitSignals(_ClosedModel):
    provider: MailProvider
    provider_confirmed: bool = False
    sector: str | None = None
    role: str | None = None
    employee_count: int | None = Field(default=None, ge=0)
    employee_count_range: tuple[int, int] | None = None
    recent_public_activity_source: str | None = None
    public_contact_channel_sources: tuple[str, ...] = Field(default=(), max_length=16)
    operational_decision_maker: bool = False


class FitAssessment(_ClosedModel):
    total: int = Field(ge=0, le=100)
    breakdown: dict[str, int]
    missing_reasons: tuple[str, ...]
    tier: str
    mail_pain_score: int = Field(ge=0, le=100)
    score_version: str


def score_fit(value: FitSignals, *, config: AcquisitionProgramConfig) -> FitAssessment:
    facts = {
        "google_workspace": value.provider is MailProvider.GOOGLE_WORKSPACE
        and value.provider_confirmed,
        "email_dependent_sector": value.sector in config.target_sectors,
        "decision_maker": value.role in config.target_roles,
        "company_size": (
            value.employee_count is not None and
            config.target_company_size_min <= value.employee_count <= config.target_company_size_max
        ) or (
            value.employee_count_range is not None and
            config.target_company_size_min <= value.employee_count_range[0] <=
            value.employee_count_range[1] <= config.target_company_size_max
        ),
        "recent_public_activity": bool(value.recent_public_activity_source),
    }
    breakdown = {
        key: config.score_weights[key] if satisfied else 0 for key, satisfied in facts.items()
    }
    total = sum(breakdown.values())
    tier = (
        "candidate_for_policy_review"
        if total >= config.send_review_threshold
        else "HOLD"
        if total >= config.hold_threshold
        else "NO_SEND"
    )
    reason_names = {
        "google_workspace": "GOOGLE_WORKSPACE_MISSING",
        "email_dependent_sector": "EMAIL_DEPENDENT_SECTOR_MISSING",
        "decision_maker": "DECISION_MAKER_MISSING",
        "company_size": "COMPANY_SIZE_MISSING_OR_EXCLUDED",
        "recent_public_activity": "RECENT_PUBLIC_ACTIVITY_MISSING",
    }
    pain_facts = {
        "service_sector": facts["email_dependent_sector"],
        "operational_decision_maker": value.operational_decision_maker,
        "public_contact_channels": bool(value.public_contact_channel_sources),
        "recent_public_activity": facts["recent_public_activity"],
    }
    pain = sum(config.mail_pain_weights[key] for key, satisfied in pain_facts.items() if satisfied)
    return FitAssessment(
        total=total,
        breakdown=breakdown,
        missing_reasons=tuple(
            reason_names[key] for key, satisfied in facts.items() if not satisfied
        ),
        tier=tier,
        mail_pain_score=pain,
        score_version=config.score_version,
    )


__all__ = [
    "CapacityAssessment",
    "FitAssessment",
    "FitSignals",
    "ProfessionalEvidenceInput",
    "RecipientCapacity",
    "classify_recipient",
    "score_fit",
]
