"""Synthèse commerciale des attributions publiques d'un titulaire."""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Any, Literal

import sqlalchemy as sa

from signals.companies.contracts import safe_https_url
from signals.companies.schema import saas_company
from signals.domain.french_departments import NUTS3_DEPARTMENTS, location_subdivision
from signals.feed.text import normalize_text
from signals.persistence.schema import contract_award, materialized_signal, source_event

Resolution = Literal["company_key", "normalized_name_department"]


@dataclass(frozen=True)
class AwardFact:
    award_key: str
    known_date: dt.date | None
    amount: Decimal | None
    currency: str | None
    buyer_names: tuple[str, ...]
    is_consortium: bool


def _decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _one_decimal(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), "f")


def _year_before(value: dt.date) -> dt.date:
    try:
        return value.replace(year=value.year - 1)
    except ValueError:  # 29 février
        return value.replace(year=value.year - 1, day=28)


def _money_rows(facts: tuple[AwardFact, ...], *, operation: str) -> list[dict[str, str]]:
    grouped: dict[str, list[Decimal]] = {}
    for fact in facts:
        if fact.amount is not None and fact.currency:
            grouped.setdefault(fact.currency, []).append(fact.amount)
    rows = []
    for currency, values in sorted(grouped.items()):
        value = sum(values, Decimal(0)) if operation == "sum" else median(values)
        rows.append({"currency": currency, "value": _decimal(value)})
    return rows


def _recurring_buyers(facts: tuple[AwardFact, ...]) -> list[str]:
    counts = Counter(name for fact in facts for name in set(fact.buyer_names) if name.strip())
    return [name for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])) if count > 1][:2]


def summarize_awards(
    facts: tuple[AwardFact, ...], *, as_of: dt.date, resolution: Resolution
) -> dict[str, Any] | None:
    """Agrège des contrats dédupliqués sans compléter une donnée manquante."""
    unique = tuple({fact.award_key: fact for fact in facts}.values())
    if not unique:
        return None
    dated = tuple(fact for fact in unique if fact.known_date is not None)
    recent = tuple(
        fact for fact in dated if _year_before(as_of) <= fact.known_date <= as_of  # type: ignore[operator]
    )
    last_year: dict[str, Any] = {"awards_count": len(recent)}
    recent_money = _money_rows(recent, operation="sum")
    recent_buyers = _recurring_buyers(recent)
    if recent_money:
        last_year["total_amounts"] = recent_money
    if recent_buyers:
        last_year["recurring_buyers"] = recent_buyers

    summary: dict[str, Any] = {}
    known_dates = sorted(fact.known_date for fact in dated if fact.known_date is not None)
    if known_dates:
        first = known_dates[0]
        summary["first_award_at"] = first.isoformat()
        months = (as_of.year - first.year) * 12 + as_of.month - first.month
        quarters = max(1, months // 3 + 1)
        summary["awards_per_quarter"] = _one_decimal(
            Decimal(len(unique)) / Decimal(quarters)
        )
    medians = _money_rows(unique, operation="median")
    if medians:
        summary["median_amounts"] = medians
    summary["consortium_share"] = _one_decimal(
        Decimal(sum(fact.is_consortium for fact in unique)) / Decimal(len(unique))
    )
    buyers = _recurring_buyers(unique)
    if buyers:
        summary["recurring_buyers"] = buyers

    result: dict[str, Any] = {
        "resolution": resolution,
        "last_12_months": last_year,
        "summary": summary,
        "source": "public_awards",
    }
    if resolution == "normalized_name_department":
        result["resolution_note"] = "rapprochement par nom"
    return result


def department_for_place(place: dict[str, Any] | None) -> str | None:
    subdivision = location_subdivision(place)
    if subdivision is None:
        return None
    if subdivision.startswith("FR-"):
        return subdivision.removeprefix("FR-")
    return NUTS3_DEPARTMENTS.get(subdivision)


def _normalized(value: str | None) -> str:
    return " ".join(normalize_text(value or "").split())


def _safe_source_url(value: str | None) -> str | None:
    try:
        return safe_https_url(value)
    except ValueError:
        return None


def _winner_names(parties: list[dict[str, Any]] | None) -> tuple[str, ...]:
    return tuple(
        name
        for party in parties or ()
        for member in (party or {}).get("members") or ()
        if (name := ((member or {}).get("organization") or {}).get("legal_name"))
    )


def _is_consortium(parties: list[dict[str, Any]] | None) -> bool:
    for party in parties or ():
        members = (party or {}).get("members") or ()
        if len(members) > 1 or any(
            (member or {}).get("role") in {"consortium_lead", "consortium_member"}
            for member in members
        ):
            return True
    return False


def _buyer_names(buyers: list[dict[str, Any]] | None) -> tuple[str, ...]:
    return tuple(
        name.strip()
        for buyer in buyers or ()
        if isinstance((buyer or {}).get("legal_name"), str)
        and (name := (buyer or {})["legal_name"]).strip()
    )


def _award_rows(
    connection: sa.Connection,
    *,
    identity_fingerprints: tuple[str, ...] | None,
):
    columns = (
        contract_award.c.award_key,
        contract_award.c.title,
        contract_award.c.award_date,
        contract_award.c.contract_notification_date,
        contract_award.c.amount,
        contract_award.c.currency,
        contract_award.c.awardee_parties,
        contract_award.c.place_of_performance,
        source_event.c.published_on,
        source_event.c.procedure_buyers,
        source_event.c.source_url,
    )
    if identity_fingerprints is None:
        statement = sa.select(*columns).select_from(
            contract_award.join(source_event, contract_award.c.event_key == source_event.c.event_key)
        )
    else:
        award_keys = (
            sa.select(materialized_signal.c.materialization_award_key)
            .where(
                materialized_signal.c.company_identity_fingerprint.in_(
                    identity_fingerprints
                )
            )
            .distinct()
            .subquery("directory_award_keys")
        )
        statement = (
            sa.select(*columns)
            .select_from(
                award_keys.join(
                    contract_award,
                    award_keys.c.materialization_award_key == contract_award.c.award_key,
                ).join(source_event, contract_award.c.event_key == source_event.c.event_key)
            )
        )
    return connection.execute(statement.order_by(contract_award.c.award_key)).mappings()


def _fallback_award_rows(
    connection: sa.Connection,
    *,
    winner_name: str,
    department: str,
) -> tuple[Mapping[str, Any], ...]:
    wanted_name = _normalized(winner_name)
    if not wanted_name or not department:
        return ()
    return tuple(
        row
        for row in _award_rows(connection, identity_fingerprints=None)
        if department_for_place(row["place_of_performance"]) == department
        and wanted_name
        in {_normalized(name) for name in _winner_names(row["awardee_parties"])}
    )


def _award_facts(rows: Iterable[Mapping[str, Any]]) -> tuple[AwardFact, ...]:
    return tuple(
        AwardFact(
            award_key=row["award_key"],
            known_date=(
                row["award_date"]
                or row["contract_notification_date"]
                or row["published_on"]
            ),
            amount=(None if row["amount"] is None else Decimal(str(row["amount"]))),
            currency=row["currency"],
            buyer_names=_buyer_names(row["procedure_buyers"]),
            is_consortium=_is_consortium(row["awardee_parties"]),
        )
        for row in rows
    )


def _markets_from_rows(
    rows: Iterable[Mapping[str, Any]], *, limit: int
) -> tuple[dict[str, Any], ...]:
    matches: list[tuple[dt.date | None, str, dict[str, Any]]] = []
    for row in rows:
        known_date = row["award_date"] or row["contract_notification_date"] or row["published_on"]
        market: dict[str, Any] = {
            "market_id": row["award_key"],
            "source": "public_awards",
        }
        optional = {
            "title": row["title"],
            "date": known_date.isoformat() if known_date is not None else None,
            "source_url": _safe_source_url(row["source_url"]),
        }
        market.update({key: value for key, value in optional.items() if value})
        if row["amount"] is not None and row["currency"]:
            market["amount"] = {
                "value": _decimal(Decimal(str(row["amount"]))),
                "currency": row["currency"],
            }
        buyers = _buyer_names(row["procedure_buyers"])
        if buyers:
            market["buyers"] = list(buyers)
        matches.append((known_date, row["award_key"], market))
    matches.sort(key=lambda item: (item[0] or dt.date.min, item[1]), reverse=True)
    return tuple(market for _date, _key, market in matches[:limit])


def history_for_company(
    connection: sa.Connection,
    *,
    company_key: str | None,
    winner_name: str | None,
    department: str | None,
    as_of: dt.date,
) -> dict[str, Any] | None:
    """Lit l'historique par identité projetée, sinon par nom et département."""
    fingerprint = None
    resolution: Resolution = "normalized_name_department"
    if company_key is not None:
        fingerprint = connection.scalar(
            sa.select(saas_company.c.identity_fingerprint).where(
                saas_company.c.company_key == company_key
            )
        )
        if fingerprint is not None:
            resolution = "company_key"
    if fingerprint is None and (not _normalized(winner_name) or not department):
        return None

    rows = (
        tuple(_award_rows(connection, identity_fingerprints=(fingerprint,)))
        if fingerprint is not None
        else _fallback_award_rows(
            connection,
            winner_name=winner_name or "",
            department=department or "",
        )
    )
    return summarize_awards(_award_facts(rows), as_of=as_of, resolution=resolution)


def markets_for_company(
    connection: sa.Connection,
    *,
    winner_name: str,
    department: str,
    limit: int = 100,
) -> tuple[dict[str, Any], ...]:
    """List the public awards matched to a name and department."""

    rows = _fallback_award_rows(
        connection,
        winner_name=winner_name,
        department=department,
    )
    return _markets_from_rows(rows, limit=limit)


def directory_history_and_markets(
    connection: sa.Connection,
    *,
    winner_name: str,
    department: str,
    as_of: dt.date,
    limit: int = 100,
    siren: str | None = None,
) -> tuple[dict[str, Any] | None, tuple[dict[str, Any], ...]]:
    """Read a directory company's summary and list from one award scan."""

    fingerprints = (
        set(
            connection.scalars(
                sa.select(materialized_signal.c.company_identity_fingerprint)
                .select_from(
                    materialized_signal.join(
                        saas_company,
                        saas_company.c.identity_fingerprint
                        == materialized_signal.c.company_identity_fingerprint,
                    )
                )
                .where(
                    sa.func.lower(materialized_signal.c.winner_identifier_scheme)
                    == "siret",
                    materialized_signal.c.winner_identifier_value.like(f"{siren}_____"),
                )
                .distinct()
            )
        )
        if siren
        else set()
    )
    if fingerprints:
        rows = tuple(
            _award_rows(
                connection,
                identity_fingerprints=tuple(sorted(fingerprints)),
            )
        )
        resolution: Resolution = "company_key"
    else:
        rows = _fallback_award_rows(
            connection,
            winner_name=winner_name,
            department=department,
        )
        resolution = "normalized_name_department"
    return (
        summarize_awards(
            _award_facts(rows),
            as_of=as_of,
            resolution=resolution,
        ),
        _markets_from_rows(rows, limit=limit),
    )


__all__ = [
    "AwardFact",
    "department_for_place",
    "directory_history_and_markets",
    "history_for_company",
    "markets_for_company",
    "summarize_awards",
]
