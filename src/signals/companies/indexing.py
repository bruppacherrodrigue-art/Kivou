"""Indexed projection from materialized signals to exact public companies."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa

from signals.companies.identity import ResolvedOfficialCompany, official_company_identity
from signals.feed import query as feed_query
from signals.persistence.repository import SIGNAL_SELECT, signal_from_row
from signals.persistence.schema import (
    contract_award,
    materialized_signal,
    opportunity_representation,
    source_event,
)

INDEX_BATCH_SIZE = 250


@dataclass(frozen=True)
class IndexedOfficialCompany:
    resolved: ResolvedOfficialCompany
    source_award_key: str


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def _award_sources(
    connection: sa.Connection, award_keys: set[str]
) -> dict[str, tuple[list[dict], dt.datetime]]:
    if not award_keys:
        return {}
    rows = connection.execute(
        sa.select(
            contract_award.c.award_key,
            contract_award.c.awardee_parties,
            source_event.c.discovered_at,
            contract_award.c.created_at.label("award_created_at"),
        )
        .select_from(
            contract_award.join(
                source_event, contract_award.c.event_key == source_event.c.event_key
            )
        )
        .where(contract_award.c.award_key.in_(sorted(award_keys)))
    ).all()
    return {
        row.award_key: (
            row.awardee_parties,
            _aware(row.discovered_at or row.award_created_at),
        )
        for row in rows
    }


def index_signal_company_identities(
    connection: sa.Connection, *, signal_keys: tuple[str, ...]
) -> dict[str, IndexedOfficialCompany | None]:
    """Project exact identities for a bounded set of materialized signals."""
    if not signal_keys:
        return {}
    if len(signal_keys) > INDEX_BATCH_SIZE:
        raise ValueError(f"at most {INDEX_BATCH_SIZE} signal keys can be indexed at once")

    rows = connection.execute(
        SIGNAL_SELECT.where(materialized_signal.c.signal_key.in_(signal_keys))
        .order_by(None)
        .order_by(materialized_signal.c.signal_key)
    ).all()
    signals = [signal_from_row(row) for row in rows]
    stored_fingerprints = {row.signal_key: row.company_identity_fingerprint for row in rows}
    displays = feed_query.resolve_display_identity(connection, signals)
    sources = _award_sources(
        connection,
        {display.from_award_key for display in displays.values()},
    )
    indexed: dict[str, IndexedOfficialCompany | None] = {}
    updates: list[dict[str, str | None]] = []
    for signal in signals:
        display = displays.get(signal.signal_key)
        source = None if display is None else sources.get(display.from_award_key)
        resolved = None
        if display is not None and source is not None:
            parties, observed_at = source
            try:
                resolved = official_company_identity(
                    awardee_parties=parties,
                    display=display,
                    opportunity_key=signal.opportunity_key,
                    observed_at=observed_at,
                )
            except (TypeError, ValueError):
                resolved = None
        indexed[signal.signal_key] = (
            None
            if resolved is None or display is None
            else IndexedOfficialCompany(
                resolved=resolved,
                source_award_key=display.from_award_key,
            )
        )
        fingerprint = None if resolved is None else resolved.identity_fingerprint
        if stored_fingerprints.get(signal.signal_key) != fingerprint:
            updates.append(
                {
                    "indexed_signal_key": signal.signal_key,
                    "indexed_fingerprint": fingerprint,
                }
            )

    if updates:
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == sa.bindparam("indexed_signal_key"))
            .values(company_identity_fingerprint=sa.bindparam("indexed_fingerprint")),
            updates,
        )
    return indexed


def index_signal_company_identity(
    connection: sa.Connection, *, signal_key: str
) -> IndexedOfficialCompany | None:
    return index_signal_company_identities(connection, signal_keys=(signal_key,)).get(signal_key)


def _index_historical_company_batch(connection: sa.Connection, keys: tuple[str, ...]) -> None:
    """Revision 0022 projection: no later location columns or official cache.

    The migration imports this function on populated historical databases.
    The runtime reader above deliberately remains separate: its wider current
    schema and official-register fallback do not exist at revision 0022.
    """
    rows = connection.execute(
        sa.select(
            materialized_signal.c.signal_key,
            materialized_signal.c.opportunity_key,
            materialized_signal.c.materialization_award_key,
            materialized_signal.c.winner_name,
            materialized_signal.c.winner_country,
            materialized_signal.c.winner_identifier_scheme,
            materialized_signal.c.winner_identifier_value,
            materialized_signal.c.company_identity_fingerprint,
        )
        .where(materialized_signal.c.signal_key.in_(keys))
        .order_by(materialized_signal.c.signal_key)
    ).all()
    displays = {}
    pending = {}
    for row in rows:
        if feed_query.is_customer_display_name(row.winner_name, row.winner_identifier_value):
            displays[row.signal_key] = feed_query.DisplayIdentity(
                name=row.winner_name.strip(),
                country=row.winner_country,
                identifier_scheme=row.winner_identifier_scheme,
                identifier_value=row.winner_identifier_value,
                from_award_key=row.materialization_award_key,
            )
        else:
            pending.setdefault(row.opportunity_key, []).append(row.signal_key)
    if pending:
        siblings = connection.execute(
            sa.select(
                opportunity_representation.c.opportunity_key,
                contract_award.c.award_key,
                contract_award.c.awardee_parties,
            )
            .select_from(
                opportunity_representation.join(
                    contract_award,
                    opportunity_representation.c.award_key == contract_award.c.award_key,
                )
            )
            .where(opportunity_representation.c.opportunity_key.in_(pending))
            .order_by(opportunity_representation.c.opportunity_key, contract_award.c.award_key)
        )
        for sibling in siblings:
            named = feed_query._named_identity(sibling.awardee_parties)
            if named is None:
                continue
            name, country, identifier = named
            display = feed_query.DisplayIdentity(
                name=name,
                country=country,
                identifier_scheme=(identifier or {}).get("scheme"),
                identifier_value=(identifier or {}).get("value"),
                from_award_key=sibling.award_key,
            )
            for key in pending[sibling.opportunity_key]:
                displays.setdefault(key, display)
    sources = _award_sources(connection, {display.from_award_key for display in displays.values()})
    updates = []
    for row in rows:
        display = displays.get(row.signal_key)
        source = None if display is None else sources.get(display.from_award_key)
        resolved = None
        if display is not None and source is not None:
            parties, observed_at = source
            try:
                resolved = official_company_identity(
                    awardee_parties=parties,
                    display=display,
                    opportunity_key=row.opportunity_key,
                    observed_at=observed_at,
                )
            except (TypeError, ValueError):
                resolved = None
        fingerprint = resolved.identity_fingerprint if resolved is not None else None
        if row.company_identity_fingerprint != fingerprint:
            updates.append(
                {"indexed_signal_key": row.signal_key, "indexed_fingerprint": fingerprint}
            )
    if updates:
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == sa.bindparam("indexed_signal_key"))
            .values(company_identity_fingerprint=sa.bindparam("indexed_fingerprint")),
            updates,
        )


def backfill_signal_company_identities(connection: sa.Connection) -> int:
    """Idempotently backfill historical 0022 identities in bounded keyset batches."""
    cursor = ""
    indexed = 0
    while True:
        keys = tuple(
            connection.execute(
                sa.select(materialized_signal.c.signal_key)
                .where(materialized_signal.c.signal_key > cursor)
                .order_by(materialized_signal.c.signal_key)
                .limit(INDEX_BATCH_SIZE)
            ).scalars()
        )
        if not keys:
            break
        _index_historical_company_batch(connection, keys)
        indexed += len(keys)
        cursor = keys[-1]
        if len(keys) < INDEX_BATCH_SIZE:
            break
    return indexed
