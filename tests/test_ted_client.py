"""Client TED — testé hors ligne via un transport httpx simulé.

Aucun appel réseau : ces tests vérifient le contrat du client (forme de la
requête, pagination bornée, erreurs explicites), pas la disponibilité de TED.
Le contact avec l'API réelle se fait par `live_smoke.py`, à la demande.
"""

from __future__ import annotations

import httpx
import pytest

from signals.connectors.ted.client import TedClient
from signals.connectors.ted.errors import TedHttpError


def client_with(handler) -> TedClient:
    return TedClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_la_recherche_poste_une_requete_conforme_a_l_api_v3():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"notices": [], "totalNoticeCount": 0})

    with client_with(handler) as client:
        client.search("form-type=result", limit=5)

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.ted.europa.eu/v3/notices/search"
    assert '"query":"form-type=result"' in captured["body"].replace(" ", "")
    assert '"paginationMode":"PAGE_NUMBER"' in captured["body"].replace(" ", "")


def test_aucune_authentification_n_est_envoyee():
    """L'API de recherche est publique : inventer un en-tête d'auth serait faux."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"notices": [], "totalNoticeCount": 0})

    with client_with(handler) as client:
        client.search("form-type=result")

    assert "authorization" not in seen
    assert "x-api-key" not in seen
    assert "award-signals" in seen["user-agent"]


def test_les_resultats_sont_convertis_en_references():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "notices": [
                    {
                        "publication-number": "550374-2026",
                        "notice-identifier": "e60ad0f2",
                        "notice-version": 1,
                        "notice-type": "can-standard",
                        "publication-date": "2026-08-10+02:00",
                        "organisation-country-buyer": ["FRA"],
                    }
                ],
                "totalNoticeCount": 9300,
            },
        )

    with client_with(handler) as client:
        refs, total = client.search("form-type=result")

    assert total == 9300
    assert refs[0].publication_number == "550374-2026"
    assert refs[0].buyer_country == "FRA"


def test_la_pagination_s_arrete_au_nombre_demande():
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.read())
        pages.append(body["page"])
        rows = [{"publication-number": f"{body['page']}-{i}-2026"} for i in range(body["limit"])]
        return httpx.Response(200, json={"notices": rows, "totalNoticeCount": 10_000})

    with client_with(handler) as client:
        refs = client.search_all("form-type=result", wanted=7, page_size=3)

    assert len(refs) == 7
    assert pages == [1, 2, 3]  # ni boucle infinie, ni page superflue


def test_la_pagination_s_arrete_sur_une_page_vide():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"notices": [], "totalNoticeCount": 0})

    with client_with(handler) as client:
        assert client.search_all("form-type=result", wanted=100, page_size=50) == []


def test_une_erreur_http_est_explicite():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    with client_with(handler) as client, pytest.raises(TedHttpError) as raised:
        client.search("form-type=result")
    assert raised.value.status_code == 503
    assert "503" in str(raised.value)


def test_une_panne_reseau_est_explicite():
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connexion refusée")

    with client_with(handler) as client, pytest.raises(TedHttpError, match="injoignable"):
        client.search("form-type=result")


def test_le_xml_est_recupere_a_l_url_officielle():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, content=b"<ContractAwardNotice/>")

    with client_with(handler) as client:
        content = client.fetch_notice_xml("550374-2026")

    assert captured["url"] == "https://ted.europa.eu/en/notice/550374-2026/xml"
    assert content == b"<ContractAwardNotice/>"


def test_un_xml_absent_est_explicite():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with client_with(handler) as client, pytest.raises(TedHttpError, match="indisponible"):
        client.fetch_notice_xml("000000-1999")
