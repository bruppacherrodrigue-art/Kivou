from __future__ import annotations

import pytest

from signals.contact_discovery.contracts import (
    MAX_ENRICHMENT_ATTEMPTS,
    MAX_SEARCH_PAGES,
    MAX_SEARCH_RESULTS,
    PROFILE_VERSION,
    PeopleSearchCandidate,
)
from signals.contact_discovery.identity import contact_ref_for
from signals.contact_discovery.profile import (
    RUNTIME_QA_PROFILE_VERSION,
    build_decision_maker_profile,
)
from signals.contact_discovery.ranking import classify_title, rank_candidates


def test_profile_is_kivou_owned_bounded_and_excludes_stream_version() -> None:
    profile = build_decision_maker_profile(
        acquisition_opportunity_id="ao-1",
        supplier_ref="supplier-1",
        provider_organization_id="apollo-org-1",
    )

    assert profile.profile_version == PROFILE_VERSION
    assert profile.max_pages == MAX_SEARCH_PAGES == 1
    assert profile.per_page == MAX_SEARCH_RESULTS == 25
    assert profile.max_enrichment_attempts == MAX_ENRICHMENT_ATTEMPTS == 3
    assert profile.contact_email_statuses == ("verified",)
    assert profile.include_similar_titles is False
    assert {"head", "director", "manager", "c_suite"}.issubset(profile.person_seniorities)
    assert "Sales Director" in profile.person_titles
    assert "Directeur commercial" in profile.person_titles
    assert {
        "Directrice commerciale",
        "Directrice des ventes",
        "Directrice du développement commercial",
        "Directrice générale",
        "Fondatrice",
        "Dirigeante",
        "Responsable commerciale",
        "Responsable du développement commercial",
    }.issubset(profile.person_titles)
    assert "expected_opportunity_version" not in profile.model_dump()
    assert len(profile.profile_fingerprint) == 64


def test_profile_fingerprint_is_deterministic_and_provider_semantic_only() -> None:
    first = build_decision_maker_profile(
        acquisition_opportunity_id="ao-1",
        supplier_ref="supplier-1",
        provider_organization_id="apollo-org-1",
    )
    second = build_decision_maker_profile(
        acquisition_opportunity_id="ao-1",
        supplier_ref="supplier-1",
        provider_organization_id="apollo-org-1",
    )

    assert first == second
    assert first.profile_fingerprint == second.profile_fingerprint


def test_profile_supports_a_closed_versioned_seniority_variant() -> None:
    default = build_decision_maker_profile(
        acquisition_opportunity_id="ao-1",
        supplier_ref="supplier-1",
        provider_organization_id="apollo-org-1",
    )
    bounded = build_decision_maker_profile(
        acquisition_opportunity_id="ao-1",
        supplier_ref="supplier-1",
        provider_organization_id="apollo-org-1",
        profile_version=RUNTIME_QA_PROFILE_VERSION,
    )

    assert bounded.profile_version == RUNTIME_QA_PROFILE_VERSION
    assert bounded.person_seniorities == (
        "owner",
        "founder",
        "c_suite",
        "vp",
        "head",
        "director",
    )
    assert "manager" not in bounded.person_seniorities
    assert bounded.profile_fingerprint != default.profile_fingerprint
    with pytest.raises(ValueError, match="unsupported decision-maker search profile version"):
        build_decision_maker_profile(
            acquisition_opportunity_id="ao-1",
            supplier_ref="supplier-1",
            provider_organization_id="apollo-org-1",
            profile_version="arbitrary-profile",
        )


def test_profile_rejects_limits_outside_approved_bounds() -> None:
    profile = build_decision_maker_profile(
        acquisition_opportunity_id="ao-1",
        supplier_ref="supplier-1",
        provider_organization_id="apollo-org-1",
    )

    with pytest.raises(ValueError):
        profile.model_copy(update={"max_pages": 2}, deep=True).__class__.model_validate(
            {**profile.model_dump(), "max_pages": 2}
        )
    with pytest.raises(ValueError):
        profile.__class__.model_validate({**profile.model_dump(), "per_page": 26})
    with pytest.raises(ValueError):
        profile.__class__.model_validate({**profile.model_dump(), "max_enrichment_attempts": 4})


def _candidate(person_id: str, title: str, position: int) -> PeopleSearchCandidate:
    return PeopleSearchCandidate(
        provider_person_id=person_id,
        first_name="Alex",
        last_name_obfuscated="Du***d",
        title=title,
        provider_position=position,
        organization_name="Supplier SA",
        provider_refreshed_at=None,
        has_email=True,
    )


def test_commercial_roles_outrank_operational_roles_without_llm() -> None:
    ranked = rank_candidates(
        (
            _candidate("person-ops", "Director of Operations", 0),
            _candidate("person-ceo", "CEO", 1),
            _candidate("person-sales", "Sales Director", 2),
            _candidate("person-fr", "Responsable commercial", 3),
        )
    )

    assert [item.candidate.provider_person_id for item in ranked] == [
        "person-sales",
        "person-fr",
        "person-ceo",
    ]
    assert all(item.role_tier in {1, 2, 3, 4} for item in ranked)


@pytest.mark.parametrize(
    ("title", "tier"),
    [
        ("Directrice commerciale", 1),
        ("Directrice des ventes", 1),
        ("Directrice du développement commercial", 2),
        ("Responsable du développement commercial", 2),
        ("Responsable commerciale", 3),
        ("Directrice générale", 4),
        ("Fondatrice", 4),
        ("Dirigeante", 4),
    ],
)
def test_french_literal_variants_share_the_kivou_role_classifier(title, tier) -> None:
    classified = classify_title(title)

    assert classified is not None
    assert classified.role_tier == tier


def test_unsupported_role_is_not_classified_as_a_decision_maker() -> None:
    assert classify_title("CTO") is None


def test_ranking_is_stable_when_provider_order_changes() -> None:
    candidates = (
        _candidate("person-b", "Sales Director", 0),
        _candidate("person-a", "Sales Director", 1),
    )

    first = rank_candidates(candidates)
    second = rank_candidates(tuple(reversed(candidates)))

    assert (
        [item.candidate.provider_person_id for item in first]
        == [item.candidate.provider_person_id for item in second]
        == ["person-a", "person-b"]
    )


def test_contact_identity_is_scoped_to_supplier_not_email_or_name() -> None:
    original = contact_ref_for("apollo", "person-1", "supplier-1")
    replay = contact_ref_for("apollo", "person-1", "supplier-1")
    changed_employer = contact_ref_for("apollo", "person-1", "supplier-2")

    assert original == replay
    assert changed_employer != original
    assert len(original) == 64
