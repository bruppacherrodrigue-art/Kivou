"""Ce que le client dit d'un signal — et ce qu'il faut vérifier avant de l'écouter.

Juger suppose d'avoir vu (§30)
──────────────────────────────
Un aperçu verrouillé ne montre ni l'entreprise, ni le marché : il n'y a rien
à juger. Accepter un avis dessus ferait du formulaire de retour un oracle —
« ce signal est-il pertinent ? » finirait par renseigner sur ce qu'il cache.
L'accès au détail est donc la condition, et il porte déjà la propriété du
compte, l'identité affichable et le droit du plan.

Le retour ne touche pas le moteur (§2)
──────────────────────────────────────
Il est stocké et observé. Aucune règle, aucun score, aucun besoin ne change
parce qu'un client a cliqué.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from signals.accounts import service as account_service
from signals.api.dependencies import current_session, enforce_origin, request_now
from signals.api.errors import api_error
from signals.billing import service as billing_service
from signals.billing.access import feed_access
from signals.companies.service import company_keys_for_signals
from signals.engagement import company as company_engagement
from signals.engagement import feedback
from signals.engagement.schema import MAXIMUM_NOTE_LENGTH
from signals.feed import query as feed_query

router = APIRouter()

Relevance = Literal["relevant", "not_relevant"]
NegativeReason = Literal[
    "already_covered",
    "done_internally",
    "wrong_customer_type",
    "too_late",
    "wrong_need",
    "other",
]


class FeedbackRequest(BaseModel):
    """§7 — ni `account_id`, ni `target_icp_id` : la propriété vient de la session.

    `extra="forbid"` : un champ inconnu fait échouer la requête plutôt que
    d'être ignoré en silence.
    """

    model_config = ConfigDict(extra="forbid")

    relevance: Relevance
    reason: NegativeReason | None = None
    note: str | None = Field(default=None, max_length=MAXIMUM_NOTE_LENGTH)


def _accessible_signal(connection, session, signal_key: str, now: dt.datetime):
    """Le signal, s'il est possédé ET débloqué. Sinon, l'erreur qui convient.

    Un signal d'un autre compte reste indiscernable d'un signal inexistant ;
    un signal verrouillé, lui, existe bel et bien pour ce compte — le lui
    cacher l'empêcherait de comprendre ce qu'un paiement débloquerait.
    """
    as_of = now.date()
    access = feed_access(connection, account_id=session.account_id, as_of=as_of)
    account_service.reconcile_territory_plan_limits(
        connection,
        account_id=session.account_id,
        max_territories=access.entitlements.max_territories_per_icp,
        now=now,
    )
    allowed = frozenset(
        billing_service.feedable_target_icps(
            connection,
            account_id=session.account_id,
            limit=access.entitlements.max_active_icps,
        )
    )
    item = feed_query.owned_signal(
        connection,
        account_id=session.account_id,
        signal_key=signal_key,
        as_of=as_of,
        allowed_target_icp_ids=allowed,
    )
    if item is None:
        raise api_error(404, "signal_not_found", "signal introuvable")
    if not access.is_unlocked(item):
        raise api_error(
            403,
            "signal_not_accessible",
            "ce signal doit être débloqué avant de pouvoir être jugé",
        )
    return item


def _context(item) -> feedback.SignalContext:
    """Ce que le client a sous les yeux, figé pour l'analyse future (§32).

    L'âge vient de l'horloge qui a DÉCIDÉ du statut — la même que celle affichée
    dans le feed. Le recalculer plus tard donnerait un autre nombre, et un
    « trop tard » deviendrait inanalysable.
    """
    from signals.feed import policy as feed_policy

    status = item.status
    clock_name = feed_policy.STATUS_CLOCK.get(status)
    clock = item.recency.clocks[clock_name] if clock_name else None
    return feedback.SignalContext(
        signal_key=item.signal.signal_key,
        opportunity_key=item.signal.opportunity_key,
        target_icp_id=item.signal.target_icp_id,
        revision=item.signal.revision,
        event_status=status,
        event_age_days=clock.age_days if clock else None,
    )


def interaction_block(stored: feedback.StoredFeedback | None) -> dict[str, Any] | None:
    """§8 — le bloc d'interaction, séparé des faits et des inférences.

    L'avis d'un client n'est ni un fait public ni une déduction du moteur : le
    mélanger à `contract`, `event`, `evidence` ou `analysis` rendrait
    indistinguable ce que la source publie et ce qu'un utilisateur pense.
    """
    if stored is None:
        return None
    return {
        "relevance": stored.relevance,
        "reason": stored.reason_code,
        "note": stored.note,
        "contacted": stored.contacted,
        "contacted_at": stored.contacted_at.isoformat() if stored.contacted_at else None,
        "updated_at": stored.updated_at.isoformat(),
    }


@router.get("/signals/{signal_key}/feedback")
def read_feedback(signal_key: str, request: Request) -> dict[str, Any]:
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        _accessible_signal(connection, session, signal_key, now)
        stored = feedback.get_feedback(
            connection, account_id=session.account_id, signal_key=signal_key
        )
    return {"signal_id": signal_key, "interaction": interaction_block(stored)}


@router.put("/signals/{signal_key}/feedback")
def write_feedback(signal_key: str, payload: FeedbackRequest, request: Request) -> dict[str, Any]:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        item = _accessible_signal(connection, session, signal_key, now)
        try:
            stored = feedback.put_feedback(
                connection,
                account_id=session.account_id,
                context=_context(item),
                relevance=payload.relevance,
                reason_code=payload.reason,
                note=payload.note,
                now=now,
                user_id=session.user_id,
            )
        except feedback.InvalidFeedback as error:
            raise api_error(422, error.code, str(error)) from error
    return {"signal_id": signal_key, "interaction": interaction_block(stored)}


@router.post("/signals/{signal_key}/contacted")
def mark_contacted(signal_key: str, request: Request) -> dict[str, Any]:
    """§6 — une ACTION, idempotente. Deux clics ne font pas deux démarches."""
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        item = _accessible_signal(connection, session, signal_key, now)
        stored, changed = feedback.mark_contacted(
            connection,
            account_id=session.account_id,
            context=_context(item),
            now=now,
            user_id=session.user_id,
        )
        if changed:
            # PR1 §4 — un signal contacté fait avancer SON entreprise, jamais
            # l'inverse : le contact d'entreprise ne touche pas ses signaux.
            company_key = company_keys_for_signals(
                connection, signal_keys=(signal_key,)
            ).get(signal_key)
            if company_key is not None:
                company_engagement.mark_contacted_if_pending(
                    connection,
                    account_id=session.account_id,
                    company_key=company_key,
                    now=now,
                )
    return {
        "signal_id": signal_key,
        "interaction": interaction_block(stored),
        # `False` dit « c'était déjà enregistré » — utile au client, et sans
        # effet sur le décompte des actions commerciales.
        "recorded": changed,
    }
