"""Le feed client et le détail d'un signal — les deux seules lectures publiques.

Aucun `POST` : un signal est produit par Kivou, jamais rédigé par un client.

    La facturation est la DERNIÈRE condition (SPEC-013 §22)
    ───────────────────────────────────────────────────────
        propriété du compte → identité affichable → politique de signal
                            → droit du plan → accès

    L'accès payant s'ajoute au bout : il ne peut ni élargir la propriété, ni
    ressusciter un signal non lié, ni rendre montrable un attributaire sans nom.
    Un signal hors du droit n'est pas retiré — il est **verrouillé**, avec un
    aperçu qui ne livre pas la piste commerciale qu'il protège.

    Le temps entre par ici, une seule fois (§6)
    ──────────────────────────────────────────
    `request_now()` donne l'instant de la requête ; sa date devient l'`as_of`
    passé explicitement au feed. Toute la fraîcheur affichée est recalculée à
    partir de là, depuis les dates BRUTES. L'instantané `materialized_*` reste
    en base pour l'audit et ne sort pas d'ici : un signal figé « vient de
    remporter » en août ne doit pas le dire encore en octobre.

    Ce que la langue change, et ce qu'elle ne change pas (§21)
    ─────────────────────────────────────────────────────────
    La langue vient de `account.locale`. Elle n'affecte que les libellés :
    statuts, catégories, identifiants et dates restent identiques d'une langue
    à l'autre, parce qu'un fait ne se traduit pas.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Literal

from fastapi import APIRouter, Query, Request

from signals.accounts import service
from signals.api.dependencies import current_session, request_now
from signals.api.errors import api_error
from signals.billing import discovery, paywall
from signals.billing import service as billing
from signals.billing.access import FeedAccess, FilterNotEntitled, check_filters, feed_access
from signals.engagement import analytics, feedback
from signals.feed import policy, query, view
from signals.recency import RECENCY_POLICY_VERSION

router = APIRouter()

Freshness = Literal["new", "recent_or_aging", "all"]

#: CLOSEOUT §3 — les seules valeurs qui désignent un événement client. Refuser
#: les autres vaut mieux que de rendre une page vide sans dire pourquoi.
PrimaryEvent = Literal[
    "recent_award",
    "recently_notified_contract",
    "recently_published_award",
]


def _language(connection, *, user_id: str) -> str:
    """La langue du compte. Une locale hors catalogue retombe sur le français."""
    from signals.recency.claim import LANGUAGES

    locale = service.current_user(connection, user_id=user_id).locale
    return locale if locale in LANGUAGES else "fr"


@router.get("/signals")
def list_signals(
    request: Request,
    freshness: Freshness = policy.DEFAULT_FRESHNESS,
    target_icp_id: str | None = None,
    primary_event: PrimaryEvent | None = None,
    country: str | None = Query(default=None, min_length=2, max_length=2),
    winner: str | None = None,
    limit: int = Query(default=policy.DEFAULT_PAGE_SIZE, ge=1, le=policy.MAXIMUM_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Les signaux de CE compte, les plus actionnables d'abord.

    `limit` est plafonné par le serveur : un client ne peut pas demander la
    table entière, et `le=MAXIMUM_PAGE_SIZE` rend le refus explicite plutôt que
    de rogner la demande en silence.
    """
    now = request_now(request)
    as_of = now.date()
    # Une transaction, pas une simple lecture : un compte Discovery peut voir
    # ses trois déblocages écrits ici, une fois pour toutes (§20).
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        lang = _language(connection, user_id=session.user_id)
        access = feed_access(connection, account_id=session.account_id, as_of=as_of)
        service.reconcile_territory_plan_limits(
            connection,
            account_id=session.account_id,
            max_territories=access.entitlements.max_territories_per_icp,
            now=now,
        )
        try:
            check_filters(
                access.entitlements,
                {
                    "target_icp_id": target_icp_id,
                    "country": country,
                    "primary_event": primary_event,
                    "winner": winner,
                },
            )
        except FilterNotEntitled as error:
            raise api_error(
                403,
                error.code,
                "ce filtre demande un plan supérieur",
                filter=error.filter_name,
                required_level=error.required_level,
            ) from error

        allowed = frozenset(
            billing.feedable_target_icps(
                connection,
                account_id=session.account_id,
                limit=access.entitlements.max_active_icps,
            )
        )
        access = _grant_discovery(connection, session.account_id, access, allowed, now)
        try:
            page = query.feed_page(
                connection,
                account_id=session.account_id,
                as_of=as_of,
                freshness=freshness,
                target_icp_id=target_icp_id,
                allowed_target_icp_ids=allowed,
                primary_event=primary_event,
                country=country,
                winner=winner,
                limit=limit,
                offset=offset,
            )
        except query.ForeignTargetIcp as error:
            # Le profil d'un autre compte se comporte comme un profil inexistant.
            raise api_error(404, "target_icp_not_found", "profil de ciblage introuvable") from error

        # §34 — UNE consultation par appel de feed, jamais une par carte : une
        # ligne par signal affiché noierait la table et ne dirait rien de plus.
        analytics.record(
            connection,
            account_id=session.account_id,
            user_id=session.user_id,
            target_icp_id=target_icp_id,
            event_type="signal_feed_viewed",
            occurred_at=now,
            properties={
                "freshness": freshness,
                "returned": len(page.items),
                "plan_code": access.plan_code,
                "offset": offset,
            },
        )

    return {
        "items": [_render(item, access, lang=lang) for item in page.items],
        "total_returned": len(page.items),
        "page": {
            "limit": page.limit,
            "offset": page.offset,
            "has_more": page.has_more,
            "scan_truncated": page.scan_truncated,
        },
        "excluded": {
            "without_display_name": page.excluded_without_display_name,
            "by_freshness": page.excluded_by_freshness,
        },
        "read_at": as_of.isoformat(),
        "freshness": freshness,
        "language": lang,
        "plan_code": access.plan_code,
        "policy": {
            "feed": policy.FEED_POLICY_VERSION,
            "recency": RECENCY_POLICY_VERSION,
            "paywall": paywall.PAYWALL_VERSION,
        },
    }


def _render(item, access: FeedAccess, *, lang: str) -> dict[str, Any]:
    """La carte complète si le plan l'ouvre, l'aperçu verrouillé sinon."""
    if access.is_unlocked(item):
        card = view.feed_item(item, lang=lang)
        card["locked"] = False
        return card
    return paywall.locked_teaser(item, lang=lang)


def _grant_discovery(connection, account_id: str, access: FeedAccess, allowed, now):
    """Attribue les trois signaux offerts, si le compte y a encore droit (§20).

    La file d'attente est TOUJOURS le feed par défaut — pas celui que le client
    a demandé. Faire dépendre les déblocages d'un paramètre de requête
    permettrait de choisir ses cadeaux en changeant l'URL, et rendrait le
    résultat non déterministe.
    """
    if access.is_paid or discovery.remaining_slots(connection, account_id=account_id) == 0:
        return access
    eligible = query.feed_page(
        connection,
        account_id=account_id,
        as_of=access.as_of,
        freshness=policy.DEFAULT_FRESHNESS,
        allowed_target_icp_ids=allowed,
        limit=policy.MAXIMUM_PAGE_SIZE,
    )
    granted = discovery.grant_up_to_limit(
        connection, account_id=account_id, candidates=list(eligible.items), now=now
    )
    if not granted:
        return access
    return dataclasses.replace(access, granted=access.granted | frozenset(granted))


@router.get("/signals/{signal_key}")
def get_signal(signal_key: str, request: Request) -> dict[str, Any]:
    """Le détail d'un signal possédé — de quoi vérifier, pas seulement lire."""
    now = request_now(request)
    as_of = now.date()
    # La consultation est ENREGISTRÉE : d'où une transaction plutôt qu'une
    # simple lecture.
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        lang = _language(connection, user_id=session.user_id)
        access = feed_access(connection, account_id=session.account_id, as_of=as_of)
        service.reconcile_territory_plan_limits(
            connection,
            account_id=session.account_id,
            max_territories=access.entitlements.max_territories_per_icp,
            now=now,
        )
        allowed = frozenset(
            billing.feedable_target_icps(
                connection,
                account_id=session.account_id,
                limit=access.entitlements.max_active_icps,
            )
        )
        item = query.owned_signal(
            connection,
            account_id=session.account_id,
            signal_key=signal_key,
            as_of=as_of,
            allowed_target_icp_ids=allowed,
        )
        if item is not None:
            # §34 — la tentative sur un signal verrouillé est enregistrée aussi,
            # avec `access_granted` : c'est elle qui mesure l'appétit derrière
            # le mur payant. Un signal d'un autre compte n'existe pas ici, donc
            # rien n'est écrit — l'analytique ne doit pas devenir un annuaire.
            unlocked = access.is_unlocked(item)
            analytics.record(
                connection,
                account_id=session.account_id,
                user_id=session.user_id,
                target_icp_id=item.signal.target_icp_id,
                signal_key=signal_key,
                event_type="signal_detail_viewed",
                occurred_at=now,
                properties={"access_granted": unlocked, "plan_code": access.plan_code},
            )
            interaction = feedback.get_feedback(
                connection, account_id=session.account_id, signal_key=signal_key
            )
    if item is None:
        raise api_error(404, "signal_not_found", "signal introuvable")

    if not access.is_unlocked(item):
        # Le compte POSSÈDE ce signal : répondre 404 confondrait « pas à vous »
        # et « pas encore accessible », et empêcherait de dire ce que le
        # paiement débloquerait.
        locked = paywall.locked_detail(item, lang=lang)
        locked["read_at"] = as_of.isoformat()
        locked["language"] = lang
        return locked

    detail = view.signal_detail(item, lang=lang)
    detail["read_at"] = as_of.isoformat()
    detail["language"] = lang
    detail["locked"] = False
    # §8 — l'avis du client vit dans SON bloc. Il n'est ni un fait publié ni une
    # inférence du moteur, et il ne doit contaminer ni `contract`, ni `event`,
    # ni `evidence`, ni `analysis`.
    detail["interaction"] = _interaction(interaction)
    return detail


def _interaction(stored) -> dict[str, Any] | None:
    from signals.api.routes_feedback import interaction_block

    return interaction_block(stored)
