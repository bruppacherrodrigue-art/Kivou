"""Le feed client et le détail d'un signal — les deux seules lectures publiques.

Aucun `POST` : un signal est produit par Kivou, jamais rédigé par un client.

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

from typing import Any, Literal

from fastapi import APIRouter, Query, Request

from signals.accounts import service
from signals.api.dependencies import current_session, request_now
from signals.api.errors import api_error
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
    with request.app.state.engine.connect() as connection:
        session = current_session(request, connection, now)
        lang = _language(connection, user_id=session.user_id)
        try:
            page = query.feed_page(
                connection,
                account_id=session.account_id,
                as_of=now.date(),
                freshness=freshness,
                target_icp_id=target_icp_id,
                primary_event=primary_event,
                country=country,
                winner=winner,
                limit=limit,
                offset=offset,
            )
        except query.ForeignTargetIcp as error:
            # Le profil d'un autre compte se comporte comme un profil inexistant.
            raise api_error(404, "target_icp_not_found", "profil de ciblage introuvable") from error

    return {
        "items": [view.feed_item(item, lang=lang) for item in page.items],
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
        "read_at": now.date().isoformat(),
        "freshness": freshness,
        "language": lang,
        "policy": {
            "feed": policy.FEED_POLICY_VERSION,
            "recency": RECENCY_POLICY_VERSION,
        },
    }


@router.get("/signals/{signal_key}")
def get_signal(signal_key: str, request: Request) -> dict[str, Any]:
    """Le détail d'un signal possédé — de quoi vérifier, pas seulement lire."""
    now = request_now(request)
    with request.app.state.engine.connect() as connection:
        session = current_session(request, connection, now)
        lang = _language(connection, user_id=session.user_id)
        item = query.owned_signal(
            connection,
            account_id=session.account_id,
            signal_key=signal_key,
            as_of=now.date(),
        )
    if item is None:
        raise api_error(404, "signal_not_found", "signal introuvable")

    detail = view.signal_detail(item, lang=lang)
    detail["read_at"] = now.date().isoformat()
    detail["language"] = lang
    return detail
