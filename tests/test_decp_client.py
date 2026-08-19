from __future__ import annotations

import datetime as dt

import httpx
import pytest

from signals.connectors.decp import DecpClient, DecpCursor, DecpHttpError, decp_query


def test_decp_query_uses_publication_window_and_stable_order():
    query = decp_query(
        DecpCursor(since=dt.date(2026, 8, 1), until=dt.date(2026, 8, 18), offset=100)
    )
    assert "datepublicationdonnees>=date'2026-08-01'" in query["where"]
    assert "datepublicationdonnees<=date'2026-08-18'" in query["where"]
    assert query["order_by"] == "datepublicationdonnees asc, id asc"
    assert query["offset"] == 100


def test_decp_pagination_is_bounded_by_max_records():
    offsets: list[int] = []

    def handler(request: httpx.Request):
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        return httpx.Response(200, json={"results": [{"id": offset + i} for i in range(100)]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    records = list(
        DecpClient(client=client).fetch_contracts_since(
            dt.date(2026, 8, 1), until=dt.date(2026, 8, 18), max_records=101
        )
    )
    assert len(records) == 101
    assert offsets == [0, 100]


@pytest.mark.parametrize(
    ("status", "category"),
    [(429, "rate_limited"), (503, "server_error"), (403, "unauthorized"), (400, "client_error")],
)
def test_decp_http_failures_remain_typed(status: int, category: str):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status)))
    with pytest.raises(DecpHttpError) as caught:
        DecpClient(client=client).fetch_page(DecpCursor(since=dt.date(2026, 8, 1)))
    assert caught.value.category == category
    assert caught.value.status_code == status


def test_decp_network_and_malformed_payload_are_typed():
    def network(request):
        raise httpx.ConnectError("offline", request=request)

    client = httpx.Client(transport=httpx.MockTransport(network))
    with pytest.raises(DecpHttpError) as caught:
        DecpClient(client=client).fetch_page(DecpCursor(since=dt.date(2026, 8, 1)))
    assert caught.value.category == "network"

    malformed = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"results": {}}))
    )
    with pytest.raises(DecpHttpError) as caught:
        DecpClient(client=malformed).fetch_page(DecpCursor(since=dt.date(2026, 8, 1)))
    assert caught.value.category == "malformed"
