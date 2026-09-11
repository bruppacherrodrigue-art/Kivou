from __future__ import annotations

import datetime as dt

import httpx

from signals.companies.sirene import SireneCompanySearch, SireneSearchCriteria


def test_sirene_search_sends_naf_department_size_and_active_filters() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "nom_complet": "Entreprise Test (ET)",
                        "nom_raison_sociale": "Entreprise Test",
                        "siren": "123456789",
                        "activite_principale": "43.99C",
                        "tranche_effectif_salarie": "11",
                        "siege": {
                            "siret": "12345678900010",
                            "code_postal": "75001",
                            "libelle_commune": "Paris",
                            "activite_principale": "43.99C",
                        },
                        "matching_etablissements": [
                            {
                                "siret": "12345678900028",
                                "code_postal": "69001",
                                "libelle_commune": "Lyon",
                                "activite_principale": "43.99C",
                                "etat_administratif": "A",
                            }
                        ],
                    }
                ],
                "total_results": 1,
            },
        )

    search = SireneCompanySearch(
        transport=httpx.MockTransport(handler),
        clock=lambda: dt.datetime(2026, 9, 9, tzinfo=dt.UTC),
    )
    result = search.find(
        SireneSearchCriteria(
            naf_codes=("43.99C",),
            departments=("69", "01"),
            min_employees=5,
            max_employees=250,
            limit=25,
        )
    )

    assert len(result) == 1
    assert result[0].legal_name == "Entreprise Test"
    assert result[0].siren == "123456789"
    assert result[0].siret == "12345678900028"
    assert result[0].city == "Lyon"
    assert requests[0].url.path == "/search"
    query = dict(requests[0].url.params.multi_items())
    assert query["activite_principale"] == "43.99C"
    assert query["departement"] == "69,01"
    assert query["etat_administratif"] == "A"
    assert query["minimal"] == "true"
    assert query["include"] == "matching_etablissements,siege"


def test_sirene_search_rejects_wrong_naf_closed_and_out_of_department_establishments() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "nom_complet": "Fermée",
                        "siren": "111111111",
                        "activite_principale": "43.99C",
                        "tranche_effectif_salarie": "11",
                        "matching_etablissements": [
                            {
                                "siret": "11111111100010",
                                "code_postal": "69001",
                                "activite_principale": "43.99C",
                                "etat_administratif": "C",
                            }
                        ],
                    },
                    {
                        "nom_complet": "Mauvais NAF établissement",
                        "siren": "222222222",
                        "activite_principale": "43.99C",
                        "tranche_effectif_salarie": "11",
                        "matching_etablissements": [
                            {
                                "siret": "22222222200010",
                                "code_postal": "69001",
                                "activite_principale": "68.20B",
                                "etat_administratif": "A",
                            }
                        ],
                    },
                    {
                        "nom_complet": "Hors département",
                        "siren": "333333333",
                        "activite_principale": "43.99C",
                        "tranche_effectif_salarie": "11",
                        "matching_etablissements": [
                            {
                                "siret": "33333333300010",
                                "code_postal": "75001",
                                "activite_principale": "43.99C",
                                "etat_administratif": "A",
                            }
                        ],
                    },
                ],
                "total_results": 2,
            },
        )

    result = SireneCompanySearch(transport=httpx.MockTransport(handler)).find(
        SireneSearchCriteria(naf_codes=("43.99C",), departments=("69",), limit=25)
    )
    assert result == ()


def test_sirene_search_paginates_until_limit_after_invalid_matches() -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        pages.append(page)
        if page == 1:
            results = [
                {
                    "nom_complet": "Siège seul",
                    "siren": "111111111",
                    "activite_principale": "23.63Z",
                    "tranche_effectif_salarie": "11",
                    "matching_etablissements": [],
                }
            ]
        else:
            results = [
                {
                    "nom_complet": "Centrale locale",
                    "siren": "222222222",
                    "activite_principale": "23.63Z",
                    "tranche_effectif_salarie": "12",
                    "matching_etablissements": [
                        {
                            "siret": "22222222200020",
                            "code_postal": "38000",
                            "libelle_commune": "Grenoble",
                            "activite_principale": "23.63Z",
                            "etat_administratif": "A",
                        }
                    ],
                }
            ]
        return httpx.Response(200, json={"results": results, "total_results": 26})

    result = SireneCompanySearch(transport=httpx.MockTransport(handler)).find(
        SireneSearchCriteria(naf_codes=("23.63Z",), departments=("38",), limit=1)
    )

    assert pages == [1, 2]
    assert [company.legal_name for company in result] == ["Centrale locale"]


def test_sirene_search_accepts_one_hundred_and_sorts_by_employee_count() -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        pages.append(page)
        start = (page - 1) * 25
        results = []
        for index in range(start, min(start + 25, 100)):
            tranche = ("03", "11", "12", "21")[index % 4]
            siren = f"{100_000_000 + index:09d}"
            results.append(
                {
                    "nom_raison_sociale": f"Entreprise {index:03d}",
                    "siren": siren,
                    "activite_principale": "43.99C",
                    "tranche_effectif_salarie": tranche,
                    "matching_etablissements": [
                        {
                            "siret": f"{siren}00010",
                            "code_postal": "69001",
                            "libelle_commune": "Lyon",
                            "activite_principale": "43.99C",
                            "etat_administratif": "A",
                        }
                    ],
                }
            )
        return httpx.Response(200, json={"results": results, "total_results": 100})

    result = SireneCompanySearch(transport=httpx.MockTransport(handler)).find(
        SireneSearchCriteria(naf_codes=("43.99C",), departments=("69",), limit=100)
    )

    assert pages == [1, 2, 3, 4]
    assert len(result) == 100
    assert [company.employees or 0 for company in result] == sorted(
        (company.employees or 0 for company in result), reverse=True
    )
