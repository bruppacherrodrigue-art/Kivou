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
import datetime as dt
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Query, Request

from signals.accounts import service
from signals.api.dependencies import current_session, request_now
from signals.api.errors import api_error
from signals.billing import discovery, paywall
from signals.billing import service as billing
from signals.billing.access import (
    FeedAccess,
    FilterNotEntitled,
    check_filters,
    eligible_upgrade_plans,
    feed_access,
    filter_is_available,
)
from signals.card_intelligence.contracts import PublishedCardPresentation
from signals.card_intelligence.store import (
    published_artifact_for_signal,
    published_for_signals,
)
from signals.companies.service import (
    ensure_companies_for_unlocked_signals,
    ensure_company_for_unlocked_signal,
)
from signals.engagement import analytics, feedback
from signals.feed import policy, query, view
from signals.feed.history import InvalidHistoryCursor
from signals.persistence.schema import materialized_signal
from signals.recency import RECENCY_POLICY_VERSION

router = APIRouter()

Freshness = Literal["new", "recent_or_aging", "all"]
SignalView = Literal["recent", "history"]
HistoryStatus = Literal[
    "recent_award",
    "recently_notified_contract",
    "recently_published_award",
    "aging_award",
    "stale_award",
    "invalid_award_date",
    "award_date_unknown",
]

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


def _presentation_bindings(connection, items) -> dict[str, tuple[int, int]]:
    """Reload only revision numbers absent from the legacy feed dataclass.

    The query is batched and receives only items whose access has already been
    granted.  Presentation lookup therefore never sees a locked signal key.
    """

    by_key = {item.signal.signal_key: item for item in items}
    if not by_key:
        return {}
    revisions = {
        row.signal_key: row.target_icp_revision
        for row in connection.execute(
            sa.select(
                materialized_signal.c.signal_key,
                materialized_signal.c.target_icp_revision,
            ).where(materialized_signal.c.signal_key.in_(tuple(by_key)))
        )
    }
    return {
        signal_key: (item.signal.revision, revisions[signal_key])
        for signal_key, item in by_key.items()
        if signal_key in revisions
    }


@router.get("/signals")
def list_signals(
    request: Request,
    view_mode: Annotated[SignalView, Query(alias="view")] = "recent",
    freshness: Freshness = policy.DEFAULT_FRESHNESS,
    target_icp_id: str | None = None,
    primary_event: PrimaryEvent | None = None,
    country: str | None = Query(default=None, min_length=2, max_length=2),
    subdivision_code: str | None = Query(
        default=None,
        min_length=2,
        max_length=16,
        pattern=r"^[A-Z0-9-]+$",
    ),
    status: HistoryStatus | None = None,
    cpv_prefix: str | None = Query(default=None, min_length=1, max_length=8, pattern=r"^\d+$"),
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    winner: str | None = None,
    limit: int = Query(default=policy.DEFAULT_PAGE_SIZE, ge=1, le=policy.MAXIMUM_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None, max_length=512),
) -> dict[str, Any]:
    """Les signaux de CE compte, les plus actionnables d'abord.

    `limit` est plafonné par le serveur : un client ne peut pas demander la
    table entière, et `le=MAXIMUM_PAGE_SIZE` rend le refus explicite plutôt que
    de rogner la demande en silence.
    """
    now = request_now(request)
    as_of = now.date()
    if cursor is not None and view_mode != "history":
        raise api_error(
            422,
            "cursor_requires_history_view",
            "un curseur historique exige view=history",
        )
    if view_mode != "history" and any(
        value is not None
        for value in (date_from, date_to, subdivision_code, status, cpv_prefix)
    ):
        raise api_error(
            422,
            "history_filters_require_history_view",
            "ces filtres exigent view=history",
        )
    if view_mode == "history" and offset != 0:
        raise api_error(
            422,
            "offset_not_supported_for_history",
            "l'historique utilise un curseur, pas un décalage",
        )
    if date_from is not None and date_to is not None and date_from > date_to:
        raise api_error(
            422,
            "invalid_history_date_range",
            "la date de début doit précéder la date de fin",
        )
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
                    "date_from": date_from,
                    "date_to": date_to,
                    "country": country,
                    "subdivision_code": subdivision_code,
                    "status": status,
                    "primary_event": primary_event,
                    "cpv_prefix": cpv_prefix,
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
            if view_mode == "history":
                page = query.history_page(
                    connection,
                    account_id=session.account_id,
                    as_of=as_of,
                    target_icp_id=target_icp_id,
                    allowed_target_icp_ids=allowed,
                    country=country,
                    subdivision_code=subdivision_code,
                    status=status,
                    cpv_prefix=cpv_prefix,
                    date_from=date_from,
                    date_to=date_to,
                    limit=limit,
                    cursor=cursor,
                )
            else:
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
        except InvalidHistoryCursor as error:
            raise api_error(
                422,
                "invalid_history_cursor",
                "curseur historique invalide",
            ) from error

        unlocked_items = tuple(item for item in page.items if access.is_unlocked(item))
        presentation_bindings = _presentation_bindings(connection, unlocked_items)
        presentations = published_for_signals(
            connection,
            account_id=session.account_id,
            bindings=presentation_bindings,
            language=lang,
        )
        company_keys = ensure_companies_for_unlocked_signals(
            connection,
            items=unlocked_items,
            now=now,
        )

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
                "freshness": "all" if view_mode == "history" else freshness,
                "view": view_mode,
                "returned": len(page.items),
                "plan_code": access.plan_code,
                "offset": 0 if view_mode == "history" else offset,
            },
        )

    page_payload = (
        {
            "limit": page.limit,
            "offset": 0,
            "cursor": page.cursor,
            "next_cursor": page.next_cursor,
            "has_more": page.has_more,
            "scan_truncated": page.scan_truncated,
        }
        if view_mode == "history"
        else {
            "limit": page.limit,
            "offset": page.offset,
            "has_more": page.has_more,
            "scan_truncated": page.scan_truncated,
        }
    )
    return {
        "items": [
            _render(
                item,
                access,
                lang=lang,
                presentation=presentations.get(item.signal.signal_key),
                company_key=company_keys.get(item.signal.signal_key),
            )
            for item in page.items
        ],
        "total_returned": len(page.items),
        "page": page_payload,
        "excluded": {
            "without_display_name": page.excluded_without_display_name,
            "by_freshness": (
                0 if view_mode == "history" else page.excluded_by_freshness
            ),
            "by_filters": (
                page.excluded_by_filters if view_mode == "history" else 0
            ),
        },
        "read_at": as_of.isoformat(),
        "freshness": "all" if view_mode == "history" else freshness,
        "view": view_mode,
        "language": lang,
        "plan_code": access.plan_code,
        "history_access": _history_access(access),
        "filter_access": _filter_access(access),
        "policy": {
            "feed": policy.FEED_POLICY_VERSION,
            "recency": RECENCY_POLICY_VERSION,
            "paywall": paywall.PAYWALL_VERSION,
        },
    }


def _history_access(access: FeedAccess) -> dict[str, Any]:
    if not access.is_paid:
        scope = "grants_only"
    elif access.entitlements.history_days is None:
        scope = "all_available"
    else:
        scope = "window"
    return {
        "scope": scope,
        "history_days": access.entitlements.history_days,
    }


def _filter_access(access: FeedAccess) -> dict[str, bool]:
    entitlements = access.entitlements
    return {
        "date_range": filter_is_available(entitlements, "date_from"),
        "country": filter_is_available(entitlements, "country"),
        "subdivision": filter_is_available(entitlements, "subdivision_code"),
        "status": filter_is_available(entitlements, "status"),
        "sector": filter_is_available(entitlements, "cpv_prefix"),
    }


def _render(
    item,
    access: FeedAccess,
    *,
    lang: str,
    presentation: PublishedCardPresentation | None,
    company_key: str | None,
) -> dict[str, Any]:
    """La carte complète si le plan l'ouvre, l'aperçu verrouillé sinon."""
    if access.is_unlocked(item):
        card = view.feed_item(item, lang=lang, presentation=presentation)
        card["locked"] = False
        if company_key is not None:
            card["company_key"] = company_key
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
def get_signal(
    signal_key: str,
    request: Request,
    presentation_artifact_id: str | None = Query(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    ),
) -> dict[str, Any]:
    """Le détail d'un signal possédé — de quoi vérifier, pas seulement lire."""
    now = request_now(request)
    as_of = now.date()
    # La consultation est ENREGISTRÉE : d'où une transaction plutôt qu'une
    # simple lecture.
    company_key = None
    presentation = None
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
            if unlocked:
                binding = _presentation_bindings(connection, (item,)).get(signal_key)
                if binding is not None:
                    if presentation_artifact_id is None:
                        presentation = published_for_signals(
                            connection,
                            account_id=session.account_id,
                            bindings={signal_key: binding},
                            language=lang,
                        ).get(signal_key)
                    else:
                        presentation = published_artifact_for_signal(
                            connection,
                            account_id=session.account_id,
                            signal_key=signal_key,
                            binding=binding,
                            language=lang,
                            artifact_id=presentation_artifact_id,
                        )
                company_key = ensure_company_for_unlocked_signal(
                    connection,
                    item=item,
                    now=now,
                )
    if item is None:
        raise api_error(404, "signal_not_found", "signal introuvable")

    if not access.is_unlocked(item):
        # Le compte POSSÈDE ce signal : répondre 404 confondrait « pas à vous »
        # et « pas encore accessible », et empêcherait de dire ce que le
        # paiement débloquerait.
        locked = paywall.locked_detail(
            item, lang=lang, upgrade_to=eligible_upgrade_plans(item, access=access)
        )
        locked["read_at"] = as_of.isoformat()
        locked["language"] = lang
        return locked

    detail = view.signal_detail(item, lang=lang, presentation=presentation)
    detail["read_at"] = as_of.isoformat()
    detail["language"] = lang
    detail["locked"] = False
    if company_key is not None:
        detail["company_key"] = company_key
    # §8 — l'avis du client vit dans SON bloc. Il n'est ni un fait publié ni une
    # inférence du moteur, et il ne doit contaminer ni `contract`, ni `event`,
    # ni `evidence`, ni `analysis`.
    detail["interaction"] = _interaction(interaction)
    return detail


def _interaction(stored) -> dict[str, Any] | None:
    from signals.api.routes_feedback import interaction_block

    return interaction_block(stored)
