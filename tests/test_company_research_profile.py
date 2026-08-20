from __future__ import annotations

import pytest
from pydantic import ValidationError

from signals.company_research.profile import (
    build_company_research_profile,
    policy_action_fingerprint,
    provider_request_fingerprint,
)


def test_company_research_profile_contains_only_provider_request_semantics() -> None:
    profile = build_company_research_profile("apollo-org-1")

    assert profile.profile_version == "company-research-v1"
    assert profile.provider == "apollo"
    assert profile.provider_organization_id == "apollo-org-1"
    assert profile.endpoint_kind == "exact_organization_id"
    assert profile.max_response_bytes == 1_048_576
    assert not {
        "acquisition_opportunity_id",
        "supplier_ref",
        "contact_ref",
        "evaluation_id",
        "expected_opportunity_version",
        "run_id",
        "correlation_id",
        "timestamp",
    } & set(type(profile).model_fields)


def test_provider_and_policy_action_fingerprints_have_distinct_scope() -> None:
    profile = build_company_research_profile("apollo-org-1")

    provider_one = provider_request_fingerprint(profile)
    provider_two = provider_request_fingerprint(build_company_research_profile("apollo-org-1"))
    action_one = policy_action_fingerprint(
        profile,
        acquisition_opportunity_id="ao-1",
        supplier_ref="supplier-1",
        contact_ref="contact-1",
    )
    action_two = policy_action_fingerprint(
        profile,
        acquisition_opportunity_id="ao-2",
        supplier_ref="supplier-1",
        contact_ref="contact-2",
    )

    assert provider_one == provider_two
    assert action_one != action_two
    assert provider_one != action_one


def test_provider_organization_changes_all_provider_fingerprints() -> None:
    first = build_company_research_profile("apollo-org-1")
    second = build_company_research_profile("apollo-org-2")

    assert first.profile_fingerprint != second.profile_fingerprint
    assert provider_request_fingerprint(first) != provider_request_fingerprint(second)


@pytest.mark.parametrize(
    "unsafe_id",
    ("../people/search", "abc?x=1", "apollo/org", "abc#fragment", "."),
)
def test_provider_organization_id_is_one_bounded_symbolic_path_segment(
    unsafe_id: str,
) -> None:
    with pytest.raises(ValidationError):
        build_company_research_profile(unsafe_id)
