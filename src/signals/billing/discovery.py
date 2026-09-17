"""Les trois signaux offerts — donnés une fois, pas prêtés chaque jour.

Pourquoi persister les déblocages
─────────────────────────────────
« Les 3 signaux les plus récents » serait un produit gratuit permanent :
chaque matin, trois nouvelles opportunités, sans jamais payer. Kivou offre
donc **trois signaux nommés**, débloqués une fois pour toutes et conservés.

Comment ils sont choisis
────────────────────────
La portée canonique du feed garantit la propriété du compte, le profil actif,
l'identité affichable et la sémantique d'événement courante. Dans cette portée,
le backfill initial applique le classement commercial explicite de l'offre :
pertinence, fraîcheur, qualité documentaire, timing, puis clé stable.

Ce qui se passe s'il y en a moins de trois
─────────────────────────────────────────
On donne ce qu'il y a. Les places restantes se remplissent plus tard, quand
des signaux éligibles apparaissent. Une fois les trois attribués, ils ne
tournent plus : un signal offert reste offert.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa

from signals.accounts.schema import account
from signals.accounts.service import landing_signal_keys
from signals.billing.catalogue import DISCOVERY_GRANT_LIMIT
from signals.billing.schema import discovery_signal_grant
from signals.feed import policy
from signals.feed import query as feed_query
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import evidence, materialized_signal


@dataclasses.dataclass(frozen=True)
class Grant:
    account_id: str
    signal_key: str
    opportunity_key: str
    granted_at: dt.datetime


@dataclasses.dataclass(frozen=True)
class BackfillPreview:
    """Read-only explanation of one account's lifetime Discovery allocation."""

    account_id: str
    plan_code: str
    granted_signal_keys: tuple[str, ...]
    eligible_signal_keys: tuple[str, ...]
    proposed_signal_keys: tuple[str, ...]
    scan_truncated: bool = False

    @property
    def remaining_slots(self) -> int:
        return max(0, DISCOVERY_GRANT_LIMIT - len(self.granted_signal_keys))


def granted_signal_keys(connection: sa.Connection, *, account_id: str) -> frozenset[str]:
    rows = connection.execute(
        sa.select(discovery_signal_grant.c.signal_key).where(
            discovery_signal_grant.c.account_id == account_id
        )
    ).all()
    return frozenset(row.signal_key for row in rows)


def grants(connection: sa.Connection, *, account_id: str) -> tuple[Grant, ...]:
    rows = connection.execute(
        sa.select(discovery_signal_grant)
        .where(discovery_signal_grant.c.account_id == account_id)
        .order_by(discovery_signal_grant.c.granted_at, discovery_signal_grant.c.signal_key)
    ).all()
    return tuple(
        Grant(row.account_id, row.signal_key, row.opportunity_key, _aware(row.granted_at))
        for row in rows
    )


def remaining_slots(connection: sa.Connection, *, account_id: str) -> int:
    return max(
        0,
        DISCOVERY_GRANT_LIMIT - len(opened_signal_keys(connection, account_id=account_id)),
    )


def opened_signal_keys(connection: sa.Connection, *, account_id: str) -> frozenset[str]:
    """The three Discovery signals visible to the account, bait included."""

    return granted_signal_keys(connection, account_id=account_id) | landing_signal_keys(
        connection, account_id=account_id
    )


def _lock_account(connection: sa.Connection, *, account_id: str) -> None:
    """Serialize the count-and-insert boundary on both supported databases."""

    statement = sa.select(account.c.account_id).where(account.c.account_id == account_id)
    if connection.dialect.name == "sqlite":
        # SQLite ignores SELECT FOR UPDATE. A bounded no-op write acquires its
        # writer lock before the grant count is read, matching PostgreSQL's row
        # lock closely enough for local execution and concurrency tests.
        result = connection.execute(
            sa.update(account)
            .where(account.c.account_id == account_id)
            .values(account_id=account.c.account_id)
        )
        if result.rowcount != 1:
            raise LookupError(f"unknown account: {account_id}")
    else:
        statement = statement.with_for_update()
    if connection.dialect.name != "sqlite" and connection.scalar(statement) is None:
        raise LookupError(f"unknown account: {account_id}")


def _evidence_by_award(
    connection: sa.Connection, award_keys: tuple[str, ...]
) -> dict[str, tuple[int, bool]]:
    if not award_keys:
        return {}
    rows = connection.execute(
        sa.select(evidence.c.award_key, evidence.c.source_url).where(
            evidence.c.award_key.in_(award_keys)
        )
    ).all()
    collected: dict[str, tuple[int, bool]] = {}
    for row in rows:
        count, has_url = collected.get(row.award_key, (0, False))
        collected[row.award_key] = (count + 1, has_url or bool((row.source_url or "").strip()))
    return collected


def _document_score(item, *, evidence_count: int) -> int:
    award = item.signal.award
    event = item.signal.event
    return min(evidence_count, 8) + sum(
        (
            bool((event.source_url or "").strip()),
            bool((event.source_notice_id or "").strip()),
            bool((award.title or "").strip()),
            bool(award.cpv_main),
            award.amount is not None and award.currency is not None,
            bool(award.place_of_performance),
            bool(event.procedure_buyers),
            award.award_date is not None,
            award.contract_notification_date is not None,
            award.contract_start_date is not None,
            award.contract_end_date is not None,
            award.duration_value is not None and award.duration_unit is not None,
        )
    )


def _commercial_timing_key(item, *, as_of: dt.date) -> tuple[int, int]:
    """Prefer an upcoming/active execution clock, then documented duration."""

    award = item.signal.award
    if award.contract_start_date is not None and award.contract_start_date >= as_of:
        return (0, (award.contract_start_date - as_of).days)
    if award.contract_end_date is not None and award.contract_end_date >= as_of:
        return (1, (award.contract_end_date - as_of).days)
    if award.duration_value is not None and award.duration_unit is not None:
        return (2, 0)
    return (3, 0)


def _candidate_sort_key(item, *, evidence_count: int, as_of: dt.date) -> tuple:
    band_rank = {"strong": 0, "promising": 1, "weak": 2}.get(
        item.signal.icp_match_band, 3
    )
    score = item.signal.icp_match_normalized_score
    event_date = item.event_date
    return (
        band_rank,
        -(score if score is not None else -1),
        policy.rank_of(item.status),
        -_document_score(item, evidence_count=evidence_count),
        *_commercial_timing_key(item, as_of=as_of),
        -(event_date.toordinal() if event_date is not None else 0),
        item.signal.signal_key,
    )


def preview_initial_backfill(
    connection: sa.Connection,
    *,
    account_id: str,
    as_of: dt.date,
) -> BackfillPreview:
    """Select real existing candidates without writing or applying plan history.

    This scan is intentionally independent of ``history_days``. Ownership,
    active target revision and display identity still come from the canonical
    feed query; only the three proposed signal IDs can become freely readable.
    """

    # Local import avoids making billing service's catalogue dependency a
    # module-import cycle with this grant service.
    from signals.billing import service as billing_service

    state = billing_service.billing_state(connection, account_id=account_id)
    existing = tuple(sorted(opened_signal_keys(connection, account_id=account_id)))
    if not state.is_discovery or len(existing) >= DISCOVERY_GRANT_LIMIT:
        return BackfillPreview(account_id, state.plan_code, existing, (), ())

    allowed = frozenset(
        billing_service.feedable_target_icps(
            connection,
            account_id=account_id,
            limit=state.entitlements.max_active_icps,
        )
    )
    if not allowed:
        return BackfillPreview(account_id, state.plan_code, existing, (), ())

    page = feed_query.feed_page(
        connection,
        account_id=account_id,
        as_of=as_of,
        freshness="all",
        allowed_target_icp_ids=allowed,
        limit=1,
    )
    awards = tuple(
        dict.fromkeys(item.signal.materialization_award_key for item in page.matched)
    )
    proof = _evidence_by_award(connection, awards)
    eligible = []
    for item in page.matched:
        evidence_count, evidence_has_url = proof.get(
            item.signal.materialization_award_key, (0, False)
        )
        source_has_url = bool((item.signal.event.source_url or "").strip()) or evidence_has_url
        if (
            item.display is None
            or not (item.signal.award.title or "").strip()
            or not source_has_url
            or item.event_date is None
            or item.status in {"invalid_award_date", "award_date_unknown"}
        ):
            continue
        eligible.append((item, evidence_count))
    eligible.sort(
        key=lambda candidate: _candidate_sort_key(
            candidate[0], evidence_count=candidate[1], as_of=as_of
        )
    )
    eligible_keys = tuple(item.signal.signal_key for item, _count in eligible)
    already_open = frozenset(existing)
    proposed = tuple(
        key
        for key in eligible_keys
        if key not in already_open
    )[: max(0, DISCOVERY_GRANT_LIMIT - len(existing))]
    return BackfillPreview(
        account_id,
        state.plan_code,
        existing,
        eligible_keys,
        proposed,
        scan_truncated=page.scan_truncated,
    )


def reconcile_initial_backfill(
    connection: sa.Connection,
    *,
    account_id: str,
    as_of: dt.date,
    now: dt.datetime,
) -> tuple[str, ...]:
    """Fill this Discovery account's remaining lifetime slots atomically."""

    from signals.billing import service as billing_service

    if not billing_service.billing_state(connection, account_id=account_id).is_discovery:
        return ()
    # Grants are monotone in the product. Avoid taking the account lock and
    # rescanning up to 500 candidates on every later ingestion once the
    # lifetime allocation is complete. A stale positive value is harmless:
    # the locked preview below rechecks the exact count.
    if remaining_slots(connection, account_id=account_id) == 0:
        return ()
    _lock_account(connection, account_id=account_id)
    preview = preview_initial_backfill(connection, account_id=account_id, as_of=as_of)
    if preview.plan_code != "discovery" or not preview.proposed_signal_keys:
        return ()
    opportunities = dict(
        connection.execute(
            sa.select(
                materialized_signal.c.signal_key,
                materialized_signal.c.opportunity_key,
            ).where(
                materialized_signal.c.signal_key.in_(preview.proposed_signal_keys)
            )
        ).tuples().all()
    )
    newly: list[str] = []
    for key in preview.proposed_signal_keys:
        opportunity_key = opportunities.get(key)
        if opportunity_key is None:
            continue
        inserted = insert_if_absent(
            connection,
            discovery_signal_grant,
            {
                "account_id": account_id,
                "signal_key": key,
                "opportunity_key": opportunity_key,
                "granted_at": now,
                "created_at": now,
            },
        )
        if inserted:
            newly.append(key)
    return tuple(newly)


def grant_up_to_limit(
    connection: sa.Connection,
    *,
    account_id: str,
    candidates: list,
    now: dt.datetime,
) -> tuple[str, ...]:
    """Débloque les premiers candidats éligibles, jusqu'au plafond.

    `candidates` est la page de feed déjà ordonnée et filtrée par SPEC-012 :
    cette fonction ne rejuge rien, elle prend dans l'ordre. Les signaux déjà
    débloqués sont sautés sans consommer de place.
    """
    _lock_account(connection, account_id=account_id)
    slots = remaining_slots(connection, account_id=account_id)
    if slots <= 0:
        return ()

    # Le signal d'atterrissage est déjà ouvert par `feed_access` et compte dans
    # les trois signaux visibles : seules deux autres places restent à remplir.
    already = opened_signal_keys(connection, account_id=account_id)
    newly: list[str] = []
    for item in candidates:
        if slots <= 0:
            break
        key = item.signal.signal_key
        if key in already:
            continue
        inserted = insert_if_absent(
            connection,
            discovery_signal_grant,
            {
                "account_id": account_id,
                "signal_key": key,
                "opportunity_key": item.signal.opportunity_key,
                "granted_at": now,
                "created_at": now,
            },
        )
        if not inserted:
            already = already | {key}
            continue
        newly.append(key)
        already = already | {key}
        slots -= 1
    return tuple(newly)


def _aware(value) -> dt.datetime:
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
