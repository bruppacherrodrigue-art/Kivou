"""Deterministic customer location projected from published source facts."""

from __future__ import annotations

import dataclasses
import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

from signals.domain.french_departments import location_subdivision

_TECHNICAL_WORDS = frozenset(
    {
        "boamp",
        "comm",
        "commune",
        "decp",
        "dept",
        "departement",
        "france",
        "pays",
        "reg",
        "region",
        "territoire metropolitain",
        "france metropolitaine",
    }
)
_CODE_ONLY = re.compile(
    r"^(?:(?:[A-Z]{2,4}[- ]?)?\d{2,8}|[A-Z]{2}\d[A-Z0-9]{2,5})$",
    re.IGNORECASE,
)


@dataclasses.dataclass(frozen=True)
class ResolvedClientLocation:
    location: dict[str, str | None]
    basis: str


def _mapping(value: Any) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return None


def _fold(value: str) -> str:
    return " ".join(
        "".join(
            character
            for character in unicodedata.normalize("NFD", value)
            if unicodedata.category(character) != "Mn"
        ).casefold().split()
    )


def human_city(value: object) -> str | None:
    """Return a readable city, rejecting source markers and bare codes."""

    if not isinstance(value, str):
        return None
    clean = " ".join(value.split())
    folded = _fold(clean)
    if not clean or folded in _TECHNICAL_WORDS:
        return None
    if any(word in folded for word in ("boamp", "decp")):
        return None
    if clean.isdigit() or _CODE_ONLY.fullmatch(clean):
        return None
    return clean


def _project(place: Mapping[str, Any], *, locality: str | None) -> dict[str, str | None]:
    subdivision = location_subdivision(dict(place))
    return {
        "country": place.get("country"),
        "locality": locality,
        "postal_code": place.get("postal_code") if locality else None,
        "subdivision_code": subdivision,
    }


def _buyer_place(buyer: Mapping[str, Any]) -> Mapping[str, Any] | None:
    structured = _mapping(buyer.get("location"))
    if structured is not None:
        return structured
    address = buyer.get("address")
    if not isinstance(address, str):
        return None
    parts = [part.strip() for part in address.split(",") if part.strip()]
    if not parts:
        return None
    postal_match = re.search(r"\b(?P<postal>\d{5})\b", address)
    candidate = re.sub(r"^\d{5}\s+", "", parts[-1]).strip()
    city = human_city(candidate)
    if city is None:
        return None
    return {
        "country": buyer.get("country"),
        "locality": city,
        "postal_code": postal_match.group("postal") if postal_match else None,
        "subdivision_code": None,
    }


def resolve_client_location(
    *, execution: Any, buyers: Iterable[Any]
) -> ResolvedClientLocation | None:
    """Resolve execution city, buyer city, department, then no display value."""

    execution_place = _mapping(execution)
    if execution_place is not None:
        city = human_city(execution_place.get("locality"))
        if city:
            return ResolvedClientLocation(
                location=_project(execution_place, locality=city),
                basis="execution_city",
            )
    for buyer in buyers:
        buyer_record = _mapping(buyer)
        buyer_place = _buyer_place(buyer_record) if buyer_record is not None else None
        if buyer_place is None:
            continue
        city = human_city(buyer_place.get("locality"))
        if city:
            return ResolvedClientLocation(
                location=_project(buyer_place, locality=city),
                basis="buyer_city",
            )
    if execution_place is not None:
        subdivision = location_subdivision(dict(execution_place))
        if subdivision:
            return ResolvedClientLocation(
                location={
                    "country": execution_place.get("country"),
                    "locality": None,
                    "postal_code": None,
                    "subdivision_code": subdivision,
                },
                basis="department",
            )
    return None


__all__ = ["ResolvedClientLocation", "human_city", "resolve_client_location"]
