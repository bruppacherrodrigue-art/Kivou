"""Minimal public Opendatasoft client for the approved DECP 2022 dataset."""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Iterator
from typing import Any, Self

import httpx

from signals.connectors.decp.errors import DecpHttpError, FailureCategory
from signals.connectors.decp.parser import DECP_DATASET

DECP_DATASET_URL = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
    f"{DECP_DATASET}/records"
)
PAGE_SIZE = 100
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

    def next_page(self) -> DecpCursor:
        return dataclasses.replace(self, offset=self.offset + PAGE_SIZE)


def decp_query(cursor: DecpCursor) -> dict[str, Any]:
    clauses = [f"datepublicationdonnees>=date'{cursor.since.isoformat()}'"]
    if cursor.until is not None:
        clauses.append(f"datepublicationdonnees<=date'{cursor.until.isoformat()}'")
    return {
        "where": " and ".join(clauses),
        "order_by": "datepublicationdonnees asc, id asc",
        "limit": PAGE_SIZE,
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

    def fetch_page(self, cursor: DecpCursor) -> list[dict]:
        try:
            response = self._client.get(DECP_DATASET_URL, params=decp_query(cursor))
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
        except (ValueError, AttributeError) as error:
            raise DecpHttpError("DECP malformed response", category="malformed") from error
        if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
            raise DecpHttpError("DECP malformed results", category="malformed")
        return results

    def fetch_contracts_since(
        self,
        since: dt.date,
        *,
        until: dt.date | None = None,
        max_records: int | None = None,
    ) -> Iterator[dict]:
        cursor = DecpCursor(since=since, until=until)
        seen = 0
        while True:
            page = self.fetch_page(cursor)
            if not page:
                return
            for record in page:
                yield record
                seen += 1
                if max_records is not None and seen >= max_records:
                    return
            if len(page) < PAGE_SIZE:
                return
            cursor = cursor.next_page()
