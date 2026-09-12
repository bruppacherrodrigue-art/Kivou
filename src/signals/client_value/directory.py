"""Read-only client views over the supplier directory."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

import sqlalchemy as sa

from signals.accounts.schema import target_icp
from signals.companies.contracts import safe_https_url
from signals.domain.french_departments import DEPARTMENTS
from signals.feed.text import normalize_text
from signals.persistence.schema import supplier_directory
from signals.supplier_discovery.families import (
    SupplierFamily,
    load_supplier_family_catalog,
)

_TRADE_VERTICALS = {
    "earthworks_and_demolition": "earthworks_demolition",
    "building_construction": "general_building",
    "roads_and_civil_works": "roadworks_civil",
    "rail_infrastructure": "rail_infrastructure",
    "special_civil_engineering": "special_civil",
    "technical_installations": "technical_installation",
    "interior_finishing": "interior_finishing",
    "equipment_hire": "equipment_hire",
}

_GENERIC_MAILBOXES = frozenset(
    {
        "accueil",
        "bonjour",
        "commercial",
        "contact",
        "info",
        "secretariat",
        "service-client",
    }
)


def _normalized_name(value: str | None) -> str:
    return " ".join(normalize_text(value or "").split())


def _family_index() -> dict[str, SupplierFamily]:
    return {
        family.key: family
        for families in load_supplier_family_catalog().values()
        for family in families
    }


def _selected_families(customer_input: Mapping[str, Any]) -> tuple[SupplierFamily, ...]:
    catalog = load_supplier_family_catalog()
    trades = (
        *(customer_input.get("buyer_trades") or ()),
        *(customer_input.get("secondary_buyer_trades") or ()),
    )
    families = {
        family.key: family
        for trade in trades
        for family in catalog.get(_TRADE_VERTICALS.get(str(trade), ""), ())
    }
    return tuple(sorted(families.values(), key=lambda item: (item.priority, item.key)))


def _safe_website(value: str | None) -> str | None:
    try:
        return safe_https_url(value)
    except ValueError:
        return None


def _published_generic_email(row: Mapping[str, Any]) -> tuple[str, str] | None:
    """Return only a clearly generic mailbox observed on its own public site."""

    email = row["professional_email"]
    evidence_url = _safe_website(row["email_evidence_url"])
    if not isinstance(email, str) or not evidence_url or row["email_source"] != "site":
        return None
    local, separator, _domain = email.casefold().partition("@")
    if not separator or local not in _GENERIC_MAILBOXES:
        return None
    return email, evidence_url


def _director_tokens(value: str | None) -> set[str]:
    without_parentheses = re.sub(r"\([^)]*\)", " ", value or "")
    return set(_normalized_name(without_parentheses).split())


def _person_name(value: str) -> str:
    without_parentheses = re.sub(r"\([^)]*\)", " ", value)
    return " ".join(without_parentheses.split()).title()


def _director_role(value: str) -> str:
    formatted = value.strip().capitalize()
    for acronym in ("sas", "sarl", "sa", "scop", "selarl"):
        formatted = re.sub(
            rf"\b{acronym}\b",
            acronym.upper(),
            formatted,
            flags=re.IGNORECASE,
        )
    return formatted


def _clean_directors(
    value: object, *, preferred_name: str | None = None
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    formatted_preferred = _person_name(preferred_name) if preferred_name else None
    preferred_tokens = _director_tokens(preferred_name)
    for entry in value:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        raw_tokens = _director_tokens(name)
        client_name = (
            formatted_preferred
            if formatted_preferred and preferred_tokens and preferred_tokens <= raw_tokens
            else _person_name(name)
        )
        normalized = _normalized_name(client_name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        director = {"name": client_name}
        title = entry.get("title")
        if isinstance(title, str) and title.strip():
            director["title"] = _director_role(title)
        result.append(director)
    return result


def _director_title(row: Mapping[str, Any], display_name: str | None) -> str | None:
    if not display_name:
        return None
    wanted = _normalized_name(display_name)
    for director in _clean_directors(row["directors"], preferred_name=display_name):
        if _normalized_name(director["name"]) == wanted:
            return director.get("title")
    return None


def _company_view(
    row: Mapping[str, Any], *, matched_by_name: bool, include_public_contact: bool
) -> dict[str, Any]:
    families = _family_index()
    family_labels = [families[key].label_fr for key in row["family_keys"] or () if key in families]
    result: dict[str, Any] = {
        "siren": row["siren"],
        "name": row["legal_name"],
        "source": "registre",
        "removal_path": "/contact",
    }
    optional = {
        "naf_code": row["naf_code"],
        "naf_label": row["naf_label"],
        "department": row["department"],
        "department_label": DEPARTMENTS.get(row["department"]),
        "city": row["city"],
        "employees": row["employees"],
        "website_url": _safe_website(row["website_url"]),
    }
    result.update({key: value for key, value in optional.items() if value is not None})
    if result.get("website_url") and row["domain_source"]:
        result["website_source"] = row["domain_source"]
    if result.get("website_url") and row["domain_observed_at"]:
        result["website_observed_at"] = row["domain_observed_at"].isoformat()
    if family_labels:
        result["family_labels"] = family_labels
    if row["suppressed_at"] is None:
        directors = _clean_directors(
            row["directors"], preferred_name=row["director_display_name"]
        )
        if directors:
            result["directors"] = directors
            if row["directors_observed_at"]:
                result["directors_observed_at"] = row[
                    "directors_observed_at"
                ].isoformat()
        if include_public_contact:
            display_name = row["director_display_name"]
            if display_name:
                result["director_display_name"] = display_name
                title = _director_title(row, display_name)
                if title:
                    result["director_display_title"] = title
            if row["phone"]:
                result["phone"] = row["phone"]
                if row["phone_source"]:
                    result["phone_source"] = row["phone_source"]
                if row["phone_observed_at"]:
                    result["phone_observed_at"] = row["phone_observed_at"].isoformat()
            published_email = _published_generic_email(row)
            if published_email is not None:
                result["published_email"] = published_email[0]
                result["published_email_source_url"] = published_email[1]
                if row["email_observed_at"]:
                    result["published_email_observed_at"] = row[
                        "email_observed_at"
                    ].isoformat()
            if row["enrichment_observed_at"]:
                result["contact_observed_at"] = row["enrichment_observed_at"].isoformat()
    if include_public_contact and row["legal_name_observed_at"]:
        result["register_observed_at"] = row["legal_name_observed_at"].isoformat()
    if matched_by_name:
        result["resolution_note"] = "rapprochement par nom"
    return result


def directory_company(
    connection: sa.Connection,
    *,
    siren: str | None,
    legal_name: str | None,
    department: str | None,
    include_public_contact: bool = False,
) -> dict[str, Any] | None:
    """Return public directory facts, preferring the stable SIREN."""

    if siren:
        exact = (
            connection.execute(
                sa.select(supplier_directory).where(supplier_directory.c.siren == siren)
            )
            .mappings()
            .first()
        )
        if exact is not None:
            return _company_view(
                exact,
                matched_by_name=False,
                include_public_contact=include_public_contact,
            )

    wanted_name = _normalized_name(legal_name)
    if not wanted_name or not department:
        return None
    candidates = connection.execute(
        sa.select(supplier_directory).where(supplier_directory.c.department == department)
    ).mappings()
    match = next(
        (row for row in candidates if _normalized_name(row["legal_name"]) == wanted_name),
        None,
    )
    return (
        None
        if match is None
        else _company_view(
            match,
            matched_by_name=True,
            include_public_contact=include_public_contact,
        )
    )


def _matching_family(
    keys: Iterable[str], selected: tuple[SupplierFamily, ...]
) -> SupplierFamily | None:
    available = set(keys)
    return next((family for family in selected if family.key in available), None)


def local_circuit(
    connection: sa.Connection,
    *,
    target_icp_id: str,
    department: str | None,
    city: str | None,
) -> tuple[dict[str, Any], ...]:
    """Return up to eight nearby directory companies matching the target profile."""

    if not department:
        return ()
    customer_input = connection.execute(
        sa.select(target_icp.c.customer_input).where(target_icp.c.target_icp_id == target_icp_id)
    ).scalar_one_or_none()
    if not isinstance(customer_input, dict):
        return ()
    selected = _selected_families(customer_input)
    if not selected:
        return ()

    matches: list[tuple[Mapping[str, Any], SupplierFamily]] = []
    rows = connection.execute(
        sa.select(supplier_directory).where(supplier_directory.c.department == department)
    ).mappings()
    for row in rows:
        family = _matching_family(row["family_keys"] or (), selected)
        if family is not None:
            matches.append((row, family))

    wanted_city = _normalized_name(city)
    matches.sort(
        key=lambda pair: (
            0 if wanted_city and _normalized_name(pair[0]["city"]) == wanted_city else 1,
            -(pair[0]["employees"] if pair[0]["employees"] is not None else -1),
            _normalized_name(pair[0]["legal_name"]),
            pair[0]["siren"],
        )
    )
    result: list[dict[str, Any]] = []
    for row, family in matches[:8]:
        item: dict[str, Any] = {
            "siren": row["siren"],
            "name": row["legal_name"],
            "trade": family.label_fr,
            "href": f"/app/companies/directory/{row['siren']}",
            "source": "registre",
        }
        item.update(
            {
                key: value
                for key, value in {
                    "city": row["city"],
                    "employees": row["employees"],
                }.items()
                if value is not None
            }
        )
        result.append(item)
    return tuple(result)


__all__ = ["directory_company", "local_circuit"]
