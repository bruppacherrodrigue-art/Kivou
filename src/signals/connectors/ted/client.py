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

import datetime as dt
import email.utils
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self

import httpx

from signals.connectors.ted.errors import TedHttpError

SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
NOTICE_XML_URL = "https://ted.europa.eu/en/notice/{publication_number}/xml"

USER_AGENT_DEFAULT = "award-signals/0.1 (+https://github.com/; TED data reuse)"
RETRYABLE_STATUS_CODES = frozenset({202, 429})

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
        request_interval_seconds: float = 1.0,
        max_attempts: int = 4,
        max_retry_seconds: float = 120.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        if request_interval_seconds < 0:
            raise ValueError("TED request interval cannot be negative")
        if max_attempts < 1:
            raise ValueError("TED max attempts must be positive")
        if max_retry_seconds <= 0:
            raise ValueError("TED max retry duration must be positive")
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
        self._request_timeout_seconds = timeout
        self._request_interval_seconds = request_interval_seconds
        self._max_attempts = max_attempts
        self._max_retry_seconds = max_retry_seconds
        self._sleep = sleep
        self._monotonic = monotonic
        self._wall_clock = wall_clock or (lambda: dt.datetime.now(tz=dt.UTC))
        self._request_lock = threading.Lock()
        self._last_request_started: float | None = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @staticmethod
    def _category(status_code: int | None, error: BaseException | None = None) -> str:
        if status_code == 429:
            return "rate_limited"
        if status_code == 202 or (status_code is not None and status_code >= 500):
            return "server_error"
        if status_code in (401, 403):
            return "unauthorized"
        if status_code is not None and status_code >= 400:
            return "client_error"
        if isinstance(error, httpx.TimeoutException):
            return "timeout"
        return "network"

    @staticmethod
    def _retryable_status(status_code: int) -> bool:
        return status_code in RETRYABLE_STATUS_CODES or status_code >= 500

    def _retry_after_seconds(self, response: httpx.Response) -> float | None:
        raw = response.headers.get("Retry-After")
        if raw is None:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            try:
                parsed = email.utils.parsedate_to_datetime(raw)
            except (TypeError, ValueError, OverflowError):
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.UTC)
            now = self._wall_clock()
            if now.tzinfo is None:
                now = now.replace(tzinfo=dt.UTC)
            return max(0.0, (parsed - now).total_seconds())

    def _pace(self, *, deadline: float) -> None:
        if self._last_request_started is None:
            return
        now = self._monotonic()
        delay = self._last_request_started + self._request_interval_seconds - now
        if delay <= 0:
            return
        if now + delay > deadline:
            raise TedHttpError(
                "requête TED interrompue par la durée maximale",
                category="timeout",
            )
        self._sleep(delay)

    def _request(
        self,
        method: str,
        url: str,
        *,
        operation: str,
        headers: dict[str, str],
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        with self._request_lock:
            deadline = self._monotonic() + self._max_retry_seconds
            for attempt in range(1, self._max_attempts + 1):
                self._pace(deadline=deadline)
                self._last_request_started = self._monotonic()
                response: httpx.Response | None = None
                cause: httpx.HTTPError | None = None
                try:
                    remaining_seconds = deadline - self._monotonic()
                    if remaining_seconds <= 0:
                        raise TedHttpError(
                            "requête TED interrompue par la durée maximale",
                            url=url,
                            category="timeout",
                        )
                    response = self._client.request(
                        method,
                        url,
                        headers=headers,
                        json=json,
                        timeout=min(self._request_timeout_seconds, remaining_seconds),
                    )
                except httpx.HTTPError as error:
                    cause = error

                if response is not None and response.status_code == 200:
                    return response

                status_code = response.status_code if response is not None else None
                category = self._category(status_code, cause)
                if operation == "recherche":
                    message = (
                        f"recherche TED en échec ({status_code})"
                        if status_code is not None
                        else "recherche TED injoignable"
                    )
                else:
                    message = (
                        f"XML TED indisponible ({status_code})"
                        if status_code is not None
                        else "XML TED injoignable"
                    )
                failure = TedHttpError(
                    message,
                    status_code=status_code,
                    url=url,
                    category=category,
                )
                retryable = cause is not None or (
                    status_code is not None and self._retryable_status(status_code)
                )
                if not retryable or attempt == self._max_attempts:
                    raise failure from cause

                exponential_delay = float(min(30, 2 ** (attempt - 1)))
                provider_delay = (
                    self._retry_after_seconds(response) if response is not None else None
                )
                delay = max(exponential_delay, provider_delay or 0.0)
                now = self._monotonic()
                if now + delay > deadline:
                    raise failure from cause
                self._sleep(delay)
        raise AssertionError("bounded TED retry loop exhausted")  # pragma: no cover

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
        response = self._request(
            "POST",
            self.search_url,
            operation="recherche",
            json=payload,
            headers={**self._headers, "Accept": "application/json"},
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
        response = self._request(
            "GET",
            url,
            operation="XML",
            headers={**self._headers, "Accept": "application/xml"},
        )
        return response.content
