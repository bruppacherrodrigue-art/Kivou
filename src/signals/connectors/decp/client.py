"""Minimal public Opendatasoft client for the approved DECP 2022 dataset."""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Iterator
from typing import Any, Self

import httpx

from signals.connectors.decp.errors import (
    DecpHttpError,
    DecpWindowLimitError,
    FailureCategory,
)
from signals.connectors.decp.parser import DECP_DATASET

DECP_DATASET_URL = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
    f"{DECP_DATASET}/records"
)
PAGE_SIZE = 100
DECP_RESULT_CEILING = 10_000
USER_AGENT_DEFAULT = "Kivou/0.1 (award signals; reutilisation de donnees publiques)"


@dataclasses.dataclass(frozen=True)
class DecpCursor:
    since: dt.date
    until: dt.date | None = None
    offset: int = 0

    def __post_init__(self) -> None:
        if self.until is not None and self.until < self.since:
            raise ValueError("invalid DECP window")
        if self.offset < 0:
            raise ValueError("negative DECP offset")

    def next_page(self, size: int = PAGE_SIZE) -> DecpCursor:
        if size <= 0:
            raise ValueError("non-positive DECP page size")
        return dataclasses.replace(self, offset=self.offset + size)


def decp_query(cursor: DecpCursor, *, limit: int = PAGE_SIZE) -> dict[str, Any]:
    if limit <= 0 or limit > PAGE_SIZE:
        raise ValueError("invalid DECP page limit")
    if cursor.offset + limit >= DECP_RESULT_CEILING:
        raise DecpWindowLimitError("DECP request would reach or cross the provider result ceiling")
    clauses = [f"datepublicationdonnees>=date'{cursor.since.isoformat()}'"]
    if cursor.until is not None:
        clauses.append(f"datepublicationdonnees<=date'{cursor.until.isoformat()}'")
    return {
        "where": " and ".join(clauses),
        "order_by": "datepublicationdonnees asc, id asc",
        "limit": limit,
        "offset": cursor.offset,
    }


class DecpClient:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        user_agent: str = USER_AGENT_DEFAULT,
        timeout: float = 60.0,
    ) -> None:
        self._owned = client is None
        self._client = client or httpx.Client(timeout=timeout, headers={"User-Agent": user_agent})

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owned:
            self._client.close()

    def _fetch_payload(
        self, cursor: DecpCursor, *, limit: int
    ) -> tuple[list[dict], int | None]:
        try:
            response = self._client.get(
                DECP_DATASET_URL,
                params=decp_query(cursor, limit=limit),
            )
        except httpx.TimeoutException as error:
            raise DecpHttpError("DECP request timed out", category="timeout") from error
        except httpx.HTTPError as error:
            raise DecpHttpError("DECP network failure", category="network") from error
        if response.status_code != 200:
            category: FailureCategory = (
                "rate_limited"
                if response.status_code == 429
                else "server_error"
                if response.status_code >= 500
                else "unauthorized"
                if response.status_code in (401, 403)
                else "client_error"
            )
            raise DecpHttpError(
                f"DECP HTTP {response.status_code}",
                category=category,
                status_code=response.status_code,
                url=str(response.request.url),
            )
        try:
            payload = response.json()
            results = payload.get("results")
            total_count = payload.get("total_count")
        except (ValueError, AttributeError) as error:
            raise DecpHttpError("DECP malformed response", category="malformed") from error
        if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
            raise DecpHttpError("DECP malformed results", category="malformed")
        if total_count is not None and (
            not isinstance(total_count, int) or isinstance(total_count, bool) or total_count < 0
        ):
            raise DecpHttpError("DECP malformed total_count", category="malformed")
        return results, total_count

    def fetch_page(self, cursor: DecpCursor, *, limit: int = PAGE_SIZE) -> list[dict]:
        results, _ = self._fetch_payload(cursor, limit=limit)
        return results

    def count_contracts(self, since: dt.date, *, until: dt.date) -> int:
        _, total = self._fetch_payload(DecpCursor(since=since, until=until), limit=1)
        if total is None:
            raise DecpHttpError("DECP response omitted total_count", category="malformed")
        return total

    def _safe_windows(
        self, since: dt.date, until: dt.date
    ) -> Iterator[tuple[DecpCursor, int]]:
        total = self.count_contracts(since, until=until)
        if total < DECP_RESULT_CEILING:
            yield DecpCursor(since=since, until=until), total
            return
        if since == until:
            raise DecpWindowLimitError(
                f"DECP day {since.isoformat()} contains {total} records at the provider ceiling"
            )
        midpoint = since + dt.timedelta(days=(until - since).days // 2)
        yield from self._safe_windows(since, midpoint)
        yield from self._safe_windows(midpoint + dt.timedelta(days=1), until)

    def _fetch_counted_window(
        self, cursor: DecpCursor, *, planned_total: int
    ) -> Iterator[dict]:
        remaining = planned_total
        current = cursor
        while remaining:
            limit = min(PAGE_SIZE, remaining)
            page, observed_total = self._fetch_payload(current, limit=limit)
            if observed_total is not None and observed_total != planned_total:
                raise DecpWindowLimitError("DECP window changed during pagination")
            if len(page) != limit:
                raise DecpWindowLimitError("DECP window became incomplete during pagination")
            yield from page
            current = current.next_page(limit)
            remaining -= limit

        if cursor.until is None:
            raise ValueError("DECP counted acquisition requires a bounded until date")
        observed_total = self.count_contracts(cursor.since, until=cursor.until)
        if observed_total != planned_total:
            raise DecpWindowLimitError("DECP window changed after count planning")

    def fetch_contracts_since(
        self,
        since: dt.date,
        *,
        until: dt.date | None = None,
        max_records: int | None = None,
    ) -> Iterator[dict]:
        if until is None:
            raise ValueError("DECP production acquisition requires a bounded until date")
        seen = 0
        for cursor, planned_total in self._safe_windows(since, until):
            for record in self._fetch_counted_window(cursor, planned_total=planned_total):
                yield record
                seen += 1
                if max_records is not None and seen >= max_records:
                    return
