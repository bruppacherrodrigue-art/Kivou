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
                        "nom_complet": "Entreprise Test",
                        "siren": "123456789",
                        "siege": {
                            "siret": "12345678900010",
                            "code_postal": "69001",
                            "libelle_commune": "Lyon",
                            "activite_principale": "43.99C",
                            "tranche_effectif_salarie": "11",
                        },
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
    assert result[0].city == "Lyon"
    assert requests[0].url.path == "/search"
    query = dict(requests[0].url.params.multi_items())
    assert query["code_naf"] == "43.99C"
    assert query["departement"] == "69,01"
    assert query["etat_administratif"] == "A"


def test_sirene_search_rejects_non_active_and_out_of_range_results() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "nom_complet": "Fermée",
                        "siren": "111111111",
                        "siege": {
                            "siret": "11111111100010",
                            "activite_principale": "43.99C",
                            "tranche_effectif_salarie": "11",
                            "etat_administratif": "C",
                        },
                    },
                    {
                        "nom_complet": "Trop grande",
                        "siren": "222222222",
                        "siege": {
                            "siret": "22222222200010",
                            "activite_principale": "43.99C",
                            "tranche_effectif_salarie": "32",
                            "etat_administratif": "A",
                        },
                    },
                ],
                "total_results": 2,
            },
        )

    result = SireneCompanySearch(transport=httpx.MockTransport(handler)).find(
        SireneSearchCriteria(naf_codes=("43.99C",), departments=("69",), limit=25)
    )
    assert result == ()
