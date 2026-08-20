from __future__ import annotations

import datetime as dt

import pytest

from signals.company_research.contracts import (
    ApolloOrganizationObservation,
    CompanySizeBand,
    ResearchCompleteness,
    ResearchGap,
    SupplierIdentityStatus,
)
from signals.company_research.prebuild import build_acquisition_prospect_prebuild

NOW = dt.datetime(2026, 8, 20, 12, tzinfo=dt.UTC)


def _observation(**overrides: object) -> ApolloOrganizationObservation:
    values: dict[str, object] = {
        "provider_organization_id": "apollo-org-1",
        "provider_company_name": "Acme SA",
        "provider_primary_domain": "acme.example",
        "provider_website_url": "https://acme.example",
        "provider_country": "Switzerland",
        "provider_industry": "software",
        "provider_employee_count": 120,
        "provider_founded_year": 2015,
        "provider_short_description": "B2B software company",
        "provider_keywords": ("b2b", "software"),
        "provider_observed_at": NOW,
        "provider_source_fingerprint": "a" * 64,
        "research_gaps": (),
    }
    values.update(overrides)
    return ApolloOrganizationObservation(**values)


@pytest.mark.parametrize(
    ("employees", "expected"),
    [
        (None, CompanySizeBand.UNKNOWN),
        (9, CompanySizeBand.MICRO),
        (10, CompanySizeBand.SMB),
        (249, CompanySizeBand.SMB),
        (250, CompanySizeBand.MID_MARKET),
        (999, CompanySizeBand.MID_MARKET),
        (1000, CompanySizeBand.ENTERPRISE),
    ],
)
def test_size_band_boundaries(employees: int | None, expected: CompanySizeBand) -> None:
    gaps = () if employees is not None else (ResearchGap.MISSING_EMPLOYEE_COUNT,)
    prebuild = build_acquisition_prospect_prebuild(
        acquisition_opportunity_id="ao-1",
        signal_ref="procurement-opportunity:opp-1",
        supplier_ref="supplier-1",
        contact_ref="contact-1",
        supplier_identity_status=SupplierIdentityStatus.PROVIDER_IDENTIFIED,
        contact_role_profile_version="decision-maker-search-v1",
        contact_role_tier=1,
        observation=_observation(
            provider_employee_count=employees,
            research_gaps=gaps,
        ),
    )

    assert prebuild.size_band is expected


def test_prebuild_is_limited_when_required_company_fact_is_unusable() -> None:
    observation = _observation(
        provider_primary_domain=None,
        provider_website_url=None,
        research_gaps=(ResearchGap.MISSING_DOMAIN_OR_WEBSITE,),
    )

    prebuild = build_acquisition_prospect_prebuild(
        acquisition_opportunity_id="ao-1",
        signal_ref="procurement-opportunity:opp-1",
        supplier_ref="supplier-1",
        contact_ref="contact-1",
        supplier_identity_status=SupplierIdentityStatus.DOMAIN_CONFLICT,
        contact_role_profile_version="decision-maker-search-v1",
        contact_role_tier=2,
        observation=observation,
    )

    assert prebuild.research_completeness is ResearchCompleteness.LIMITED
    assert prebuild.research_gaps == (ResearchGap.MISSING_DOMAIN_OR_WEBSITE,)
    assert prebuild.supplier_identity_status is SupplierIdentityStatus.DOMAIN_CONFLICT


def test_complete_prebuild_is_deterministic_and_has_no_decision_fields() -> None:
    kwargs = {
        "acquisition_opportunity_id": "ao-1",
        "signal_ref": "procurement-opportunity:opp-1",
        "supplier_ref": "supplier-1",
        "contact_ref": "contact-1",
        "supplier_identity_status": SupplierIdentityStatus.PROVIDER_IDENTIFIED,
        "contact_role_profile_version": "decision-maker-search-v1",
        "contact_role_tier": 1,
        "observation": _observation(),
    }

    first = build_acquisition_prospect_prebuild(**kwargs)
    second = build_acquisition_prospect_prebuild(**kwargs)

    assert first.research_completeness is ResearchCompleteness.COMPLETE
    assert first.prebuild_fingerprint == second.prebuild_fingerprint
    forbidden = {"fit_score", "lead_score", "send", "decision", "purchase_intent"}
    assert not forbidden & set(type(first).model_fields)
