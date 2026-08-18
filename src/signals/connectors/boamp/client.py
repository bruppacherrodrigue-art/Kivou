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
from collections.abc import Iterator
from typing import Any, Self

import httpx

BOAMP_DATASET_URL = (
    "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp"
)
RECORDS_URL = f"{BOAMP_DATASET_URL}/records"

PAGE_SIZE = 100
"""Plafond de l'API Opendatasoft pour un appel `records`."""

USER_AGENT_DEFAULT = "Kivou/0.1 (award signals; reutilisation de donnees publiques)"

AWARD_NATURE = "ATTRIBUTION"


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

    def fetch_page(self, cursor: AwardCursor) -> list[dict]:
        response = self._client.get(RECORDS_URL, params=award_query(cursor))
        response.raise_for_status()
        payload = response.json()
        return list(payload.get("results", []))

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
