"""Closed contracts exposed by the SaaS company-profile boundary."""

from __future__ import annotations

import datetime as dt
import ipaddress
from decimal import Decimal
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
)

MAX_OFFICIAL_IDENTIFIERS = 16
MAX_RELATED_SIGNALS = 100
MAX_NEEDS_PER_SIGNAL = 16
MAX_FIT_REASONS = 16
MAX_UNAVAILABLE_FIELDS = 16
MAX_ENRICHMENT_MISSING_FIELDS = 16

CompanyKey = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=16,
        max_length=64,
        pattern=r"^cmp_[A-Za-z0-9_-]+$",
    ),
]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4_000)]
CountryCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=2, max_length=2, to_upper=True),
]


class CompanyContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def safe_https_url(value: str | None) -> str | None:
    """Return a browser-safe public HTTPS URL, or reject the value."""
    if value is None:
        return None
    parsed = urlsplit(value)
    hostname = parsed.hostname
    normalized_hostname = (hostname or "").rstrip(".").casefold()
    try:
        is_ip_literal = bool(hostname) and ipaddress.ip_address(hostname) is not None
    except ValueError:
        is_ip_literal = False
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or normalized_hostname == "localhost"
        or normalized_hostname.endswith((".localhost", ".local", ".internal"))
        or is_ip_literal
        or "." not in hostname
    ):
        raise ValueError("website_url must be a public HTTPS URL without credentials")
    return value


def aware_datetime(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


def aware_optional_datetime(value: dt.datetime | None) -> dt.datetime | None:
    return None if value is None else aware_datetime(value)


class CompanyOfficialIdentifier(CompanyContract):
    scheme: ShortText
    value: ShortText


class CompanyOfficialIdentity(CompanyContract):
    name: ShortText
    country: CountryCode | None = None
    address: LongText | None = None
    identifiers: tuple[CompanyOfficialIdentifier, ...] = Field(
        default=(), max_length=MAX_OFFICIAL_IDENTIFIERS
    )
    website_url: Annotated[str, StringConstraints(max_length=2_048)] | None = None
    observed_at: dt.datetime
    source: Literal["public_notice", "official_register"] = "public_notice"

    _safe_website = field_validator("website_url")(safe_https_url)
    _aware_observation = field_validator("observed_at")(aware_datetime)


class WinnerEnrichmentSource(CompanyContract):
    kind: Literal["public_notice", "official_register"] = "public_notice"
    connector: ShortText
    notice_id: ShortText
    url: Annotated[str, StringConstraints(max_length=2_048)] | None = None
    retrieved_at: dt.datetime | None = None

    _safe_url = field_validator("url")(safe_https_url)
    _aware_retrieval = field_validator("retrieved_at")(aware_optional_datetime)


class WinnerEnrichmentView(CompanyContract):
    status: Literal["pending", "in_progress", "completed", "partial", "failed"]
    official_name: ShortText | None = None
    missing_fields: tuple[ShortText, ...] = Field(
        default=(), max_length=MAX_ENRICHMENT_MISSING_FIELDS
    )
    last_verified_at: dt.datetime | None = None
    error_code: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
        ]
        | None
    ) = None
    source: WinnerEnrichmentSource

    _aware_verification = field_validator("last_verified_at")(aware_optional_datetime)


class CompanySignalAmount(CompanyContract):
    value: Annotated[str, StringConstraints(pattern=r"^\d+(?:\.\d+)?$")]
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class CompanySignalEvent(CompanyContract):
    status: ShortText
    date: dt.date | None = None
    headline: LongText
    why_now: LongText
    award_date_note: LongText | None = None


class CompanyPlausibleNeed(CompanyContract):
    label: ShortText
    statement: LongText | None = None
    timing_label: ShortText | None = None
    reasoning: LongText | None = None


class CompanyFit(CompanyContract):
    label: ShortText
    reasons: tuple[ShortText, ...] = Field(default=(), max_length=MAX_FIT_REASONS)


class CompanyRelatedSignal(CompanyContract):
    signal_id: ShortText
    contract_title: LongText | None = None
    amount: CompanySignalAmount | None = None
    event: CompanySignalEvent
    plausible_needs: tuple[CompanyPlausibleNeed, ...] = Field(
        default=(), max_length=MAX_NEEDS_PER_SIGNAL
    )
    fit: CompanyFit


class CompanyCoverage(CompanyContract):
    related_signals_complete: bool
    unavailable_fields: tuple[ShortText, ...] = Field(default=(), max_length=MAX_UNAVAILABLE_FIELDS)


class CompanyContactLookupOrganization(CompanyContract):
    employees: int | None = Field(default=None, ge=0, exclude_if=lambda value: value is None)
    website_url: Annotated[str, StringConstraints(max_length=2_048)] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    phone: ShortText | None = Field(default=None, exclude_if=lambda value: value is None)
    linkedin_url: Annotated[str, StringConstraints(max_length=2_048)] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    _safe_website = field_validator("website_url")(safe_https_url)
    _safe_linkedin = field_validator("linkedin_url")(safe_https_url)


class CompanyDecisionMaker(CompanyContract):
    name: ShortText
    title: ShortText
    email: Annotated[EmailStr, Field(max_length=320)]
    email_status: Literal["verified"]
    linkedin_url: Annotated[str, StringConstraints(max_length=2_048)] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    _safe_linkedin = field_validator("linkedin_url")(safe_https_url)


class CompanyContactLookupView(CompanyContract):
    state: Literal[
        "locked",
        "available",
        "researching",
        "ready",
        "no_contact",
        "failed",
        "quota_exhausted",
        "identity_unavailable",
    ]
    remaining: int = Field(ge=0)
    monthly_quota: int = Field(ge=0)
    source: Literal["apollo"]
    removal_path: Literal["/contact"]
    researched_at: dt.datetime | None = Field(default=None, exclude_if=lambda value: value is None)
    refresh_after: dt.datetime | None = Field(default=None, exclude_if=lambda value: value is None)
    next_reset_at: dt.datetime | None = Field(default=None, exclude_if=lambda value: value is None)
    can_refresh: bool | None = Field(default=None, exclude_if=lambda value: value is None)
    organization: CompanyContactLookupOrganization | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    contacts: tuple[CompanyDecisionMaker, ...] | None = Field(
        default=None,
        max_length=3,
        exclude_if=lambda value: value is None,
    )

    _aware_researched = field_validator("researched_at")(aware_optional_datetime)
    _aware_refresh = field_validator("refresh_after")(aware_optional_datetime)
    _aware_reset = field_validator("next_reset_at")(aware_optional_datetime)


class DirectoryDirectorView(CompanyContract):
    name: ShortText
    title: ShortText | None = Field(default=None, exclude_if=lambda value: value is None)


class DirectoryCompanyView(CompanyContract):
    siren: Annotated[str, StringConstraints(pattern=r"^\d{9}$")]
    name: ShortText
    naf_code: ShortText | None = Field(default=None, exclude_if=lambda value: value is None)
    naf_label: ShortText | None = Field(default=None, exclude_if=lambda value: value is None)
    family_labels: tuple[ShortText, ...] | None = Field(
        default=None,
        max_length=32,
        exclude_if=lambda value: value is None,
    )
    department: ShortText | None = Field(default=None, exclude_if=lambda value: value is None)
    department_label: ShortText | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    city: ShortText | None = Field(default=None, exclude_if=lambda value: value is None)
    employees: int | None = Field(
        default=None, ge=0, exclude_if=lambda value: value is None
    )
    website_url: Annotated[str, StringConstraints(max_length=2_048)] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    website_source: ShortText | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    website_observed_at: dt.datetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    directors: tuple[DirectoryDirectorView, ...] | None = Field(
        default=None,
        max_length=100,
        exclude_if=lambda value: value is None,
    )
    directors_observed_at: dt.datetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    director_display_name: ShortText | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    director_display_title: ShortText | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    phone: ShortText | None = Field(default=None, exclude_if=lambda value: value is None)
    phone_source: ShortText | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    phone_observed_at: dt.datetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    published_email: Annotated[EmailStr, Field(max_length=320)] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    published_email_source_url: Annotated[
        str, StringConstraints(max_length=2_048)
    ] | None = Field(default=None, exclude_if=lambda value: value is None)
    published_email_observed_at: dt.datetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    contact_observed_at: dt.datetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    register_observed_at: dt.datetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    resolution_note: Literal["rapprochement par nom"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    source: Literal["registre"]
    removal_path: Literal["/contact"]

    _safe_website = field_validator("website_url")(safe_https_url)
    _safe_email_source = field_validator("published_email_source_url")(safe_https_url)


class CompanyMarketSummaryLastYear(CompanyContract):
    awards_count: int = Field(ge=0)
    total_amounts: tuple[CompanySignalAmount, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    recurring_buyers: tuple[ShortText, ...] | None = Field(
        default=None,
        max_length=2,
        exclude_if=lambda value: value is None,
    )


class CompanyMarketSummaryView(CompanyContract):
    first_award_at: dt.date | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    awards_per_quarter: Decimal | None = Field(
        default=None, ge=0, exclude_if=lambda value: value is None
    )
    median_amounts: tuple[CompanySignalAmount, ...] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    consortium_share: Decimal | None = Field(
        default=None, ge=0, le=1, exclude_if=lambda value: value is None
    )
    recurring_buyers: tuple[ShortText, ...] | None = Field(
        default=None,
        max_length=2,
        exclude_if=lambda value: value is None,
    )
    last_12_months: CompanyMarketSummaryLastYear
    resolution: Literal["company_key", "normalized_name_department"]
    resolution_note: Literal["rapprochement par nom"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    source: Literal["public_awards"]


class DirectoryPublicMarketView(CompanyContract):
    market_id: ShortText
    title: LongText | None = Field(default=None, exclude_if=lambda value: value is None)
    date: dt.date | None = Field(default=None, exclude_if=lambda value: value is None)
    amount: CompanySignalAmount | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    buyers: tuple[ShortText, ...] | None = Field(
        default=None, max_length=100, exclude_if=lambda value: value is None
    )
    source_url: Annotated[str, StringConstraints(max_length=2_048)] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    source: Literal["public_awards"]

    _safe_source_url = field_validator("source_url")(safe_https_url)


class DirectoryCompanyProfileView(CompanyContract):
    company_key: CompanyKey
    company_profile_v2_enabled: bool
    plan_code: Literal["discovery", "essential", "pro"]
    directory: DirectoryCompanyView
    market_summary: CompanyMarketSummaryView | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    markets: tuple[DirectoryPublicMarketView, ...] = Field(default=(), max_length=100)
    contact_status: Literal["to_contact", "contacted", "replied"] = "to_contact"
    contacted_at: dt.datetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    history: tuple[dict[str, Any], ...] = Field(default=(), max_length=500)
    note: str | None = Field(default=None, exclude_if=lambda value: value is None)
    contact_lookup: CompanyContactLookupView | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class CompanyProfile(CompanyContract):
    company_key: CompanyKey
    city: ShortText | None = None
    official_identity: CompanyOfficialIdentity
    related_signals: tuple[CompanyRelatedSignal, ...] = Field(
        min_length=1, max_length=MAX_RELATED_SIGNALS
    )
    coverage: CompanyCoverage
    #: PR1 §4 — le suivi commercial de CE compte sur cette entreprise.
    contact_status: Literal["to_contact", "contacted", "replied"] = "to_contact"
    contacted_at: dt.datetime | None = None
    note: str | None = None
    #: Chaque entrée est une carte complète du feed (`view.feed_item` + statut) ;
    #: `dict[str, Any]` parce que `CompanyContract` interdit les clés inconnues
    #: et qu'une carte de feed en porte plus qu'un contrat figé n'en admettrait.
    signals: tuple[dict[str, Any], ...] = Field(default=(), max_length=MAX_RELATED_SIGNALS)
    history: tuple[dict[str, Any], ...] = Field(default=(), max_length=500)
    market_summary: CompanyMarketSummaryView | None = None
    directory: DirectoryCompanyView | None = None
    contact_lookup: CompanyContactLookupView | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    company_profile_v2_enabled: bool = False
    plan_code: Literal["discovery", "essential", "pro"] = "discovery"

    _aware_contacted_at = field_validator("contacted_at")(aware_optional_datetime)
