"""Versioned, bounded configuration and audit contracts for acquisition programs."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ProgramMessageConfig(_ClosedModel):
    locale: Literal["fr-FR"]
    subject: str = Field(min_length=1, max_length=90)
    initial_body: str = Field(min_length=1, max_length=1200)
    follow_up_body: str = Field(min_length=1, max_length=800)
    cta_text: str = Field(min_length=1, max_length=150)
    sender_identity: str = Field(min_length=1, max_length=200)
    source_notice: str = Field(min_length=1, max_length=300)
    follow_up_delay_days: int = Field(ge=1, le=14)
    max_steps: Literal[2] = 2

    @model_validator(mode="after")
    def reviewed_copy(self) -> ProgramMessageConfig:
        text = f"{self.initial_body} {self.follow_up_body}".casefold()
        if any(
            value in text
            for value in (
                "nous avons analysé votre boîte",
                "votre boîte est désorganisée",
                "votre boîte",
                "vos e-mails",
                "vos messages",
                "milo a analysé votre boîte",
                "milo pro est disponible",
                "milo agent est disponible",
            )
        ):
            raise ValueError("message makes an unsupported or unavailable-plan claim")
        if any(token in text for token in ("{{", "}}", "{%", "%}")):
            raise ValueError("provider interpolation is forbidden in reviewed copy")
        return self


class AcquisitionProgramConfig(_ClosedModel):
    schema_version: Literal["acquisition-program-v1"] = "acquisition-program-v1"
    program_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    brand: str = Field(min_length=1, max_length=100)
    product_name: str = Field(min_length=1, max_length=100)
    offer_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    available_plan: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    coming_soon_plans: tuple[str, ...] = Field(max_length=8)
    target_country: str = Field(pattern=r"^[A-Z]{2}$")
    target_locale: str = Field(pattern=r"^[a-z]{2}-[A-Z]{2}$")
    target_company_size_min: int = Field(ge=1, le=100_000)
    target_company_size_max: int = Field(ge=1, le=100_000)
    target_roles: tuple[str, ...] = Field(min_length=1, max_length=32)
    role_terms: dict[str, tuple[str, ...]]
    target_sectors: tuple[str, ...] = Field(min_length=1, max_length=32)
    sector_terms: dict[str, tuple[str, ...]]
    apollo_organization_keywords: tuple[str, ...] = Field(min_length=1, max_length=32)
    apollo_person_titles: tuple[str, ...] = Field(min_length=1, max_length=32)
    apollo_person_seniorities: tuple[str, ...] = Field(min_length=1, max_length=16)
    apollo_max_pages: int = Field(default=1, ge=1, le=5)
    apollo_per_page: int = Field(default=25, ge=1, le=100)
    allowed_mail_providers: tuple[str, ...] = Field(min_length=1, max_length=8)
    campaign_mode: Literal["SHADOW", "ASSISTED_REVIEW", "AUTONOMOUS_CAPPED", "LIVE"] = "SHADOW"
    enabled: bool = False
    policy_version: str = Field(min_length=1, max_length=64)
    score_version: str = Field(min_length=1, max_length=64)
    template_version: str = Field(min_length=1, max_length=64)
    messages: ProgramMessageConfig
    max_daily_contacts: int = Field(default=0, ge=0)
    max_monthly_contacts: int = Field(default=0, ge=0)
    max_cost_chf: Decimal = Field(default=Decimal("0"), ge=0)
    target_cost_chf_per_contact_min: Decimal = Field(default=Decimal("0.10"), ge=0)
    target_cost_chf_per_contact_max: Decimal = Field(default=Decimal("0.20"), ge=0)
    bounce_alert_threshold: Decimal = Field(default=Decimal("0.02"), ge=0, le=1)
    complaint_alert_threshold: Decimal = Field(default=Decimal("0.001"), ge=0, le=1)
    unknown_provider_alert_threshold: Decimal = Field(default=Decimal("0.25"), ge=0, le=1)
    score_weights: dict[str, int]
    mail_pain_weights: dict[str, int] = Field(
        default_factory=lambda: {
            "service_sector": 30,
            "operational_decision_maker": 25,
            "public_contact_channels": 20,
            "recent_public_activity": 25,
        }
    )
    send_review_threshold: int = Field(default=80, ge=0, le=100)
    hold_threshold: int = Field(default=65, ge=0, le=100)
    mx_cache_ttl_seconds: int = Field(default=86_400, ge=60, le=604_800)
    professional_evidence_ttl_days: int = Field(default=180, ge=1, le=365)
    dns_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    dns_attempts: int = Field(default=2, ge=1, le=3)
    sender_configuration_ref: str | None = Field(default=None, max_length=256)
    sender_legal_name: str | None = Field(default=None, max_length=200)
    sender_postal_address: str | None = Field(default=None, max_length=300)
    sender_domains: tuple[str, ...] = Field(default=(), max_length=16)
    transactional_domain: str | None = Field(default=None, max_length=253)
    instantly_workspace_ref: str | None = Field(default=None, max_length=128)
    landing_url: str | None = Field(default=None, max_length=2048)
    privacy_url: str | None = Field(default=None, max_length=2048)
    opt_out_url: str | None = Field(default=None, max_length=2048)

    @field_validator("landing_url", "privacy_url", "opt_out_url")
    @classmethod
    def https_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or parsed.query
            or parsed.port not in (None, 443)
        ):
            raise ValueError("program URLs require HTTPS without credentials or fragment")
        from signals.acquisition_programs.mail_provider import normalize_domain

        normalize_domain(parsed.hostname)
        return value

    @field_validator("sender_domains", "transactional_domain")
    @classmethod
    def valid_domain(cls, value: tuple[str, ...] | str | None):
        if value is None:
            return None
        domains = value if isinstance(value, tuple) else (value,)
        for domain in domains:
            if not re.fullmatch(
                r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
                r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?",
                domain,
            ):
                raise ValueError("invalid program sender domain")
        return value

    @model_validator(mode="after")
    def coherent(self) -> AcquisitionProgramConfig:
        if self.target_company_size_max < self.target_company_size_min:
            raise ValueError("company size bounds are reversed")
        if set(self.role_terms) != set(self.target_roles) or any(
            not terms for terms in self.role_terms.values()
        ):
            raise ValueError("role terms must cover every target role")
        if set(self.sector_terms) != set(self.target_sectors) or any(
            not terms for terms in self.sector_terms.values()
        ):
            raise ValueError("sector terms must cover every target sector")
        if self.hold_threshold >= self.send_review_threshold:
            raise ValueError("score thresholds are reversed")
        if (
            set(self.score_weights)
            != {
                "google_workspace",
                "email_dependent_sector",
                "decision_maker",
                "company_size",
                "recent_public_activity",
            }
            or sum(self.score_weights.values()) != 100
            or any(value < 0 for value in self.score_weights.values())
        ):
            raise ValueError("score weights must define five nonnegative factors totaling 100")
        if (
            set(self.mail_pain_weights)
            != {
                "service_sector",
                "operational_decision_maker",
                "public_contact_channels",
                "recent_public_activity",
            }
            or sum(self.mail_pain_weights.values()) != 100
            or any(value < 0 for value in self.mail_pain_weights.values())
        ):
            raise ValueError("mail pain weights must define four public factors totaling 100")
        if self.target_cost_chf_per_contact_min > self.target_cost_chf_per_contact_max:
            raise ValueError("target cost interval is reversed")
        if self.transactional_domain and any(
            domain == self.transactional_domain or domain.endswith("." + self.transactional_domain)
            for domain in self.sender_domains
        ):
            raise ValueError("sender domain overlaps transactional domain")
        if len(set(self.sender_domains)) != len(self.sender_domains):
            raise ValueError("duplicate sender domain")
        if self.apollo_max_pages * self.apollo_per_page > 500:
            raise ValueError("Apollo candidate cap exceeded")
        if self.messages.locale != self.target_locale:
            raise ValueError("message locale must match target locale")
        return self


class ProgramRuntimeFlags(_ClosedModel):
    enabled: bool = False
    mode: Literal["SHADOW"] = "SHADOW"
    allowed_countries: tuple[str, ...] = ("FR",)
    allowed_providers: tuple[str, ...] = ("GOOGLE_WORKSPACE",)
    max_daily_contacts: int = Field(default=0, ge=0)
    max_monthly_contacts: int = Field(default=0, ge=0)
    max_cost_chf: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def reviewed_allowlists(self) -> ProgramRuntimeFlags:
        if set(self.allowed_countries) - {"FR"}:
            raise ValueError("country has no reviewed Milo Mail policy")
        if set(self.allowed_providers) - {"GOOGLE_WORKSPACE"}:
            raise ValueError("provider has no reviewed Milo Mail policy")
        return self


__all__ = ["AcquisitionProgramConfig", "ProgramMessageConfig", "ProgramRuntimeFlags"]
