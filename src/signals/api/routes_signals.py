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
from decimal import Decimal
from typing import Annotated, Any, Literal, get_args

from fastapi import APIRouter, Query, Request

from signals.accounts import service
from signals.api.cards import presentation_bindings_for_items, render_unlocked_card
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
from signals.companies.contracts import WinnerEnrichmentView
from signals.companies.enrichment import winner_enrichments_for_signals
from signals.companies.service import (
    company_keys_for_signals,
)
from signals.engagement import analytics, feedback
from signals.engagement.status import (
    DEFAULT_LISTING_STATUSES,
    UNIFIED_STATUSES,
    status_resolver,
    unified_status,
)
from signals.feed import policy, query, view
from signals.feed.history import InvalidHistoryCursor
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
    status: Annotated[list[str] | None, Query()] = None,
    recency_status: HistoryStatus | None = None,
    cpv_prefix: str | None = Query(default=None, min_length=1, max_length=8, pattern=r"^\d+$"),
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    # `noqa: B008` — bugbear n'exempte `Query(...)` de son garde-fou « appel en
    # défaut » que pour les annotations qu'il reconnaît (str, int, float…) ;
    # `Decimal` n'y figure pas, alors que `ge=0` est le SEUL endroit qui peut
    # porter cette borne sans dupliquer la validation dans le corps de route.
    min_amount: Decimal | None = Query(default=None, ge=0),  # noqa: B008
    q: str | None = Query(default=None, min_length=2, max_length=120),
    winner: str | None = None,
    limit: int = Query(default=policy.DEFAULT_PAGE_SIZE, ge=1, le=policy.MAXIMUM_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None, max_length=512),
) -> dict[str, Any]:
    """Les signaux de CE compte, les plus actionnables d'abord.

    `limit` est plafonné par le serveur : un client ne peut pas demander la
    table entière, et `le=MAXIMUM_PAGE_SIZE` rend le refus explicite plutôt que
    de rogner la demande en silence.

    `status` est répétable et mélange deux vocabulaires par compatibilité :
    un statut unifié (`new | saved | ignored | contacted`) filtre la liste, et
    une valeur de récence héritée (`recent_award`, …) est comprise comme
    `recency_status` — le nom que porte désormais ce filtre.
    """
    now = request_now(request)
    as_of = now.date()

    unified_selected: set[str] = set()
    legacy_recency_values: list[str] = []
    for value in status or ():
        if value in UNIFIED_STATUSES:
            unified_selected.add(value)
        elif value in get_args(HistoryStatus):
            legacy_recency_values.append(value)
        else:
            raise api_error(422, "invalid_status", f"statut inconnu : {value!r}")
    if len(set(legacy_recency_values)) > 1:
        raise api_error(
            422, "invalid_status", "un seul statut de récence est admis par requête"
        )
    if legacy_recency_values:
        legacy_recency_status = legacy_recency_values[0]
        if recency_status is not None and recency_status != legacy_recency_status:
            raise api_error(422, "invalid_status", "statut de récence ambigu")
        recency_status = legacy_recency_status
    statuses = frozenset(unified_selected) or DEFAULT_LISTING_STATUSES

    if cursor is not None and view_mode != "history":
        raise api_error(
            422,
            "cursor_requires_history_view",
            "un curseur historique exige view=history",
        )
    if view_mode != "history" and recency_status is not None:
        # PR2b tâche 3 — `date_from`/`date_to`/`subdivision_code`/`cpv_prefix`
        # sont désormais disponibles en vue Récentes aussi (`feed_page` les
        # applique lui-même) ; seule `recency_status` reste un concept propre
        # à l'historique, une horloge FIGÉE que la vue Récentes ne connaît pas.
        raise api_error(
            422,
            "history_filters_require_history_view",
            "ce filtre exige view=history",
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
                    "status": recency_status,
                    "primary_event": primary_event,
                    "cpv_prefix": cpv_prefix,
                    "winner": winner,
                    "min_amount": min_amount,
                    "q": q,
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
        # §2 — une lecture groupée par requête ; le statut de chaque signal se
        # dérive de là, jamais d'un aller-retour en base par carte.
        resolve_status = status_resolver(
            feedback.feedback_by_signal(connection, account_id=session.account_id)
        )
        try:
            if view_mode == "history":
                page = query.history_page(
                    connection,
                    account_id=session.account_id,
                    as_of=as_of,
                    target_icp_id=target_icp_id,
                    allowed_target_icp_ids=allowed,
                    primary_event=primary_event,
                    country=country,
                    subdivision_code=subdivision_code,
                    status=recency_status,
                    cpv_prefix=cpv_prefix,
                    date_from=date_from,
                    date_to=date_to,
                    min_amount=min_amount,
                    text_query=q,
                    winner=winner,
                    limit=limit,
                    cursor=cursor,
                    status_of=resolve_status,
                    statuses=statuses,
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
                    subdivision_code=subdivision_code,
                    cpv_prefix=cpv_prefix,
                    date_from=date_from,
                    date_to=date_to,
                    min_amount=min_amount,
                    text_query=q,
                    winner=winner,
                    limit=limit,
                    offset=offset,
                    status_of=resolve_status,
                    statuses=statuses,
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
        presentation_bindings = presentation_bindings_for_items(connection, unlocked_items)
        presentations = published_for_signals(
            connection,
            account_id=session.account_id,
            bindings=presentation_bindings,
            language=lang,
        )
        unlocked_keys = tuple(item.signal.signal_key for item in unlocked_items)
        company_keys = company_keys_for_signals(
            connection,
            signal_keys=unlocked_keys,
        )
        enrichments = winner_enrichments_for_signals(
            connection,
            signal_keys=unlocked_keys,
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
                enrichment=enrichments.get(item.signal.signal_key),
                status=resolve_status(item.signal.signal_key),
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
            # PR2b tâche 3 — `feed_page` compte désormais lui aussi ce que
            # `subdivision_code`/`q` écartent, exactement comme l'historique.
            "by_filters": page.excluded_by_filters,
            "by_status": page.excluded_by_status,
        },
        "counts": page.status_counts,
        "counts_truncated": page.counts_truncated,
        # PR1 §2 (fix round 2) — l'historique ne compte que sur sa première
        # page. Les suivantes rendent quand même les quatre clés, à zéro, et
        # `counts_available: false` dit pourquoi : un client qui affiche les
        # compteurs doit les garder de la première page, pas les remplacer.
        "counts_available": page.counts_available,
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
        "min_amount": filter_is_available(entitlements, "min_amount"),
        "search": filter_is_available(entitlements, "q"),
    }


def _render(
    item,
    access: FeedAccess,
    *,
    lang: str,
    presentation: PublishedCardPresentation | None,
    company_key: str | None,
    enrichment: WinnerEnrichmentView | None,
    status: str,
) -> dict[str, Any]:
    """La carte complète si le plan l'ouvre, l'aperçu verrouillé sinon."""
    if access.is_unlocked(item):
        return render_unlocked_card(
            item,
            lang=lang,
            presentation=presentation,
            company_key=company_key,
            enrichment=enrichment,
            status=status,
        )
    return paywall.locked_teaser(item, lang=lang, status=status)


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
    enrichment = None
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
                binding = presentation_bindings_for_items(connection, (item,)).get(signal_key)
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
                company_key = company_keys_for_signals(
                    connection,
                    signal_keys=(signal_key,),
                ).get(signal_key)
                enrichment = winner_enrichments_for_signals(
                    connection, signal_keys=(signal_key,)
                ).get(signal_key)
    if item is None:
        raise api_error(404, "signal_not_found", "signal introuvable")

    status = unified_status(interaction)
    if not access.is_unlocked(item):
        # Le compte POSSÈDE ce signal : répondre 404 confondrait « pas à vous »
        # et « pas encore accessible », et empêcherait de dire ce que le
        # paiement débloquerait.
        locked = paywall.locked_detail(
            item,
            lang=lang,
            status=status,
            upgrade_to=eligible_upgrade_plans(item, access=access),
        )
        locked["read_at"] = as_of.isoformat()
        locked["language"] = lang
        return locked

    detail = view.signal_detail(item, lang=lang, presentation=presentation)
    detail["read_at"] = as_of.isoformat()
    detail["language"] = lang
    detail["locked"] = False
    detail["status"] = status
    if company_key is not None:
        detail["company_key"] = company_key
    if enrichment is not None:
        detail["winner_enrichment"] = enrichment.model_dump(mode="json")
        if enrichment.official_name is not None:
            detail["company"]["name"] = enrichment.official_name
    # §8 — l'avis du client vit dans SON bloc. Il n'est ni un fait publié ni une
    # inférence du moteur, et il ne doit contaminer ni `contract`, ni `event`,
    # ni `evidence`, ni `analysis`.
    detail["interaction"] = _interaction(interaction)
    return detail


def _interaction(stored) -> dict[str, Any] | None:
    from signals.api.routes_feedback import interaction_block

    return interaction_block(stored)
