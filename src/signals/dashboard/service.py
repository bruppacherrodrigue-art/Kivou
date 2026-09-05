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

    Fix round 1 (C1/I1) — le droit du plan n'est jamais optionnel
    ───────────────────────────────────────────────────────────────
    `feed_page` sait désormais filtrer par `admit` (le prédicat du plan,
    typiquement `access.is_unlocked`) et par `published_since`. CE module
    l'utilise pour LES QUATRE agrégats qui lisent le feed
    (`new_since_last_visit`, `strong_matches`, `top3`, `week.new`) : un compte
    non payant sans déblocage Discovery ne doit jamais recevoir une carte
    complète — nom du vainqueur, montant, analyse, présentation — pour un
    signal qu'il n'a pas le droit de voir. Le premier tour de revue avait
    laissé passer exactement ce contournement.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa

from signals.accounts import service as accounts
from signals.api.cards import presentation_bindings_for_items, render_unlocked_card
from signals.billing.access import FeedAccess
from signals.card_intelligence.store import published_for_signals
from signals.companies.enrichment import winner_enrichments_for_signals
from signals.companies.listing import list_companies
from signals.companies.service import company_keys_for_signals
from signals.engagement.feedback import feedback_by_signal
from signals.engagement.schema import company_contact, signal_feedback
from signals.engagement.status import status_resolver
from signals.feed import policy
from signals.feed import query as feed_query
from signals.feed.history import effective_history_date
from signals.feed.query import FeedSignal

#: Meilleur `icp_match_band` d'abord. `None`/inconnu ne prétend à rien (§5).
_BAND_RANK: dict[str, int] = {"strong": 3, "promising": 2, "weak": 1}

#: Fix round 2 (F4) — le nombre de relances rendues, et donc le nombre de
#: lectures par signal que ce bloc peut coûter. Sans plafond, une entreprise
#: contactée de plus valait un balayage complet de plus : le tableau de bord
#: devenait plus lent à mesure que le compte travaillait. Dix relances les plus
#: anciennes suffisent à un écran « à faire aujourd'hui » ; au-delà,
#: `to_follow_up_truncated` le dit plutôt que de le taire.
_FOLLOW_UP_LIMIT = 10


def _band_rank(band: str | None) -> int:
    return _BAND_RANK.get(band, 0)


def _top3_sort_key(item: FeedSignal) -> tuple[int, int, int]:
    """Bande, puis score, puis date effective — tous décroissants (§5)."""
    date, _kind = effective_history_date(item.signal)
    score = item.signal.icp_match_normalized_score
    return (
        _band_rank(item.signal.icp_match_band),
        -1 if score is None else score,
        date.toordinal() if date is not None else -1,
    )


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
    Chaque `item` fourni ici DOIT déjà avoir passé `access.is_unlocked` — cette
    fonction ne le vérifie pas une seconde fois, elle fait confiance à
    l'appelant (§C1 : la garde est dans `feed_page`, pas ici).
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
    allowed_target_icp_ids: frozenset[str],
    access: FeedAccess,
    now: dt.datetime,
    lang: str,
    resolve_status: Callable[[str], str],
) -> tuple[list[dict[str, Any]], bool, bool]:
    """Entreprises `contacted` depuis au moins 7 jours, la plus ancienne relance d'abord.

    Fix round 1 (I3) — le filtre `contacted_before` est appliqué DANS
    `list_companies`, avant le tri et la pagination : la liste ne pioche plus
    dans les 50 entreprises les plus récemment récompensées pour les filtrer
    ensuite, ce qui aurait pu faire disparaître une relance légitime derrière
    une entreprise plus « fraîche » mais pas encore due. `limit` est porté à
    `HISTORY_SCAN_CAP` (pas de plafond à 50 ici — c'est la route `GET
    /companies`, pas cette fonction, qui impose `le=50`).

    Fix round 2 (F4) — le tri par `contacted_at` précède la découpe, et la
    découpe précède toute lecture par entreprise : le coût du bloc est borné à
    `_FOLLOW_UP_LIMIT` signaux lus, quel que soit le nombre d'entreprises dues.
    Le dernier signal de chaque relance se relit par sa CLÉ (`last_signal_key`,
    déjà connue de l'agrégation), et non en rebalayant l'entreprise entière.

    Rend `(relances, scan_truncated de la liste, to_follow_up_truncated)`.
    """
    page = list_companies(
        connection,
        account_id=account_id,
        as_of=as_of,
        allowed_target_icp_ids=allowed_target_icp_ids,
        access=access,
        contact_statuses=frozenset({"contacted"}),
        contacted_before=now - dt.timedelta(days=7),
        query=None,
        limit=feed_query.HISTORY_SCAN_CAP,
        cursor=None,
    )
    ordered = sorted(page.rows, key=lambda row: row.contacted_at)
    follow_up_truncated = len(ordered) > _FOLLOW_UP_LIMIT or page.scan_truncated
    due_rows = ordered[:_FOLLOW_UP_LIMIT]

    last_item_by_company: dict[str, FeedSignal] = {}
    for row in due_rows:
        if row.last_signal_key is None:
            continue
        item = feed_query.owned_signal(
            connection,
            account_id=account_id,
            signal_key=row.last_signal_key,
            as_of=as_of,
            allowed_target_icp_ids=allowed_target_icp_ids,
        )
        # La propriété ne suffit pas : le droit du PLAN décide, exactement
        # comme pour `top3` (`admit=access.is_unlocked` dans `feed_page`). Un
        # signal sans nom affichable n'a rien à montrer non plus.
        if item is None or item.display is None or not access.is_unlocked(item):
            continue
        last_item_by_company[row.company_key] = item

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
    return results, page.scan_truncated, follow_up_truncated


def build_dashboard(
    connection: sa.Connection,
    *,
    account_id: str,
    now: dt.datetime,
    as_of: dt.date,
    allowed_target_icp_ids: frozenset[str],
    access: FeedAccess,
    lang: str,
    previous_seen: dt.datetime | None,
) -> dict[str, Any]:
    """L'agrégat entier de `GET /dashboard`, à `as_of`.

    N'écrit rien : ni `account_visit`, ni aucune autre table. C'est le seul
    moyen de rendre la fonction testable sans exiger une transaction, et
    d'empêcher que la lecture même du tableau de bord modifie ce qu'elle lit.

    `new_since_last_visit` compte les signaux dont `published_on >=
    previous_seen.date()` (borne INCLUSIVE — fix round 1, I4) : une parution du
    même jour qu'une visite passée n'est jamais perdue, quitte à être comptée
    deux fois si le client revient plusieurs fois le même jour, ce qui est
    accepté plutôt que de risquer l'inverse. Un signal sans `published_on`
    n'est compté que quand `previous_seen is None` (compte jamais vu — tout y
    compte, faute d'une date de visite à comparer).
    """
    resolve_status = status_resolver(feedback_by_signal(connection, account_id=account_id))

    # Fix round 1 (C1/I1) — UNE portée, pour `new_since_last_visit`,
    # `strong_matches` ET `top3` : possédé + autorisé par le plan de territoire
    # + nommé + DÉBLOQUÉ (`admit=access.is_unlocked`). Un signal qu'un compte
    # Discovery ou impayé n'a pas débloqué n'apparaît dans AUCUN des trois.
    # Fix round 2 (F1) — `limit=1` : la PAGE ne sert à rien ici, seul
    # `scope.matched` compte. Demander `MAXIMUM_PAGE_SIZE` puis lire
    # `scope.items` plafonnait les trois agrégats à cinquante — un compte avec
    # soixante nouveautés en annonçait cinquante, et un signal `strong` classé
    # cinquante-et-unième par date ne pouvait plus jamais atteindre `top3`.
    scope = feed_query.feed_page(
        connection,
        account_id=account_id,
        as_of=as_of,
        freshness=policy.DEFAULT_FRESHNESS,
        allowed_target_icp_ids=allowed_target_icp_ids,
        limit=1,
        offset=0,
        status_of=resolve_status,
        statuses=frozenset({"new"}),
        admit=access.is_unlocked,
    )

    if previous_seen is None:
        since_visit = list(scope.matched)
    else:
        cutoff_date = previous_seen.date()
        since_visit = [
            item
            for item in scope.matched
            if item.signal.event.published_on is not None
            and item.signal.event.published_on >= cutoff_date
        ]

    new_since_last_visit = len(since_visit)
    strong_matches = sum(
        1
        for item in since_visit
        if item.signal.icp_match_band == "strong" and item.model_fit != "none"
    )

    top3_candidates = [
        item
        for item in scope.matched
        if item.model_fit != "none"
        and item.display is not None
        and bool((item.signal.award.title or "").strip())
    ]
    seen_top3 = {item.signal.signal_key for item in top3_candidates}
    for landing_key in accounts.landing_signal_keys(connection, account_id=account_id):
        if landing_key in seen_top3:
            continue
        landing_item = feed_query.owned_signal(
            connection,
            account_id=account_id,
            signal_key=landing_key,
            as_of=as_of,
            allowed_target_icp_ids=allowed_target_icp_ids,
        )
        if (
            landing_item is not None
            and landing_item.display is not None
            and landing_item.model_fit != "none"
            and bool((landing_item.signal.award.title or "").strip())
            and access.is_unlocked(landing_item)
        ):
            top3_candidates.append(landing_item)
    top3_items = sorted(top3_candidates, key=_top3_sort_key, reverse=True)[:3]
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

    to_follow_up, follow_up_scan_truncated, to_follow_up_truncated = _to_follow_up(
        connection,
        account_id=account_id,
        as_of=as_of,
        allowed_target_icp_ids=allowed_target_icp_ids,
        access=access,
        now=now,
        lang=lang,
        resolve_status=resolve_status,
    )

    # Fix round 1 (I2) — `week.new` réutilise `feed_page`, PAS un décompte SQL
    # séparé : la même portée (propriété, identité affichable, droit du plan)
    # doit gouverner ce nombre. `freshness="all"` lève le filtre de fraîcheur
    # (un `aging_award`/`stale_award` publié dans la fenêtre compte quand même,
    # « quel que soit son statut ») ; `published_since` pose la fenêtre des 7
    # jours ; `limit=1` suffit — les compteurs portent sur `selected`, jamais
    # sur la page rendue.
    week_page = feed_query.feed_page(
        connection,
        account_id=account_id,
        as_of=as_of,
        freshness="all",
        allowed_target_icp_ids=allowed_target_icp_ids,
        limit=1,
        offset=0,
        status_of=resolve_status,
        admit=access.is_unlocked,
        published_since=as_of - dt.timedelta(days=7),
    )
    week = {
        "new": sum(week_page.status_counts.values()),
        **_week_activity_counts(connection, account_id=account_id, now=now),
    }

    return {
        "as_of": as_of.isoformat(),
        "last_seen_at": previous_seen.isoformat() if previous_seen is not None else None,
        "new_since_last_visit": new_since_last_visit,
        "strong_matches": strong_matches,
        "top3": top3,
        "to_follow_up": to_follow_up,
        #: PR1 §5 (fix round 2, F4) — vrai quand plus de `_FOLLOW_UP_LIMIT`
        #: relances étaient dues, ou quand le balayage de la liste a été
        #: tronqué : la liste rendue est alors un extrait, jamais « tout ».
        "to_follow_up_truncated": to_follow_up_truncated,
        "week": week,
        "scan_truncated": (
            scope.scan_truncated or week_page.counts_truncated or follow_up_scan_truncated
        ),
    }


__all__ = ["build_dashboard"]
