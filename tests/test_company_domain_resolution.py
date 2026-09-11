from __future__ import annotations

import datetime as dt
import json
import logging

import httpx
import pytest

import signals.company_research.domain as domain_module
from signals.company_research.domain import (
    AnnuaireWebsiteClient,
    CompanyDomainResolver,
    DomainResolution,
    SerperDomainSearchClient,
    rejected_supplier_domain,
)
from signals.company_research.identity import (
    normalized_organization_name,
    significant_name_words,
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


def test_supplier_name_normalization_removes_business_prefixes_and_initials() -> None:
    name = "ENT A. SOCIETE ETABLISSEMENTS GIRARD SARL"

    assert normalized_organization_name(name) == "Girard"
    assert significant_name_words(name) == ("girard",)


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


def test_serper_validates_all_ten_results_in_order_after_normalizing_name() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = str(json.loads(request.content)["q"])
        requests.append(query)
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "title": f"ENT — résultat sans rapport {index}",
                        "link": f"https://construction-{index}.fr",
                    }
                    for index in range(1, 10)
                ]
                + [
                    {
                        "title": "Entreprise Girard — site officiel",
                        "link": "https://batiment-valence.fr",
                    }
                ]
            },
        )

    resolution = CompanyDomainResolver(
        official=lambda _identity: None,
        serper=SerperDomainSearchClient(
            api_key="secret", client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
        clock=lambda: NOW,
    ).resolve(
        _identity(
            display_name="ENT A. GIRARD SARL",
            normalized_name="ent a girard sarl",
            location="VALENCE",
            department="26",
        )
    )

    assert resolution is not None
    assert resolution.domain == "batiment-valence.fr"
    assert resolution.query == "Girard Valence"
    assert requests == ["Girard Valence"]


def test_serper_returns_none_when_no_result_contains_significant_name_words() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "organic": [
                        {"title": "Construction Grenoble", "link": "https://ciment.fr"}
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

    assert resolution is None


def test_serper_retries_with_official_site_then_name_and_department() -> None:
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = str(json.loads(request.content)["q"])
        queries.append(query)
        if query.endswith("38"):
            return httpx.Response(
                200,
                json={
                    "organic": [
                        {
                            "title": "Escolle Béton — site officiel",
                            "link": "https://escolle-beton.fr",
                        }
                    ]
                },
            )
        if query.endswith("site officiel"):
            return httpx.Response(
                200,
                json={
                    "organic": [
                        {"title": "Escolle Béton", "link": "https://societe.com/escolle"}
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "title": "Ciment près de Grenoble",
                        "link": "https://ciment-grenoble.fr",
                    }
                ]
            },
        )

    resolution = CompanyDomainResolver(
        official=lambda identity: None,
        serper=SerperDomainSearchClient(
            api_key="secret", client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
        clock=lambda: NOW,
    ).resolve(_identity(department="38"))

    assert resolution is not None
    assert resolution.domain == "escolle-beton.fr"
    assert resolution.query == "Escolle Beton 38"
    assert queries == [
        "Escolle Beton Saint-Egreve",
        "Escolle Beton Saint-Egreve site officiel",
        "Escolle Beton 38",
    ]


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


@pytest.mark.parametrize("domain", ["localbiz.fr", "neyron.localbiz.fr"])
def test_localbiz_is_rejected_as_a_directory(domain: str) -> None:
    assert rejected_supplier_domain(domain) is True


@pytest.mark.parametrize(
    "domain",
    (
        "societeinfo.com",
        "doctrine.fr",
        "pappers.fr",
        "societe.com",
        "verif.com",
        "infogreffe.fr",
        "kompass.com",
        "pagesjaunes.fr",
        "manageo.fr",
        "annuaire-entreprises.data.gouv.fr",
        "data.inpi.fr",
        "bilansgratuits.fr",
        "dnb.com",
        "rubypayeur.com",
        "gowork.fr",
        "actulegales.fr",
        "placegrenet.fr",
        "01.lavieduvillage.fr",
        "grenoble.cci.fr",
        "instagram.com",
        "facebook.com",
        "linkedin.com",
        "compao.fr",
        "socs.fr",
        "pple.fr",
        "mairie-certines.fr",
        "commune-certines.fr",
        "ville-saint-etienne.fr",
        "entreprises.gouv.fr",
    ),
)
def test_domain_validation_rejects_every_forbidden_registry_and_public_domain(domain) -> None:
    assert rejected_supplier_domain(domain)


def test_domain_resolver_accepts_unmatched_domain_only_when_legal_page_contains_siren() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text='<footer><a href="/mentions-legales">Mentions légales</a></footer>',
            )
        assert request.url.path == "/mentions-legales"
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="SIREN : 331 364 729",
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    resolution = CompanyDomainResolver(
        official=lambda _identity: DomainResolution(
            domain="centrale-grenoble.fr",
            website_url="https://centrale-grenoble.fr",
            source="annuaire_entreprises",
            observed_at=NOW,
        ),
        serper=lambda _identity: None,
        registration=domain_module.CompanyWebsiteRegistrationClient(client=client),
        clock=lambda: NOW,
    ).resolve(_identity())

    assert resolution is not None
    assert resolution.validation_method == "registration_number"
    assert resolution.validation_evidence_url == "https://centrale-grenoble.fr/mentions-legales"


def test_registration_probes_fixed_legal_paths_and_accepts_rcs_number() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        text = (
            "RCS Grenoble 331 364 729"
            if request.url.path == "/conditions-generales"
            else "Aucune identité légale"
        )
        return httpx.Response(200, headers={"content-type": "text/html"}, text=text)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    evidence = domain_module.CompanyWebsiteRegistrationClient(client=client)(
        DomainResolution(
            domain="centrale-grenoble.fr",
            website_url="https://centrale-grenoble.fr",
            source="serper",
            observed_at=NOW,
        ),
        _identity(),
    )

    assert evidence == "https://centrale-grenoble.fr/conditions-generales"
    assert requested == [
        "/",
        "/mentions-legales",
        "/mentions-legales.html",
        "/cgv",
        "/conditions-generales",
    ]


def test_domain_name_match_accepts_word_inside_domain_and_company_initials() -> None:
    for name, candidate_domain in (
        ("MEYNET BETON SAS", "livraisonbeton.fr"),
        ("SOCIETE TRAVAUX GROS OEUVRE", "stgo.eu"),
    ):
        resolution = CompanyDomainResolver(
            official=lambda _identity, domain=candidate_domain: DomainResolution(
                domain=domain,
                website_url=f"https://{domain}",
                source="annuaire_entreprises",
                observed_at=NOW,
            ),
            serper=lambda _identity: None,
            clock=lambda: NOW,
        ).resolve(_identity(display_name=name, normalized_name=name.casefold()))

        assert resolution is not None
        assert resolution.validation_method == "name_word"


def test_domain_resolver_accepts_normalized_company_name_in_homepage_title() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="<html><head><title>Escolle Béton — Saint-Égrève</title></head></html>",
            )
        ),
        follow_redirects=True,
    )
    resolution = CompanyDomainResolver(
        official=lambda _identity: DomainResolution(
            domain="centrale-grenoble.fr",
            website_url="https://centrale-grenoble.fr",
            source="annuaire_entreprises",
            observed_at=NOW,
        ),
        serper=lambda _identity: None,
        registration=domain_module.CompanyWebsiteRegistrationClient(client=client),
        clock=lambda: NOW,
    ).resolve(_identity())

    assert resolution is not None
    assert resolution.validation_method == "name_word"
    assert resolution.validation_evidence_url == "https://centrale-grenoble.fr/"


def test_domain_resolver_rejects_unmatched_domain_without_registration_number(caplog) -> None:
    caplog.set_level(logging.INFO)
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="Entreprise de construction régionale",
            )
        ),
        follow_redirects=True,
    )

    resolution = CompanyDomainResolver(
        official=lambda _identity: DomainResolution(
            domain="centrale-grenoble.fr",
            website_url="https://centrale-grenoble.fr",
            source="annuaire_entreprises",
            observed_at=NOW,
        ),
        serper=lambda _identity: None,
        registration=domain_module.CompanyWebsiteRegistrationClient(client=client),
        clock=lambda: NOW,
    ).resolve(_identity())

    assert resolution is None
    decision = next(
        record for record in caplog.records if record.message == "supplier_domain_validation"
    )
    assert decision.domain_validation_criterion == "identity_unconfirmed"


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
