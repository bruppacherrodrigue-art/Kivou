from __future__ import annotations

import datetime as dt
import re

import httpx
import pytest

from signals.connectors.decp import (
    DecpClient,
    DecpCursor,
    DecpHttpError,
    DecpWindowLimitError,
    decp_query,
)

_DATES = re.compile(
    r"datepublicationdonnees>=date'(?P<since>\d{4}-\d{2}-\d{2})'.*"
    r"datepublicationdonnees<=date'(?P<until>\d{4}-\d{2}-\d{2})'"
)


def _bounds(request: httpx.Request) -> tuple[dt.date, dt.date]:
    matched = _DATES.search(str(request.url.params["where"]))
    assert matched is not None
    return (
        dt.date.fromisoformat(matched.group("since")),
        dt.date.fromisoformat(matched.group("until")),
    )


def _partition_transport(
    totals: dict[tuple[dt.date, dt.date], int],
    requests: list[tuple[dt.date, dt.date, int, int]],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        since, until = _bounds(request)
        offset = int(request.url.params["offset"])
        limit = int(request.url.params["limit"])
        requests.append((since, until, offset, limit))
        assert offset + limit < 10_000
        total = totals[(since, until)]
        count = max(0, min(limit, total - offset))
        results = [
            {"id": f"{since.isoformat()}:{until.isoformat()}:{offset + index}"}
            for index in range(count)
        ]
        return httpx.Response(200, json={"total_count": total, "results": results})

    return httpx.MockTransport(handler)


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
        limit = int(request.url.params["limit"])
        offsets.append(offset)
        return httpx.Response(
            200,
            json={
                "total_count": 1_000,
                "results": [{"id": offset + i} for i in range(limit)],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    records = list(
        DecpClient(client=client).fetch_contracts_since(
            dt.date(2026, 8, 1), until=dt.date(2026, 8, 18), max_records=101
        )
    )
    assert len(records) == 101
    assert offsets == [0, 0, 100]


def test_9999_records_use_the_exact_final_page_size_without_crossing_the_ceiling():
    since = dt.date(2026, 8, 1)
    until = dt.date(2026, 8, 1)
    requests: list[tuple[dt.date, dt.date, int, int]] = []
    client = httpx.Client(
        transport=_partition_transport({(since, until): 9_999}, requests)
    )

    records = list(DecpClient(client=client).fetch_contracts_since(since, until=until))

    assert len(records) == 9_999
    assert (since, until, 9_900, 99) in requests
    assert requests[-1] == (since, until, 0, 1)
    assert (since, until, 9_999, 1) not in requests
    assert all(offset + limit < 10_000 for _, _, offset, limit in requests)


def test_decp_query_rejects_every_request_at_or_above_the_strict_ceiling():
    day = dt.date(2026, 8, 1)

    with pytest.raises(DecpWindowLimitError) as equal:
        decp_query(DecpCursor(since=day, until=day, offset=9_999), limit=1)

    assert equal.value.category == "source_limit"

    with pytest.raises(DecpWindowLimitError) as above:
        decp_query(DecpCursor(since=day, until=day, offset=9_999), limit=2)

    assert above.value.category == "source_limit"


def test_exactly_10000_records_partition_before_unsafe_offset_pagination():
    first = dt.date(2026, 8, 1)
    second = dt.date(2026, 8, 2)
    requests: list[tuple[dt.date, dt.date, int, int]] = []
    totals = {
        (first, second): 10_000,
        (first, first): 5_000,
        (second, second): 5_000,
    }
    client = httpx.Client(transport=_partition_transport(totals, requests))

    records = list(DecpClient(client=client).fetch_contracts_since(first, until=second))

    assert len(records) == 10_000
    assert not any(
        since == first and until == second and limit > 1
        for since, until, _, limit in requests
    )
    assert {record["id"].split(":", 1)[0] for record in records} == {
        first.isoformat(),
        second.isoformat(),
    }


def test_above_ceiling_recursively_partitions_in_chronological_date_order():
    day1 = dt.date(2026, 8, 1)
    day2 = dt.date(2026, 8, 2)
    day3 = dt.date(2026, 8, 3)
    day4 = dt.date(2026, 8, 4)
    requests: list[tuple[dt.date, dt.date, int, int]] = []
    totals = {
        (day1, day4): 12_000,
        (day1, day2): 11_000,
        (day1, day1): 6_000,
        (day2, day2): 5_000,
        (day3, day4): 1_000,
    }
    client = httpx.Client(transport=_partition_transport(totals, requests))

    records = list(DecpClient(client=client).fetch_contracts_since(day1, until=day4))

    assert len(records) == 12_000
    record_windows = [record["id"].rsplit(":", 1)[0] for record in records]
    assert record_windows == sorted(record_windows)
    assert {bounds[:2] for bounds in requests if bounds[3] > 1} == {
        (day1, day1),
        (day2, day2),
        (day3, day4),
    }


def test_one_calendar_day_at_the_ceiling_fails_with_typed_source_limit():
    day = dt.date(2026, 8, 1)
    requests: list[tuple[dt.date, dt.date, int, int]] = []
    client = httpx.Client(transport=_partition_transport({(day, day): 10_000}, requests))

    with pytest.raises(DecpWindowLimitError) as caught:
        list(DecpClient(client=client).fetch_contracts_since(day, until=day))

    assert caught.value.category == "source_limit"


@pytest.mark.parametrize("final_total", [10_001, 9_998])
def test_final_count_drift_fails_closed_without_an_unsafe_probe(final_total: int):
    day = dt.date(2026, 8, 1)
    requests: list[tuple[int, int]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        limit = int(request.url.params["limit"])
        requests.append((offset, limit))
        assert offset + limit < 10_000
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={"total_count": 9_999, "results": [{"id": "initial-count"}]},
            )
        if offset == 0 and limit == 1:
            return httpx.Response(
                200,
                json={"total_count": final_total, "results": [{"id": "final-count"}]},
            )
        count = min(limit, 9_999 - offset)
        return httpx.Response(
            200,
            json={
                "total_count": 9_999,
                "results": [{"id": offset + index} for index in range(count)],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(DecpWindowLimitError) as caught:
        list(DecpClient(client=client).fetch_contracts_since(day, until=day))

    assert caught.value.category == "source_limit"
    assert (9_999, 1) not in requests
    assert requests[-1] == (0, 1)
    assert all(offset + limit < 10_000 for offset, limit in requests)


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


def test_decp_stop_callback_prevents_the_next_provider_request() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"total_count": 1, "results": [{"id": "one"}]})

    class StopRequested(RuntimeError):
        pass

    def stop() -> None:
        raise StopRequested("bounded pass ended")

    client = DecpClient(client=httpx.Client(transport=httpx.MockTransport(handler)))

    with pytest.raises(StopRequested, match="bounded pass ended"):
        list(
            client.fetch_contracts_since(
                dt.date(2026, 8, 25),
                until=dt.date(2026, 8, 25),
                should_stop=stop,
            )
        )

    assert requests == []


def test_decp_batch_resumes_at_an_intra_day_offset_and_is_strictly_bounded() -> None:
    day = dt.date(2026, 8, 25)
    requests: list[tuple[dt.date, dt.date, int, int]] = []
    client = DecpClient(
        client=httpx.Client(
            transport=_partition_transport({(day, day): 5}, requests)
        )
    )

    batch = client.fetch_contract_batch(
        day,
        offset=2,
        expected_total=5,
        batch_size=2,
    )

    assert [record["id"] for record in batch.records] == [
        "2026-08-25:2026-08-25:2",
        "2026-08-25:2026-08-25:3",
    ]
    assert batch.next_offset == 4
    assert batch.window_total == 5
    assert batch.day_complete is False
    assert batch.reset is False
    assert requests == [
        (day, day, 0, 1),
        (day, day, 2, 2),
        (day, day, 0, 1),
    ]


def test_decp_batch_resets_idempotently_when_the_day_total_changed() -> None:
    day = dt.date(2026, 8, 25)
    requests: list[tuple[dt.date, dt.date, int, int]] = []
    client = DecpClient(
        client=httpx.Client(
            transport=_partition_transport({(day, day): 4}, requests)
        )
    )

    batch = client.fetch_contract_batch(
        day,
        offset=3,
        expected_total=5,
        batch_size=2,
    )

    assert [record["id"] for record in batch.records] == [
        "2026-08-25:2026-08-25:0",
        "2026-08-25:2026-08-25:1",
    ]
    assert batch.next_offset == 2
    assert batch.window_total == 4
    assert batch.day_complete is False
    assert batch.reset is True
    assert requests[1] == (day, day, 0, 2)


def test_decp_batch_rejects_an_offset_beyond_the_observed_day() -> None:
    day = dt.date(2026, 8, 25)
    requests: list[tuple[dt.date, dt.date, int, int]] = []
    client = DecpClient(
        client=httpx.Client(
            transport=_partition_transport({(day, day): 3}, requests)
        )
    )

    with pytest.raises(DecpWindowLimitError, match="offset") as caught:
        client.fetch_contract_batch(
            day,
            offset=4,
            expected_total=3,
            batch_size=2,
        )

    assert caught.value.category == "source_limit"
    assert requests == [(day, day, 0, 1)]
