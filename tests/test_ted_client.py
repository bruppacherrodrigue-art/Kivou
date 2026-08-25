"""Client TED — testé hors ligne via un transport httpx simulé.

Aucun appel réseau : ces tests vérifient le contrat du client (forme de la
requête, pagination bornée, erreurs explicites), pas la disponibilité de TED.
Le contact avec l'API réelle se fait par `live_smoke.py`, à la demande.
"""

from __future__ import annotations

import datetime as dt
import threading

import httpx
import pytest

from signals.connectors.ted.client import TedClient
from signals.connectors.ted.errors import TedHttpError


def client_with(handler, **kwargs) -> TedClient:
    return TedClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


class FakeTime:
    def __init__(self, *, wall: dt.datetime | None = None) -> None:
        self.elapsed = 0.0
        self.wall = wall or dt.datetime(2026, 8, 25, 12, tzinfo=dt.UTC)
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.elapsed

    def now(self) -> dt.datetime:
        return self.wall + dt.timedelta(seconds=self.elapsed)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.elapsed += seconds


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


def test_search_and_xml_share_one_conservative_request_pace() -> None:
    clock = FakeTime()
    requested_at: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_at.append(clock.elapsed)
        if request.method == "POST":
            return httpx.Response(200, json={"notices": [], "totalNoticeCount": 0})
        return httpx.Response(200, content=b"<ContractAwardNotice/>")

    with client_with(
        handler,
        request_interval_seconds=1.0,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        wall_clock=clock.now,
    ) as client:
        client.search("form-type=result")
        client.fetch_notice_xml("550374-2026")

    assert requested_at == [0.0, 1.0]
    assert clock.sleeps == [1.0]


def test_retry_after_delta_seconds_recovers_a_search_429() -> None:
    clock = FakeTime()
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, json={"notices": [], "totalNoticeCount": 0})

    with client_with(
        handler,
        request_interval_seconds=1.0,
        max_attempts=4,
        max_retry_seconds=30,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        wall_clock=clock.now,
    ) as client:
        refs, total = client.search("form-type=result")

    assert refs == []
    assert total == 0
    assert attempts == 2
    assert clock.sleeps == [3.0]


def test_retry_after_http_date_recovers_an_xml_429() -> None:
    clock = FakeTime()
    attempts = 0
    retry_at = "Tue, 25 Aug 2026 12:00:05 GMT"

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": retry_at})
        return httpx.Response(200, content=b"<ContractAwardNotice/>")

    with client_with(
        handler,
        request_interval_seconds=1.0,
        max_attempts=4,
        max_retry_seconds=30,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        wall_clock=clock.now,
    ) as client:
        assert client.fetch_notice_xml("550374-2026") == b"<ContractAwardNotice/>"

    assert attempts == 2
    assert clock.sleeps == [5.0]


def test_retry_is_bounded_by_attempt_count_and_omits_response_body() -> None:
    clock = FakeTime()
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, text="private-provider-response")

    with (
        client_with(
            handler,
            request_interval_seconds=0,
            max_attempts=3,
            max_retry_seconds=30,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            wall_clock=clock.now,
        ) as client,
        pytest.raises(TedHttpError) as raised,
    ):
        client.search("form-type=result")

    assert attempts == 3
    assert clock.sleeps == [1.0, 2.0]
    assert raised.value.status_code == 429
    assert raised.value.category == "rate_limited"
    assert "private-provider-response" not in str(raised.value)


def test_retry_does_not_sleep_past_the_total_duration_bound() -> None:
    clock = FakeTime()
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "10"})

    with (
        client_with(
            handler,
            request_interval_seconds=0,
            max_attempts=4,
            max_retry_seconds=5,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            wall_clock=clock.now,
        ) as client,
        pytest.raises(TedHttpError),
    ):
        client.fetch_notice_xml("550374-2026")

    assert attempts == 1
    assert clock.sleeps == []


def test_retry_deadline_bounds_the_http_attempt_itself() -> None:
    clock = FakeTime()
    timeouts: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeout = request.extensions["timeout"]["read"]
        timeouts.append(timeout)
        clock.elapsed += min(10.0, timeout)
        raise httpx.ReadTimeout("simulated slow response", request=request)

    with (
        client_with(
            handler,
            timeout=30,
            request_interval_seconds=0,
            max_attempts=4,
            max_retry_seconds=5,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            wall_clock=clock.now,
        ) as client,
        pytest.raises(TedHttpError) as raised,
    ):
        client.search("form-type=result")

    assert raised.value.category == "timeout"
    assert timeouts == [5.0]
    assert clock.elapsed == 5.0


def test_transient_network_failure_retries_then_recovers() -> None:
    clock = FakeTime()
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("temporary", request=request)
        return httpx.Response(200, json={"notices": [], "totalNoticeCount": 0})

    with client_with(
        handler,
        request_interval_seconds=0,
        max_attempts=2,
        max_retry_seconds=5,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        wall_clock=clock.now,
    ) as client:
        assert client.search("form-type=result") == ([], 0)

    assert attempts == 2
    assert clock.sleeps == [1.0]


def test_non_retryable_http_failure_stops_immediately() -> None:
    clock = FakeTime()
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404)

    with (
        client_with(
            handler,
            request_interval_seconds=0,
            max_attempts=4,
            max_retry_seconds=30,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            wall_clock=clock.now,
        ) as client,
        pytest.raises(TedHttpError),
    ):
        client.fetch_notice_xml("missing")

    assert attempts == 1
    assert clock.sleeps == []


def test_client_serializes_requests_from_concurrent_callers() -> None:
    first_entered = threading.Event()
    release_first = threading.Event()
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
            first = not first_entered.is_set()
            first_entered.set()
        if first:
            assert release_first.wait(timeout=2)
        with state_lock:
            active -= 1
        return httpx.Response(200, json={"notices": [], "totalNoticeCount": 0})

    with client_with(handler, request_interval_seconds=0) as client:
        first = threading.Thread(target=client.search, args=("form-type=result",))
        second = threading.Thread(target=client.search, args=("form-type=result",))
        first.start()
        assert first_entered.wait(timeout=2)
        second.start()
        release_first.set()
        first.join(timeout=2)
        second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert maximum_active == 1
