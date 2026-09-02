"""Closed contracts exposed by the SaaS company-profile boundary."""

from __future__ import annotations

import datetime as dt
import ipaddress
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

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
    error_code: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ] | None = None
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
    unavailable_fields: tuple[ShortText, ...] = Field(
        default=(), max_length=MAX_UNAVAILABLE_FIELDS
    )


class CompanyProfile(CompanyContract):
    company_key: CompanyKey
    official_identity: CompanyOfficialIdentity
    related_signals: tuple[CompanyRelatedSignal, ...] = Field(
        min_length=1, max_length=MAX_RELATED_SIGNALS
    )
    coverage: CompanyCoverage
