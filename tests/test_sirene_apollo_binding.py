from __future__ import annotations

import datetime as dt
from decimal import Decimal

import httpx
import pytest
import sqlalchemy as sa
from alembic import command

from signals.company_research.apollo import ApolloCompanyResearchClient
from signals.company_research.binding import (
    BindingStatus,
    SireneApolloBindingStore,
    SireneApolloResolver,
)
from signals.company_research.contracts import (
    ApolloOrganizationObservation,
    CompanyResearchProviderError,
)
from signals.company_research.profile import build_company_research_profile
from signals.persistence.database import alembic_config, create_database_engine
from signals.supplier_discovery.contracts import SireneOrganizationCandidate

NOW = dt.datetime(2026, 9, 9, 12, tzinfo=dt.UTC)


def _identity(**updates) -> SireneOrganizationCandidate:
    values = {
        "provider_organization_id": "123456789",
        "display_name": "BETON ALPES",
        "normalized_name": "beton alpes",
        "location": "Lyon",
        "industry": "ready_mix_concrete:23.63Z",
        "provider_observed_at": NOW,
        "source_fingerprint": "a" * 64,
    }
    values.update(updates)
    return SireneOrganizationCandidate(**values)


class Provider:
    def __init__(self, *, missing: bool = False) -> None:
        self.calls = 0
        self.profiles = []
        self.missing = missing

    def fetch_organization(self, profile):
        self.calls += 1
        self.profiles.append(profile)
        if self.missing:
            raise CompanyResearchProviderError("not_found")
        return ApolloOrganizationObservation(
            provider_organization_id="apollo-org-42",
            provider_company_name="Beton Alpes",
            provider_country="France",
            provider_employee_count=42,
            provider_observed_at=NOW,
            provider_source_fingerprint="b" * 64,
        )


def _engine(tmp_path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'binding.db'}")
    command.upgrade(alembic_config(engine), "head")
    return engine


def test_resolver_persists_siren_to_apollo_binding_and_reuses_it(tmp_path) -> None:
    engine = _engine(tmp_path)
    provider = Provider()
    resolver = SireneApolloResolver(engine, provider=provider)

    first = resolver.resolve(_identity())
    second = resolver.resolve(_identity())

    assert first == second
    assert first.status is BindingStatus.RESOLVED
    assert first.siren == "123456789"
    assert first.apollo_organization_id == "apollo-org-42"
    assert first.resolution_method == "name_city"
    assert first.confidence_score == Decimal("0.8000")
    assert provider.calls == 1
    assert provider.profiles[0].siren == "123456789"
    assert provider.profiles[0].organization_name == "BETON ALPES"
    assert provider.profiles[0].organization_city == "Lyon"


def test_resolver_persists_unresolved_binding_without_apollo_id(tmp_path) -> None:
    engine = _engine(tmp_path)
    result = SireneApolloResolver(engine, provider=Provider(missing=True)).resolve(_identity())

    assert result.status is BindingStatus.UNRESOLVED
    assert result.apollo_organization_id is None
    assert result.confidence_score is None


def test_binding_store_rejects_no_implicit_legacy_lookup(tmp_path) -> None:
    engine = _engine(tmp_path)
    store = SireneApolloBindingStore(engine, clock=lambda: NOW)

    assert store.get("999999999") is None


def test_migration_marks_apollo_first_suppliers_legacy_without_binding(tmp_path) -> None:
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'legacy.db'}")
    config = alembic_config(engine)
    command.upgrade(config, "0045_pr7_shadow_mail")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO acquisition_supplier "
                "(supplier_ref, provider, provider_organization_id, display_name, "
                "normalized_name, identity_status, provider_observed_at, "
                "source_fingerprint, created_at, updated_at) VALUES "
                "(:ref, 'apollo', 'apollo-old-1', 'Ancienne SA', 'ancienne sa', "
                "'PROVIDER_IDENTIFIED', :now, :fingerprint, :now, :now)"
            ),
            {"ref": "sup_legacy", "now": NOW, "fingerprint": "c" * 64},
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        status = connection.scalar(
            sa.text(
                "SELECT identity_status FROM acquisition_supplier WHERE supplier_ref='sup_legacy'"
            )
        )
        binding_count = connection.scalar(sa.text("SELECT count(*) FROM sirene_apollo_binding"))

    assert status == "LEGACY_APOLLO"
    assert binding_count == 0


def test_apollo_resolution_is_name_city_then_one_exact_organization_get() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "organizations": [
                        {
                            "id": "apollo-org-42",
                            "name": "Beton Alpes Groupe",
                            "city": "Lyon",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "organization": {
                    "id": "apollo-org-42",
                    "name": "BETON ALPES",
                    "country": "France",
                    "estimated_num_employees": 42,
                }
            },
        )

    client = ApolloCompanyResearchClient(
        api_key="test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )
    result = SireneApolloResolver(_memory_engine(), provider=client).resolve(_identity())

    assert result.apollo_organization_id == "apollo-org-42"
    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/api/v1/mixed_companies/search"),
        ("GET", "/api/v1/organizations/apollo-org-42"),
    ]
    query = dict(requests[0].url.params.multi_items())
    assert query == {
        "q_organization_name": "Beton Alpes",
        "organization_locations[]": "Lyon",
    }


def test_apollo_resolution_rejects_first_result_and_accepts_strict_name_city_match() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "organizations": [
                        {"id": "wrong", "name": "Alpes Habitat", "city": "Lyon"},
                        {
                            "id": "right",
                            "name": "Beton Du Bourbonnais",
                            "city": "Saint-Victor",
                        },
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "organization": {
                    "id": "right",
                    "name": "Beton Du Bourbonnais",
                    "country": "France",
                    "estimated_num_employees": 12,
                }
            },
        )

    client = ApolloCompanyResearchClient(
        api_key="test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )
    result = client.fetch_organization(
        build_company_research_profile(
            "123456789",
            siren="123456789",
            organization_name="SARL BÉTON DU BOURBONNAIS",
            organization_city="ST-VICTOR",
        )
    )

    assert result.provider_organization_id == "right"
    assert result.resolution_confidence_score == Decimal("0.80")
    query = dict(requests[0].url.params.multi_items())
    assert query["q_organization_name"] == "Beton Du Bourbonnais"
    assert query["organization_locations[]"] == "Saint-Victor"


def test_apollo_resolution_requires_significant_name_words_and_city_or_domain() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "organizations": [
                        {
                            "id": "wrong-name",
                            "name": "Alpes Construction",
                            "city": "Lyon",
                            "primary_domain": "beton-alpes.fr",
                        },
                        {
                            "id": "wrong-place",
                            "name": "Beton Alpes",
                            "city": "Paris",
                            "primary_domain": "unrelated.example",
                        },
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "organization": {
                    "id": "wrong-place",
                    "name": "Beton Alpes",
                    "city": "Paris",
                    "primary_domain": "unrelated.example",
                }
            },
        )

    client = ApolloCompanyResearchClient(
        api_key="test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        clock=lambda: NOW,
    )

    with pytest.raises(CompanyResearchProviderError) as caught:
        client.fetch_organization(
            build_company_research_profile(
                "123456789",
                siren="123456789",
                organization_name="SAS BETON ALPES",
                organization_city="Lyon",
                organization_domain="beton-alpes.fr",
            )
        )

    assert caught.value.category == "not_found"


def _memory_engine():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    command.upgrade(alembic_config(engine), "head")
    return engine
