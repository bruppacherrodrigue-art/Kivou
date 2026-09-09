from __future__ import annotations

import datetime as dt

from signals.acquisition_runtime.fake_providers import build_fake_apollo_components
from signals.supplier_discovery.contracts import SupplierSearchProfile


def test_fake_apollo_is_deterministic_and_returns_named_verified_contact() -> None:
    profile = SupplierSearchProfile(
        signal_ref="procurement-opportunity:signal-001",
        representative_award_key="award-001",
        need_categories=("bardage",),
        keyword_tags=("bardage",),
        organization_locations=("Auvergne-Rhône-Alpes",),
        employee_ranges=("5,250",),
        max_pages=1,
        per_page=25,
        candidate_cap=25,
        search_too_broad_threshold=200,
        profile_fingerprint="a" * 64,
    )
    observed = dt.datetime(2026, 9, 9, tzinfo=dt.UTC)
    components = build_fake_apollo_components()
    first = components.organization_search.search_page(profile, page=1, observed_at=observed)
    second = components.organization_search.search_page(profile, page=1, observed_at=observed)
    assert first == second
    org = first.candidates[0]
    people = components.contact_discovery.search_people(
        type("Profile", (), {"provider_organization_id": org.provider_organization_id})(),
        observed_at=observed,
    )
    contact = components.contact_discovery.enrich_person(
        people.candidates[0].provider_person_id, observed_at=observed
    )
    assert contact is not None
    assert contact.business_email is not None
    assert contact.provider_email_status == "verified"
    assert contact.title == "Directeur commercial"
