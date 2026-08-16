"""Clients des registres officiels — le seul code de résolution qui sort sur le réseau.

Un registre est une **preuve externe**, pas une nouvelle vérité. Deux règles en
découlent, appliquées ici :

- une panne n'est jamais un résultat négatif : `VatCheck.unavailable` existe
  précisément pour ne pas confondre « je n'ai pas pu vérifier » avec « ce n'est
  pas valide » ;
- rien n'est inventé : aucune requête n'est fabriquée à partir d'un nom
  d'entreprise pour deviner un numéro.

Deux registres, deux réalités mesurées sur le corpus :

* **VIES** (Commission européenne) — REST public, sans authentification. Valide
  un numéro de TVA déjà publié et retourne parfois le nom et l'adresse.
* **Zefix** (registre du commerce suisse) — `Zefix PublicREST API 2.7.2.3`,
  **authentification obligatoire** (`Zefix-Credentials`) sur tous les endpoints.
  Le client est prêt ; sans identifiants il ne part jamais sur le réseau.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self

import httpx

VIES_URL = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{country}/vat/{number}"
ZEFIX_URL = "https://www.zefix.admin.ch/ZefixPublicREST"
USER_AGENT_DEFAULT = "Kivou/0.1 (public procurement data reuse)"


class RegistryError(Exception):
    """Le registre n'a pas répondu utilement. Jamais interprété comme un « non »."""


class RegistryAuthRequiredError(RegistryError):
    """Le registre exige des identifiants que nous n'avons pas."""


@dataclass(frozen=True)
class VatCheck:
    """Réponse VIES pour un numéro donné."""

    country: str
    number: str
    valid: bool | None  # None = indéterminé (service indisponible)
    name: str | None = None
    address: str | None = None
    unavailable: bool = False
    detail: str | None = None

    @property
    def discloses_holder(self) -> bool:
        """Certains États ne divulguent ni nom ni adresse — l'absence n'est pas un refus."""
        return bool(self.name and self.name.strip("- "))


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    # VIES renvoie « --- » quand l'État membre ne divulgue pas l'information.
    return None if not text or set(text) <= {"-", " "} else text


class ViesClient:
    """Validation de TVA intracommunautaire. Public, sans authentification.

    Le cache est celui d'un run : une même entreprise revient des dizaines de
    fois dans un corpus, le registre ne doit pas être appelé à chaque fois.
    """

    def __init__(
        self,
        *,
        base_url: str = VIES_URL,
        timeout: float = 20.0,
        user_agent: str = USER_AGENT_DEFAULT,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url
        self._owns_client = client is None
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self._client = client or httpx.Client(timeout=timeout, headers=self._headers)
        self._cache: dict[tuple[str, str], VatCheck] = {}
        self.requests_sent = 0
        self.cache_hits = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def check(self, country: str, number: str) -> VatCheck:
        key = (country.upper(), number.upper())
        if key in self._cache:
            self.cache_hits += 1
            return self._cache[key]

        url = self.base_url.format(country=key[0], number=key[1])
        try:
            self.requests_sent += 1
            response = self._client.get(url)
        except httpx.HTTPError as exc:
            result = VatCheck(*key, valid=None, unavailable=True, detail=str(exc))
            self._cache[key] = result
            return result

        if response.status_code != 200:
            result = VatCheck(
                *key, valid=None, unavailable=True, detail=f"HTTP {response.status_code}"
            )
            self._cache[key] = result
            return result

        body = response.json()
        error = body.get("userError")
        # `MS_UNAVAILABLE` : l'État membre interrogé est hors ligne. Ce n'est pas
        # un numéro invalide, c'est une absence de réponse.
        if error and error != "VALID" and error.endswith("UNAVAILABLE"):
            result = VatCheck(*key, valid=None, unavailable=True, detail=error)
        else:
            result = VatCheck(
                *key,
                valid=bool(body.get("isValid")),
                name=_clean(body.get("name")),
                address=_clean(body.get("address")),
                detail=error,
            )
        self._cache[key] = result
        return result


@dataclass
class ZefixCredentials:
    """Identifiants du registre suisse, obtenus auprès de l'Office fédéral."""

    username: str
    password: str


class ZefixClient:
    """Registre du commerce suisse — `AUTH REQUIRED`.

    Tous les endpoints de `Zefix PublicREST API 2.7.2.3` sont protégés par
    `Zefix-Credentials` : une recherche anonyme répond **401**. Sans
    identifiants, ce client lève `RegistryAuthRequiredError` **sans émettre de
    requête** — il ne va pas éprouver un mur pour le plaisir, et il ne cherche
    aucun contournement.
    """

    def __init__(
        self,
        *,
        credentials: ZefixCredentials | None = None,
        base_url: str = ZEFIX_URL,
        timeout: float = 20.0,
        user_agent: str = USER_AGENT_DEFAULT,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.credentials = credentials
        self._owns_client = client is None
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self._client = client or httpx.Client(timeout=timeout, headers=self._headers)
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self.requests_sent = 0
        self.cache_hits = 0

    @property
    def available(self) -> bool:
        return self.credentials is not None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def search_by_name(self, name: str) -> list[dict[str, Any]]:
        """Candidats du registre pour une raison sociale. Lève si non authentifié."""
        if not self.available:
            raise RegistryAuthRequiredError(
                "Zefix exige des identifiants (Zefix-Credentials) sur tous ses endpoints"
            )
        if name in self._cache:
            self.cache_hits += 1
            return self._cache[name]

        url = f"{self.base_url}/api/v1/company/search"
        try:
            self.requests_sent += 1
            response = self._client.post(
                url,
                json={"name": name},
                headers=self._headers,
                auth=(self.credentials.username, self.credentials.password),
            )
        except httpx.HTTPError as exc:
            raise RegistryError(f"Zefix injoignable : {exc}") from exc
        if response.status_code in (401, 403):
            raise RegistryAuthRequiredError(
                f"Zefix a refusé les identifiants ({response.status_code})"
            )
        if response.status_code != 200:
            raise RegistryError(f"Zefix a répondu {response.status_code}")
        result = response.json()
        rows = result if isinstance(result, list) else result.get("list") or []
        self._cache[name] = rows
        return rows
