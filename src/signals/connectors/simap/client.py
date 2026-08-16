"""Client HTTP SIMAP — le seul module qui touche au réseau.

API officielle simap.ch (OpenAPI 3.0.3, `version: 1.5.1`), lecture publique sans
authentification :

* recherche : `GET /api/publications/v2/project/project-search`
  (pagination roulante par `lastItem`) ;
* détail     : `GET /api/publications/v1/project/{projectId}/publication-details/{publicationId}` ;
* en-tête    : `GET /api/publications/v2/project/{projectId}/project-header` ;
* historique : `GET /api/publications/v1/publication/{publicationId}/past-publications`
  — `lotId` est **obligatoire** pour un projet à lots, sinon HTTP 400.

Aucun scraping HTML, aucun navigateur, aucun compte créé.

    SIMAP DOCUMENT ACCESS REQUIRES AUTHENTICATED ROLE — SPEC-006 DESIGN INPUT

Aucun endpoint public ne liste ni ne télécharge les documents de marché :
`/project-documents/v1/docs/{id}/token` exige un rôle `procurement_*` ou
`vendor_*`. Le connecteur mesure cette frontière (`SimapAuthRequiredError`), il
ne la contourne pas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self

import httpx

from signals.connectors.simap.errors import SimapAuthRequiredError, SimapHttpError
from signals.connectors.simap.parser import load_json

BASE_URL = "https://www.simap.ch/api"
USER_AGENT_DEFAULT = "Kivou/0.1 (public procurement data reuse)"

# Familles de publications annonçant une attribution, côté filtre de recherche.
AWARD_PUB_TYPE_FILTERS = (
    "award_tender",
    "award_study_contract",
    "award_competition",
    "direct_award",
)


@dataclass(frozen=True)
class PublicationRef:
    """Une publication repérée par la recherche, pas encore téléchargée.

    La recherche SIMAP retourne des **projets**, chacun accompagné de sa
    publication la plus récente : c'est cette publication-là qui est référencée
    ici, et le filtre garantit qu'elle est bien une adjudication.
    """

    project_id: str
    publication_id: str
    publication_number: str | None = None
    project_number: str | None = None
    pub_type: str | None = None
    project_sub_type: str | None = None
    process_type: str | None = None
    lots_type: str | None = None
    publication_date: str | None = None
    canton: str | None = None
    corrected: bool | None = None
    search_entry: dict[str, Any] | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> PublicationRef:
        return cls(
            project_id=row["id"],
            publication_id=row["publicationId"],
            publication_number=row.get("publicationNumber"),
            project_number=row.get("projectNumber"),
            pub_type=row.get("pubType"),
            project_sub_type=row.get("projectSubType"),
            process_type=row.get("processType"),
            lots_type=row.get("lotsType"),
            publication_date=row.get("publicationDate"),
            canton=(row.get("orderAddress") or {}).get("cantonId"),
            corrected=row.get("corrected"),
            search_entry=row,
        )


class SimapClient:
    """Client minimal, lecture publique seulement."""

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        user_agent: str = USER_AGENT_DEFAULT,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        # En-têtes posés à chaque requête : un client injecté ne doit pas faire
        # disparaître le User-Agent qui nous identifie auprès de simap.ch.
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self._client = client or httpx.Client(
            timeout=timeout, headers=self._headers, follow_redirects=True
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ─── Recherche ──────────────────────────────────────────────────────────────

    def search_awards(
        self,
        *,
        pub_type_filter: str = "award_tender",
        published_from: str | None = None,
        last_item: str | None = None,
    ) -> tuple[list[PublicationRef], str | None]:
        """Une page de projets dont la publication la plus récente est une adjudication.

        Retourne les publications et le curseur `lastItem` de la page suivante.
        """
        params: dict[str, Any] = {"newestPubTypes": pub_type_filter}
        if published_from:
            params["newestPublicationFrom"] = published_from
        if last_item:
            params["lastItem"] = last_item
        body = self._get("/publications/v2/project/project-search", params=params)
        rows = body.get("projects") or []
        return [PublicationRef.from_row(row) for row in rows], (body.get("pagination") or {}).get(
            "lastItem"
        )

    def search_all_awards(
        self,
        *,
        wanted: int,
        published_from: str | None = None,
        pub_type_filters: tuple[str, ...] = AWARD_PUB_TYPE_FILTERS,
        max_pages_per_filter: int = 10,
    ) -> list[PublicationRef]:
        """Pagination bornée, RÉPARTIE sur les familles d'adjudication.

        Les familles sont interrogées à tour de rôle, une page chacune : épuiser
        la première donnerait un échantillon de procédures ouvertes uniquement,
        sans gré à gré, sans concours, sans mandat d'étude.

        `max_pages_per_filter` est un plafond dur : une requête trop large
        s'arrête au lieu de marteler l'API.
        """
        collected: dict[str, PublicationRef] = {}
        cursors: dict[str, str | None] = dict.fromkeys(pub_type_filters)
        exhausted: set[str] = set()
        for _ in range(max_pages_per_filter):
            for pub_type in pub_type_filters:
                if pub_type in exhausted or len(collected) >= wanted:
                    continue
                rows, cursors[pub_type] = self.search_awards(
                    pub_type_filter=pub_type,
                    published_from=published_from,
                    last_item=cursors[pub_type],
                )
                for row in rows:
                    collected.setdefault(row.publication_id, row)
                if not rows or not cursors[pub_type]:
                    exhausted.add(pub_type)
            if len(collected) >= wanted or len(exhausted) == len(pub_type_filters):
                break
        return list(collected.values())[:wanted]

    # ─── Détail, en-tête, historique ────────────────────────────────────────────

    def fetch_publication(self, project_id: str, publication_id: str) -> Any:
        return self._get(
            f"/publications/v1/project/{project_id}/publication-details/{publication_id}"
        )

    def fetch_project_header(self, project_id: str) -> Any:
        return self._get(f"/publications/v2/project/{project_id}/project-header")

    def fetch_past_publications(self, publication_id: str, *, lot_id: str | None = None) -> Any:
        """Historique des publications antérieures.

        `lot_id` est requis dès que le projet a des lots : sans lui, l'API répond
        400. Ce n'est pas une erreur de notre côté, c'est le contrat de l'API.
        """
        params = {"lotId": lot_id} if lot_id else None
        return self._get(f"/publications/v1/publication/{publication_id}/past-publications", params)

    # ─── Transport ──────────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self._client.get(url, params=params, headers=self._headers)
        except httpx.HTTPError as exc:
            raise SimapHttpError(f"simap.ch injoignable : {exc}", url=url) from exc
        if response.status_code in (401, 403):
            raise SimapAuthRequiredError(
                f"accès refusé sans authentification ({response.status_code})",
                status_code=response.status_code,
                url=url,
            )
        if response.status_code != 200:
            raise SimapHttpError(
                f"simap.ch a répondu {response.status_code} : {response.text[:300]}",
                status_code=response.status_code,
                url=url,
            )
        # Décodage à la main pour garder les montants en Decimal exact.
        return load_json(response.content)
