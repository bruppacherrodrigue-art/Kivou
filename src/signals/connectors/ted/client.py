"""Client HTTP TED — le seul module qui touche au réseau.

API officielle, publique, sans authentification :

* recherche : `POST https://api.ted.europa.eu/v3/notices/search`
  (Search API v3, destinée aux réutilisateurs de données) ;
* XML d'une notice : `GET https://ted.europa.eu/{lang}/notice/{n°}/xml`,
  lien fourni par la recherche elle-même (`links.xml.MUL`).

Aucun scraping : ni HTML de résultats, ni moteur de recherche. Le parsing vit
dans `parser.py` et n'a jamais besoin de ce module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self

import httpx

from signals.connectors.ted.errors import TedHttpError

SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
NOTICE_XML_URL = "https://ted.europa.eu/en/notice/{publication_number}/xml"

USER_AGENT_DEFAULT = "award-signals/0.1 (+https://github.com/; TED data reuse)"

# Champs demandés à la recherche : le strict nécessaire pour identifier une
# notice et aller chercher son XML. Le contenu métier vient du XML, pas d'ici.
DEFAULT_FIELDS = (
    "publication-number",
    "notice-identifier",
    "notice-version",
    "notice-type",
    "publication-date",
    "organisation-country-buyer",
)


@dataclass(frozen=True)
class NoticeRef:
    """Une notice repérée par la recherche, pas encore téléchargée."""

    publication_number: str
    notice_identifier: str | None = None
    notice_version: int | None = None
    notice_type: str | None = None
    publication_date: str | None = None
    buyer_country: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> NoticeRef:
        countries = row.get("organisation-country-buyer") or []
        return cls(
            publication_number=row["publication-number"],
            notice_identifier=row.get("notice-identifier"),
            notice_version=row.get("notice-version"),
            notice_type=row.get("notice-type"),
            publication_date=row.get("publication-date"),
            buyer_country=countries[0] if countries else None,
        )


class TedClient:
    """Client minimal. Un seul portail aujourd'hui : pas d'abstraction de plugin."""

    def __init__(
        self,
        *,
        search_url: str = SEARCH_URL,
        notice_xml_url: str = NOTICE_XML_URL,
        timeout: float = 30.0,
        user_agent: str = USER_AGENT_DEFAULT,
        client: httpx.Client | None = None,
    ) -> None:
        self.search_url = search_url
        self.notice_xml_url = notice_xml_url
        self._owns_client = client is None
        # Les en-têtes sont posés à CHAQUE requête, pas seulement sur le client
        # créé ici : un `httpx.Client` injecté (tests, proxy d'entreprise) ne doit
        # pas faire disparaître le User-Agent qui nous identifie auprès de TED.
        self._headers = {"User-Agent": user_agent}
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

    def search(
        self,
        query: str,
        *,
        limit: int = 25,
        page: int = 1,
        fields: tuple[str, ...] = DEFAULT_FIELDS,
    ) -> tuple[list[NoticeRef], int]:
        """Une page de résultats. Retourne les notices et le total annoncé par TED."""
        payload = {
            "query": query,
            "fields": list(fields),
            "limit": limit,
            "page": page,
            "scope": "ALL",
            "paginationMode": "PAGE_NUMBER",
        }
        try:
            response = self._client.post(
                self.search_url,
                json=payload,
                headers={**self._headers, "Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise TedHttpError(f"recherche TED injoignable : {exc}", url=self.search_url) from exc
        if response.status_code != 200:
            raise TedHttpError(
                f"recherche TED en échec ({response.status_code}) : {response.text[:300]}",
                status_code=response.status_code,
                url=self.search_url,
            )
        body = response.json()
        rows = body.get("notices") or []
        return [NoticeRef.from_row(row) for row in rows], int(body.get("totalNoticeCount", 0))

    def search_all(
        self,
        query: str,
        *,
        wanted: int,
        page_size: int = 50,
        max_pages: int = 20,
    ) -> list[NoticeRef]:
        """Pagination bornée : ni boucle infinie, ni aspiration du corpus.

        `max_pages` est un plafond dur — une requête trop large s'arrête au lieu
        de marteler l'API.
        """
        collected: list[NoticeRef] = []
        for page in range(1, max_pages + 1):
            rows, _ = self.search(query, limit=min(page_size, wanted - len(collected)), page=page)
            collected.extend(rows)
            if not rows or len(collected) >= wanted:
                break
        return collected[:wanted]

    # ─── XML d'une notice ───────────────────────────────────────────────────────

    def fetch_notice_xml(self, publication_number: str) -> bytes:
        url = self.notice_xml_url.format(publication_number=publication_number)
        try:
            response = self._client.get(url, headers={**self._headers, "Accept": "application/xml"})
        except httpx.HTTPError as exc:
            raise TedHttpError(f"XML TED injoignable : {exc}", url=url) from exc
        if response.status_code != 200:
            raise TedHttpError(
                f"XML TED indisponible ({response.status_code}) pour {publication_number}",
                status_code=response.status_code,
                url=url,
            )
        return response.content
