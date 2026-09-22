"""Public, reproducible page sampling for the Milo Mail A1 organization census."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from statistics import NormalDist

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.persistence.schema import (
    acquisition_census_call,
    acquisition_census_partition,
    acquisition_census_run,
    acquisition_census_sample_page,
    acquisition_census_sample_plan,
)
from signals.supplier_discovery.contracts import SupplierSearchPage

MAX_APOLLO_PAGES = 500


@dataclass(frozen=True)
class SelectedPage:
    page: int
    block_start: int
    block_end: int


def public_seed(permit_id: str) -> str:
    """Bind the public sampling seed to the permit without using a secret."""
    if not permit_id.strip():
        raise ValueError("sample permit id is required")
    return hashlib.sha256(f"milomail-a1-sample-v1\0{permit_id}".encode()).hexdigest()


def select_pages(*, partition_id: str, total_pages: int, seed: str,
                 max_new_pages: int = 9) -> tuple[SelectedPage, ...]:
    """Select one page uniformly within each disjoint depth block."""
    if not partition_id or len(seed) != 64 or total_pages < 0 or max_new_pages < 0:
        raise ValueError("invalid A1 page-selection inputs")
    accessible = min(total_pages, MAX_APOLLO_PAGES)
    count = min(max_new_pages, max(accessible - 1, 0))
    if count == 0:
        return ()
    available = accessible - 1
    selected: list[SelectedPage] = []
    for block in range(count):
        first = 2 + block * available // count
        last = 1 + (block + 1) * available // count
        digest = hashlib.sha256(
            f"{seed}\0{partition_id}\0{block}".encode()
        ).digest()
        page = first + int.from_bytes(digest, "big") % (last - first + 1)
        selected.append(SelectedPage(page=page, block_start=first, block_end=last))
    return tuple(selected)


def wilson_interval(successes: int, total: int, *, confidence: float = 0.95
                    ) -> tuple[float, float]:
    """Wilson score interval for an observed binomial proportion."""
    if total < 0 or successes < 0 or successes > total or not 0 < confidence < 1:
        raise ValueError("invalid binomial interval inputs")
    if total == 0:
        return (0.0, 1.0)
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    observed = successes / total
    z2 = z * z
    denominator = 1 + z2 / total
    center = (observed + z2 / (2 * total)) / denominator
    radius = z * math.sqrt(
        observed * (1 - observed) / total + z2 / (4 * total * total)
    ) / denominator
    return (max(0.0, center - radius), min(1.0, center + radius))


def _hash_json(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str,
    ).encode()).hexdigest()


class SamplePlanStore:
    """Freeze the A1 page schedule before a permit or paid search exists."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _a0_pages(connection: sa.Connection, census_id: str) -> tuple[tuple[dict, SupplierSearchPage, str], ...]:
        partitions = connection.execute(sa.select(acquisition_census_partition).where(
            acquisition_census_partition.c.census_id == census_id,
        ).order_by(acquisition_census_partition.c.partition_id)).mappings().all()
        if len(partitions) != 9:
            raise ValueError("A1 requires exactly nine A0 partitions")
        pages: list[tuple[dict, SupplierSearchPage, str]] = []
        for partition in partitions:
            calls = connection.execute(sa.select(acquisition_census_call).where(
                acquisition_census_call.c.census_id == census_id,
                acquisition_census_call.c.partition_id == partition["partition_id"],
                acquisition_census_call.c.kind == "ORG_SEARCH",
            )).mappings().all()
            cached = [row for row in calls if row["status"] == "COMPLETED" and
                      isinstance(row["result_snapshot"], dict) and
                      row["result_snapshot"].get("page") == 1]
            if len(cached) != 1 or partition["cursor_page"] < 2:
                raise ValueError("A0 cache must contain one completed first page per partition")
            page = SupplierSearchPage.model_validate(cached[0]["result_snapshot"])
            if page.per_page != partition["filters"]["per_page"]:
                raise ValueError("A0 cache page size differs from partition filters")
            pages.append((dict(partition), page, cached[0]["call_id"]))
        return tuple(pages)

    def plan(self, census_id: str, *, permit_id: str, at, max_new_pages: int = 81) -> dict:
        if not 1 <= max_new_pages <= 81 or not 8 <= len(permit_id) <= 64:
            raise ValueError("A1 sample page cap or permit id is invalid")
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("sample plan time must be timezone-aware")
        with self.engine.begin() as connection:
            run = connection.execute(sa.select(acquisition_census_run).where(
                acquisition_census_run.c.census_id == census_id,
            ).with_for_update()).mappings().one()
            if run["status"] != "ACTIVE" or run["pages_reserved"] != 9 or run["credits_reserved"] != 9:
                raise ValueError("A1 requires the completed nine-page A0 baseline")
            baseline = self._a0_pages(connection, census_id)
            baseline_hash = _hash_json([
                (part["partition_id"], call_id, page.model_dump(mode="json"))
                for part, page, call_id in baseline
            ])
            seed = public_seed(permit_id)
            capacities = [min(max(page.total_pages - 1, 0), MAX_APOLLO_PAGES - 1)
                          for _, page, _ in baseline]
            assigned = [0] * len(baseline)
            for _ in range(max_new_pages):
                next_index = next((index for index in range(len(baseline))
                                   if assigned[index] < capacities[index] and
                                   assigned[index] == min(assigned)), None)
                if next_index is None:
                    next_index = next((index for index in range(len(baseline))
                                       if assigned[index] < capacities[index]), None)
                if next_index is None:
                    break
                assigned[next_index] += 1
            entries = [
                {"plan_id": permit_id, "partition_id": part["partition_id"],
                 "page": item.page, "block_start": item.block_start,
                 "block_end": item.block_end, "status": "PLANNED",
                 "call_id": None, "observed_at": None}
                for (part, page, _), count in zip(baseline, assigned, strict=True)
                for item in select_pages(partition_id=part["partition_id"],
                                         total_pages=page.total_pages, seed=seed,
                                         max_new_pages=count)
            ]
            if not entries:
                raise ValueError("A1 sample has no accessible new pages")
            entries.sort(key=lambda item: (item["partition_id"], item["page"]))
            plan_hash = _hash_json({
                "census_id": census_id, "seed": seed, "baseline": baseline_hash,
                "requested_new_pages": max_new_pages,
                "pages": [(item["partition_id"], item["page"], item["block_start"],
                           item["block_end"]) for item in entries],
            })
            prior = connection.execute(sa.select(acquisition_census_sample_plan).where(
                acquisition_census_sample_plan.c.plan_id == permit_id,
            )).mappings().one_or_none()
            if prior:
                if (prior["census_id"] != census_id or prior["seed"] != seed or
                        prior["plan_hash"] != plan_hash or
                        prior["a0_baseline_hash"] != baseline_hash or
                        prior["requested_new_pages"] != max_new_pages):
                    raise ValueError("A1 sample plan is immutable")
            else:
                connection.execute(sa.insert(acquisition_census_sample_plan).values(
                    plan_id=permit_id, census_id=census_id, seed=seed,
                    plan_hash=plan_hash, a0_baseline_hash=baseline_hash,
                    requested_new_pages=max_new_pages, created_at=at,
                ))
                connection.execute(sa.insert(acquisition_census_sample_page), entries)
        return self.details(permit_id)

    def details(self, permit_id: str) -> dict:
        with self.engine.connect() as connection:
            plan = connection.execute(sa.select(acquisition_census_sample_plan).where(
                acquisition_census_sample_plan.c.plan_id == permit_id,
            )).mappings().one()
            pages = connection.execute(sa.select(acquisition_census_sample_page).where(
                acquisition_census_sample_page.c.plan_id == permit_id,
            ).order_by(acquisition_census_sample_page.c.partition_id,
                       acquisition_census_sample_page.c.page)).mappings().all()
        return {
            "plan_id": permit_id, "census_id": plan["census_id"],
            "seed": plan["seed"], "plan_hash": plan["plan_hash"],
            "a0_baseline_hash": plan["a0_baseline_hash"],
            "a0_cached_pages": 9, "requested_new_pages": plan["requested_new_pages"],
            "new_pages_planned": len(pages),
            "pages": [dict(page) for page in pages],
        }

    def verify_baseline(self, permit_id: str) -> bool:
        with self.engine.connect() as connection:
            plan = connection.execute(sa.select(acquisition_census_sample_plan).where(
                acquisition_census_sample_plan.c.plan_id == permit_id,
            )).mappings().one()
            baseline = self._a0_pages(connection, plan["census_id"])
        return plan["a0_baseline_hash"] == _hash_json([
            (part["partition_id"], call_id, page.model_dump(mode="json"))
            for part, page, call_id in baseline
        ])
