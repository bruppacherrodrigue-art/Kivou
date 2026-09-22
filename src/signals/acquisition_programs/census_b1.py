"""Closed-by-default B1 credit caps and reproducible organization page allocation.

This module only plans organization searches. Contact work requires a separate
frozen permit and never passes through an Instantly adapter.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition_programs.census import CensusLimits, CensusReviewRequired, CensusStore
from signals.acquisition_programs.mail_provider import (
    MailProvider,
    MailProviderDetector,
    normalize_domain,
)
from signals.compliance.suppression import MILOMAIL_SUPPRESSION_SCOPE
from signals.persistence.schema import (
    acquisition_census_b0_entry,
    acquisition_census_b1_entry,
    acquisition_census_b1_page,
    acquisition_census_b1_plan,
    acquisition_census_call,
    acquisition_census_candidate,
    acquisition_census_company_match,
    acquisition_census_occurrence,
    acquisition_census_partition,
    acquisition_census_permit,
    acquisition_census_run,
    acquisition_contact_suppression,
    acquisition_supplier,
)
from signals.supplier_discovery.contracts import ApolloOrganizationCandidate, SupplierSearchPage


@dataclass(frozen=True)
class B1Caps:
    enabled: bool = False
    max_new_credits: int = 0
    max_new_pages: int = 0
    max_companies: int = 0
    max_person_searches: int = 0
    max_enrichments: int = 0
    min_remaining_pool_balance: int = 1000
    target_total_verified_emails: int = 500

    @classmethod
    def from_environment(cls, source: Mapping[str, str]) -> B1Caps:
        flag = source.get("MILOMAIL_B1_ENABLED", "false").casefold()
        if flag not in {"true", "false"}:
            raise ValueError("MILOMAIL_B1_ENABLED must be true or false")
        return cls(
            enabled=flag == "true",
            max_new_credits=int(source.get("MILOMAIL_B1_MAX_NEW_CREDITS", "0")),
            max_new_pages=int(source.get("MILOMAIL_B1_MAX_NEW_PAGES", "0")),
            max_companies=int(source.get("MILOMAIL_B1_MAX_COMPANIES", "0")),
            max_person_searches=int(source.get("MILOMAIL_B1_MAX_PERSON_SEARCHES", "0")),
            max_enrichments=int(source.get("MILOMAIL_B1_MAX_ENRICHMENTS", "0")),
            min_remaining_pool_balance=int(source.get("MILOMAIL_B1_MIN_POOL_BALANCE", "1000")),
            target_total_verified_emails=int(source.get("MILOMAIL_B1_TARGET_TOTAL", "500")),
        )

    def __post_init__(self) -> None:
        values = (self.max_new_credits, self.max_new_pages, self.max_companies,
                  self.max_person_searches, self.max_enrichments)
        if any(value < 0 for value in values):
            raise ValueError("B1 caps must not be negative")
        if (self.max_new_credits > 900 or self.max_new_pages > 220 or
                self.max_companies > 1200 or self.max_person_searches > 1200 or
                self.max_enrichments > 900 or self.min_remaining_pool_balance < 1000 or
                self.target_total_verified_emails > 500):
            raise ValueError("B1 authorization ceiling exceeded")

    def available_credits(self, balance: int) -> int:
        if not self.enabled:
            return 0
        return max(0, min(self.max_new_credits,
                          balance - self.min_remaining_pool_balance))

    def can_reserve(self, *, balance: int, spent: int, credits: int) -> bool:
        return bool(self.enabled and credits > 0 and spent >= 0 and
                    spent + credits <= self.max_new_credits and
                    balance - credits >= self.min_remaining_pool_balance)


@dataclass(frozen=True)
class PartitionYield:
    partition_id: str
    sector: str
    size_band: str
    accessible_pages: int
    cached_pages: tuple[int, ...]
    verified_emails: int
    consumed_credits: int


@dataclass(frozen=True)
class PlannedPage:
    partition_id: str
    page: int
    sector: str
    size_band: str
    allocation_reason: str


def _hash(seed: str, *parts: object) -> int:
    material = ":".join((seed, *(str(part) for part in parts)))
    return int(hashlib.sha256(material.encode()).hexdigest(), 16)


def _spread_pages(partition: PartitionYield, count: int, seed: str) -> list[int]:
    """Pick at most one page per quantile before filling sparse quantiles.

    Apollo only exposes its documented first 500 pages. Cached pages are
    omitted before sampling, so resume cannot pay for them again.
    """
    choices = [page for page in range(2, min(partition.accessible_pages, 500) + 1)
               if page not in partition.cached_pages]
    if count >= len(choices):
        return choices
    selected: list[int] = []
    for slot in range(count):
        low = slot * len(choices) // count
        high = (slot + 1) * len(choices) // count
        bucket = choices[low:high]
        selected.append(min(bucket, key=lambda page: _hash(seed, partition.partition_id,
                                                            slot, page)))
    return selected


def allocate_pages(partitions: tuple[PartitionYield, ...], *, max_new_pages: int,
                   seed: str) -> tuple[PlannedPage, ...]:
    if max_new_pages < 0 or not seed or len({p.partition_id for p in partitions}) != len(partitions):
        raise ValueError("B1 page plan requires a cap, public seed and unique partitions")
    ordered = sorted(partitions, key=lambda part: part.partition_id)
    capacity = {p.partition_id: len([page for page in range(
        2, min(p.accessible_pages, 500) + 1) if page not in p.cached_pages])
                for p in ordered}
    quota = {p.partition_id: 0 for p in ordered}
    remaining = min(max_new_pages, sum(capacity.values()))
    # Give every stratum an exploratory share before prioritizing observed yield.
    for _ in range(2):
        for part in ordered:
            if remaining and quota[part.partition_id] < capacity[part.partition_id]:
                quota[part.partition_id] += 1
                remaining -= 1
    while remaining:
        candidates = [part for part in ordered
                      if quota[part.partition_id] < capacity[part.partition_id]]
        if not candidates:
            break
        next_part = max(candidates, key=lambda part: (
            (part.verified_emails + 1) / (part.consumed_credits + 2) /
            (quota[part.partition_id] + 1),
            -_hash(seed, part.partition_id) % 1000000,
        ))
        quota[next_part.partition_id] += 1
        remaining -= 1
    planned: list[PlannedPage] = []
    for part in ordered:
        for index, page in enumerate(_spread_pages(part, quota[part.partition_id], seed)):
            planned.append(PlannedPage(part.partition_id, page, part.sector,
                                       part.size_band,
                                       "EXPLORATION" if index < 2 else "OBSERVED_YIELD"))
    return tuple(planned)


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


class B1PlanStore:
    """Frozen public page plan, bounded selection and durable checkpoints."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def plan(self, census_id: str, *, permit_id: str, caps: B1Caps,
             pool_balance: int, seed: str, at: dt.datetime) -> dict:
        if (not caps.enabled or not 1 <= caps.max_new_credits <= 900 or
                caps.max_companies < 184 or caps.max_enrichments < 1 or
                caps.max_person_searches < 184 or not 8 <= len(permit_id) <= 64 or
                pool_balance - caps.max_new_credits < 1000):
            raise ValueError("B1 requires explicit company, credit and reserve caps")
        with self.engine.begin() as connection:
            existing = connection.execute(sa.select(acquisition_census_b1_plan).where(
                acquisition_census_b1_plan.c.plan_id == permit_id,
            )).mappings().one_or_none()
            if existing is not None:
                if (existing["census_id"] != census_id or existing["seed"] != seed or
                        existing["caps"] != caps.__dict__ or
                        existing["pool_before"] != pool_balance):
                    raise ValueError("B1 plan is immutable")
                return self.details(permit_id)
            run = connection.execute(sa.select(acquisition_census_run).where(
                acquisition_census_run.c.census_id == census_id,
            ).with_for_update()).mappings().one()
            if run["pages_reserved"] < 90 or run["active_sample_plan_id"] is None:
                raise ValueError("B1 requires the observed A1 baseline")
            active_b1 = connection.scalar(sa.select(sa.func.count()).select_from(
                acquisition_census_permit).where(
                acquisition_census_permit.c.census_id == census_id,
                acquisition_census_permit.c.phase == "FRANCE_B1_READY_BASE",
                acquisition_census_permit.c.status == "ACTIVE",
            )) or 0
            if active_b1:
                raise ValueError("prior B1 permit must be revoked before continuation")
            if run["credits_reserved"] + caps.max_new_credits > 1791:
                raise ValueError("B1 cumulative 900-credit authorization would be exceeded")
            limits = CensusLimits(
                enabled=True, max_partitions=9,
                max_pages=run["pages_reserved"] + caps.max_new_pages,
                max_candidates=(run["candidate_slots_reserved"] +
                                caps.max_new_pages * 25 + caps.max_person_searches),
                max_enrichments=run["enrichments_reserved"] + caps.max_enrichments,
                max_apollo_credits=run["credits_reserved"] + caps.max_new_credits,
                max_cost_chf=Decimal(0), chf_per_credit_ceiling=Decimal(0),
                credits_org_search_page=1, credits_org_enrichment=1,
                credits_people_search=0, credits_person_enrichment_max=1,
                retention_days=30,
                authorization_ref="user-prompt-2026-09-22-b1-900-reserve1000",
            )
            limits.require_run_authorization(phase="FRANCE_B1_READY_BASE")
            parts = connection.execute(sa.select(acquisition_census_partition).where(
                acquisition_census_partition.c.census_id == census_id,
            ).order_by(acquisition_census_partition.c.partition_id)).mappings().all()
            if len(parts) != 9:
                raise ValueError("B1 requires exactly nine commercial partitions")
            known_partition_ids = {part["partition_id"] for part in parts}
            completed_b0 = connection.execute(sa.select(acquisition_census_b0_entry).join(
                acquisition_census_candidate,
                acquisition_census_b0_entry.c.candidate_id ==
                acquisition_census_candidate.c.candidate_id,
            ).where(
                acquisition_census_candidate.c.census_id == census_id,
                acquisition_census_b0_entry.c.status == "COMPLETE",
            )).mappings().all()
            already = {row["candidate_id"] for row in completed_b0}
            already.update(row[0] for row in connection.execute(sa.select(
                acquisition_census_b1_entry.c.candidate_id,
            ).join(acquisition_census_candidate,
                   acquisition_census_b1_entry.c.candidate_id ==
                   acquisition_census_candidate.c.candidate_id).where(
                acquisition_census_candidate.c.census_id == census_id,
                acquisition_census_b1_entry.c.status == "COMPLETE",
            )))
            prior_searches = {row[0] for row in connection.execute(sa.select(
                acquisition_census_call.c.subject_hash,
            ).where(acquisition_census_call.c.census_id == census_id,
                    acquisition_census_call.c.kind == "PEOPLE_SEARCH",
                    acquisition_census_call.c.status == "COMPLETED"))}
            b0_yield: dict[str, list[int]] = defaultdict(lambda: [0, 0])
            for row in completed_b0:
                partition_id = row["stratum"].get("partition_id")
                if partition_id is None:
                    continue
                result = row["result"] or {}
                b0_yield[partition_id][0] += int(result.get("verified_email") is True)
                b0_yield[partition_id][1] += sum(
                    call.get("observed_pool_delta") if call.get("observed_pool_delta") is not None
                    else call.get("reserved", 0)
                    for call in result.get("calls", [])
                )
            for row in connection.execute(sa.select(acquisition_census_b1_entry).join(
                acquisition_census_candidate,
                acquisition_census_b1_entry.c.candidate_id ==
                acquisition_census_candidate.c.candidate_id,
            ).where(
                acquisition_census_candidate.c.census_id == census_id,
                acquisition_census_b1_entry.c.status == "COMPLETE",
            )).mappings():
                partition_id = row["stratum"].get("partition_id")
                if partition_id in known_partition_ids:
                    b0_yield[partition_id][0] += int(bool(
                        row["result"] and row["result"].get("verified_email")
                    ))
            for partition_id, reserved in connection.execute(sa.select(
                acquisition_census_call.c.partition_id,
                acquisition_census_call.c.reserved_credits,
            ).join(acquisition_census_permit,
                   acquisition_census_call.c.permit_id == acquisition_census_permit.c.permit_id)
             .where(acquisition_census_permit.c.census_id == census_id,
                    acquisition_census_permit.c.phase == "FRANCE_B1_READY_BASE")):
                if partition_id in known_partition_ids:
                    b0_yield[partition_id][1] += reserved
            cached: dict[str, set[int]] = {part["partition_id"]: {1} for part in parts}
            from signals.persistence.schema import acquisition_census_sample_page

            for row in connection.execute(sa.select(acquisition_census_sample_page).where(
                acquisition_census_sample_page.c.status == "COMPLETED",
            )).mappings():
                if row["partition_id"] in cached:
                    cached[row["partition_id"]].add(row["page"])
            for row in connection.execute(sa.select(acquisition_census_b1_page).where(
                acquisition_census_b1_page.c.status == "COMPLETED",
            )).mappings():
                if row["partition_id"] in cached:
                    cached[row["partition_id"]].add(row["page"])
            yields = tuple(PartitionYield(
                partition_id=part["partition_id"], sector=part["sector"],
                size_band=f"{part['size_min']}-{part['size_max']}",
                accessible_pages=min(500, math.ceil((part["estimated_result_count"] or 0) /
                                                    part["filters"]["per_page"])),
                cached_pages=tuple(sorted(cached[part["partition_id"]])),
                verified_emails=b0_yield[part["partition_id"]][0],
                consumed_credits=b0_yield[part["partition_id"]][1],
            ) for part in parts)
            pages = allocate_pages(yields, max_new_pages=caps.max_new_pages, seed=seed)
            rows = connection.execute(sa.select(acquisition_census_candidate).where(
                acquisition_census_candidate.c.census_id == census_id,
                acquisition_census_candidate.c.provider == "GOOGLE_WORKSPACE",
                acquisition_census_candidate.c.provider_confidence == "CONFIRMED",
                acquisition_census_candidate.c.primary_domain.is_not(None),
            ).order_by(acquisition_census_candidate.c.candidate_id)).mappings().all()
            official = {row["provider_organization_id"]: row["match_evidence"]
                        for row in connection.execute(sa.select(acquisition_census_company_match).where(
                            acquisition_census_company_match.c.census_id == census_id,
                        )).mappings()}
            occurrences = defaultdict(list)
            for row in connection.execute(sa.select(acquisition_census_occurrence).join(
                acquisition_census_partition).where(
                acquisition_census_partition.c.census_id == census_id,
            )).mappings():
                occurrences[row["candidate_id"]].append(row)
            suppressed_orgs = {row[0] for row in connection.execute(sa.select(
                acquisition_supplier.c.provider_organization_id,
            ).join(acquisition_contact_suppression,
                   acquisition_contact_suppression.c.supplier_ref == acquisition_supplier.c.supplier_ref)
             .where(acquisition_supplier.c.provider == "apollo",
                    acquisition_contact_suppression.c.scope == MILOMAIL_SUPPRESSION_SCOPE,
                    acquisition_contact_suppression.c.effective_at <= at))}
            selected: list[tuple[str, dict]] = []
            part_lookup = {part["partition_id"]: part for part in parts}
            for row in rows:
                if (row["candidate_id"] in already or
                        hashlib.sha256(f'{row["candidate_id"]}:people-search'.encode()).hexdigest()
                        in prior_searches or
                        row["provider_organization_id"] in suppressed_orgs):
                    continue
                proof = official.get(row["provider_organization_id"], {})
                if proof.get("match_confidence") == "CONFIRMED_MATCH" and proof.get("legal_status") == "CEASED":
                    continue
                try:
                    if normalize_domain(row["primary_domain"]) != row["primary_domain"]:
                        continue
                except ValueError:
                    continue
                occurrence = sorted(occurrences[row["candidate_id"]],
                                    key=lambda item: (item["observed_at"], item["partition_id"]))
                if not occurrence:
                    continue
                part = part_lookup[occurrence[0]["partition_id"]]
                selected.append((row["candidate_id"], {
                    "partition_id": part["partition_id"], "sector": part["sector"],
                    "size_band": f"{part['size_min']}-{part['size_max']}",
                    "depth": "first" if occurrence[0]["first_page"] == 1 else "deep",
                }))
            selected.sort(key=lambda item: _hash(seed, item[1]["partition_id"], item[0]))
            selected = selected[:caps.max_companies]
            plan_hash = _digest((census_id, seed, caps.__dict__,
                                 limits.model_dump(mode="json"), pool_balance,
                                 [(item.partition_id, item.page) for item in pages], selected))
            connection.execute(sa.insert(acquisition_census_b1_plan).values(
                plan_id=permit_id, census_id=census_id, plan_hash=plan_hash, seed=seed,
                caps=caps.__dict__, cumulative_limits=limits.model_dump(mode="json"),
                pool_before=pool_balance, pool_after=None,
                status="PLANNED", created_at=at, updated_at=at,
            ))
            if pages:
                connection.execute(sa.insert(acquisition_census_b1_page), [
                    {"plan_id": permit_id, "partition_id": page.partition_id,
                     "page": page.page, "allocation_reason": page.allocation_reason,
                     "status": "PLANNED", "call_id": None, "completed_at": None}
                    for page in pages
                ])
            if selected:
                connection.execute(sa.insert(acquisition_census_b1_entry), [
                    {"plan_id": permit_id, "candidate_id": candidate_id,
                     "selection_rank": rank, "stratum": stratum,
                     "status": "PLANNED", "result": None, "completed_at": None}
                    for rank, (candidate_id, stratum) in enumerate(selected, 1)
                ])
        return self.details(permit_id)

    def details(self, permit_id: str) -> dict:
        with self.engine.connect() as connection:
            plan = connection.execute(sa.select(acquisition_census_b1_plan).where(
                acquisition_census_b1_plan.c.plan_id == permit_id,
            )).mappings().one()
            pages = connection.execute(sa.select(acquisition_census_b1_page).where(
                acquisition_census_b1_page.c.plan_id == permit_id,
            ).order_by(acquisition_census_b1_page.c.partition_id,
                       acquisition_census_b1_page.c.page)).mappings().all()
            entries = connection.execute(sa.select(acquisition_census_b1_entry).where(
                acquisition_census_b1_entry.c.plan_id == permit_id,
            )).mappings().all()
            calls = connection.execute(sa.select(acquisition_census_call.c.partition_id,
                                                 acquisition_census_call.c.kind,
                                                 acquisition_census_call.c.status,
                                                 acquisition_census_call.c.reserved_credits).where(
                acquisition_census_call.c.permit_id == permit_id,
            )).all()
        partitions: dict[str, dict[str, int]] = defaultdict(lambda: {
            "companies_completed": 0, "verified_emails": 0,
            "credits_reserved": 0, "organization_pages": 0,
        })
        for row in entries:
            partition_id = row["stratum"].get("partition_id")
            if partition_id and row["status"] == "COMPLETE":
                partitions[partition_id]["companies_completed"] += 1
                partitions[partition_id]["verified_emails"] += int(bool(
                    row["result"] and row["result"].get("verified_email")
                ))
        for partition_id, kind, _status, reserved in calls:
            if partition_id:
                partitions[partition_id]["credits_reserved"] += reserved
                partitions[partition_id]["organization_pages"] += int(kind == "ORG_SEARCH")
        return {"plan_id": permit_id, "plan_hash": plan["plan_hash"],
                "status": plan["status"], "pool_before": plan["pool_before"],
                "pool_after": plan["pool_after"], "caps": plan["caps"],
                "cumulative_limits": plan["cumulative_limits"],
                "pages": [{"partition_id": row["partition_id"], "page": row["page"],
                           "status": row["status"]} for row in pages],
                "companies_planned": len(entries),
                "companies_completed": sum(row["status"] == "COMPLETE" for row in entries),
                "new_verified_emails": sum(bool(row["result"] and
                                               row["result"].get("verified_email")) for row in entries),
                "calls_by_kind": {kind: sum(call[1] == kind for call in calls)
                                  for kind in {call[1] for call in calls}},
                "credits_reserved": sum(call[3] for call in calls),
                "partition_yield": {partition_id: data for partition_id, data in
                                    sorted(partitions.items()) if
                                    data["companies_completed"] >= 5},
                "instantly_mutations": 0, "emails_sent": 0}

    def summary(self, permit_id: str) -> dict:
        details = self.details(permit_id)
        pages = details.pop("pages")
        details.pop("cumulative_limits")
        details["new_pages_planned"] = len(pages)
        details["new_pages_completed"] = sum(page["status"] == "COMPLETED" for page in pages)
        return details

    def next_planned_page(self, permit_id: str) -> dict | None:
        """Execute exploratory pages across strata before yield-weighted depth."""
        with self.engine.connect() as connection:
            row = connection.execute(sa.select(acquisition_census_b1_page).where(
                acquisition_census_b1_page.c.plan_id == permit_id,
                acquisition_census_b1_page.c.status == "PLANNED",
            ).order_by(sa.case(
                (acquisition_census_b1_page.c.allocation_reason == "EXPLORATION", 0),
                else_=1,
            ), acquisition_census_b1_page.c.partition_id,
                acquisition_census_b1_page.c.page).limit(1)).mappings().one_or_none()
        return dict(row) if row is not None else None

    def reconcile_usage(self, permit_id: str, *, pool_after: int,
                        at: dt.datetime) -> dict:
        """Record the shared-pool endpoint balance without claiming exclusive use."""
        if pool_after < 0:
            raise ValueError("Apollo pool balance is invalid")
        with self.engine.begin() as connection:
            plan = connection.execute(sa.select(acquisition_census_b1_plan).where(
                acquisition_census_b1_plan.c.plan_id == permit_id,
            ).with_for_update()).mappings().one()
            before = plan["pool_before"]
            if pool_after > before or pool_after < plan["caps"]["min_remaining_pool_balance"]:
                raise CensusReviewRequired("B1 shared pool changed outside the permitted range")
            if plan["pool_after"] is not None and plan["pool_after"] != pool_after:
                raise CensusReviewRequired("B1 reconciliation receipt is immutable")
            reserved = connection.scalar(sa.select(sa.func.coalesce(sa.func.sum(
                acquisition_census_call.c.reserved_credits), 0)).where(
                acquisition_census_call.c.permit_id == permit_id,
            )) or 0
            # A falling shared pool can include other applications. It is never
            # silently assigned to Milo Mail; the run ledger is an upper bound.
            connection.execute(sa.update(acquisition_census_b1_plan).where(
                acquisition_census_b1_plan.c.plan_id == permit_id,
            ).values(pool_after=pool_after, updated_at=at))
        return {"pool_before": before, "pool_after": pool_after,
                "shared_pool_delta": before - pool_after,
                "run_credits_reserved_upper_bound": reserved,
                "shared_pool_attribution": "AMBIGUOUS_SHARED_POOL",
                "incremental_charge_chf": "0.00",
                "allocation_cost_chf": None}

    def record_page(self, census_id: str, permit_id: str, partition_id: str,
                    page: SupplierSearchPage, *, call_id: str, at: dt.datetime) -> None:
        """Checkpoint identities and progress atomically before the next paid page."""
        with self.engine.begin() as connection:
            selected = connection.execute(sa.select(acquisition_census_b1_page).where(
                acquisition_census_b1_page.c.plan_id == permit_id,
                acquisition_census_b1_page.c.partition_id == partition_id,
                acquisition_census_b1_page.c.page == page.page,
            ).with_for_update()).mappings().one()
            call = connection.execute(sa.select(acquisition_census_call).where(
                acquisition_census_call.c.call_id == call_id,
            )).mappings().one()
            if (call["status"] != "COMPLETED" or call["permit_id"] != permit_id or
                    call["kind"] != "ORG_SEARCH" or
                    call["partition_id"] != partition_id or
                    call["result_snapshot"] != page.model_dump(mode="json")):
                raise CensusReviewRequired("B1 page differs from the completed Apollo call")
            if selected["status"] == "COMPLETED":
                if selected["call_id"] != call_id:
                    raise CensusReviewRequired("B1 page checkpoint conflict")
                return
            if selected["status"] != "PLANNED":
                raise CensusReviewRequired("B1 page requires manual review")
            part = connection.execute(sa.select(acquisition_census_partition).where(
                acquisition_census_partition.c.partition_id == partition_id,
            ).with_for_update()).mappings().one()
            if page.per_page != part["filters"]["per_page"]:
                raise CensusReviewRequired("B1 page size differs from partition")
            store = CensusStore(self.engine)
            unique = duplicates = 0
            for candidate in page.candidates:
                if not isinstance(candidate, ApolloOrganizationCandidate):
                    raise CensusReviewRequired("B1 page contains non-Apollo organization")
                created = store._record_candidate_in_transaction(
                    connection, census_id, partition_id, page.page,
                    candidate, part["sector"], at,
                )
                unique += int(created)
                duplicates += int(not created)
            seen = len(page.candidates) + len(page.rejections)
            if seen > call["candidate_slots"]:
                raise CensusReviewRequired("B1 page exceeds reserved candidate slots")
            if seen < call["candidate_slots"]:
                connection.execute(sa.update(acquisition_census_run).where(
                    acquisition_census_run.c.census_id == census_id,
                ).values(candidate_slots_reserved=
                         acquisition_census_run.c.candidate_slots_reserved -
                         (call["candidate_slots"] - seen)))
            connection.execute(sa.update(acquisition_census_partition).where(
                acquisition_census_partition.c.partition_id == partition_id,
            ).values(processed_count=part["processed_count"] + seen,
                     unique_count=part["unique_count"] + unique,
                     duplicate_count=part["duplicate_count"] + duplicates))
            connection.execute(sa.update(acquisition_census_b1_page).where(
                acquisition_census_b1_page.c.plan_id == permit_id,
                acquisition_census_b1_page.c.partition_id == partition_id,
                acquisition_census_b1_page.c.page == page.page,
            ).values(status="COMPLETED", call_id=call_id, completed_at=at))

    def add_observed_google_companies(self, census_id: str, permit_id: str,
                                      *, detector: MailProviderDetector,
                                      at: dt.datetime) -> int:
        """Use public MX only; skip previously enriched or suppressed firms."""
        with self.engine.connect() as connection:
            plan = connection.execute(sa.select(acquisition_census_b1_plan).where(
                acquisition_census_b1_plan.c.plan_id == permit_id,
            )).mappings().one()
            completed_pages = connection.execute(sa.select(acquisition_census_b1_page).where(
                acquisition_census_b1_page.c.plan_id == permit_id,
                acquisition_census_b1_page.c.status == "COMPLETED",
            )).mappings().all()
            completed_pairs = {(row["partition_id"], row["page"]) for row in completed_pages}
            if not completed_pairs:
                return 0
            occurred = connection.execute(sa.select(acquisition_census_occurrence).where(
                sa.tuple_(acquisition_census_occurrence.c.partition_id,
                          acquisition_census_occurrence.c.first_page).in_(completed_pairs),
            )).mappings().all()
            candidate_ids = {row["candidate_id"] for row in occurred}
            rows = connection.execute(sa.select(acquisition_census_candidate).where(
                acquisition_census_candidate.c.census_id == census_id,
                acquisition_census_candidate.c.candidate_id.in_(candidate_ids),
            )).mappings().all()
            official = {row["provider_organization_id"]: row["match_evidence"]
                        for row in connection.execute(sa.select(acquisition_census_company_match).where(
                            acquisition_census_company_match.c.census_id == census_id,
                        )).mappings()}
            prior_searches = {row[0] for row in connection.execute(sa.select(
                acquisition_census_call.c.subject_hash,
            ).where(acquisition_census_call.c.census_id == census_id,
                    acquisition_census_call.c.kind == "PEOPLE_SEARCH",
                    acquisition_census_call.c.status == "COMPLETED"))}
            suppressed_orgs = {row[0] for row in connection.execute(sa.select(
                acquisition_supplier.c.provider_organization_id,
            ).join(acquisition_contact_suppression,
                   acquisition_contact_suppression.c.supplier_ref == acquisition_supplier.c.supplier_ref)
             .where(acquisition_supplier.c.provider == "apollo",
                    acquisition_contact_suppression.c.scope == MILOMAIL_SUPPRESSION_SCOPE,
                    acquisition_contact_suppression.c.effective_at <= at))}
        created = 0
        for row in sorted(rows, key=lambda item: _hash(plan["seed"], item["candidate_id"])):
            proof = official.get(row["provider_organization_id"], {})
            if (row["provider_organization_id"] in suppressed_orgs or
                    hashlib.sha256(f'{row["candidate_id"]}:people-search'.encode()).hexdigest()
                    in prior_searches or
                    (proof.get("match_confidence") == "CONFIRMED_MATCH" and
                     proof.get("legal_status") == "CEASED")):
                continue
            candidate = ApolloOrganizationCandidate.model_validate(row["snapshot"])
            # Apollo's France-filtered organization result may omit its country
            # field. This is eligible for technical yield measurement only;
            # policy still HOLDs an unresolved country before any SEND.
            if candidate.country_code not in (None, "FR") or not candidate.primary_domain:
                continue
            try:
                domain = normalize_domain(candidate.primary_domain)
            except ValueError:
                continue
            if domain != candidate.primary_domain:
                continue
            provider = detector.detect_domain(domain, observed_at=at)
            with self.engine.begin() as connection:
                connection.execute(sa.update(acquisition_census_candidate).where(
                    acquisition_census_candidate.c.candidate_id == row["candidate_id"],
                ).values(provider=provider.provider.value,
                         provider_confidence=provider.confidence.value,
                         provider_evidence={
                             "mx_records": list(provider.mx_records),
                             "source": provider.source,
                             "observed_at": provider.observed_at.isoformat(),
                             "expires_at": provider.expires_at.isoformat(),
                             "detector_version": provider.detector_version,
                         },
                         updated_at=at))
                if provider.provider != MailProvider.GOOGLE_WORKSPACE or provider.confidence.value != "CONFIRMED":
                    continue
                existing = connection.scalar(sa.select(sa.func.count()).select_from(
                    acquisition_census_b1_entry).where(
                    acquisition_census_b1_entry.c.plan_id == permit_id,
                )) or 0
                if existing >= plan["caps"]["max_companies"]:
                    break
                if connection.scalar(sa.select(sa.func.count()).select_from(
                    acquisition_census_b1_entry).where(
                    acquisition_census_b1_entry.c.plan_id == permit_id,
                    acquisition_census_b1_entry.c.candidate_id == row["candidate_id"],
                )):
                    continue
                if connection.scalar(sa.select(sa.func.count()).select_from(
                    acquisition_census_b0_entry).where(
                    acquisition_census_b0_entry.c.candidate_id == row["candidate_id"],
                    acquisition_census_b0_entry.c.status == "COMPLETE",
                )):
                    continue
                occurrence = next((item for item in occurred
                                   if item["candidate_id"] == row["candidate_id"]), None)
                if occurrence is None:
                    continue
                part = connection.execute(sa.select(acquisition_census_partition).where(
                    acquisition_census_partition.c.partition_id == occurrence["partition_id"],
                )).mappings().one()
                connection.execute(sa.insert(acquisition_census_b1_entry).values(
                    plan_id=permit_id, candidate_id=row["candidate_id"],
                    selection_rank=existing + 1,
                    stratum={"partition_id": part["partition_id"],
                             "sector": part["sector"],
                             "size_band": f"{part['size_min']}-{part['size_max']}",
                             "depth": "deep"},
                    status="PLANNED", result=None, completed_at=None,
                ))
                created += 1
        return created
