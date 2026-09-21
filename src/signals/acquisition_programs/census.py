"""Durable, capped Apollo preparation for Milo Mail; no sending surface."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, TypeVar

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import Engine, RowMapping

from signals.acquisition_programs.contracts import AcquisitionProgramConfig
from signals.acquisition_programs.mail_provider import MailProviderEvidence, normalize_domain
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import (
    acquisition_census_call,
    acquisition_census_candidate,
    acquisition_census_identity,
    acquisition_census_occurrence,
    acquisition_census_partition,
    acquisition_census_run,
    acquisition_program,
    acquisition_program_eligibility,
)
from signals.supplier_discovery.contracts import ApolloOrganizationCandidate, SupplierSearchPage

FILTER_VERSION = "milomail-census-filters-v1"
APOLLO_DISPLAY_LIMIT = 50_000
MAX_APOLLO_PAGES_PER_SEARCH = 500


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class CensusBudgetExceeded(RuntimeError):
    """No provider call occurred; an explicit cap stopped the census."""


class CensusReviewRequired(RuntimeError):
    """A prior billed call has an ambiguous outcome and cannot be replayed."""


class CensusRetryLater(RuntimeError):
    """A confirmed Apollo rate limit requires a later bounded resume."""


class CensusLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    enabled: bool = False
    max_partitions: int = Field(default=0, ge=0, le=1000)
    max_pages: int = Field(default=0, ge=0, le=500_000)
    max_candidates: int = Field(default=0, ge=0, le=5_000_000)
    max_enrichments: int = Field(default=0, ge=0, le=5_000_000)
    max_apollo_credits: int = Field(default=0, ge=0, le=50_000_000)
    max_cost_chf: Decimal = Field(default=Decimal(0), ge=0)
    chf_per_credit_ceiling: Decimal = Field(default=Decimal(0), ge=0)
    credits_org_search_page: int = Field(default=1, ge=1, le=100)
    credits_org_enrichment: int = Field(default=1, ge=1, le=100)
    credits_person_enrichment_max: int = Field(default=9, ge=9, le=100)
    credits_people_search: int = Field(default=0, ge=0, le=100)
    retention_days: int = Field(default=30, ge=1, le=365)
    authorization_ref: str | None = Field(default=None, max_length=128)

    @classmethod
    def from_environment(cls, source: Mapping[str, str]) -> CensusLimits:
        enabled = source.get("MILOMAIL_CENSUS_ENABLED", "false").casefold()
        if enabled not in {"true", "false"}:
            raise ValueError("MILOMAIL_CENSUS_ENABLED must be true or false")
        return cls(
            enabled=enabled == "true",
            max_partitions=int(source.get("MILOMAIL_CENSUS_MAX_PARTITIONS", "0")),
            max_pages=int(source.get("MILOMAIL_CENSUS_MAX_PAGES", "0")),
            max_candidates=int(source.get("MILOMAIL_CENSUS_MAX_CANDIDATES", "0")),
            max_enrichments=int(source.get("MILOMAIL_CENSUS_MAX_ENRICHMENTS", "0")),
            max_apollo_credits=int(source.get("MILOMAIL_CENSUS_MAX_APOLLO_CREDITS", "0")),
            max_cost_chf=Decimal(source.get("MILOMAIL_CENSUS_MAX_COST_CHF", "0")),
            chf_per_credit_ceiling=Decimal(
                source.get("MILOMAIL_CENSUS_CHF_PER_CREDIT_CEILING", "0")
            ),
            credits_org_search_page=int(source.get("MILOMAIL_CENSUS_CREDITS_ORG_PAGE", "1")),
            credits_org_enrichment=int(source.get("MILOMAIL_CENSUS_CREDITS_ORG_ENRICH", "1")),
            credits_person_enrichment_max=int(
                source.get("MILOMAIL_CENSUS_CREDITS_PERSON_ENRICH_MAX", "9")
            ),
            credits_people_search=int(source.get("MILOMAIL_CENSUS_CREDITS_PEOPLE_SEARCH", "0")),
            retention_days=int(source.get("MILOMAIL_CENSUS_RETENTION_DAYS", "30")),
            authorization_ref=source.get("MILOMAIL_CENSUS_AUTHORIZATION_REF"),
        )

    def require_run_authorization(self) -> None:
        if not self.enabled or not self.authorization_ref or not all(
            (
                self.max_partitions,
                self.max_pages,
                self.max_candidates,
                self.max_enrichments,
                self.max_apollo_credits,
                self.max_cost_chf,
                self.chf_per_credit_ceiling,
            )
        ):
            raise ValueError("explicit census authorization and nonzero limits are required")


@dataclass(frozen=True)
class CensusPartition:
    partition_id: str
    filter_signature: str
    parent_partition_id: str | None
    sector: str
    size_min: int
    size_max: int
    profile_ref: str
    employee_ranges: tuple[str, ...]
    organization_locations: tuple[str, ...]
    organization_not_locations: tuple[str, ...]
    keyword_tags: tuple[str, ...]
    max_pages: int
    per_page: int

    def filters(self) -> dict[str, object]:
        return {
            "employee_ranges": list(self.employee_ranges),
            "organization_locations": list(self.organization_locations),
            "organization_not_locations": list(self.organization_not_locations),
            "keyword_tags": list(self.keyword_tags),
            "max_pages": self.max_pages,
            "per_page": self.per_page,
            "profile_ref": self.profile_ref,
        }

    @classmethod
    def from_row(cls, row: RowMapping) -> CensusPartition:
        filters = row["filters"]
        return cls(
            partition_id=row["partition_id"],
            filter_signature=row["filter_signature"],
            parent_partition_id=row["parent_partition_id"],
            sector=row["sector"],
            size_min=row["size_min"],
            size_max=row["size_max"],
            profile_ref=filters["profile_ref"],
            employee_ranges=tuple(filters["employee_ranges"]),
            organization_locations=tuple(filters["organization_locations"]),
            organization_not_locations=tuple(filters["organization_not_locations"]),
            keyword_tags=tuple(filters["keyword_tags"]),
            max_pages=filters["max_pages"],
            per_page=filters["per_page"],
        )


def build_partitions(config: AcquisitionProgramConfig) -> tuple[CensusPartition, ...]:
    """Three disjoint size bands per sector; sector keywords can overlap."""
    if config.program_key != "milomail" or config.target_country != "FR":
        raise ValueError("census is scoped to the France Milo Mail program")
    config_fingerprint = _digest(_canonical(config.model_dump(mode="json")))
    count = config.target_company_size_max - config.target_company_size_min + 1
    bands = min(3, count)
    width, remainder = divmod(count, bands)
    cursor = config.target_company_size_min
    sizes: list[tuple[int, int]] = []
    for index in range(bands):
        size = width + (remainder if index == bands - 1 else 0)
        sizes.append((cursor, cursor + size - 1))
        cursor += size
    partitions: list[CensusPartition] = []
    for sector in sorted(config.target_sectors):
        terms = config.sector_terms.get(sector)
        if not terms:
            raise ValueError("sector has no configured Apollo keyword terms")
        for low, high in sizes:
            filters: dict[str, object] = {
                "version": FILTER_VERSION,
                "program_config_fingerprint": config_fingerprint,
                "country": "FR",
                "sector": sector,
                "employee_ranges": [f"{low},{high}"],
                "organization_locations": ["France"],
                "organization_not_locations": [],
                "keyword_tags": sorted(set(terms), key=str.casefold),
                "per_page": config.apollo_per_page,
            }
            signature = _digest(_canonical(filters))
            partitions.append(
                CensusPartition(
                    partition_id=signature,
                    filter_signature=signature,
                    parent_partition_id=None,
                    sector=sector,
                    size_min=low,
                    size_max=high,
                    profile_ref=f"milomail-census:{FILTER_VERSION}:{signature[:16]}",
                    employee_ranges=(f"{low},{high}",),
                    organization_locations=("France",),
                    organization_not_locations=(),
                    keyword_tags=tuple(filters["keyword_tags"]),  # type: ignore[arg-type]
                    max_pages=MAX_APOLLO_PAGES_PER_SEARCH,
                    per_page=config.apollo_per_page,
                )
            )
    return tuple(partitions)


T = TypeVar("T")


class CensusStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def plan(
        self, *, program_id: str, partitions: tuple[CensusPartition, ...], at: dt.datetime
    ) -> str:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("census time must be timezone-aware")
        if not partitions:
            raise ValueError("census needs partitions")
        census_id = _digest("milomail-census-v1\0" + program_id + "\0" + FILTER_VERSION)
        with self._engine.begin() as connection:
            program = connection.execute(
                sa.select(acquisition_program).where(acquisition_program.c.program_id == program_id)
            ).mappings().one()
            if program["program_key"] != "milomail" or program["mode"] != "SHADOW":
                raise ValueError("census requires a registered SHADOW Milo Mail program")
            inserted = insert_if_absent(
                connection, acquisition_census_run,
                {
                    "census_id": census_id,
                    "program_id": program_id,
                    "filter_version": FILTER_VERSION,
                    "status": "PLANNED",
                    "limits_snapshot": None,
                    "pages_reserved": 0,
                    "candidate_slots_reserved": 0,
                    "enrichments_reserved": 0,
                    "credits_reserved": 0,
                    "created_at": at,
                    "started_at": None,
                    "updated_at": at,
                },
            )
            if not inserted:
                existing = connection.execute(
                    sa.select(acquisition_census_run).where(
                        acquisition_census_run.c.census_id == census_id
                    )
                ).mappings().one()
                if existing["program_id"] != program_id or existing["filter_version"] != FILTER_VERSION:
                    raise ValueError("census plan identity conflict")
            for part in partitions:
                values = {
                    "partition_id": part.partition_id,
                    "census_id": census_id,
                    "filter_signature": part.filter_signature,
                    "parent_partition_id": part.parent_partition_id,
                    "filters": part.filters(),
                    "sector": part.sector,
                    "size_min": part.size_min,
                    "size_max": part.size_max,
                    "status": "PLANNED",
                    "cursor_page": 1,
                    "estimated_result_count": None,
                    "processed_count": 0,
                    "unique_count": 0,
                    "duplicate_count": 0,
                    "credit_count": 0,
                    "started_at": None,
                    "completed_at": None,
                    "last_error": None,
                }
                if not insert_if_absent(connection, acquisition_census_partition, values):
                    previous = connection.execute(
                        sa.select(acquisition_census_partition).where(
                            acquisition_census_partition.c.partition_id == part.partition_id
                        )
                    ).mappings().one()
                    if previous["census_id"] != census_id or previous["filters"] != part.filters():
                        raise ValueError("census partition identity conflict")
        return census_id

    def start(self, census_id: str, limits: CensusLimits, *, at: dt.datetime) -> None:
        limits.require_run_authorization()
        snapshot = limits.model_dump(mode="json")
        with self._engine.begin() as connection:
            row = connection.execute(
                sa.select(acquisition_census_run)
                .where(acquisition_census_run.c.census_id == census_id)
                .with_for_update()
            ).mappings().one()
            if row["status"] == "PLANNED":
                connection.execute(
                    sa.update(acquisition_census_run)
                    .where(acquisition_census_run.c.census_id == census_id)
                    .values(status="ACTIVE", limits_snapshot=snapshot, started_at=at, updated_at=at)
                )
            elif row["status"] in {"ACTIVE", "PAUSED"} and row["limits_snapshot"] == snapshot:
                connection.execute(
                    sa.update(acquisition_census_run)
                    .where(acquisition_census_run.c.census_id == census_id)
                    .values(status="ACTIVE", updated_at=at)
                )
            elif row["status"] == "COMPLETE" and row["limits_snapshot"] == snapshot:
                return
            else:
                raise ValueError("census limits changed or run requires review")

    def status(self, census_id: str) -> dict[str, Any]:
        with self._engine.connect() as connection:
            row = connection.execute(
                sa.select(acquisition_census_run).where(acquisition_census_run.c.census_id == census_id)
            ).mappings().one()
        result = dict(row)
        limits = result.get("limits_snapshot")
        result["cost_reserved_chf"] = (
            str(Decimal(result["credits_reserved"]) * Decimal(limits["chf_per_credit_ceiling"]))
            if limits else "0"
        )
        if limits:
            result["limits_snapshot"] = {
                key: ("REDACTED" if key == "authorization_ref" else value)
                for key, value in limits.items()
            }
        result["actual_cost_chf"] = (
            str(result["actual_cost_chf"])
            if result["actual_cost_chf"] is not None else None
        )
        return result

    def record_actual_usage(
        self, census_id: str, *, credits: int, cost_chf: Decimal,
        evidence_ref: str, at: dt.datetime,
    ) -> None:
        """Record an externally verified, exclusively attributable usage snapshot once."""
        if (
            credits < 0 or not cost_chf.is_finite() or cost_chf < 0
            or cost_chf != cost_chf.quantize(Decimal("0.0001"))
        ):
            raise ValueError("actual usage must be nonnegative and precise to CHF 0.0001")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_-]{5,127}", evidence_ref):
            raise ValueError("a non-sensitive opaque usage evidence reference is required")
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("usage reconciliation time must be timezone-aware")
        with self._engine.begin() as connection:
            run = connection.execute(
                sa.select(acquisition_census_run)
                .where(acquisition_census_run.c.census_id == census_id)
                .with_for_update()
            ).mappings().one()
            previous = run["actual_apollo_credits"]
            if previous is not None:
                if (previous, Decimal(run["actual_cost_chf"]), run["usage_evidence_ref"]) == (
                    credits, cost_chf, evidence_ref,
                ):
                    return
                raise ValueError("actual usage receipt is immutable; review discrepancy")
            limits = run["limits_snapshot"]
            over_cap = (
                credits > run["credits_reserved"]
                or (limits is not None and (
                    credits > limits["max_apollo_credits"]
                    or cost_chf > Decimal(limits["max_cost_chf"])
                ))
            )
            connection.execute(
                sa.update(acquisition_census_run)
                .where(acquisition_census_run.c.census_id == census_id)
                .values(
                    actual_apollo_credits=credits,
                    actual_cost_chf=cost_chf,
                    usage_evidence_ref=evidence_ref,
                    usage_reconciled_at=at,
                    status="REVIEW_REQUIRED" if over_cap else run["status"],
                    updated_at=at,
                )
            )

    def partitions(self, census_id: str) -> tuple[dict[str, Any], ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                sa.select(acquisition_census_partition)
                .where(acquisition_census_partition.c.census_id == census_id)
                .order_by(acquisition_census_partition.c.partition_id)
            ).mappings().all()
        return tuple(dict(row) for row in rows)

    def candidates(self, census_id: str, *, status: str | None = None) -> tuple[dict[str, Any], ...]:
        statement = sa.select(acquisition_census_candidate).where(
            acquisition_census_candidate.c.census_id == census_id
        )
        if status:
            statement = statement.where(acquisition_census_candidate.c.status == status)
        with self._engine.connect() as connection:
            rows = connection.execute(
                statement.order_by(acquisition_census_candidate.c.candidate_id)
            ).mappings().all()
        return tuple(dict(row) for row in rows)

    def first_partition_for_candidate(self, candidate_id: str) -> str:
        with self._engine.connect() as connection:
            return connection.execute(
                sa.select(acquisition_census_occurrence.c.partition_id)
                .where(acquisition_census_occurrence.c.candidate_id == candidate_id)
                .order_by(acquisition_census_occurrence.c.observed_at,
                          acquisition_census_occurrence.c.partition_id)
                .limit(1)
            ).scalar_one()

    def reserve_call(
        self, census_id: str, *, kind: str, subject: str, attempt: int,
        partition_id: str | None, credits: int, candidate_slots: int,
        at: dt.datetime,
    ) -> dict[str, Any]:
        """Persist the worst-case charge before an Apollo request can begin."""
        if attempt not in (1, 2) or kind not in {
            "ORG_SEARCH", "ORG_ENRICH", "PEOPLE_SEARCH", "PERSON_ENRICH"
        }:
            raise ValueError("unsupported census call")
        if credits < 0 or candidate_slots < 0:
            raise ValueError("negative reservation")
        subject_hash = _digest(subject)
        call_id = _digest(f"census-call-v1\0{census_id}\0{kind}\0{subject_hash}\0{attempt}")
        with self._engine.begin() as connection:
            run = connection.execute(
                sa.select(acquisition_census_run)
                .where(acquisition_census_run.c.census_id == census_id)
                .with_for_update()
            ).mappings().one()
            existing = connection.execute(
                sa.select(acquisition_census_call).where(acquisition_census_call.c.call_id == call_id)
            ).mappings().one_or_none()
            if existing is not None:
                if (existing["kind"], existing["subject_hash"], existing["partition_id"]) != (
                    kind, subject_hash, partition_id
                ):
                    raise ValueError("census call identity conflict")
                return {**dict(existing), "claimed_now": False}
            if run["status"] != "ACTIVE" or run["limits_snapshot"] is None:
                raise CensusBudgetExceeded("census is not active")
            limits = CensusLimits.model_validate(run["limits_snapshot"])
            pages = 1 if kind == "ORG_SEARCH" else 0
            enrichments = 1 if kind in {"ORG_ENRICH", "PERSON_ENRICH"} else 0
            if partition_id is not None and kind == "ORG_SEARCH":
                used_partitions = connection.scalar(
                    sa.select(sa.func.count(sa.distinct(acquisition_census_call.c.partition_id)))
                    .where(
                        acquisition_census_call.c.census_id == census_id,
                        acquisition_census_call.c.kind == "ORG_SEARCH",
                    )
                ) or 0
                already_started = connection.scalar(
                    sa.select(sa.func.count()).select_from(acquisition_census_call).where(
                        acquisition_census_call.c.census_id == census_id,
                        acquisition_census_call.c.kind == "ORG_SEARCH",
                        acquisition_census_call.c.partition_id == partition_id,
                    )
                ) or 0
                if not already_started and used_partitions >= limits.max_partitions:
                    raise CensusBudgetExceeded("partition limit reached")
            if (
                run["pages_reserved"] + pages > limits.max_pages
                or run["candidate_slots_reserved"] + candidate_slots > limits.max_candidates
                or run["enrichments_reserved"] + enrichments > limits.max_enrichments
                or run["credits_reserved"] + credits > limits.max_apollo_credits
                or Decimal(run["credits_reserved"] + credits)
                * limits.chf_per_credit_ceiling > limits.max_cost_chf
            ):
                raise CensusBudgetExceeded("census page, candidate, enrichment or cost cap reached")
            values = {
                "call_id": call_id,
                "census_id": census_id,
                "partition_id": partition_id,
                "kind": kind,
                "subject_hash": subject_hash,
                "attempt": attempt,
                "status": "RESERVED",
                "reserved_credits": credits,
                "candidate_slots": candidate_slots,
                "result_snapshot": None,
                "result_count": None,
                "error_category": None,
                "retry_after": None,
                "started_at": at,
                "completed_at": None,
            }
            connection.execute(sa.insert(acquisition_census_call).values(**values))
            connection.execute(
                sa.update(acquisition_census_run)
                .where(acquisition_census_run.c.census_id == census_id)
                .values(
                    pages_reserved=run["pages_reserved"] + pages,
                    candidate_slots_reserved=run["candidate_slots_reserved"] + candidate_slots,
                    enrichments_reserved=run["enrichments_reserved"] + enrichments,
                    credits_reserved=run["credits_reserved"] + credits,
                    updated_at=at,
                )
            )
            if partition_id is not None and credits:
                connection.execute(
                    sa.update(acquisition_census_partition)
                    .where(acquisition_census_partition.c.partition_id == partition_id)
                    .values(credit_count=acquisition_census_partition.c.credit_count + credits)
                )
        return {**values, "claimed_now": True}

    def execute_call(
        self, census_id: str, *, kind: str, subject: str, partition_id: str | None,
        credits: int, candidate_slots: int, at: dt.datetime,
        invoke: Callable[[], T], encode: Callable[[T], object],
        decode: Callable[[object], T],
    ) -> tuple[T, str]:
        """Cache completed responses; never replay an ambiguous provider request."""
        for attempt in (1, 2):
            call = self.reserve_call(
                census_id, kind=kind, subject=subject, attempt=attempt,
                partition_id=partition_id, credits=credits,
                candidate_slots=candidate_slots, at=at,
            )
            if call["status"] == "COMPLETED":
                if call["result_snapshot"] is None:
                    raise CensusReviewRequired("purged Apollo response cannot be replayed")
                return decode(call["result_snapshot"]), call["call_id"]
            if call["status"] == "RATE_LIMITED":
                retry_after = call["retry_after"]
                if retry_after and retry_after.replace(tzinfo=retry_after.tzinfo or dt.UTC) > at:
                    raise CensusRetryLater("Apollo rate limit has not elapsed")
                continue
            if call["status"] != "RESERVED" or not call["claimed_now"]:
                raise CensusReviewRequired("ambiguous Apollo call requires manual review")
            try:
                result = invoke()
            except Exception as error:
                # Only a bounded, known Apollo rate-limit response is retryable.
                category = getattr(error, "category", "provider_error")
                retry_after = getattr(error, "retry_after", None)
                self.fail_call(
                    call["call_id"], category=category,
                    retry_after=retry_after, at=at,
                )
                if category == "rate_limited" and attempt == 1 and (
                    retry_after is None or retry_after <= at
                ):
                    continue
                if category == "rate_limited" and attempt == 1:
                    raise CensusRetryLater("Apollo rate limit requires later resume") from error
                raise CensusReviewRequired(f"Apollo {category}; no automatic replay") from error
            encoded = encode(result)
            self.complete_call(call["call_id"], encoded, at=at)
            return result, call["call_id"]
        raise CensusReviewRequired("Apollo retry limit reached")

    def complete_call(self, call_id: str, result: object, *, at: dt.datetime) -> None:
        with self._engine.begin() as connection:
            row = connection.execute(
                sa.select(acquisition_census_call)
                .where(acquisition_census_call.c.call_id == call_id)
                .with_for_update()
            ).mappings().one()
            if row["status"] == "COMPLETED":
                if row["result_snapshot"] != result:
                    raise ValueError("census call result conflict")
                return
            if row["status"] != "RESERVED":
                raise CensusReviewRequired("census call is not reservable")
            connection.execute(
                sa.update(acquisition_census_call)
                .where(acquisition_census_call.c.call_id == call_id)
                .values(
                    status="COMPLETED",
                    result_snapshot=result,
                    result_count=(
                        len(result.get("candidates", []))
                        if row["kind"] == "PEOPLE_SEARCH" and isinstance(result, dict)
                        else None
                    ),
                    completed_at=at,
                )
            )

    def fail_call(
        self, call_id: str, *, category: str, retry_after: dt.datetime | None,
        at: dt.datetime,
    ) -> None:
        safe_category = category if category in {
            "rate_limited", "timeout", "network_error", "server_error", "client_error",
            "unauthorized", "forbidden", "not_found", "unprocessable_entity",
            "malformed_response",
        } else "provider_error"
        new_status = "RATE_LIMITED" if safe_category == "rate_limited" else "REVIEW_REQUIRED"
        with self._engine.begin() as connection:
            row = connection.execute(
                sa.select(acquisition_census_call)
                .where(acquisition_census_call.c.call_id == call_id)
                .with_for_update()
            ).mappings().one()
            if row["status"] != "RESERVED":
                raise CensusReviewRequired("census call outcome already recorded")
            connection.execute(
                sa.update(acquisition_census_call)
                .where(acquisition_census_call.c.call_id == call_id)
                .values(
                    status=new_status, error_category=safe_category,
                    retry_after=retry_after, completed_at=at,
                )
            )
            if new_status == "REVIEW_REQUIRED":
                connection.execute(
                    sa.update(acquisition_census_run)
                    .where(acquisition_census_run.c.census_id == row["census_id"])
                    .values(status="REVIEW_REQUIRED", updated_at=at)
                )

    def record_page(
        self, census_id: str, partition_id: str, page: SupplierSearchPage,
        *, call_id: str, at: dt.datetime,
    ) -> None:
        """Commit candidate identities and the next page cursor in one transaction."""
        with self._engine.begin() as connection:
            part = connection.execute(
                sa.select(acquisition_census_partition)
                .where(acquisition_census_partition.c.partition_id == partition_id)
                .with_for_update()
            ).mappings().one()
            call = connection.execute(
                sa.select(acquisition_census_call).where(acquisition_census_call.c.call_id == call_id)
            ).mappings().one()
            if part["census_id"] != census_id or call["partition_id"] != partition_id:
                raise ValueError("census page/partition mismatch")
            if call["status"] != "COMPLETED" or call["kind"] != "ORG_SEARCH":
                raise CensusReviewRequired("uncommitted Apollo page cannot advance cursor")
            if call["result_snapshot"] != page.model_dump(mode="json"):
                raise ValueError("census page differs from the cached Apollo response")
            if part["cursor_page"] > page.page:
                return
            if part["cursor_page"] != page.page or page.per_page != part["filters"]["per_page"]:
                raise ValueError("census page cursor mismatch")
            unique = duplicates = 0
            for candidate in page.candidates:
                if not isinstance(candidate, ApolloOrganizationCandidate):
                    raise TypeError("Apollo census received a non-Apollo organization")
                created = self._record_candidate_in_transaction(
                    connection, census_id, partition_id, page.page, candidate, part["sector"], at
                )
                unique += int(created)
                duplicates += int(not created)
            seen = len(page.candidates) + len(page.rejections)
            if seen > call["candidate_slots"]:
                raise ValueError("Apollo page exceeds reserved candidate slots")
            if call["candidate_slots"] > seen:
                connection.execute(
                    sa.update(acquisition_census_run)
                    .where(acquisition_census_run.c.census_id == census_id)
                    .values(
                        candidate_slots_reserved=acquisition_census_run.c.candidate_slots_reserved
                        - (call["candidate_slots"] - seen)
                    )
                )
            coverage_gap = (
                page.total_entries >= APOLLO_DISPLAY_LIMIT
                or page.partial_results_only is True
                or page.total_pages > MAX_APOLLO_PAGES_PER_SEARCH
            )
            finished = page.page >= page.total_pages or page.page >= MAX_APOLLO_PAGES_PER_SEARCH
            status = (
                "INCOMPLETE" if finished and coverage_gap else
                "COMPLETE" if finished else "ACTIVE"
            )
            connection.execute(
                sa.update(acquisition_census_partition)
                .where(acquisition_census_partition.c.partition_id == partition_id)
                .values(
                    status=status,
                    cursor_page=page.page + 1,
                    estimated_result_count=page.total_entries,
                    processed_count=part["processed_count"] + seen,
                    unique_count=part["unique_count"] + unique,
                    duplicate_count=part["duplicate_count"] + duplicates,
                    started_at=part["started_at"] or at,
                    completed_at=at if finished else None,
                    last_error="APOLLO_COVERAGE_LIMIT" if coverage_gap else None,
                )
            )

    def _record_candidate_in_transaction(
        self, connection: sa.Connection, census_id: str, partition_id: str,
        page: int, candidate: ApolloOrganizationCandidate, sector: str, at: dt.datetime,
    ) -> bool:
        identities = [("APOLLO_ORG", _digest(candidate.provider_organization_id))]
        if candidate.primary_domain:
            identities.append(("DOMAIN", _digest(normalize_domain(candidate.primary_domain))))
        matches = {
            row["candidate_id"]
            for row in connection.execute(
                sa.select(acquisition_census_identity.c.candidate_id).where(
                    acquisition_census_identity.c.census_id == census_id,
                    sa.tuple_(
                        acquisition_census_identity.c.identity_kind,
                        acquisition_census_identity.c.identity_hash,
                    ).in_(identities),
                )
            ).mappings()
        }
        if len(matches) > 1:
            raise CensusReviewRequired("Apollo organization and domain identities disagree")
        created = not matches
        candidate_id = next(iter(matches)) if matches else _digest(
            f"census-candidate-v1\0{census_id}\0{candidate.provider_organization_id}"
        )
        if created:
            connection.execute(
                sa.insert(acquisition_census_candidate).values(
                    candidate_id=candidate_id,
                    census_id=census_id,
                    provider_organization_id=candidate.provider_organization_id,
                    primary_domain=candidate.primary_domain,
                    snapshot=candidate.model_dump(mode="json"),
                    sector=sector,
                    location=candidate.location,
                    company_size=None,
                    role=None,
                    provider="UNKNOWN",
                    provider_confidence="UNKNOWN",
                    provider_evidence=None,
                    recipient_provider=None,
                    recipient_provider_confidence=None,
                    contact_found=False,
                    leader_identified=False,
                    email_verified=False,
                    opportunity_id=None,
                    contact_ref=None,
                    status="PENDING",
                    decision=None,
                    reason_codes=[],
                    created_at=at,
                    updated_at=at,
                )
            )
        for kind, identity_hash in identities:
            insert_if_absent(
                connection, acquisition_census_identity,
                {
                    "census_id": census_id,
                    "identity_kind": kind,
                    "identity_hash": identity_hash,
                    "candidate_id": candidate_id,
                },
            )
        insert_if_absent(
            connection, acquisition_census_occurrence,
            {
                "partition_id": partition_id,
                "candidate_id": candidate_id,
                "first_page": page,
                "observed_at": at,
            },
        )
        return created

    def record_decision(
        self, census_id: str, candidate_id: str, *, provider: MailProviderEvidence | None,
        decision: str, reasons: tuple[str, ...], at: dt.datetime,
        opportunity_id: str | None = None, contact_ref: str | None = None,
        company_size: int | None = None,
    ) -> None:
        with self._engine.begin() as connection:
            row = connection.execute(
                sa.select(acquisition_census_candidate)
                .where(
                    acquisition_census_candidate.c.candidate_id == candidate_id,
                    acquisition_census_candidate.c.census_id == census_id,
                )
                .with_for_update()
            ).mappings().one()
            if row["status"] == "DECIDED":
                return
            role = recipient_provider = recipient_confidence = None
            if opportunity_id:
                research = connection.execute(
                    sa.select(acquisition_census_call.c.result_snapshot).where(
                        acquisition_census_call.c.census_id == census_id,
                        acquisition_census_call.c.kind == "ORG_ENRICH",
                        acquisition_census_call.c.subject_hash
                        == _digest(row["provider_organization_id"]),
                        acquisition_census_call.c.status == "COMPLETED",
                    )
                ).scalar_one_or_none()
                if isinstance(research, dict):
                    company_size = research.get("provider_employee_count")
                eligibility = connection.execute(
                    sa.select(acquisition_program_eligibility)
                    .where(
                        acquisition_program_eligibility.c.program_id == self._program_id(connection, census_id),
                        acquisition_program_eligibility.c.acquisition_opportunity_id == opportunity_id,
                    )
                    .order_by(acquisition_program_eligibility.c.evaluated_at.desc())
                    .limit(1)
                ).mappings().one()
                role = eligibility["professional_evidence"].get("role")
                stored_provider = eligibility["provider_evidence"]
                recipient_provider = stored_provider["provider"]
                recipient_confidence = stored_provider["confidence"]
                identity = eligibility["professional_evidence"].get("recipient_identity_hmac")
                if identity:
                    prior = connection.execute(
                        sa.select(acquisition_census_identity.c.candidate_id).where(
                            acquisition_census_identity.c.census_id == census_id,
                            acquisition_census_identity.c.identity_kind == "EMAIL",
                            acquisition_census_identity.c.identity_hash == identity,
                        )
                    ).scalar_one_or_none()
                    if prior is not None and prior != candidate_id:
                        decision, reasons = "NO_SEND", ("DUPLICATE_RECIPIENT_IN_CENSUS",)
                    elif prior is None:
                        connection.execute(
                            sa.insert(acquisition_census_identity).values(
                                census_id=census_id, identity_kind="EMAIL",
                                identity_hash=identity, candidate_id=candidate_id,
                            )
                        )
            connection.execute(
                sa.update(acquisition_census_candidate)
                .where(acquisition_census_candidate.c.candidate_id == candidate_id)
                .values(
                    provider=provider.provider.value if provider else "UNKNOWN",
                    provider_confidence=provider.confidence.value if provider else "UNKNOWN",
                    provider_evidence={
                        "mx_records": list(provider.mx_records),
                        "source": provider.source,
                        "observed_at": provider.observed_at.isoformat(),
                        "expires_at": provider.expires_at.isoformat(),
                        "detector_version": provider.detector_version,
                    } if provider else None,
                    recipient_provider=recipient_provider,
                    recipient_provider_confidence=recipient_confidence,
                    status="DECIDED",
                    decision=decision,
                    reason_codes=list(reasons),
                    opportunity_id=opportunity_id,
                    contact_ref=contact_ref,
                    contact_found=contact_ref is not None,
                    leader_identified=role is not None,
                    email_verified=contact_ref is not None,
                    role=role,
                    company_size=company_size,
                    updated_at=at,
                )
            )

    def record_provider(
        self, census_id: str, candidate_id: str,
        provider: MailProviderEvidence, *, at: dt.datetime,
    ) -> None:
        """Durable MX cache for a pending candidate across process restarts."""
        with self._engine.begin() as connection:
            row = connection.execute(
                sa.select(acquisition_census_candidate)
                .where(
                    acquisition_census_candidate.c.census_id == census_id,
                    acquisition_census_candidate.c.candidate_id == candidate_id,
                )
                .with_for_update()
            ).mappings().one()
            if row["status"] != "PENDING":
                return
            connection.execute(
                sa.update(acquisition_census_candidate)
                .where(acquisition_census_candidate.c.candidate_id == candidate_id)
                .values(
                    provider=provider.provider.value,
                    provider_confidence=provider.confidence.value,
                    provider_evidence={
                        "mx_records": list(provider.mx_records),
                        "source": provider.source,
                        "observed_at": provider.observed_at.isoformat(),
                        "expires_at": provider.expires_at.isoformat(),
                        "detector_version": provider.detector_version,
                    },
                    updated_at=at,
                )
            )

    @staticmethod
    def _program_id(connection: sa.Connection, census_id: str) -> str:
        return connection.execute(
            sa.select(acquisition_census_run.c.program_id).where(
                acquisition_census_run.c.census_id == census_id
            )
        ).scalar_one()

    def pause(
        self, census_id: str, partition_id: str | None, reason: str, *, at: dt.datetime,
        review: bool = False,
    ) -> None:
        with self._engine.begin() as connection:
            connection.execute(
                sa.update(acquisition_census_run)
                .where(acquisition_census_run.c.census_id == census_id)
                .values(status="REVIEW_REQUIRED" if review else "PAUSED", updated_at=at)
            )
            if partition_id:
                connection.execute(
                    sa.update(acquisition_census_partition)
                    .where(acquisition_census_partition.c.partition_id == partition_id)
                    .values(
                        status="REVIEW_REQUIRED" if review else "INCOMPLETE",
                        last_error=sa.func.coalesce(
                            acquisition_census_partition.c.last_error, reason[:64]
                        ),
                    )
                )

    def finish(self, census_id: str, *, at: dt.datetime) -> None:
        with self._engine.begin() as connection:
            remaining = connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_census_partition).where(
                    acquisition_census_partition.c.census_id == census_id,
                    acquisition_census_partition.c.status != "COMPLETE",
                )
            ) or 0
            pending = connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_census_candidate).where(
                    acquisition_census_candidate.c.census_id == census_id,
                    acquisition_census_candidate.c.status != "DECIDED",
                )
            ) or 0
            connection.execute(
                sa.update(acquisition_census_run)
                .where(acquisition_census_run.c.census_id == census_id)
                .values(status="COMPLETE" if not remaining and not pending else "PAUSED", updated_at=at)
            )

    def purge_contact_cache(self, census_id: str, *, at: dt.datetime) -> int:
        """Remove duplicate Apollo person payloads; Kivou contact records remain."""
        with self._engine.begin() as connection:
            run = connection.execute(
                sa.select(acquisition_census_run)
                .where(acquisition_census_run.c.census_id == census_id)
                .with_for_update()
            ).mappings().one()
            limits = run["limits_snapshot"]
            if not limits:
                return 0
            retention = dt.timedelta(days=int(limits["retention_days"]))
            start = run["started_at"] or run["created_at"]
            start = start.replace(tzinfo=start.tzinfo or dt.UTC)
            expired = at >= start + retention
            if run["status"] != "COMPLETE" and not expired:
                raise ValueError("contact cache retention interval has not elapsed")
            result = connection.execute(
                sa.update(acquisition_census_call)
                .where(
                    acquisition_census_call.c.census_id == census_id,
                    acquisition_census_call.c.kind.in_(("PEOPLE_SEARCH", "PERSON_ENRICH")),
                    acquisition_census_call.c.status == "COMPLETED",
                    acquisition_census_call.c.result_snapshot.is_not(None),
                )
                .values(result_snapshot=None)
            )
            if run["status"] != "COMPLETE":
                connection.execute(
                    sa.update(acquisition_census_run)
                    .where(acquisition_census_run.c.census_id == census_id)
                    .values(status="REVIEW_REQUIRED", updated_at=at)
                )
            return result.rowcount or 0

    def report(self, census_id: str) -> dict[str, Any]:
        """Read-only, aggregate funnel. No name, email, Apollo key or mailbox data."""
        run = self.status(census_id)
        parts = self.partitions(census_id)
        candidates = self.candidates(census_id)
        with self._engine.connect() as connection:
            calls = connection.execute(
                sa.select(acquisition_census_call).where(
                    acquisition_census_call.c.census_id == census_id
                )
            ).mappings().all()
            email_identities = connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_census_identity).where(
                    acquisition_census_identity.c.census_id == census_id,
                    acquisition_census_identity.c.identity_kind == "EMAIL",
                )
            ) or 0
        decision_counts = Counter(
            row["decision"] for row in candidates if row["decision"] is not None
        )
        providers = Counter(row["provider"] for row in candidates)
        reasons = Counter(
            reason for row in candidates for reason in row["reason_codes"]
        )
        calls_by_kind = Counter(
            f"{row['kind']}:{row['status']}" for row in calls
        )
        contacts_found = sum(
            row["result_count"] or 0
            for row in calls
            if row["kind"] == "PEOPLE_SEARCH" and row["status"] == "COMPLETED"
        )

        def breakdown(field: str) -> dict[str, dict[str, int]]:
            result: dict[str, dict[str, int]] = {}
            for row in candidates:
                key = str(row.get(field) or "UNKNOWN")
                bucket = result.setdefault(key, {"companies": 0, "SEND": 0, "HOLD": 0, "NO_SEND": 0})
                bucket["companies"] += 1
                if row["decision"]:
                    bucket[row["decision"]] += 1
            return dict(sorted(result.items()))

        reserved = Decimal(run["cost_reserved_chf"])
        send_count = decision_counts["SEND"]
        return {
            "census_id": census_id,
            "program_key": "milomail",
            "mode": "SHADOW",
            "status": run["status"],
            "filter_version": run["filter_version"],
            "organizations_found": sum(
                row["unique_count"] + row["duplicate_count"] for row in parts
            ),
            "organizations_unique": len(candidates),
            "contacts_found": contacts_found,
            "leaders_identified": sum(bool(row["leader_identified"]) for row in candidates),
            "valid_domains": sum(bool(row["primary_domain"]) for row in candidates),
            "google_workspace_confirmed": sum(
                row["provider"] == "GOOGLE_WORKSPACE"
                and row["provider_confidence"] == "CONFIRMED"
                for row in candidates
            ),
            "gmail_consumer": providers["GMAIL_CONSUMER"],
            "microsoft_365": providers["MICROSOFT_365"],
            "other_provider": providers["OTHER"],
            "provider_unknown": providers["UNKNOWN"],
            "verified_addresses_unique": email_identities,
            "verified_addresses_observed": sum(bool(row["email_verified"]) for row in candidates),
            "suppressions": reasons["SUPPRESSION_MATCH"],
            "SEND_theoretical": send_count,
            "HOLD": decision_counts["HOLD"],
            "NO_SEND": decision_counts["NO_SEND"],
            "pending": sum(row["status"] != "DECIDED" for row in candidates),
            "company_duplicates": sum(row["duplicate_count"] for row in parts),
            "email_duplicates": reasons["DUPLICATE_RECIPIENT_IN_CENSUS"],
            "partitions_complete": sum(row["status"] == "COMPLETE" for row in parts),
            "partitions_incomplete": sum(row["status"] != "COMPLETE" for row in parts),
            "coverage_holes": [
                {"partition_id": row["partition_id"], "reason": row["last_error"] or row["status"]}
                for row in parts if row["status"] != "COMPLETE"
            ],
            "apollo_credits_reserved_upper_bound": run["credits_reserved"],
            "apollo_credits_actual": run["actual_apollo_credits"],
            "cost_chf_reserved_upper_bound": str(reserved),
            "cost_chf_actual": run["actual_cost_chf"],
            "cost_chf_per_SEND_actual": (
                str(Decimal(run["actual_cost_chf"]) / send_count)
                if send_count and run["actual_cost_chf"] is not None else None
            ),
            "cost_chf_per_SEND_upper_bound": (
                str(reserved / send_count) if send_count else None
            ),
            "api_calls": dict(sorted(calls_by_kind.items())),
            "by_sector": breakdown("sector"),
            "by_company_size": breakdown("company_size"),
            "by_location": breakdown("location"),
            "by_role": breakdown("role"),
            "by_mail_provider": breakdown("provider"),
            "by_recipient_mail_provider": breakdown("recipient_provider"),
            "recipient_gmail_consumer": sum(
                row["recipient_provider"] == "GMAIL_CONSUMER" for row in candidates
            ),
            "by_reason_code": dict(sorted(reasons.items())),
            "by_partition": {
                row["partition_id"]: {
                    "sector": row["sector"],
                    "size_min": row["size_min"],
                    "size_max": row["size_max"],
                    "status": row["status"],
                    "estimated_result_count": row["estimated_result_count"],
                    "processed_count": row["processed_count"],
                    "unique_count": row["unique_count"],
                    "duplicate_count": row["duplicate_count"],
                    "credit_count_reserved": row["credit_count"],
                }
                for row in parts
            },
            "population_estimate_15000_50000": "UNMEASURED_HYPOTHESIS",
        }
