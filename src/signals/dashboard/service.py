"""PR1 §5 — `GET /dashboard` : le résumé du jour, sur la portée du compte.

Une lecture unique, jamais un moteur à part. Tout ce qui apparaît ici est déjà
calculé ailleurs — `feed_page` pour les nouveautés, `list_companies` pour le
suivi commercial, `signal_feedback`/`company_contact` pour l'activité de la
semaine — ce module ne fait que les assembler à une seule date de lecture.

    `previous_seen` n'est jamais lu ici
    ────────────────────────────────────
    L'appelant (la route) lit `account_visit.last_seen_at` AVANT d'appeler
    `build_dashboard`, et ne le met à jour qu'APRÈS. Le mélanger aux deux
    rendrait un compte incapable de savoir ce qu'il vient de voir : la
    fonction ne modifie jamais la visite, elle la reçoit toute faite.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa

from signals.api.cards import presentation_bindings_for_items, render_unlocked_card
from signals.billing.access import FeedAccess
from signals.card_intelligence.store import published_for_signals
from signals.companies.enrichment import winner_enrichments_for_signals
from signals.companies.listing import list_companies
from signals.companies.service import company_keys_for_signals, company_profile_with_items
from signals.engagement.feedback import feedback_by_signal
from signals.engagement.schema import company_contact, signal_feedback
from signals.engagement.status import status_resolver
from signals.feed import policy
from signals.feed import query as feed_query
from signals.feed.history import effective_history_date
from signals.feed.query import FEEDING_ICP_STATUS, FeedSignal, _ownership_scoped, owned_target_icps
from signals.persistence.repository import signal_from_row
from signals.persistence.schema import materialized_signal, source_event

_WEEK_SCAN_BATCH = 250
_WEEK_SCAN_CAP = feed_query.HISTORY_SCAN_CAP

#: Meilleur `icp_match_band` d'abord. `None`/inconnu ne prétend à rien (§5).
_BAND_RANK: dict[str, int] = {"strong": 3, "promising": 2, "weak": 1}

_FOLLOW_UP_LIMIT = 50


def _band_rank(band: str | None) -> int:
    return _BAND_RANK.get(band, 0)


def _top3_sort_key(item: FeedSignal) -> tuple[int, int, int]:
    """Bande, puis score, puis date effective — tous décroissants (§5)."""
    date, _kind = effective_history_date(item.signal)
    score = item.signal.icp_match_normalized_score
    return (
        _band_rank(item.signal.icp_match_band),
        score or -1,
        date.toordinal() if date is not None else -1,
    )


def _history_sort_key(item: FeedSignal) -> tuple[int, int]:
    """Le signal le plus récent d'une entreprise, date effective décroissante."""
    date, _kind = effective_history_date(item.signal)
    if date is None:
        return (1, 0)
    return (0, -date.toordinal())


def _render_items(
    connection: sa.Connection,
    items: list[FeedSignal],
    *,
    company_key_of: Callable[[FeedSignal], str | None],
    account_id: str,
    lang: str,
    resolve_status: Callable[[str], str],
) -> dict[str, dict[str, Any]]:
    """Rend la carte complète de chaque item, en une seule volée de lectures.

    Partagé par `top3` et `to_follow_up` : deux surfaces qui montrent la MÊME
    carte qu'un signal débloqué ne doivent jamais en dériver (`api/cards.py`).
    """
    if not items:
        return {}
    presentation_bindings = presentation_bindings_for_items(connection, items)
    presentations = published_for_signals(
        connection,
        account_id=account_id,
        bindings=presentation_bindings,
        language=lang,
    )
    signal_keys = tuple(item.signal.signal_key for item in items)
    enrichments = winner_enrichments_for_signals(connection, signal_keys=signal_keys)
    return {
        item.signal.signal_key: render_unlocked_card(
            item,
            lang=lang,
            presentation=presentations.get(item.signal.signal_key),
            company_key=company_key_of(item),
            enrichment=enrichments.get(item.signal.signal_key),
            status=resolve_status(item.signal.signal_key),
        )
        for item in items
    }


def _week_new_count(
    connection: sa.Connection,
    *,
    account_id: str,
    as_of: dt.date,
    allowed_target_icp_ids: frozenset[str] | None,
    access: FeedAccess,
) -> int:
    """Signaux accessibles publiés dans `[as_of - 7j, as_of]`, quel que soit leur statut.

    Écrit en SQL direct plutôt que via `feed_page` : le mode de fraîcheur par
    défaut n'admet que les statuts « nouveauté », et `week.new` doit compter
    toute publication récente, y compris un signal déjà vieilli par ailleurs.
    """
    owned = owned_target_icps(connection, account_id=account_id)
    if not any(profile.status == FEEDING_ICP_STATUS for profile in owned.values()):
        return 0
    if allowed_target_icp_ids is not None and not allowed_target_icp_ids:
        return 0

    floor = as_of - dt.timedelta(days=7)
    query = _ownership_scoped(account_id).where(
        source_event.c.published_on >= floor,
        source_event.c.published_on <= as_of,
    )
    if allowed_target_icp_ids is not None:
        query = query.where(materialized_signal.c.target_icp_id.in_(sorted(allowed_target_icp_ids)))

    count = 0
    scanned = 0
    last_at: dt.datetime | None = None
    last_key: str | None = None
    while scanned < _WEEK_SCAN_CAP:
        batch_query = query
        if last_key is not None:
            batch_query = batch_query.where(
                sa.or_(
                    materialized_signal.c.materialized_at < last_at,
                    sa.and_(
                        materialized_signal.c.materialized_at == last_at,
                        materialized_signal.c.signal_key > last_key,
                    ),
                )
            )
        batch_limit = min(_WEEK_SCAN_BATCH, _WEEK_SCAN_CAP - scanned)
        rows = connection.execute(batch_query.limit(batch_limit)).all()
        if not rows:
            break
        last_row = rows[-1]
        last_at = last_row.materialized_at
        last_key = last_row.signal_key
        scanned += len(rows)
        for row in rows:
            signal = signal_from_row(row)
            profile = owned[signal.target_icp_id]
            item = FeedSignal(
                signal=signal,
                recency=signal.current_recency(as_of=as_of),
                account_id=account_id,
                target_icp_label=profile.label,
            )
            if access.is_unlocked(item):
                count += 1
        if len(rows) < batch_limit:
            break
    return count


def _week_activity_counts(
    connection: sa.Connection, *, account_id: str, now: dt.datetime
) -> dict[str, int]:
    """`saved`, `contacted`, `replied` — trois lectures directes sur `[now - 7j, now]`."""
    floor = now - dt.timedelta(days=7)
    saved = connection.execute(
        sa.select(sa.func.count())
        .select_from(signal_feedback)
        .where(
            signal_feedback.c.account_id == account_id,
            signal_feedback.c.relevance == "relevant",
            signal_feedback.c.updated_at >= floor,
            signal_feedback.c.updated_at <= now,
        )
    ).scalar_one()
    contacted = connection.execute(
        sa.select(sa.func.count())
        .select_from(signal_feedback)
        .where(
            signal_feedback.c.account_id == account_id,
            signal_feedback.c.contacted_at.is_not(None),
            signal_feedback.c.contacted_at >= floor,
            signal_feedback.c.contacted_at <= now,
        )
    ).scalar_one()
    replied = connection.execute(
        sa.select(sa.func.count())
        .select_from(company_contact)
        .where(
            company_contact.c.account_id == account_id,
            company_contact.c.status == "replied",
            company_contact.c.updated_at >= floor,
            company_contact.c.updated_at <= now,
        )
    ).scalar_one()
    return {"saved": saved, "contacted": contacted, "replied": replied}


def _to_follow_up(
    connection: sa.Connection,
    *,
    account_id: str,
    as_of: dt.date,
    allowed_target_icp_ids: frozenset[str] | None,
    access: FeedAccess,
    now: dt.datetime,
    lang: str,
    resolve_status: Callable[[str], str],
) -> list[dict[str, Any]]:
    """Entreprises `contacted` depuis au moins 7 jours, la plus ancienne relance d'abord."""
    page = list_companies(
        connection,
        account_id=account_id,
        as_of=as_of,
        allowed_target_icp_ids=allowed_target_icp_ids,
        access=access,
        contact_statuses=frozenset({"contacted"}),
        query=None,
        limit=_FOLLOW_UP_LIMIT,
        cursor=None,
    )
    cutoff = now - dt.timedelta(days=7)
    due_rows = sorted(
        (row for row in page.rows if row.contacted_at is not None and row.contacted_at <= cutoff),
        key=lambda row: row.contacted_at,
    )

    last_item_by_company: dict[str, FeedSignal] = {}
    for row in due_rows:
        result = company_profile_with_items(
            connection,
            company_key=row.company_key,
            account_id=account_id,
            as_of=as_of,
            allowed_target_icp_ids=allowed_target_icp_ids,
            access=access,
            lang=lang,
        )
        if result is None:
            continue
        _profile, items = result
        if not items:
            continue
        last_item_by_company[row.company_key] = min(items, key=_history_sort_key)

    signal_company_key = {
        item.signal.signal_key: company_key for company_key, item in last_item_by_company.items()
    }
    cards_by_signal = _render_items(
        connection,
        list(last_item_by_company.values()),
        company_key_of=lambda item: signal_company_key.get(item.signal.signal_key),
        account_id=account_id,
        lang=lang,
        resolve_status=resolve_status,
    )

    results: list[dict[str, Any]] = []
    for row in due_rows:
        item = last_item_by_company.get(row.company_key)
        if item is None:
            continue
        results.append(
            {
                "company_key": row.company_key,
                "name": row.name,
                "last_signal": cards_by_signal[item.signal.signal_key],
                "days_since_contact": (now - row.contacted_at).days,
            }
        )
    return results


def build_dashboard(
    connection: sa.Connection,
    *,
    account_id: str,
    now: dt.datetime,
    as_of: dt.date,
    allowed_target_icp_ids: frozenset[str] | None,
    access: FeedAccess,
    lang: str,
    previous_seen: dt.datetime | None,
) -> dict[str, Any]:
    """L'agrégat entier de `GET /dashboard`, à `as_of`.

    N'écrit rien : ni `account_visit`, ni aucune autre table. C'est le seul
    moyen de rendre la fonction testable sans exiger une transaction, et
    d'empêcher que la lecture même du tableau de bord modifie ce qu'elle lit.
    """
    resolve_status = status_resolver(feedback_by_signal(connection, account_id=account_id))

    scope = feed_query.feed_page(
        connection,
        account_id=account_id,
        as_of=as_of,
        freshness=policy.DEFAULT_FRESHNESS,
        allowed_target_icp_ids=allowed_target_icp_ids,
        limit=policy.MAXIMUM_PAGE_SIZE,
        offset=0,
        status_of=resolve_status,
        statuses=frozenset({"new"}),
    )

    if previous_seen is None:
        since_visit = list(scope.items)
    else:
        cutoff_date = previous_seen.date()
        since_visit = [
            item
            for item in scope.items
            if item.signal.event.published_on is not None
            and item.signal.event.published_on > cutoff_date
        ]

    new_since_last_visit = len(since_visit)
    strong_matches = sum(1 for item in since_visit if item.signal.icp_match_band == "strong")

    top3_items = sorted(scope.items, key=_top3_sort_key, reverse=True)[:3]
    top3_company_keys = company_keys_for_signals(
        connection, signal_keys=tuple(item.signal.signal_key for item in top3_items)
    )
    top3_cards = _render_items(
        connection,
        top3_items,
        company_key_of=lambda item: top3_company_keys.get(item.signal.signal_key),
        account_id=account_id,
        lang=lang,
        resolve_status=resolve_status,
    )
    top3 = [top3_cards[item.signal.signal_key] for item in top3_items]

    to_follow_up = _to_follow_up(
        connection,
        account_id=account_id,
        as_of=as_of,
        allowed_target_icp_ids=allowed_target_icp_ids,
        access=access,
        now=now,
        lang=lang,
        resolve_status=resolve_status,
    )

    week = {
        "new": _week_new_count(
            connection,
            account_id=account_id,
            as_of=as_of,
            allowed_target_icp_ids=allowed_target_icp_ids,
            access=access,
        ),
        **_week_activity_counts(connection, account_id=account_id, now=now),
    }

    return {
        "as_of": as_of.isoformat(),
        "last_seen_at": previous_seen.isoformat() if previous_seen is not None else None,
        "new_since_last_visit": new_since_last_visit,
        "strong_matches": strong_matches,
        "top3": top3,
        "to_follow_up": to_follow_up,
        "week": week,
        "scan_truncated": scope.scan_truncated,
    }


__all__ = ["build_dashboard"]
