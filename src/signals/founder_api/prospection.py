"""Read-only projections for the Founder Console Prospection page."""

from __future__ import annotations

import datetime as dt
import math
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Literal

import sqlalchemy as sa
from pydantic import Field, field_validator
from sqlalchemy.engine import Engine

from signals.founder_api.contracts import FounderContract
from signals.persistence.schema import supplier_directory

FOUNDER_PROSPECTION_VERSION = "founder-prospection-v1"
ACQUISITION_TIMER_UNIT = "kivou-acquisition-production.timer"


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


class FounderDirectoryStatus(StrEnum):
    CONFIRMED_DOMAIN = "confirmed_domain"
    WITHOUT_WEBSITE = "without_website"
    REVERIFICATION_REQUIRED = "reverification_required"


class FounderAcquisitionTimer(FounderContract):
    state: Literal["RUNNING", "STOPPED", "UNKNOWN"]
    unit: Literal["kivou-acquisition-production.timer"] = ACQUISITION_TIMER_UNIT
    inactive_since: dt.datetime | None = None
    last_triggered_at: dt.datetime | None = None
    next_trigger_at: dt.datetime | None = None

    _times = field_validator(
        "inactive_since", "last_triggered_at", "next_trigger_at"
    )(lambda value: _aware(value) if value is not None else None)


class FounderCountFacet(FounderContract):
    key: str
    count: int = Field(ge=0)


class FounderDirectorySummary(FounderContract):
    company_count: int = Field(ge=0)
    confirmed_domain_count: int = Field(ge=0)
    verified_email_count: int = Field(ge=0)
    reverification_required_count: int = Field(ge=0)


class FounderDirectoryRow(FounderContract):
    siren: str
    legal_name: str
    family_keys: tuple[str, ...]
    department: str | None = None
    city: str | None = None
    employees: int | None = Field(default=None, ge=0)
    domain: str | None = None
    website_url: str | None = None
    confirmed_domain: bool
    professional_email: str | None = None
    email_source: str | None = None
    email_verification_status: str | None = None
    email_contact_name: str | None = None
    email_contact_title: str | None = None
    reverification_required_at: dt.datetime | None = None
    reverification_reason: str | None = None
    updated_at: dt.datetime

    _times = field_validator("reverification_required_at", "updated_at")(
        lambda value: _aware(value) if value is not None else None
    )


class FounderDirectoryPagination(FounderContract):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=1)


class FounderSupplierDirectory(FounderContract):
    summary: FounderDirectorySummary
    family_counts: tuple[FounderCountFacet, ...]
    department_counts: tuple[FounderCountFacet, ...]
    rows: tuple[FounderDirectoryRow, ...]
    pagination: FounderDirectoryPagination


class FounderQueueItem(FounderContract):
    target_ref: str
    status: Literal["pending_review"] = "pending_review"
    company_name: str
    city: str | None = None
    employees: int | None = Field(default=None, ge=0)
    family_key: str
    director_name: str | None = None
    director_title: str | None = None
    email_address: str
    email_source: Literal["apollo", "site", "manual"]
    email_verification_status: str
    bait_holder: str
    bait_subject: str
    bait_amount_minor_units: int | None = Field(default=None, ge=0)
    bait_currency: str | None = None
    mail_subject: str
    mail_body: str


class FounderProspectionQueue(FounderContract):
    available: bool
    last_cycle_at: dt.datetime | None = None
    items: tuple[FounderQueueItem, ...]

    _last_cycle_at = field_validator("last_cycle_at")(
        lambda value: _aware(value) if value is not None else None
    )


class FounderTargetingSignal(FounderContract):
    title: str | None = None
    amount_minor_units: int | None = None
    currency: str | None = None


class FounderRoleLevelCount(FounderContract):
    level: int = Field(ge=1, le=4)
    count: int = Field(ge=0)


class FounderDeviationCount(FounderContract):
    reason_code: str
    count: int = Field(ge=0)


class FounderTargetingCycle(FounderContract):
    cycle_ref: str
    status: str
    started_at: dt.datetime
    updated_at: dt.datetime
    completed_at: dt.datetime | None = None
    recent: bool
    signal: FounderTargetingSignal
    family_keys: tuple[str, ...]
    sirene_account_count: int = Field(ge=0)
    confirmed_domain_count: int = Field(ge=0)
    email_counts_by_level: tuple[FounderRoleLevelCount, ...]
    deviation_counts: tuple[FounderDeviationCount, ...]

    _times = field_validator("started_at", "updated_at", "completed_at")(
        lambda value: _aware(value) if value is not None else None
    )


class FounderMoneyTotal(FounderContract):
    currency: str
    minor_units: int


class FounderProspectionResults(FounderContract):
    sent_count: int = Field(ge=0)
    opened_count: int = Field(ge=0)
    attribution_click_count: int = Field(ge=0)
    landing_count: int = Field(ge=0)
    confirmed_profile_count: int = Field(ge=0)
    paid_account_count: int = Field(ge=0)
    mrr_by_currency: tuple[FounderMoneyTotal, ...]
    no_sends_yet: bool


class FounderProspection(FounderContract):
    version: Literal["founder-prospection-v1"] = FOUNDER_PROSPECTION_VERSION
    generated_at: dt.datetime
    read_only: Literal[True] = True
    timer: FounderAcquisitionTimer
    queue: FounderProspectionQueue
    directory: FounderSupplierDirectory
    targeting: FounderTargetingCycle | None
    results: FounderProspectionResults

    _generated_at = field_validator("generated_at")(_aware)


TimerReader = Callable[[dt.datetime], FounderAcquisitionTimer]


class FounderProspectionReadService:
    def __init__(
        self,
        engine: Engine,
        *,
        timer_reader: TimerReader | None = None,
    ) -> None:
        self._engine = engine
        self._timer_reader = timer_reader or _unknown_timer

    def read(
        self,
        *,
        now: dt.datetime,
        page: int = 1,
        page_size: int = 25,
        q: str | None = None,
        family: str | None = None,
        department: str | None = None,
        directory_status: FounderDirectoryStatus | None = None,
    ) -> FounderProspection:
        now = _aware(now)
        if page < 1:
            raise ValueError("page must be positive")
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        directory = self._directory(
            page=page,
            page_size=page_size,
            q=q,
            family=family,
            department=department,
            directory_status=directory_status,
        )
        return FounderProspection(
            generated_at=now,
            timer=self._timer_reader(now),
            queue=FounderProspectionQueue(
                available=False,
                last_cycle_at=None,
                items=(),
            ),
            directory=directory,
            targeting=None,
            results=FounderProspectionResults(
                sent_count=0,
                opened_count=0,
                attribution_click_count=0,
                landing_count=0,
                confirmed_profile_count=0,
                paid_account_count=0,
                mrr_by_currency=(),
                no_sends_yet=True,
            ),
        )

    def _directory(
        self,
        *,
        page: int,
        page_size: int,
        q: str | None,
        family: str | None,
        department: str | None,
        directory_status: FounderDirectoryStatus | None,
    ) -> FounderSupplierDirectory:
        with self._engine.connect() as connection:
            records = tuple(
                connection.execute(
                    sa.select(supplier_directory).where(
                        supplier_directory.c.suppressed_at.is_(None)
                    )
                ).mappings()
            )
        rows = tuple(sorted((_directory_row(row) for row in records), key=_directory_sort_key))
        summary = FounderDirectorySummary(
            company_count=len(rows),
            confirmed_domain_count=sum(row.confirmed_domain for row in rows),
            verified_email_count=sum(
                row.professional_email is not None
                and row.email_verification_status is not None
                for row in rows
            ),
            reverification_required_count=sum(
                row.reverification_required_at is not None for row in rows
            ),
        )
        family_counts = Counter(key for row in rows for key in row.family_keys)
        department_counts = Counter(
            row.department for row in rows if row.department is not None
        )
        filtered = tuple(
            row
            for row in rows
            if _directory_matches(
                row,
                q=q,
                family=family,
                department=department,
                directory_status=directory_status,
            )
        )
        start = (page - 1) * page_size
        return FounderSupplierDirectory(
            summary=summary,
            family_counts=_facets(family_counts),
            department_counts=_facets(department_counts),
            rows=filtered[start : start + page_size],
            pagination=FounderDirectoryPagination(
                page=page,
                page_size=page_size,
                total_items=len(filtered),
                total_pages=max(1, math.ceil(len(filtered) / page_size)),
            ),
        )


def _directory_row(row: Mapping[str, object]) -> FounderDirectoryRow:
    family_keys = row["family_keys"]
    return FounderDirectoryRow(
        siren=str(row["siren"]),
        legal_name=str(row["legal_name"]),
        family_keys=tuple(str(key) for key in family_keys or ()),  # type: ignore[union-attr]
        department=str(row["department"]) if row["department"] is not None else None,
        city=str(row["city"]) if row["city"] is not None else None,
        employees=int(row["employees"]) if row["employees"] is not None else None,
        domain=str(row["domain"]) if row["domain"] is not None else None,
        website_url=(
            str(row["website_url"]) if row["website_url"] is not None else None
        ),
        confirmed_domain=(
            row["domain"] is not None and row["domain_validation_method"] is not None
        ),
        professional_email=(
            str(row["professional_email"])
            if row["professional_email"] is not None
            else None
        ),
        email_source=(
            str(row["email_source"]) if row["email_source"] is not None else None
        ),
        email_verification_status=(
            str(row["email_verification_status"])
            if row["email_verification_status"] is not None
            else None
        ),
        email_contact_name=(
            str(row["email_contact_name"])
            if row["email_contact_name"] is not None
            else None
        ),
        email_contact_title=(
            str(row["email_contact_title"])
            if row["email_contact_title"] is not None
            else None
        ),
        reverification_required_at=row["reverification_required_at"],  # type: ignore[arg-type]
        reverification_reason=(
            str(row["reverification_reason"])
            if row["reverification_reason"] is not None
            else None
        ),
        updated_at=row["updated_at"],  # type: ignore[arg-type]
    )


def _directory_matches(
    row: FounderDirectoryRow,
    *,
    q: str | None,
    family: str | None,
    department: str | None,
    directory_status: FounderDirectoryStatus | None,
) -> bool:
    if q and _searchable(q) not in _searchable(row.legal_name):
        return False
    if family and family not in row.family_keys:
        return False
    if department and row.department != department:
        return False
    if directory_status is FounderDirectoryStatus.CONFIRMED_DOMAIN:
        return row.confirmed_domain
    if directory_status is FounderDirectoryStatus.WITHOUT_WEBSITE:
        return row.domain is None and row.website_url is None
    if directory_status is FounderDirectoryStatus.REVERIFICATION_REQUIRED:
        return row.reverification_required_at is not None
    return True


def _facets(counts: Counter[str]) -> tuple[FounderCountFacet, ...]:
    return tuple(
        FounderCountFacet(key=key, count=count)
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )


def _directory_sort_key(row: FounderDirectoryRow) -> tuple[str, str]:
    return (_searchable(row.legal_name), row.siren)


def _searchable(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.strip().casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _unknown_timer(_: dt.datetime) -> FounderAcquisitionTimer:
    return FounderAcquisitionTimer(state="UNKNOWN")


__all__ = [
    "ACQUISITION_TIMER_UNIT",
    "FOUNDER_PROSPECTION_VERSION",
    "FounderAcquisitionTimer",
    "FounderDirectoryStatus",
    "FounderProspection",
    "FounderProspectionReadService",
]
