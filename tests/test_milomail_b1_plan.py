"""B1 planning never turns an absent cap into an unlimited Apollo run."""

from __future__ import annotations

import pytest

from signals.acquisition_programs.census_b1 import (
    B1Caps,
    PartitionYield,
    allocate_pages,
)


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
