"""Indexed projection from materialized signals to exact public companies."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import sqlalchemy as sa

from signals.companies.identity import ResolvedOfficialCompany, official_company_identity
from signals.feed import query as feed_query
from signals.persistence.repository import SIGNAL_SELECT, signal_from_row
from signals.persistence.schema import contract_award, materialized_signal, source_event

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
    stored_fingerprints = {
        row.signal_key: row.company_identity_fingerprint for row in rows
    }
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
            .where(
                materialized_signal.c.signal_key
                == sa.bindparam("indexed_signal_key")
            )
            .values(
                company_identity_fingerprint=sa.bindparam("indexed_fingerprint")
            ),
            updates,
        )
    return indexed


def index_signal_company_identity(
    connection: sa.Connection, *, signal_key: str
) -> IndexedOfficialCompany | None:
    return index_signal_company_identities(
        connection, signal_keys=(signal_key,)
    ).get(signal_key)


def backfill_signal_company_identities(connection: sa.Connection) -> int:
    """Idempotently backfill every persisted signal in bounded keyset batches."""
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
        index_signal_company_identities(connection, signal_keys=keys)
        indexed += len(keys)
        cursor = keys[-1]
        if len(keys) < INDEX_BATCH_SIZE:
            break
    return indexed
