"""Bounded public Annuaire/SIRENE search for named French companies."""

from __future__ import annotations

import datetime as dt
import math
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


def _department(establishment: dict[str, object]) -> str | None:
    explicit = str(establishment.get("departement") or "").strip()
    if explicit:
        return explicit
    postal = str(establishment.get("code_postal") or "").strip()
    return postal[:2] or None


def _matching_establishment(
    item: dict[str, object], criteria: SireneSearchCriteria
) -> dict[str, object] | None:
    establishments = item.get("matching_etablissements")
    if not isinstance(establishments, list):
        return None
    department_rank = {department: index for index, department in enumerate(criteria.departments)}
    matches = [
        establishment
        for establishment in establishments
        if isinstance(establishment, dict)
        and establishment.get("etat_administratif") == "A"
        and str(establishment.get("activite_principale") or "").strip() in criteria.naf_codes
        and _department(establishment) in department_rank
    ]
    if not matches:
        return None
    matches.sort(
        key=lambda establishment: (
            department_rank[_department(establishment) or ""],
            -(_tranche_employees(establishment.get("tranche_effectif_salarie")) or 0),
            str(establishment.get("siret") or ""),
        )
    )
    return matches[0]


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
        if not 1 <= criteria.limit <= 100:
            raise ValueError("SIRENE search limit must be between 1 and 100")
        ranges = tuple(
            code
            for code, upper in _TRANCHE_MAX.items()
            if upper >= criteria.min_employees and upper <= criteria.max_employees
        )
        found: list[SireneCompany] = []
        seen_sirens: set[str] = set()
        page = 1
        total_pages = 1
        with httpx.Client(
            base_url=ANNUAIRE_BASE_URL,
            timeout=httpx.Timeout(15.0, connect=5.0),
            follow_redirects=False,
            transport=self._transport,
            headers={"Accept": "application/json", "User-Agent": "Kivou/1.0"},
        ) as client:
            while page <= total_pages and len(found) < criteria.limit:
                response = client.get(
                    "/search",
                    params={
                        "activite_principale": ",".join(criteria.naf_codes),
                        "departement": ",".join(criteria.departments),
                        "tranche_effectif_salarie": ",".join(ranges),
                        "etat_administratif": "A",
                        "minimal": "true",
                        "include": "matching_etablissements,siege",
                        "limite_matching_etablissements": 100,
                        "page": page,
                        "per_page": 25,
                    },
                )
                if response.status_code != 200 or len(response.content) > MAX_RESPONSE_BYTES:
                    raise RuntimeError(f"SIRENE search failed: HTTP {response.status_code}")
                payload: Any = response.json()
                results = payload.get("results") if isinstance(payload, dict) else None
                if not isinstance(results, list):
                    raise TypeError("SIRENE response has no results list")
                total = payload.get("total_results")
                if isinstance(total, int) and total >= 0:
                    total_pages = max(1, math.ceil(total / 25))
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    establishment = _matching_establishment(item, criteria)
                    if establishment is None:
                        continue
                    name = str(
                        item.get("nom_raison_sociale") or item.get("nom_complet") or ""
                    ).strip()
                    siren = str(item.get("siren") or "").strip()
                    legal_naf = str(item.get("activite_principale") or "").strip()
                    if (
                        not name
                        or not any(c.isalpha() for c in name)
                        or len(siren) != 9
                        or siren in seen_sirens
                        or legal_naf not in criteria.naf_codes
                    ):
                        continue
                    employees = _tranche_employees(item.get("tranche_effectif_salarie"))
                    if (
                        employees is not None
                        and not criteria.min_employees <= employees <= criteria.max_employees
                    ):
                        continue
                    seen_sirens.add(siren)
                    found.append(
                        SireneCompany(
                            legal_name=name,
                            siren=siren,
                            siret=str(establishment.get("siret") or "") or None,
                            city=str(establishment.get("libelle_commune") or "") or None,
                            department=_department(establishment),
                            employees=employees,
                            naf_code=str(establishment.get("activite_principale") or "") or None,
                            observed_at=self._clock(),
                        )
                    )
                    if len(found) >= criteria.limit:
                        break
                if not results:
                    break
                page += 1
        department_rank = {
            department: index for index, department in enumerate(criteria.departments)
        }
        found.sort(
            key=lambda company: (
                -(company.employees or 0),
                department_rank.get(company.department or "", len(department_rank)),
                company.legal_name.casefold(),
                company.siren,
            )
        )
        return tuple(found[: criteria.limit])


__all__ = ["SireneCompany", "SireneCompanySearch", "SireneSearchCriteria"]
