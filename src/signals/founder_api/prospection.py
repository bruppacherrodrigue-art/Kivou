"""Read-only projections for the Founder Console Prospection page."""

from __future__ import annotations

import datetime as dt
import math
import unicodedata
from collections import Counter
from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Literal

import sqlalchemy as sa
from pydantic import Field, field_validator
from sqlalchemy.engine import Engine

from signals.accounts.schema import account_landing_signal
from signals.domain.french_departments import DEPARTMENTS
from signals.founder_api.acquisition_status import FounderAcquisitionStatus
from signals.founder_api.contracts import FounderContract
from signals.persistence.schema import (
    acquisition_campaign_member,
    acquisition_contact,
    acquisition_conversion_event,
    acquisition_opportunity,
    acquisition_provider_event,
    acquisition_runtime_cycle,
    acquisition_runtime_stage,
    acquisition_supplier,
    contact_discovery_run,
    contract_award,
    opportunity_representation,
    prospect_target,
    supplier_directory,
    supplier_discovery_run,
)

FOUNDER_PROSPECTION_VERSION = "founder-prospection-v1"


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


class FounderDirectoryStatus(StrEnum):
    CONFIRMED_DOMAIN = "confirmed_domain"
    WITHOUT_WEBSITE = "without_website"
    REVERIFICATION_REQUIRED = "reverification_required"


class FounderDirectoryQualificationStatus(StrEnum):
    CONFIRMED_DOMAIN = "confirmed_domain"
    WITHOUT_WEBSITE = "without_website"
    REVERIFICATION_REQUIRED = "reverification_required"
    TO_QUALIFY = "to_qualify"


class FounderCountFacet(FounderContract):
    key: str
    label: str
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
    department_name: str | None = None
    city: str | None = None
    employees: int | None = Field(default=None, ge=0)
    domain: str | None = None
    website_url: str | None = None
    confirmed_domain: bool
    qualification_status: FounderDirectoryQualificationStatus
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
    acquisition_status: FounderAcquisitionStatus
    queue: FounderProspectionQueue
    directory: FounderSupplierDirectory
    targeting: FounderTargetingCycle | None
    results: FounderProspectionResults

    _generated_at = field_validator("generated_at")(_aware)


class FounderProspectionReadService:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def read(
        self,
        *,
        now: dt.datetime,
        acquisition_status: FounderAcquisitionStatus,
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
        targeting = self._targeting(now=now)
        results = self._results()
        return FounderProspection(
            generated_at=now,
            acquisition_status=acquisition_status,
            queue=self._queue(
                last_cycle_at=targeting.updated_at if targeting is not None else None,
            ),
            directory=directory,
            targeting=targeting,
            results=results,
        )

    def _queue(self, *, last_cycle_at: dt.datetime | None) -> FounderProspectionQueue:
        with self._engine.connect() as connection:
            rows = tuple(
                connection.execute(
                    sa.select(prospect_target)
                    .where(prospect_target.c.status == "pending_review")
                    .order_by(
                        prospect_target.c.created_at.desc(),
                        prospect_target.c.target_id,
                    )
                    .limit(25)
                ).mappings()
            )
            if last_cycle_at is None:
                last_cycle_at = connection.scalar(
                    sa.select(sa.func.max(prospect_target.c.updated_at))
                )
        return FounderProspectionQueue(
            available=True,
            last_cycle_at=last_cycle_at,
            items=tuple(
                FounderQueueItem(
                    target_ref=str(row["target_id"]),
                    company_name=str(row["company_name"]),
                    city=str(row["company_city"]),
                    employees=int(row["company_employees"]),
                    family_key=str(row["family_key"]),
                    director_name=row["director_name"],
                    director_title=row["director_title"],
                    email_address=str(row["email_address"]),
                    email_source=str(row["email_source"]),
                    email_verification_status=str(row["email_verification_status"]),
                    bait_holder=str(row["signal_holder"]),
                    bait_subject=str(row["signal_subject"]),
                    bait_amount_minor_units=int(row["signal_amount_minor_units"]),
                    bait_currency=str(row["signal_currency"]),
                    mail_subject=str(row["mail_subject"]),
                    mail_body=str(row["mail_text"]),
                )
                for row in rows
            ),
        )

    def _results(self) -> FounderProspectionResults:
        with self._engine.connect() as connection:
            sent_count = _count(
                connection,
                sa.select(
                    sa.func.count(sa.distinct(acquisition_campaign_member.c.member_ref))
                ).where(acquisition_campaign_member.c.step_1_sent_at.is_not(None)),
            )
            sent_count += _count(
                connection,
                sa.select(sa.func.count())
                .select_from(prospect_target)
                .where(prospect_target.c.sent_at.is_not(None)),
            )
            opened_count = _count(
                connection,
                sa.select(
                    sa.func.count(sa.distinct(acquisition_provider_event.c.provider_event_ref))
                ).where(
                    acquisition_provider_event.c.provider_event_type == "email_opened",
                    acquisition_provider_event.c.resolution_state.in_(("ACCEPTED", "PROCESSED")),
                ),
            )
            opened_count += _count(
                connection,
                sa.select(sa.func.count())
                .select_from(prospect_target)
                .where(prospect_target.c.opened_at.is_not(None)),
            )
            attribution_click_count = _count(
                connection,
                sa.select(
                    sa.func.count(sa.distinct(acquisition_conversion_event.c.conversion_event_ref))
                ).where(acquisition_conversion_event.c.milestone == "CLICK"),
            )
            landing_count = _count(
                connection,
                sa.select(sa.func.count(sa.distinct(account_landing_signal.c.account_id))).where(
                    account_landing_signal.c.qa.is_(False)
                ),
            )
            confirmed_profile_count = _count(
                connection,
                sa.select(sa.func.count(sa.distinct(account_landing_signal.c.account_id))).where(
                    account_landing_signal.c.qa.is_(False),
                    account_landing_signal.c.profile_confirmed_at.is_not(None),
                ),
            )
            paid_account_count = _count(
                connection,
                sa.select(
                    sa.func.count(sa.distinct(acquisition_conversion_event.c.account_id))
                ).where(
                    acquisition_conversion_event.c.milestone == "PAID",
                    acquisition_conversion_event.c.account_id.is_not(None),
                ),
            )
            conversion_rows = tuple(
                connection.execute(
                    sa.select(
                        acquisition_conversion_event.c.conversion_event_ref,
                        acquisition_conversion_event.c.journey_ref,
                        acquisition_conversion_event.c.milestone,
                        acquisition_conversion_event.c.mrr_known,
                        acquisition_conversion_event.c.mrr_minor_units,
                        acquisition_conversion_event.c.currency,
                        acquisition_conversion_event.c.occurred_at,
                    )
                    .where(acquisition_conversion_event.c.journey_ref.is_not(None))
                    .order_by(
                        acquisition_conversion_event.c.occurred_at,
                        acquisition_conversion_event.c.conversion_event_ref,
                    )
                ).mappings()
            )
        return FounderProspectionResults(
            sent_count=sent_count,
            opened_count=opened_count,
            attribution_click_count=attribution_click_count,
            landing_count=landing_count,
            confirmed_profile_count=confirmed_profile_count,
            paid_account_count=paid_account_count,
            mrr_by_currency=_current_mrr(conversion_rows),
            no_sends_yet=sent_count == 0,
        )

    def _targeting(self, *, now: dt.datetime) -> FounderTargetingCycle | None:
        with self._engine.connect() as connection:
            cycle = (
                connection.execute(
                    sa.select(acquisition_runtime_cycle)
                    .order_by(
                        acquisition_runtime_cycle.c.updated_at.desc(),
                        acquisition_runtime_cycle.c.cycle_ref,
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            if cycle is None:
                return None
            started_at = _aware(cycle["started_at"])
            updated_at = _aware(cycle["updated_at"])
            opportunity_key = str(cycle["opportunity_key"])
            discovery = (
                connection.execute(
                    sa.select(supplier_discovery_run)
                    .where(
                        supplier_discovery_run.c.signal_ref
                        == f"procurement-opportunity:{opportunity_key}",
                        supplier_discovery_run.c.started_at >= started_at,
                        supplier_discovery_run.c.started_at <= updated_at,
                    )
                    .order_by(
                        supplier_discovery_run.c.started_at.desc(),
                        supplier_discovery_run.c.discovery_run_id,
                    )
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            award = (
                connection.execute(
                    sa.select(
                        contract_award.c.title,
                        contract_award.c.amount,
                        contract_award.c.currency,
                    )
                    .select_from(
                        opportunity_representation.join(
                            contract_award,
                            contract_award.c.award_key == opportunity_representation.c.award_key,
                        )
                    )
                    .where(opportunity_representation.c.opportunity_key == opportunity_key)
                    .order_by(contract_award.c.award_key)
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
            stage_rows = connection.execute(
                sa.select(acquisition_runtime_stage.c.reason_codes).where(
                    acquisition_runtime_stage.c.cycle_ref == cycle["cycle_ref"]
                )
            ).mappings()
            reasons: Counter[str] = Counter()
            for stage in stage_rows:
                reasons.update(str(code) for code in stage["reason_codes"] or ())
            confirmed_domain_count = int(
                connection.scalar(
                    sa.select(sa.func.count(sa.distinct(supplier_directory.c.siren)))
                    .select_from(
                        acquisition_opportunity.join(
                            acquisition_supplier,
                            acquisition_supplier.c.supplier_ref
                            == acquisition_opportunity.c.supplier_ref,
                        ).join(
                            supplier_directory,
                            supplier_directory.c.siren
                            == acquisition_supplier.c.provider_organization_id,
                        )
                    )
                    .where(
                        acquisition_opportunity.c.signal_ref
                        == f"procurement-opportunity:{opportunity_key}",
                        acquisition_opportunity.c.created_at >= started_at,
                        acquisition_opportunity.c.created_at <= updated_at,
                        supplier_directory.c.suppressed_at.is_(None),
                        supplier_directory.c.domain.is_not(None),
                        supplier_directory.c.domain_validation_method.is_not(None),
                    )
                )
                or 0
            )
            email_level_rows = connection.execute(
                sa.select(
                    acquisition_contact.c.role_tier,
                    sa.func.count(sa.distinct(acquisition_contact.c.contact_ref)),
                )
                .select_from(
                    contact_discovery_run.join(
                        acquisition_opportunity,
                        acquisition_opportunity.c.acquisition_opportunity_id
                        == contact_discovery_run.c.acquisition_opportunity_id,
                    ).join(
                        acquisition_contact,
                        acquisition_contact.c.contact_ref
                        == contact_discovery_run.c.selected_contact_ref,
                    )
                )
                .where(
                    acquisition_opportunity.c.signal_ref
                    == f"procurement-opportunity:{opportunity_key}",
                    contact_discovery_run.c.started_at >= started_at,
                    contact_discovery_run.c.started_at <= updated_at,
                )
                .group_by(acquisition_contact.c.role_tier)
            ).all()
            email_counts = {int(level): int(count) for level, count in email_level_rows}
        profile = discovery["search_profile"] if discovery is not None else {}
        if not isinstance(profile, Mapping):
            profile = {}
        family_values = profile.get("supplier_family_keys", ())
        family_keys = (
            tuple(str(value) for value in family_values)
            if isinstance(family_values, (list, tuple))
            else ()
        )
        if discovery is not None:
            rejection_counts = discovery["rejection_reason_counts"]
            if isinstance(rejection_counts, Mapping):
                reasons.update(
                    {
                        str(code): int(count)
                        for code, count in rejection_counts.items()
                        if int(count) > 0
                    }
                )
        amount = award["amount"] if award is not None else None
        return FounderTargetingCycle(
            cycle_ref=str(cycle["cycle_ref"]),
            status=str(cycle["status"]),
            started_at=started_at,
            updated_at=updated_at,
            completed_at=cycle["completed_at"],
            recent=updated_at >= now - dt.timedelta(hours=48),
            signal=FounderTargetingSignal(
                title=(
                    str(award["title"])
                    if award is not None and award["title"] is not None
                    else None
                ),
                amount_minor_units=(
                    int(Decimal(str(amount)) * Decimal(100)) if amount is not None else None
                ),
                currency=(
                    str(award["currency"])
                    if award is not None and award["currency"] is not None
                    else None
                ),
            ),
            family_keys=family_keys,
            sirene_account_count=(
                int(discovery["records_returned"] or 0) if discovery is not None else 0
            ),
            confirmed_domain_count=confirmed_domain_count,
            email_counts_by_level=tuple(
                FounderRoleLevelCount(level=level, count=email_counts.get(level, 0))
                for level in range(1, 5)
            ),
            deviation_counts=tuple(
                FounderDeviationCount(reason_code=code, count=count)
                for code, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0]))
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
                row.professional_email is not None and row.email_verification_status is not None
                for row in rows
            ),
            reverification_required_count=sum(
                row.reverification_required_at is not None for row in rows
            ),
        )
        family_counts = Counter(key for row in rows for key in row.family_keys)
        department_counts = Counter(row.department for row in rows if row.department is not None)
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
            department_counts=_facets(department_counts, names=DEPARTMENTS),
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
    department = str(row["department"]) if row["department"] is not None else None
    confirmed_domain = (
        row["domain"] is not None and row["domain_validation_method"] is not None
    )
    return FounderDirectoryRow(
        siren=str(row["siren"]),
        legal_name=str(row["legal_name"]),
        family_keys=tuple(str(key) for key in family_keys or ()),  # type: ignore[union-attr]
        department=department,
        department_name=DEPARTMENTS.get(department) if department is not None else None,
        city=str(row["city"]) if row["city"] is not None else None,
        employees=int(row["employees"]) if row["employees"] is not None else None,
        domain=(
            str(row["domain"])
            if confirmed_domain and row["domain"] is not None
            else None
        ),
        website_url=(
            str(row["website_url"])
            if confirmed_domain and row["website_url"] is not None
            else None
        ),
        confirmed_domain=confirmed_domain,
        qualification_status=_directory_qualification_status(row),
        professional_email=(
            str(row["professional_email"]) if row["professional_email"] is not None else None
        ),
        email_source=(str(row["email_source"]) if row["email_source"] is not None else None),
        email_verification_status=(
            str(row["email_verification_status"])
            if row["email_verification_status"] is not None
            else None
        ),
        email_contact_name=(
            str(row["email_contact_name"]) if row["email_contact_name"] is not None else None
        ),
        email_contact_title=(
            str(row["email_contact_title"]) if row["email_contact_title"] is not None else None
        ),
        reverification_required_at=row["reverification_required_at"],  # type: ignore[arg-type]
        reverification_reason=(
            str(row["reverification_reason"]) if row["reverification_reason"] is not None else None
        ),
        updated_at=row["updated_at"],  # type: ignore[arg-type]
    )


def _directory_qualification_status(
    row: Mapping[str, object],
) -> FounderDirectoryQualificationStatus:
    if row["reverification_required_at"] is not None:
        return FounderDirectoryQualificationStatus.REVERIFICATION_REQUIRED
    if row["domain"] is not None and row["domain_validation_method"] is not None:
        return FounderDirectoryQualificationStatus.CONFIRMED_DOMAIN
    if (
        row["domain"] is None
        and row["domain_source"] == "no_website"
        and row["reverification_reason"] == "no_website"
        and int(row["website_search_queries_completed"] or 0) >= 3
        and int(row["website_search_results_examined"] or 0) >= 30
    ):
        return FounderDirectoryQualificationStatus.WITHOUT_WEBSITE
    return FounderDirectoryQualificationStatus.TO_QUALIFY


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
    if directory_status is not None:
        return row.qualification_status.value == directory_status.value
    return True


def _count(connection: sa.Connection, statement: sa.Select[tuple[int]]) -> int:
    return int(connection.scalar(statement) or 0)


def _current_mrr(
    rows: tuple[sa.RowMapping, ...],
) -> tuple[FounderMoneyTotal, ...]:
    by_journey: dict[str, list[sa.RowMapping]] = {}
    for row in rows:
        by_journey.setdefault(str(row["journey_ref"]), []).append(row)
    totals: Counter[str] = Counter()
    for journey_rows in by_journey.values():
        if not any(row["milestone"] == "PAID" for row in journey_rows):
            continue
        mrr_indexes = [
            index for index, row in enumerate(journey_rows) if row["milestone"] == "MRR_CHANGED"
        ]
        if not mrr_indexes:
            continue
        latest_index = mrr_indexes[-1]
        latest = journey_rows[latest_index]
        if any(row["milestone"] == "CHURNED" for row in journey_rows[latest_index + 1 :]):
            continue
        currency = str(latest["currency"] or "").upper()
        if (
            latest["mrr_known"] is not True
            or latest["mrr_minor_units"] is None
            or currency not in {"CHF", "EUR"}
        ):
            continue
        totals[currency] += int(latest["mrr_minor_units"])
    return tuple(
        FounderMoneyTotal(currency=currency, minor_units=totals[currency])
        for currency in sorted(totals)
    )


def _facets(
    counts: Counter[str], *, names: Mapping[str, str] | None = None
) -> tuple[FounderCountFacet, ...]:
    return tuple(
        FounderCountFacet(
            key=key,
            label=f"{names[key]} ({key})" if names is not None and key in names else key,
            count=count,
        )
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )


def _directory_sort_key(row: FounderDirectoryRow) -> tuple[str, str]:
    return (_searchable(row.legal_name), row.siren)


def _searchable(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.strip().casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


__all__ = [
    "FOUNDER_PROSPECTION_VERSION",
    "FounderDirectoryQualificationStatus",
    "FounderDirectoryStatus",
    "FounderProspection",
    "FounderProspectionReadService",
]
