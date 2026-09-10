from __future__ import annotations

import datetime as dt
import json

import httpx

from signals.company_research.domain import (
    AnnuaireWebsiteClient,
    CompanyDomainResolver,
    SerperDomainSearchClient,
    rejected_supplier_domain,
)
from signals.supplier_discovery.contracts import SireneOrganizationCandidate

NOW = dt.datetime(2026, 9, 10, 10, tzinfo=dt.UTC)


def _identity(**updates) -> SireneOrganizationCandidate:
    values = {
        "provider_organization_id": "331364729",
        "display_name": "ESCOlLE BETON SAS",
        "normalized_name": "escolle beton sas",
        "location": "SAINT-EGREVE",
        "industry": "ready_mix_concrete:23.63Z",
        "provider_observed_at": NOW,
        "source_fingerprint": "a" * 64,
    }
    values.update(updates)
    return SireneOrganizationCandidate(**values)


def test_domain_resolver_prefers_official_website_without_serper() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host or "")
        return httpx.Response(
            200,
            json={"results": [{"siren": "331364729", "site_web": "https://escolle-beton.fr"}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    resolution = CompanyDomainResolver(
        official=AnnuaireWebsiteClient(client=client),
        serper=SerperDomainSearchClient(api_key="unused", client=client),
        clock=lambda: NOW,
    ).resolve(_identity())

    assert resolution is not None
    assert resolution.domain == "escolle-beton.fr"
    assert resolution.source == "annuaire_entreprises"
    assert calls == ["recherche-entreprises.api.gouv.fr"]


def test_serper_rejects_directories_and_unrelated_results_then_accepts_name_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "google.serper.dev"
        assert request.headers["x-api-key"] == "secret"
        assert json.loads(request.content) == {
            "q": "Escolle Beton Saint-Egreve",
            "gl": "fr",
            "hl": "fr",
            "num": 10,
        }
        return httpx.Response(
            200,
            json={
                "organic": [
                    {"title": "Escolle Béton", "link": "https://www.societe.com/societe/x"},
                    {"title": "Construction Grenoble", "link": "https://hors-sujet.fr"},
                    {
                        "title": "ESCOlLE BETON — centrale à béton",
                        "link": "https://www.escolle-beton.fr/contact/",
                    },
                ]
            },
        )

    shared = httpx.Client(transport=httpx.MockTransport(handler))
    resolution = CompanyDomainResolver(
        official=lambda identity: None,
        serper=SerperDomainSearchClient(api_key="secret", client=shared),
        clock=lambda: NOW,
    ).resolve(_identity())

    assert resolution is not None
    assert resolution.domain == "escolle-beton.fr"
    assert resolution.website_url == "https://www.escolle-beton.fr/contact/"
    assert resolution.source == "serper"
    assert resolution.query == "Escolle Beton Saint-Egreve"


def test_serper_returns_none_when_no_result_contains_significant_name_words() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"organic": [{"title": "Béton Grenoble", "link": "https://beton.fr"}]},
            )
        )
    )
    resolution = CompanyDomainResolver(
        official=lambda identity: None,
        serper=SerperDomainSearchClient(api_key="secret", client=client),
        clock=lambda: NOW,
    ).resolve(_identity())

    assert resolution is None


def test_serper_rejects_public_directory_and_municipal_false_matches() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "organic": [
                        {
                            "title": "Jacquet — mairie de Certines",
                            "link": "https://certines.grandbourg.fr/1909-contact.htm",
                        },
                        {
                            "title": "Jacquet",
                            "link": "https://jacquet.gouv.fr/contact",
                        },
                        {
                            "title": "Jacquet",
                            "link": "https://mairie-certines.fr/jacquet",
                        },
                        {
                            "title": "Jacquet",
                            "link": "https://infogreffe.fr/entreprise/jacquet",
                        },
                        {"title": "Jacquet", "link": "https://fr.mappy.com/poi/jacquet"},
                        {
                            "title": "Jacquet",
                            "link": "https://france-artisan.fr/annuaire/jacquet",
                        },
                        {
                            "title": "Jacquet",
                            "link": "https://monartisan.info/entreprise-jacquet",
                        },
                        {
                            "title": "Jacquet — ville de Certines",
                            "link": "https://ville-certines.fr/jacquet",
                        },
                    ]
                },
            )
        )
    )
    resolution = CompanyDomainResolver(
        official=lambda identity: None,
        serper=SerperDomainSearchClient(api_key="secret", client=client),
        clock=lambda: NOW,
    ).resolve(
        _identity(
            provider_organization_id="302280755",
            display_name="JACQUET",
            normalized_name="jacquet",
            location="CERTINES",
        )
    )

    assert resolution is None


def test_observed_french_directories_and_trade_press_are_rejected() -> None:
    domains = (
        "annuaire-entreprises-rge.fr",
        "entreprises.lefigaro.fr",
        "grossiste.e-pro.fr",
        "acpresse.fr",
    )

    assert all(rejected_supplier_domain(domain) for domain in domains)


def test_serper_accepts_one_significant_company_word_in_domain_or_title() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "organic": [
                        {
                            "title": "Escolle — centrale régionale",
                            "link": "https://escolle-industrie.fr/contact",
                        }
                    ]
                },
            )
        )
    )

    resolution = CompanyDomainResolver(
        official=lambda identity: None,
        serper=SerperDomainSearchClient(api_key="secret", client=client),
        clock=lambda: NOW,
    ).resolve(_identity())

    assert resolution is not None
    assert resolution.domain == "escolle-industrie.fr"
