"""Dated, independent company activity evidence for Milo Mail policy v2.

This module makes no network calls. Callers supply already observed public facts;
the policy decides whether those facts are current and mutually consistent.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping
from typing import Literal
from urllib.parse import urlsplit

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from signals.acquisition_programs.mail_provider import (
    MailProvider,
    MailProviderDetector,
    MailProviderEvidence,
    ProviderConfidence,
    normalize_domain,
)

ACTIVITY_EVIDENCE_VERSION: Literal["milomail-activity-v2"] = "milomail-activity-v2"
_OFFICIAL_REPLAY_TTL = dt.timedelta(days=7)
_LEADER_REPLAY_TTL = dt.timedelta(days=90)
_WEBSITE_REPLAY_TTL = dt.timedelta(days=7)


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class _DatedProof(_ClosedModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    observed_at: dt.datetime
    expires_at: dt.datetime

    @field_validator("observed_at", "expires_at")
    @classmethod
    def aware(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("activity evidence time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def positive_interval(self):
        if self.expires_at <= self.observed_at:
            raise ValueError("activity evidence expiry must follow observation")
        return self


def _public_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("activity evidence requires a public HTTPS URL")
    normalize_domain(parsed.hostname)
    return value


class OfficialActivityProof(_DatedProof):
    status: Literal["ACTIVE", "CEASED", "UNKNOWN"]
    source_type: Literal["ANNUAIRE_ENTREPRISES_SIRENE"]
    source_url: str

    _source_url = field_validator("source_url")(_public_url)


class LeaderAffiliationProof(_DatedProof):
    source_type: Literal["APOLLO_VERIFIED_BUSINESS_CONTACT"]
    company_domain: str
    email_domain: str
    role: str = Field(min_length=1, max_length=64)
    email_verified: bool = False

    @field_validator("company_domain", "email_domain")
    @classmethod
    def domain(cls, value: str) -> str:
        return normalize_domain(value)


class WebsiteIdentityProof(_DatedProof):
    source_url: str
    company_domain: str
    accessible: bool = False
    identity_matches: bool = False

    _source_url = field_validator("source_url")(_public_url)

    @field_validator("company_domain")
    @classmethod
    def domain(cls, value: str) -> str:
        return normalize_domain(value)


class ActivityEvidenceInput(_ClosedModel):
    version: Literal["milomail-activity-v2"] = ACTIVITY_EVIDENCE_VERSION
    company_domain: str
    official: OfficialActivityProof | None = None
    leader: LeaderAffiliationProof | None = None
    website: WebsiteIdentityProof | None = None
    contradictions: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("company_domain")
    @classmethod
    def domain(cls, value: str) -> str:
        return normalize_domain(value)


class ActivityAssessment(_ClosedModel):
    version: Literal["milomail-activity-v2"] = ACTIVITY_EVIDENCE_VERSION
    status: Literal["OFFICIAL_ACTIVE", "OPERATIONALLY_ACTIVE", "OFFICIAL_CEASED", "UNKNOWN"]
    reason_codes: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...]
    assessed_at: dt.datetime


def _fresh(proof: _DatedProof, *, at: dt.datetime, max_days: int) -> bool:
    return proof.observed_at <= at < proof.expires_at and at - proof.observed_at <= dt.timedelta(
        days=max_days
    )


def _time(value: object) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def activity_input_from_b0(
    b0_result: Mapping[str, object],
    candidate_snapshot: Mapping[str, object],
    *,
    role: str | None,
    website_proof: WebsiteIdentityProof | None = None,
) -> ActivityEvidenceInput:
    """Reconstruct only proofs present in persisted B0 snapshots, without I/O."""
    if website_proof is not None and not isinstance(website_proof, WebsiteIdentityProof):
        raise TypeError("website proof must use the validated evidence contract")
    candidate = candidate_snapshot.get("snapshot", candidate_snapshot)
    if not isinstance(candidate, Mapping):
        raise TypeError("B0 candidate snapshot is invalid")
    raw_domain = candidate.get("primary_domain")
    if not isinstance(raw_domain, str):
        raise TypeError("B0 candidate has no validated domain")
    domain = normalize_domain(raw_domain)
    organization_id = candidate.get("provider_organization_id")

    official = None
    website = None
    raw_official = b0_result.get("official")
    if (
        isinstance(raw_official, Mapping)
        and raw_official.get("match_confidence") == "CONFIRMED_MATCH"
    ):
        observed = _time(raw_official.get("observed_at"))
        legal_status = raw_official.get("legal_status")
        siren = raw_official.get("siren")
        matcher = raw_official.get("matcher_version")
        source_url = raw_official.get("source_reference")
        if (
            observed is not None
            and legal_status in {"ACTIVE", "CEASED", "UNKNOWN"}
            and isinstance(siren, str)
            and siren.isdigit()
            and len(siren) == 9
            and isinstance(matcher, str)
            and isinstance(source_url, str)
        ):
            try:
                official = OfficialActivityProof(
                    status=legal_status,
                    source_type="ANNUAIRE_ENTREPRISES_SIRENE",
                    source_url=source_url,
                    evidence_id=f"sirene:{siren}:{matcher}",
                    observed_at=observed,
                    expires_at=observed + _OFFICIAL_REPLAY_TTL,
                )
            except ValueError:
                official = None
        legal_url = raw_official.get("legal_page_source_url")
        legal_at = _time(raw_official.get("legal_page_observed_at"))
        if isinstance(legal_url, str) and legal_at is not None:
            try:
                website = WebsiteIdentityProof(
                    source_url=legal_url,
                    evidence_id=f"website:{hashlib.sha256(legal_url.encode()).hexdigest()}",
                    observed_at=legal_at,
                    expires_at=legal_at + _WEBSITE_REPLAY_TTL,
                    company_domain=domain,
                    accessible=True,
                    identity_matches=True,
                )
            except ValueError:
                website = None

    leader = None
    person = b0_result.get("person")
    if isinstance(person, Mapping) and isinstance(role, str):
        email = person.get("business_email")
        observed = _time(person.get("provider_observed_at"))
        fingerprint = person.get("source_fingerprint")
        if (
            isinstance(email, str)
            and email == b0_result.get("email")
            and person.get("provider_organization_id") == organization_id
            and person.get("provider_email_status") == "verified"
            and observed is not None
            and isinstance(fingerprint, str)
        ):
            try:
                email_domain = normalize_domain(
                    validate_email(email, check_deliverability=False).domain
                )
                leader = LeaderAffiliationProof(
                    source_type="APOLLO_VERIFIED_BUSINESS_CONTACT",
                    evidence_id=f"apollo-person:{fingerprint}",
                    observed_at=observed,
                    expires_at=observed + _LEADER_REPLAY_TTL,
                    company_domain=domain,
                    email_domain=email_domain,
                    role=role,
                    email_verified=True,
                )
            except (EmailNotValidError, ValueError):
                leader = None
    disputed_ceased = (
        isinstance(raw_official, Mapping)
        and raw_official.get("legal_status") == "CEASED"
        and official is None
    )
    return ActivityEvidenceInput(
        company_domain=domain,
        official=official,
        leader=leader,
        website=website_proof if website_proof is not None else website,
        contradictions=("OFFICIAL_CEASED_UNVERIFIED",) if disputed_ceased else (),
    )


def evaluate_activity_evidence(
    value: ActivityEvidenceInput,
    *,
    provider: MailProviderEvidence,
    allowed_roles: tuple[str, ...],
    at: dt.datetime,
) -> ActivityAssessment:
    """Official proof takes precedence; otherwise require three public origins."""
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("activity assessment time must be timezone-aware")
    reasons: list[str] = []
    evidence: list[str] = []
    official_gap: str | None = None
    official = value.official
    if official is not None:
        evidence.append(official.evidence_id)
        if official.status == "CEASED" and official.observed_at <= at:
            return ActivityAssessment(
                status="OFFICIAL_CEASED",
                reason_codes=("OFFICIAL_CEASED",),
                evidence_ids=(official.evidence_id,),
                assessed_at=at,
            )
        if not _fresh(official, at=at, max_days=30):
            official_gap = "OFFICIAL_ACTIVITY_EVIDENCE_EXPIRED"
            if official.status == "CEASED":
                reasons.append("OFFICIAL_CEASED_EVIDENCE_FROM_FUTURE")
        elif official.status == "ACTIVE":
            if value.contradictions:
                reasons.append("ACTIVITY_CONTRADICTION")
            else:
                return ActivityAssessment(
                    status="OFFICIAL_ACTIVE",
                    reason_codes=("OFFICIAL_ACTIVE_PROOF",),
                    evidence_ids=(official.evidence_id,),
                    assessed_at=at,
                )
        else:
            official_gap = "OFFICIAL_ACTIVITY_UNKNOWN"

    if value.contradictions:
        reasons.append("ACTIVITY_CONTRADICTION")
    if (
        provider.domain != value.company_domain
        or provider.provider is not MailProvider.GOOGLE_WORKSPACE
        or provider.confidence is not ProviderConfidence.CONFIRMED
        or provider.source != "DNS_MX"
        or MailProviderDetector._classify(provider.mx_records) is not MailProvider.GOOGLE_WORKSPACE
        or provider.observed_at > at
        or provider.expires_at <= at
    ):
        reasons.append("CURRENT_GOOGLE_WORKSPACE_MX_MISSING")

    leader = value.leader
    if leader is None:
        reasons.append("LEADER_AFFILIATION_MISSING")
    else:
        evidence.append(leader.evidence_id)
        if not _fresh(leader, at=at, max_days=180):
            reasons.append("LEADER_AFFILIATION_EXPIRED")
        if (
            not leader.email_verified
            or leader.company_domain != value.company_domain
            or leader.email_domain != value.company_domain
            or leader.role not in allowed_roles
        ):
            reasons.append("LEADER_DOMAIN_MISMATCH")

    website = value.website
    if website is None:
        reasons.append("WEBSITE_IDENTITY_MISSING")
    else:
        evidence.append(website.evidence_id)
        host = normalize_domain(urlsplit(website.source_url).hostname or "")
        if not _fresh(website, at=at, max_days=30):
            reasons.append("WEBSITE_IDENTITY_EXPIRED")
        if (
            not website.accessible
            or not website.identity_matches
            or website.company_domain != value.company_domain
            or host not in {value.company_domain, f"www.{value.company_domain}"}
        ):
            reasons.append("WEBSITE_IDENTITY_UNCONFIRMED")

    if len(set(evidence)) != len(evidence):
        reasons.append("ACTIVITY_SOURCES_NOT_INDEPENDENT")
    if reasons:
        if official_gap is not None:
            reasons.append(official_gap)
        return ActivityAssessment(
            status="UNKNOWN",
            reason_codes=tuple(dict.fromkeys(reasons)),
            evidence_ids=tuple(dict.fromkeys(evidence)),
            assessed_at=at,
        )
    return ActivityAssessment(
        status="OPERATIONALLY_ACTIVE",
        reason_codes=("OPERATIONAL_ACTIVITY_CORROBORATED",),
        evidence_ids=tuple(evidence),
        assessed_at=at,
    )


__all__ = [
    "ACTIVITY_EVIDENCE_VERSION",
    "ActivityAssessment",
    "ActivityEvidenceInput",
    "LeaderAffiliationProof",
    "OfficialActivityProof",
    "WebsiteIdentityProof",
    "activity_input_from_b0",
    "evaluate_activity_evidence",
]
