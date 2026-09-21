"""Configured Milo Mail profiles drive Kivou's existing Apollo adapters."""

import datetime as dt
from pathlib import Path

import httpx

from signals.acquisition_programs.config import load_program_config
from signals.acquisition_programs.discovery import (
    build_program_contact_profile,
    build_program_search_profile,
)
from signals.company_research.apollo import ApolloCompanyResearchClient
from signals.company_research.profile import build_company_research_profile
from signals.contact_discovery.apollo import ApolloContactDiscoveryClient
from signals.supplier_discovery.apollo import ApolloOrganizationSearchClient

CONFIG = load_program_config(
    Path(__file__).resolve().parents[1] / "ops/examples/milomail-acquisition.json.example"
)
NOW = dt.datetime(2026, 9, 21, tzinfo=dt.UTC)


def test_program_organization_profile_uses_existing_apollo_adapter() -> None:
    observed: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json={
            "organizations": [{
                "id": "org-1", "name": "Agence Exemple", "primary_domain": "agence.fr",
                "website_url": "https://agence.fr", "country": "France", "industry": "Marketing",
            }],
            "pagination": {"page": 1, "per_page": 25, "total_entries": 1, "total_pages": 1},
        })

    client = ApolloOrganizationSearchClient(
        api_key="synthetic-test-key", client=httpx.Client(transport=httpx.MockTransport(handle))
    )
    profile = build_program_search_profile(CONFIG)
    page = client.search_page(profile, page=1, observed_at=NOW)
    assert page.candidates[0].country_code == "FR"
    assert page.candidates[0].source_fingerprint
    assert observed[0].url.params.get("organization_num_employees_ranges[]") == "1,10"
    assert observed[0].url.params.get("organization_locations[]") == "France"
    assert "procurement-opportunity:" not in profile.profile_ref


def test_program_contact_profile_limits_apollo_to_founder_roles() -> None:
    observed: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(200, json={
            "total_entries": 1,
            "people": [{"id": "person-1", "title": "Founder", "has_email": True}],
        })

    client = ApolloContactDiscoveryClient(
        api_key="synthetic-test-key", client=httpx.Client(transport=httpx.MockTransport(handle))
    )
    profile = build_program_contact_profile(
        CONFIG, acquisition_opportunity_id="opp-1", supplier_ref="sup-1",
        provider_organization_id="org-1", organization_domain="agence.fr",
    )
    page = client.search_people(profile, observed_at=NOW)
    assert page.candidates[0].title == "Founder"
    assert "Founder" in observed[0].url.params.get_list("person_titles[]")
    assert "Sales Manager" not in observed[0].url.params.get_list("person_titles[]")


def test_existing_apollo_company_and_person_adapters_return_bounded_evidence() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/organizations/org-1":
            return httpx.Response(200, json={"organization": {
                "id": "org-1", "name": "Agence Exemple", "primary_domain": "agence.fr",
                "website_url": "https://agence.fr", "country": "France", "industry": "Marketing",
                "estimated_num_employees": 5, "keywords": ["agence digitale"],
                "phone": "must-not-be-retained",
            }})
        if request.url.path == "/api/v1/people/match":
            return httpx.Response(200, json={"person": {
                "id": "person-1", "organization_id": "org-1", "title": "Founder",
                "email": "founder@agence.fr", "email_status": "verified",
                "phone_number": "must-not-be-retained",
            }})
        raise AssertionError("unexpected provider endpoint")

    transport = httpx.MockTransport(handle)
    company = ApolloCompanyResearchClient(
        api_key="synthetic-test-key", client=httpx.Client(transport=transport), clock=lambda: NOW
    ).fetch_organization(build_company_research_profile("org-1"))
    person = ApolloContactDiscoveryClient(
        api_key="synthetic-test-key", client=httpx.Client(transport=transport)
    ).enrich_person("person-1", observed_at=NOW)
    assert company.provider_employee_count == 5
    assert company.provider_source_fingerprint
    assert person is not None and person.provider_email_status == "verified"
    assert person.source_fingerprint
    assert "phone" not in company.model_dump(mode="json")
    assert "phone_number" not in person.model_dump(mode="json")
