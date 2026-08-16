"""Client SIMAP — testé hors ligne via un transport httpx simulé.

Aucun appel réseau : ces tests vérifient le contrat du client (forme des
requêtes, pagination roulante bornée, erreurs explicites, distinction entre
panne et authentification requise). Le contact avec l'API réelle se fait par
`live_smoke.py`, à la demande.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from signals.connectors.simap.client import SimapClient
from signals.connectors.simap.errors import SimapAuthRequiredError, SimapHttpError


def client_with(handler) -> SimapClient:
    return SimapClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_la_recherche_appelle_l_endpoint_officiel():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        return httpx.Response(200, json={"projects": [], "pagination": {}})

    with client_with(handler) as client:
        client.search_awards(pub_type_filter="award_tender", published_from="2026-07-01")

    assert captured["method"] == "GET"
    assert captured["url"].startswith(
        "https://www.simap.ch/api/publications/v2/project/project-search"
    )
    assert "newestPubTypes=award_tender" in captured["url"]
    assert "newestPublicationFrom=2026-07-01" in captured["url"]


def test_aucune_authentification_n_est_envoyee():
    """Les endpoints de publication sont publics : inventer un jeton serait faux."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"projects": [], "pagination": {}})

    with client_with(handler) as client:
        client.search_awards()

    assert "authorization" not in seen
    assert "cookie" not in seen
    assert "Kivou" in seen["user-agent"]


def test_les_resultats_sont_convertis_en_references():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "projects": [
                    {
                        "id": "0d2599e8-c839-4d7d-9277-63144b4750b0",
                        "publicationId": "223ceb19-b3d4-4556-a417-84c1d5f7a3a9",
                        "publicationNumber": "33112-02",
                        "projectNumber": "33112",
                        "pubType": "award",
                        "projectSubType": "construction",
                        "processType": "open",
                        "lotsType": "without",
                        "publicationDate": "2026-08-15",
                        "corrected": False,
                        "orderAddress": {"cantonId": "LU", "countryId": "CH"},
                    }
                ],
                "pagination": {"lastItem": "20260814|32467"},
            },
        )

    with client_with(handler) as client:
        rows, last_item = client.search_awards()

    assert last_item == "20260814|32467"
    assert rows[0].publication_number == "33112-02"
    assert rows[0].canton == "LU"
    assert rows[0].search_entry["orderAddress"]["cantonId"] == "LU"


def test_la_pagination_roulante_est_bornee():
    pages: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("lastItem")
        pages.append(cursor)
        index = len(pages)
        return httpx.Response(
            200,
            json={
                "projects": [
                    {"id": f"p{index}-{i}", "publicationId": f"pub{index}-{i}"} for i in range(3)
                ],
                "pagination": {"lastItem": f"cursor{index}"},
            },
        )

    with client_with(handler) as client:
        rows = client.search_all_awards(
            wanted=5, pub_type_filters=("award_tender",), max_pages_per_filter=10
        )

    assert len(rows) == 5
    assert pages == [None, "cursor1"]  # on s'arrête dès que le quota est atteint


def test_les_familles_d_adjudication_sont_interrogees_a_tour_de_role():
    """Épuiser la première famille donnerait un échantillon sans gré à gré."""
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pub_type = request.url.params.get("newestPubTypes")
        asked.append(pub_type)
        index = len(asked)
        return httpx.Response(
            200,
            json={
                "projects": [
                    {"id": f"{pub_type}-{index}", "publicationId": f"pub-{pub_type}-{index}"}
                ],
                "pagination": {"lastItem": f"cursor{index}"},
            },
        )

    with client_with(handler) as client:
        rows = client.search_all_awards(
            wanted=4,
            pub_type_filters=("award_tender", "direct_award", "award_competition"),
            max_pages_per_filter=5,
        )

    assert asked[:3] == ["award_tender", "direct_award", "award_competition"]
    assert len({r.publication_id for r in rows}) == len(rows)


def test_la_pagination_respecte_le_plafond_de_pages():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "projects": [{"id": "p", "publicationId": "pub"}],
                "pagination": {"lastItem": "c"},
            },
        )

    with client_with(handler) as client:
        rows = client.search_all_awards(
            wanted=1000, pub_type_filters=("award_tender",), max_pages_per_filter=3
        )
    assert len(rows) == 1  # même publicationId : dédupliqué, et 3 pages maximum


def test_une_erreur_http_est_explicite():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    with client_with(handler) as client, pytest.raises(SimapHttpError) as raised:
        client.search_awards()
    assert raised.value.status_code == 503


def test_une_authentification_requise_est_distinguee_d_une_panne():
    """403 sur un document n'est pas une erreur à réessayer : c'est la règle SIMAP."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    with client_with(handler) as client, pytest.raises(SimapAuthRequiredError) as raised:
        client.fetch_publication("projet", "publication")
    assert raised.value.status_code == 403


def test_une_panne_reseau_est_explicite():
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion refusée")

    with client_with(handler) as client, pytest.raises(SimapHttpError, match="injoignable"):
        client.search_awards()


def test_le_detail_est_lu_en_decimal_exact():
    """Les montants ne doivent jamais transiter par un flottant."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"decision":{"vendors":[{"price":{"price":3513552.65}}]}}',
            headers={"Content-Type": "application/json"},
        )

    with client_with(handler) as client:
        payload = client.fetch_publication("projet", "publication")
    price = payload["decision"]["vendors"][0]["price"]["price"]
    assert isinstance(price, Decimal)
    assert price == Decimal("3513552.65")


def test_l_historique_d_un_lot_passe_le_lot_id():
    """Sans `lotId`, l'API répond 400 sur un projet à lots — le client le sait."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"pastPublications": []})

    with client_with(handler) as client:
        client.fetch_past_publications("pub-id", lot_id="lot-id")

    assert "past-publications" in captured["url"]
    assert "lotId=lot-id" in captured["url"]
