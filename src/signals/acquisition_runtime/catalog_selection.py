"""Read-only selection of exact mono-family notices for assisted preparation."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition_runtime.assisted import AssistedSignal, resolve_assisted_signal
from signals.acquisition_runtime.selection import (
    opportunity_family_keys,
    region_subdivision_codes,
)
from signals.companies.official_cache import official_holders_for_opportunities
from signals.persistence.schema import (
    contract_award,
    for_you_sentence,
    materialized_signal,
    opportunity_representation,
    source_event,
)
from signals.supplier_discovery.families import load_supplier_family_catalog


@dataclass(frozen=True)
class CatalogNotice:
    signal: AssistedSignal


@dataclass(frozen=True)
class CatalogFamilyInventory:
    family_key: str
    notices: tuple[CatalogNotice, ...]
    mono_notice_count: int
    missing_official_holder_count: int
    qualification_error_count: int
    zero_reason: str | None


def _candidate_rows(
    engine: Engine,
    *,
    country: str,
    region: str,
    observed_at: dt.datetime,
) -> tuple[sa.Row, ...]:
    horizon = observed_at.astimezone(dt.UTC).date()
    decision_date = sa.func.coalesce(
        contract_award.c.award_date,
        contract_award.c.contract_notification_date,
    )
    latest = sa.func.max(decision_date).label("latest")
    vertical = sa.func.max(materialized_signal.c.inferred_trade_domain).label("vertical")
    statement = (
        sa.select(opportunity_representation.c.opportunity_key, latest, vertical)
        .select_from(
            opportunity_representation.join(
                materialized_signal,
                materialized_signal.c.opportunity_key
                == opportunity_representation.c.opportunity_key,
            )
            .join(
                contract_award,
                opportunity_representation.c.award_key == contract_award.c.award_key,
            )
            .join(source_event, contract_award.c.event_key == source_event.c.event_key)
            .outerjoin(
                for_you_sentence,
                sa.and_(
                    for_you_sentence.c.signal_key == materialized_signal.c.signal_key,
                    for_you_sentence.c.signal_fingerprint
                    == materialized_signal.c.content_fingerprint,
                ),
            )
        )
        .where(
            source_event.c.source_country == country,
            decision_date >= horizon - dt.timedelta(days=30),
            decision_date <= horizon,
            contract_award.c.amount >= 50_000,
            contract_award.c.winner_status == "identified",
            sa.func.nullif(
                sa.func.trim(sa.func.coalesce(contract_award.c.title, "")), ""
            ).isnot(None),
            contract_award.c.place_of_performance["subdivision_code"]
            .as_string()
            .in_(region_subdivision_codes(region)),
            sa.or_(
                for_you_sentence.c.model_fit.is_(None),
                for_you_sentence.c.model_fit != "none",
            ),
        )
        .group_by(opportunity_representation.c.opportunity_key)
        .order_by(latest.desc(), opportunity_representation.c.opportunity_key)
    )
    with engine.connect() as connection:
        return tuple(connection.execute(statement))


def select_assisted_catalog_signals(
    engine: Engine,
    *,
    country: str,
    region: str,
    observed_at: dt.datetime,
) -> dict[str, CatalogFamilyInventory]:
    """Return every catalog family, populated only with exact official notices."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("catalog selection timestamp must be timezone-aware")
    catalog = load_supplier_family_catalog()
    family_keys = tuple(family.key for families in catalog.values() for family in families)
    rows = _candidate_rows(
        engine,
        country=country,
        region=region,
        observed_at=observed_at,
    )
    opportunity_keys = tuple(str(row.opportunity_key) for row in rows)
    with engine.connect() as connection:
        official_holders = official_holders_for_opportunities(connection, opportunity_keys)

    notices: dict[str, list[CatalogNotice]] = {key: [] for key in family_keys}
    mono_counts = {key: 0 for key in family_keys}
    missing_holders = {key: 0 for key in family_keys}
    errors = {key: 0 for key in family_keys}
    for row in rows:
        opportunity_key = str(row.opportunity_key)
        try:
            matched = opportunity_family_keys(
                engine,
                opportunity_key=opportunity_key,
                vertical=str(row.vertical),
            )
        except (LookupError, TypeError, ValueError):
            continue
        if len(matched) != 1:
            continue
        family_key = next(iter(matched))
        if family_key not in notices:
            continue
        mono_counts[family_key] += 1
        if opportunity_key not in official_holders:
            missing_holders[family_key] += 1
            continue
        try:
            signal = resolve_assisted_signal(
                engine,
                opportunity_key,
                required_family_key=family_key,
            )
        except (LookupError, TypeError, ValueError):
            errors[family_key] += 1
            continue
        if signal.holder_siren is None:
            missing_holders[family_key] += 1
            continue
        notices[family_key].append(CatalogNotice(signal=signal))

    result: dict[str, CatalogFamilyInventory] = {}
    for family_key in family_keys:
        values = tuple(
            sorted(
                notices[family_key],
                key=lambda notice: (
                    -notice.signal.decision_date.toordinal(),
                    notice.signal.opportunity_key,
                ),
            )
        )
        zero_reason = None
        if not values:
            zero_reason = (
                "no_mono_avis"
                if mono_counts[family_key] == 0
                else "no_official_holder"
                if missing_holders[family_key] == mono_counts[family_key]
                else "qualification_error"
            )
        result[family_key] = CatalogFamilyInventory(
            family_key=family_key,
            notices=values,
            mono_notice_count=mono_counts[family_key],
            missing_official_holder_count=missing_holders[family_key],
            qualification_error_count=errors[family_key],
            zero_reason=zero_reason,
        )
    return result


__all__ = [
    "CatalogFamilyInventory",
    "CatalogNotice",
    "select_assisted_catalog_signals",
]
