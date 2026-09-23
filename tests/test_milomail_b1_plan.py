"""B1 planning never turns an absent cap into an unlimited Apollo run."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from test_milomail_a1_plan import NOW, _a0

from signals.acquisition_programs.census_b1 import (
    B1Caps,
    B1PlanStore,
    PartitionYield,
    allocate_pages,
)
from signals.persistence.schema import acquisition_census_b1_page, acquisition_census_run


def test_prepaid_b1_budget_has_hard_reserve_and_zero_defaults() -> None:
    assert B1Caps().enabled is False
    assert B1Caps().max_new_credits == 0
    assert B1Caps().available_credits(1956) == 0
    caps = B1Caps(enabled=True, max_new_credits=900, max_new_pages=220,
                  max_companies=1200, max_person_searches=1200,
                  max_enrichments=680)
    assert caps.available_credits(1956) == 900
    assert caps.available_credits(1200) == 200
    assert caps.available_credits(1000) == 0
    assert caps.can_reserve(balance=1001, spent=899, credits=1)
    assert not caps.can_reserve(balance=1000, spent=899, credits=1)
    assert not caps.can_reserve(balance=1956, spent=900, credits=1)
    with pytest.raises(ValueError):
        B1Caps(enabled=True, max_new_credits=901, max_new_pages=1,
               max_companies=1, max_person_searches=1, max_enrichments=1)


def test_b1_page_plan_is_deterministic_spread_and_skips_cached_pages() -> None:
    partitions = tuple(
        PartitionYield(partition_id=f"p{i}", sector=("agency", "consulting", "recruiting")[i // 3],
                       size_band=("1-3", "4-6", "7-10")[i % 3],
                       accessible_pages=80, cached_pages=(1, 8, 20),
                       verified_emails=12 if i == 0 else 2,
                       consumed_credits=13 if i == 0 else 5)
        for i in range(9)
    )
    first = allocate_pages(partitions, max_new_pages=36, seed="public-b1-seed")
    assert first == allocate_pages(partitions, max_new_pages=36, seed="public-b1-seed")
    assert len(first) == 36
    assert len({(item.partition_id, item.page) for item in first}) == 36
    assert {item.partition_id for item in first} == {f"p{i}" for i in range(9)}
    assert all(2 <= item.page <= 80 and item.page not in {8, 20} for item in first)
    assert len({item.page // 20 for item in first if item.partition_id == "p0"}) >= 2
    assert sum(item.partition_id == "p0" for item in first) > sum(
        item.partition_id == "p8" for item in first)


def test_b1_page_plan_respects_apollo_display_window() -> None:
    one = PartitionYield(partition_id="p", sector="agency", size_band="1-3",
                         accessible_pages=3000, cached_pages=(1, 2),
                         verified_emails=1, consumed_credits=1)
    pages = allocate_pages((one,), max_new_pages=600, seed="public")
    assert len(pages) == 498
    assert max(item.page for item in pages) <= 500
    assert 2 not in {item.page for item in pages}


def test_exploratory_pages_run_before_depth_yield_pages() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    acquisition_census_b1_page.create(engine)
    with engine.begin() as connection:
        connection.execute(sa.insert(acquisition_census_b1_page), [
            {"plan_id": "synthetic-b1", "partition_id": "a", "page": 50,
             "allocation_reason": "OBSERVED_YIELD", "status": "PLANNED"},
            {"plan_id": "synthetic-b1", "partition_id": "b", "page": 10,
             "allocation_reason": "EXPLORATION", "status": "PLANNED"},
            {"plan_id": "synthetic-b1", "partition_id": "c", "page": 20,
             "allocation_reason": "EXPLORATION", "status": "PLANNED"},
        ])
    store = B1PlanStore(engine)
    assert store.next_planned_page("synthetic-b1")["partition_id"] == "b"
    with engine.begin() as connection:
        connection.execute(sa.update(acquisition_census_b1_page).where(
            acquisition_census_b1_page.c.partition_id == "b",
        ).values(status="COMPLETED"))
    assert store.next_planned_page("synthetic-b1")["partition_id"] == "c"


def test_continuation_plan_freezes_new_pages_under_original_900_credit_envelope() -> None:
    engine, census_id = _a0()
    with engine.begin() as connection:
        connection.execute(sa.update(acquisition_census_run).where(
            acquisition_census_run.c.census_id == census_id,
        ).values(pages_reserved=100, candidate_slots_reserved=2450,
                 enrichments_reserved=89, credits_reserved=1000,
                 active_sample_plan_id="synthetic-a1"))
    caps = B1Caps(enabled=True, max_new_credits=400, max_new_pages=10,
                  max_companies=184, max_person_searches=184,
                  max_enrichments=184)
    plan = B1PlanStore(engine).plan(
        census_id, permit_id="synthetic-b1-continue", caps=caps,
        pool_balance=1500, seed="synthetic-public-continuation", at=NOW,
    )
    assert len(plan["pages"]) == 10
    assert plan["cumulative_limits"]["max_apollo_credits"] == 1400
    assert all(row["page"] > 1 for row in plan["pages"])
    with engine.begin() as connection:
        connection.execute(sa.update(acquisition_census_run).where(
            acquisition_census_run.c.census_id == census_id,
        ).values(credits_reserved=1400))
    with pytest.raises(ValueError, match="cumulative 900-credit"):
        B1PlanStore(engine).plan(
            census_id, permit_id="synthetic-b1-over-cap", caps=caps,
            pool_balance=1500, seed="synthetic-public-continuation", at=NOW,
        )
