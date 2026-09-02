"""Exact public SIRET lookup through the French Annuaire des Entreprises API."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

ANNUAIRE_BASE_URL = "https://recherche-entreprises.api.gouv.fr"
ANNUAIRE_CONNECTOR = "annuaire-entreprises-data-gouv-fr"
MAX_RESPONSE_BYTES = 1_048_576
_SIRET = re.compile(r"^\d{14}$")


class FrenchOfficialCompanyError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"French official company lookup: {code}")


@dataclass(frozen=True)
class FrenchOfficialCompany:
    siret: str
    legal_name: str
    address: str | None
    observed_at: dt.datetime


def _system_clock() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _exact_establishment(result: dict[str, Any], siret: str) -> dict[str, Any] | None:
    candidates = [result.get("siege"), *(result.get("matching_etablissements") or [])]
    return next(
        (
            candidate
            for candidate in candidates
            if isinstance(candidate, dict) and str(candidate.get("siret") or "") == siret
        ),
        None,
    )


class FrenchOfficialCompanyClient:
    """Fixed-origin, bounded client; a fuzzy API result is never accepted."""

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], dt.datetime] = _system_clock,
    ) -> None:
        self._transport = transport
        self._clock = clock

    def fetch_siret(self, siret: str) -> FrenchOfficialCompany:
        if _SIRET.fullmatch(siret) is None:
            raise ValueError("SIRET must contain exactly fourteen digits")
        try:
            with httpx.Client(
                base_url=ANNUAIRE_BASE_URL,
                timeout=httpx.Timeout(10.0, connect=5.0),
                follow_redirects=False,
                transport=self._transport,
                headers={"Accept": "application/json", "User-Agent": "Kivou/1.0"},
            ) as client:
                response = client.get(
                    "/search",
                    params={"q": siret, "page": 1, "per_page": 1},
                )
        except httpx.TimeoutException as error:
            raise FrenchOfficialCompanyError("official_source_timeout") from error
        except httpx.NetworkError as error:
            raise FrenchOfficialCompanyError("official_source_network_error") from error
        if response.status_code == 404:
            raise FrenchOfficialCompanyError("siret_not_found")
        if response.status_code == 429:
            raise FrenchOfficialCompanyError("official_source_rate_limited")
        if response.status_code >= 500:
            raise FrenchOfficialCompanyError("official_source_unavailable")
        if response.status_code != 200:
            raise FrenchOfficialCompanyError("official_source_rejected")
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise FrenchOfficialCompanyError("official_source_response_too_large")
        try:
            payload = response.json()
        except ValueError as error:
            raise FrenchOfficialCompanyError("official_source_malformed") from error
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
            raise FrenchOfficialCompanyError("siret_not_found")
        result = results[0]
        establishment = _exact_establishment(result, siret)
        if establishment is None:
            raise FrenchOfficialCompanyError("official_source_identity_mismatch")
        legal_name = str(
            result.get("nom_raison_sociale") or result.get("nom_complet") or ""
        ).strip()
        if not legal_name or not any(character.isalpha() for character in legal_name):
            raise FrenchOfficialCompanyError("official_source_name_missing")
        observed_at = self._clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("official company clock must be timezone-aware")
        address = str(establishment.get("adresse") or "").strip() or None
        return FrenchOfficialCompany(
            siret=siret,
            legal_name=legal_name,
            address=address,
            observed_at=observed_at,
        )


__all__ = [
    "ANNUAIRE_CONNECTOR",
    "FrenchOfficialCompany",
    "FrenchOfficialCompanyClient",
    "FrenchOfficialCompanyError",
]
