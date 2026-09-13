from __future__ import annotations

import datetime as dt

import httpx
import pytest

from signals.connectors.boamp import AwardCursor, BoampClient, BoampHttpError


@pytest.mark.parametrize(
    ("status", "category"),
    [(429, "rate_limited"), (503, "server_error"), (401, "unauthorized"), (404, "client_error")],
)
def test_boamp_http_failures_remain_typed(status: int, category: str):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status)))
    with pytest.raises(BoampHttpError) as caught:
        BoampClient(client=client).fetch_page(AwardCursor(since=dt.date(2026, 8, 1)))
    assert caught.value.category == category
    assert caught.value.status_code == status


def test_boamp_timeout_and_malformed_payload_are_typed():
    def timeout(request):
        raise httpx.ReadTimeout("late", request=request)

    client = httpx.Client(transport=httpx.MockTransport(timeout))
    with pytest.raises(BoampHttpError, match="BOAMP") as caught:
        BoampClient(client=client).fetch_page(AwardCursor(since=dt.date(2026, 8, 1)))
    assert caught.value.category == "timeout"

    malformed = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text="not-json"))
    )
    with pytest.raises(BoampHttpError) as caught:
        BoampClient(client=malformed).fetch_page(AwardCursor(since=dt.date(2026, 8, 1)))
    assert caught.value.category == "malformed"


def test_exact_notice_lookup_uses_the_same_official_api_and_equality_query():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"results": [{"idweb": "26-80978", "donnees": {}}]})

    client = BoampClient(client=httpx.Client(transport=httpx.MockTransport(respond)))
    assert hasattr(client, "fetch_record"), "bounded exact BOAMP lookup is not implemented"
    assert client.fetch_record("26-80978")["idweb"] == "26-80978"
    assert requests[0].url.host == "boamp-datadila.opendatasoft.com"
    assert requests[0].url.params["where"] == 'idweb="26-80978"'
    assert requests[0].url.params["limit"] == "2"


@pytest.mark.parametrize("records", [[{"idweb": "wrong"}], [{"idweb": "26-80978"}] * 2])
def test_exact_notice_lookup_rejects_mismatched_or_duplicate_results(records):
    client = BoampClient(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"results": records})
            )
        )
    )
    assert hasattr(client, "fetch_record"), "bounded exact BOAMP lookup is not implemented"
    with pytest.raises(BoampHttpError) as caught:
        client.fetch_record("26-80978")
    assert caught.value.category == "malformed"
