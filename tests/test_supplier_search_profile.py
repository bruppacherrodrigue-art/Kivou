from __future__ import annotations

import pytest
from pydantic import ValidationError

from signals.supplier_discovery.contracts import SupplierTargetingConfig
from signals.supplier_discovery.profile import build_supplier_search_profile


def test_supplier_search_profile_is_deterministic_and_bounded() -> None:
    config = SupplierTargetingConfig(
        organization_locations=("Switzerland",),
        organization_not_locations=("United States",),
        employee_ranges=("11,50",),
        max_pages=1,
        per_page=100,
        candidate_cap=100,
        search_too_broad_threshold=10_000,
    )
    first = build_supplier_search_profile(
        signal_ref="procurement-opportunity:opp-public-1",
        representative_award_key="award-1",
        need_categories=("equipment_or_rental", "workforce_capacity"),
        targeting=config,
    )
    second = build_supplier_search_profile(
        signal_ref="procurement-opportunity:opp-public-1",
        representative_award_key="award-1",
        need_categories=("workforce_capacity", "equipment_or_rental"),
        targeting=config,
    )

    assert first == second
    assert first.profile_version == "supplier-search-v1"
    assert first.keyword_tags == (
        "equipment rental",
        "industrial equipment",
        "staffing",
        "workforce solutions",
    )
    assert len(first.profile_fingerprint) == 64


def test_profile_fingerprint_binds_search_too_broad_threshold() -> None:
    base = SupplierTargetingConfig(search_too_broad_threshold=10_000)
    changed = base.model_copy(update={"search_too_broad_threshold": 9_999})
    args = {
        "signal_ref": "procurement-opportunity:opp-public-1",
        "representative_award_key": "award-1",
        "need_categories": ("workforce_capacity",),
    }

    assert build_supplier_search_profile(**args, targeting=base).profile_fingerprint != (
        build_supplier_search_profile(**args, targeting=changed).profile_fingerprint
    )


def test_targeting_rejects_unbounded_or_unknown_provider_parameters() -> None:
    with pytest.raises(ValidationError):
        SupplierTargetingConfig(max_pages=6)
    with pytest.raises(ValidationError):
        SupplierTargetingConfig(per_page=101)
    with pytest.raises(ValidationError):
        SupplierTargetingConfig(candidate_cap=501)
    with pytest.raises(ValidationError):
        SupplierTargetingConfig.model_validate({"raw_apollo_query": {"page": 500}})
    with pytest.raises(ValidationError):
        build_supplier_search_profile(
            signal_ref="materialized-signal:customer-private-1",
            representative_award_key="award-1",
            need_categories=("workforce_capacity",),
            targeting=SupplierTargetingConfig(),
        )
