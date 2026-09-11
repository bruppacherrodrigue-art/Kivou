"""Versioned, reviewable mapping from signal facts to supplier families."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SupplierFamily:
    key: str
    label_fr: str
    apollo_tags: tuple[str, ...]
    priority: int
    cpv_prefixes: tuple[str, ...]
    object_terms: tuple[str, ...]
    naf_codes: tuple[str, ...]
    activity_terms: tuple[str, ...]


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[3] / "ops/config/supplier-families.yaml"


def load_supplier_family_catalog(path: Path | None = None) -> dict[str, tuple[SupplierFamily, ...]]:
    source = _catalog_path() if path is None else path
    try:
        raw: Any = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError("supplier family catalog unavailable") from exc
    if not isinstance(raw, dict) or raw.get("version") != "supplier-families-v1":
        raise ValueError("supplier family catalog version is invalid")
    verticals = raw.get("verticals")
    if not isinstance(verticals, dict):
        raise TypeError("supplier family catalog verticals are invalid")
    result: dict[str, tuple[SupplierFamily, ...]] = {}
    for vertical, entries in verticals.items():
        if (
            not isinstance(vertical, str)
            or not isinstance(entries, list)
            or not 3 <= len(entries) <= 5
        ):
            raise ValueError(f"supplier family catalog vertical is invalid: {vertical}")
        families: list[SupplierFamily] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise TypeError(f"supplier family entry is invalid: {vertical}")
            try:
                family = SupplierFamily(
                    key=str(entry["key"]),
                    label_fr=str(entry["label_fr"]),
                    apollo_tags=tuple(str(x) for x in entry["apollo_tags"]),
                    priority=int(entry["priority"]),
                    cpv_prefixes=tuple(str(x) for x in entry["cpv_prefixes"]),
                    object_terms=tuple(str(x) for x in entry["object_terms"]),
                    naf_codes=tuple(str(x) for x in entry["naf_codes"]),
                    activity_terms=tuple(str(x) for x in entry["activity_terms"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"supplier family entry is invalid: {vertical}") from exc
            if (
                not family.key
                or not family.label_fr
                or not family.apollo_tags
                or not family.naf_codes
                or not family.activity_terms
                or family.priority < 1
            ):
                raise ValueError(f"supplier family fields are invalid: {vertical}/{family.key}")
            families.append(family)
        if len({x.key for x in families}) != len(families):
            raise ValueError(f"supplier family keys are not unique: {vertical}")
        result[vertical] = tuple(sorted(families, key=lambda x: (x.priority, x.key)))
    expected = {
        "general_building",
        "interior_finishing",
        "technical_installation",
        "roadworks_civil",
        "earthworks_demolition",
        "special_civil",
    }
    if set(result) != expected:
        raise ValueError("supplier family catalog must cover the six PR7 verticals")
    all_keys = [family.key for families in result.values() for family in families]
    if len(all_keys) != len(set(all_keys)):
        raise ValueError("supplier family keys must be globally unique")
    return result


def _normalized_words(value: str) -> str:
    folded = "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", folded))


def supplier_matches_family(
    family: SupplierFamily,
    *,
    naf_code: str | None,
    activity_texts: tuple[str, ...],
) -> bool:
    """Require both the family NAF and explicit activity wording."""

    normalized_naf = str(naf_code or "").strip().upper()
    if normalized_naf not in {code.upper() for code in family.naf_codes}:
        return False
    evidence = f" {_normalized_words(' '.join(activity_texts))} "
    return any(
        f" {_normalized_words(term)} " in evidence
        for term in family.activity_terms
        if _normalized_words(term)
    )


def matching_supplier_family_keys(
    *, naf_code: str | None, activity_texts: tuple[str, ...]
) -> tuple[str, ...]:
    catalog = load_supplier_family_catalog()
    return tuple(
        family.key
        for family in sorted(
            (family for families in catalog.values() for family in families),
            key=lambda item: (item.priority, item.key),
        )
        if supplier_matches_family(
            family,
            naf_code=naf_code,
            activity_texts=activity_texts,
        )
    )


def families_for_signal(
    vertical: str, *, cpv_codes: tuple[str, ...], object_text: str
) -> tuple[SupplierFamily, ...]:
    """Return only catalog families supported by public signal facts."""

    catalog = load_supplier_family_catalog()
    if vertical not in catalog:
        raise ValueError(f"unknown supplier family vertical: {vertical}")
    families = tuple(family for values in catalog.values() for family in values)
    normalized = f" {_normalized_words(object_text)} "
    matched = tuple(
        family
        for family in families
        if any(
            code.replace("-", "").startswith(prefix.replace("-", ""))
            for code in cpv_codes
            for prefix in family.cpv_prefixes
        )
        or any(
            f" {_normalized_words(term)} " in normalized
            for term in family.object_terms
            if _normalized_words(term)
        )
    )
    return tuple(sorted(matched[:5], key=lambda item: (item.priority, item.key)))


_AURA_NEIGHBOURS: dict[str, tuple[str, ...]] = {
    "01": ("38", "39", "69", "71", "73", "74"),
    "03": ("18", "23", "42", "58", "63", "71"),
    "07": ("26", "30", "43", "48", "84"),
    "15": ("12", "19", "43", "46", "48", "63"),
    "26": ("04", "05", "07", "38", "84"),
    "38": ("01", "05", "26", "69", "73"),
    "42": ("03", "43", "63", "69", "71"),
    "43": ("07", "15", "42", "48", "63"),
    "63": ("03", "15", "19", "23", "42", "43"),
    "69": ("01", "38", "42", "71"),
    "73": ("01", "05", "38", "74"),
    "74": ("01", "73"),
}

_NUTS_DEPARTMENTS: dict[str, str] = {
    "FRK11": "01",
    "FRK12": "03",
    "FRK13": "07",
    "FRK14": "15",
    "FRK21": "26",
    "FRK22": "38",
    "FRK23": "42",
    "FRK24": "43",
    "FRK25": "63",
    "FRK26": "69",
    "FRK27": "73",
    "FRK28": "74",
    "FRB01": "18",
    "FRB02": "28",
    "FRB03": "36",
    "FRB04": "37",
    "FRB05": "41",
    "FRB06": "45",
}


def department_from_subdivision(subdivision: str | None) -> str | None:
    """Resolve supported ISO/NUTS subdivisions to one French department."""

    if subdivision is None:
        return None
    if subdivision.startswith("FR-") and len(subdivision) == 5:
        return subdivision.removeprefix("FR-")
    return _NUTS_DEPARTMENTS.get(subdivision)


def department_and_neighbours(department: str) -> tuple[str, ...]:
    """Return the signal department followed by its versioned adjacent set."""

    return (department, *_AURA_NEIGHBOURS.get(department, ()))


__all__ = [
    "SupplierFamily",
    "department_and_neighbours",
    "department_from_subdivision",
    "families_for_signal",
    "load_supplier_family_catalog",
    "matching_supplier_family_keys",
    "supplier_matches_family",
]
