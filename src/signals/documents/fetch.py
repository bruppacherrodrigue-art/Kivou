"""Téléchargement de documents — bornes explicites, empreinte systématique.

Rien n'est exécuté, rien n'est suivi automatiquement, rien n'est deviné. Un
serveur qui refuse produit un **état**, pas une exception qui remonte : un 403
signifie « il faut un compte », et cela reste un fait exploitable.

Le cache est celui d'un run : un même dossier est référencé par plusieurs awards,
et le même URL ne doit être téléchargé qu'une fois.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from typing import Self

import httpx

from signals.documents.model import DocumentAccessStatus

# Seuls schémas suivis. `file://` ferait du téléchargeur un lecteur de disque,
# et un avis publie parfois une adresse sans schéma du tout (« /www.example.fr »,
# rencontré en BT-15) : la refuser vaut mieux que de tomber dessus.
_FOLLOWED_SCHEMES = ("http://", "https://")

USER_AGENT_DEFAULT = "Kivou/0.1 (public procurement data reuse)"

# Types renvoyés par un portail lorsqu'il sert une page, pas un document.
_PAGE_TYPES = ("text/html", "application/xhtml+xml")


@dataclass(frozen=True)
class FetchLimits:
    """Plafonds explicites. Un document ne doit jamais pouvoir saturer la machine."""

    max_bytes: int = 64 * 1024 * 1024
    timeout: float = 60.0


@dataclass
class FetchResult:
    """Le résultat d'une tentative — toujours un état, jamais une exception nue."""

    url: str
    access_status: DocumentAccessStatus
    content: bytes | None = None
    media_type: str | None = None
    byte_size: int | None = None
    content_hash: str | None = None
    retrieved_at: dt.datetime | None = None
    detail: str | None = None

    @property
    def is_document(self) -> bool:
        return self.access_status == "available"


def content_hash(data: bytes) -> str:
    """Empreinte des octets bruts : ce qui prouve quel fichier a été lu."""
    return hashlib.sha256(data).hexdigest()


class DocumentFetcher:
    """Récupère ce qui est publiquement accessible, et qualifie le reste.

    Il ne connaît aucune authentification et n'en fabrique aucune. Une
    plateforme qui exige un compte produit `auth_required` : c'est un fait du
    dossier, pas un échec de Kivou.
    """

    def __init__(
        self,
        *,
        limits: FetchLimits | None = None,
        user_agent: str = USER_AGENT_DEFAULT,
        client: httpx.Client | None = None,
    ) -> None:
        self.limits = limits or FetchLimits()
        self._headers = {"User-Agent": user_agent, "Accept": "*/*"}
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=self.limits.timeout, headers=self._headers, follow_redirects=True
        )
        self._cache: dict[str, FetchResult] = {}
        self.requests_sent = 0
        self.cache_hits = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch(self, url: str) -> FetchResult:
        if url in self._cache:
            self.cache_hits += 1
            return self._cache[url]

        result = self._fetch(url)
        self._cache[url] = result
        return result

    def _fetch(self, url: str) -> FetchResult:
        if not url.lower().startswith(_FOLLOWED_SCHEMES):
            return FetchResult(url, "download_failed", detail="adresse non exploitable")
        try:
            self.requests_sent += 1
            response = self._client.get(url, headers=self._headers)
        except httpx.HTTPError as exc:
            return FetchResult(url, "download_failed", detail=str(exc))

        if response.status_code in (401, 403):
            return FetchResult(url, "auth_required", detail=f"HTTP {response.status_code}")
        if response.status_code == 404:
            return FetchResult(url, "not_found", detail="HTTP 404")
        if response.status_code >= 400:
            return FetchResult(url, "download_failed", detail=f"HTTP {response.status_code}")

        data = response.content
        media = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        if len(data) > self.limits.max_bytes:
            return FetchResult(
                url,
                "too_large",
                media_type=media,
                byte_size=len(data),
                detail=f"{len(data)} octets au-delà de {self.limits.max_bytes}",
            )

        # Une page de portail n'est pas un document du dossier : c'est un
        # pointeur. Le distinguer évite de traiter un menu de navigation comme
        # un cahier des charges.
        if media in _PAGE_TYPES and data[:4] not in (b"%PDF", b"PK\x03\x04"):
            return FetchResult(
                url,
                "external",
                media_type=media,
                byte_size=len(data),
                detail="page de portail, pas un fichier",
            )

        return FetchResult(
            url,
            "available",
            content=data,
            media_type=media or None,
            byte_size=len(data),
            content_hash=content_hash(data),
            retrieved_at=dt.datetime.now(dt.UTC),
        )
