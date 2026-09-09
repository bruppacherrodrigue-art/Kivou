"""Bounded public Annuaire/SIRENE search for named French companies."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from signals.companies.france import ANNUAIRE_BASE_URL, MAX_RESPONSE_BYTES


@dataclass(frozen=True)
class SireneSearchCriteria:
    naf_codes: tuple[str, ...]
    departments: tuple[str, ...]
    min_employees: int = 5
    max_employees: int = 250
    limit: int = 25


@dataclass(frozen=True)
class SireneCompany:
    legal_name: str
    siren: str
    siret: str | None
    city: str | None
    department: str | None
    employees: int | None
    naf_code: str | None
    observed_at: dt.datetime


_TRANCHE_MAX = {
    "00": 0,
    "01": 2,
    "02": 5,
    "03": 9,
    "11": 19,
    "12": 49,
    "21": 99,
    "22": 199,
    "31": 249,
    "32": 499,
    "41": 999,
}


def _tranche_employees(value: object) -> int | None:
    code = str(value or "").strip()
    if code not in _TRANCHE_MAX:
        return None
    return _TRANCHE_MAX[code]


class SireneCompanySearch:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._transport = transport
        self._clock = clock

    def find(self, criteria: SireneSearchCriteria) -> tuple[SireneCompany, ...]:
        if not criteria.naf_codes or not criteria.departments:
            raise ValueError("SIRENE search requires NAF codes and departments")
        if not 1 <= criteria.limit <= 25:
            raise ValueError("SIRENE search limit must be between 1 and 25")
        ranges = tuple(
            code
            for code, upper in _TRANCHE_MAX.items()
            if upper >= criteria.min_employees and upper <= criteria.max_employees
        )
        with httpx.Client(
            base_url=ANNUAIRE_BASE_URL,
            timeout=httpx.Timeout(15.0, connect=5.0),
            follow_redirects=False,
            transport=self._transport,
            headers={"Accept": "application/json", "User-Agent": "Kivou/1.0"},
        ) as client:
            response = client.get(
                "/search",
                params={
                    "code_naf": ",".join(criteria.naf_codes),
                    "departement": ",".join(criteria.departments),
                    "tranche_effectif_salarie": ",".join(ranges),
                    "etat_administratif": "A",
                    "page": 1,
                    "per_page": criteria.limit,
                },
            )
        if response.status_code != 200 or len(response.content) > MAX_RESPONSE_BYTES:
            raise RuntimeError(f"SIRENE search failed: HTTP {response.status_code}")
        payload: Any = response.json()
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list):
            raise TypeError("SIRENE response has no results list")
        found: list[SireneCompany] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            seat = item.get("siege") or {}
            if not isinstance(seat, dict) or seat.get("etat_administratif", "A") != "A":
                continue
            name = str(item.get("nom_complet") or item.get("nom_raison_sociale") or "").strip()
            siren = str(item.get("siren") or "").strip()
            if not name or not any(c.isalpha() for c in name) or len(siren) != 9:
                continue
            employees = _tranche_employees(seat.get("tranche_effectif_salarie"))
            if (
                employees is not None
                and not criteria.min_employees <= employees <= criteria.max_employees
            ):
                continue
            postal = str(seat.get("code_postal") or "")
            found.append(
                SireneCompany(
                    legal_name=name,
                    siren=siren,
                    siret=str(seat.get("siret") or "") or None,
                    city=str(seat.get("libelle_commune") or "") or None,
                    department=postal[:2] or None,
                    employees=employees,
                    naf_code=str(seat.get("activite_principale") or "") or None,
                    observed_at=self._clock(),
                )
            )
        department_rank = {
            department: index for index, department in enumerate(criteria.departments)
        }
        found.sort(
            key=lambda company: (
                department_rank.get(company.department or "", len(department_rank)),
                -(company.employees or 0),
                company.legal_name.casefold(),
                company.siren,
            )
        )
        return tuple(found[: criteria.limit])


__all__ = ["SireneCompany", "SireneCompanySearch", "SireneSearchCriteria"]
