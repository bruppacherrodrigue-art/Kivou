"""Client HTTP BOAMP — le seul module du connecteur qui touche au réseau.

API publique Opendatasoft v2.1, sans authentification, licence Etalab 2.0 :

    GET https://boamp-datadila.opendatasoft.com/api/explore/v2.1
        /catalog/datasets/boamp/records

Aucun scraping : ni HTML de résultats, ni portail acheteur. Le parsing vit dans
`parser.py` et n'a jamais besoin de ce module — c'est ce qui rend les tests
d'adapter exécutables hors ligne.

    Curseur (§38)
    ─────────────
    La reprise se fait sur `dateparution`, jamais sur un décalage : un offset se
    périme dès qu'un avis s'insère dans la fenêtre, une date non. L'ordre
    `dateparution asc, idweb asc` est total, donc deux pages consécutives ne
    peuvent ni se recouvrir ni sauter un avis.

Aucun daemon n'est fourni. Ce module rend seulement l'appel « donne-moi les
attributions depuis telle date » exprimable, ce que le futur polling VPS exige.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from collections.abc import Iterator
from typing import Any, Self

import httpx

from signals.connectors.boamp.errors import BoampHttpError, FailureCategory

BOAMP_DATASET_URL = (
    "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp"
)
RECORDS_URL = f"{BOAMP_DATASET_URL}/records"

PAGE_SIZE = 100
"""Plafond de l'API Opendatasoft pour un appel `records`."""

USER_AGENT_DEFAULT = "Kivou/0.1 (award signals; reutilisation de donnees publiques)"

AWARD_NATURE = "ATTRIBUTION"
TENDER_NATURE = "APPEL_OFFRE"


@dataclasses.dataclass(frozen=True)
class AwardCursor:
    """Où reprendre la lecture du catalogue — une date, pas un état de session."""

    since: dt.date
    until: dt.date | None = None
    offset: int = 0

    def __post_init__(self) -> None:
        if self.until is not None and self.until < self.since:
            raise ValueError(
                f"fenêtre invalide : {self.until.isoformat()} précède {self.since.isoformat()}"
            )
        if self.offset < 0:
            raise ValueError("offset négatif")

    def next_page(self) -> AwardCursor:
        return dataclasses.replace(self, offset=self.offset + PAGE_SIZE)

    def advance_to(self, since: dt.date) -> AwardCursor:
        """Nouvelle fenêtre, pagination remise à zéro — sinon des avis seraient sautés."""
        return AwardCursor(since=since, until=self.until, offset=0)


def award_query(cursor: AwardCursor) -> dict[str, Any]:
    """La requête correspondant à un curseur — fonction pure, testable hors ligne."""
    clauses = [f'nature="{AWARD_NATURE}"', f"dateparution>=date'{cursor.since.isoformat()}'"]
    if cursor.until is not None:
        clauses.append(f"dateparution<=date'{cursor.until.isoformat()}'")
    return {
        "where": " and ".join(clauses),
        "order_by": "dateparution asc, idweb asc",
        "limit": PAGE_SIZE,
        "offset": cursor.offset,
    }


def tender_query(cursor: AwardCursor) -> dict[str, Any]:
    """Même fenêtre déterministe, limitée aux avis d'appel à la concurrence."""
    query = award_query(cursor)
    query["where"] = query["where"].replace(f'nature="{AWARD_NATURE}"', f'nature="{TENDER_NATURE}"')
    return query


class BoampClient:
    """Lecture du catalogue BOAMP. Aucune écriture, aucune authentification."""

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

    def fetch_page(self, cursor: AwardCursor, *, tender_notices: bool = False) -> list[dict]:
        return self._fetch_records(tender_query(cursor) if tender_notices else award_query(cursor))

    def fetch_record(self, notice_id: str) -> dict | None:
        """Exact ID lookup for bounded administrative backfill, never a date scan.

        Explore v2.1 specifies that the text equality operator is exact:
        https://help.opendatasoft.com/apis/ods-explore-v2/
        """
        if not notice_id or len(notice_id) > 256 or any(ord(char) < 32 for char in notice_id):
            raise ValueError("invalid BOAMP notice identity")
        records = self._fetch_records({"where": "idweb=" + json.dumps(notice_id), "limit": 2})
        if len(records) > 1 or (records and records[0].get("idweb") != notice_id):
            raise BoampHttpError(
                "BOAMP exact lookup returned ambiguous identity", category="malformed"
            )
        return records[0] if records else None

    def _fetch_records(self, params: dict[str, Any]) -> list[dict]:
        try:
            response = self._client.get(
                RECORDS_URL,
                params=params,
            )
        except httpx.TimeoutException as error:
            raise BoampHttpError("BOAMP request timed out", category="timeout") from error
        except httpx.HTTPError as error:
            raise BoampHttpError("BOAMP network failure", category="network") from error
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
            raise BoampHttpError(
                f"BOAMP HTTP {response.status_code}",
                category=category,
                status_code=response.status_code,
                url=str(response.request.url),
            )
        try:
            payload = response.json()
            results = payload.get("results")
        except (ValueError, AttributeError) as error:
            raise BoampHttpError("BOAMP malformed response", category="malformed") from error
        if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
            raise BoampHttpError("BOAMP malformed results", category="malformed")
        return results

    def fetch_awards_since(
        self, since: dt.date, *, until: dt.date | None = None, max_records: int | None = None
    ) -> Iterator[dict]:
        """Les avis d'attribution parus depuis `since`, page par page.

        Générateur : le futur polling pourra s'arrêter quand il veut sans avoir
        chargé tout le catalogue en mémoire (§39).
        """
        cursor = AwardCursor(since=since, until=until)
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

    def fetch_tenders_since(
        self, since: dt.date, *, until: dt.date | None = None, max_records: int | None = None
    ) -> Iterator[dict]:
        cursor = AwardCursor(since=since, until=until)
        seen = 0
        while True:
            page = self.fetch_page(cursor, tender_notices=True)
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
