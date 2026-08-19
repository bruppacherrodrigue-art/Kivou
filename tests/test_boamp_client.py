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
