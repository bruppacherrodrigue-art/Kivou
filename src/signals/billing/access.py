"""Qui voit quoi — la dernière condition, jamais la première.

L'ordre compte (§22)
────────────────────
    propriété du compte  →  identité affichable  →  politique de signal
                         →  droit du plan  →  accès

Ce module n'intervient qu'à la quatrième étape. Il reçoit une page de feed
DÉJÀ restreinte par SPEC-011 (propriété) et SPEC-012 (identité affichable,
fraîcheur courante), et décide seulement de ce qui est ouvert ou verrouillé.
Il ne peut donc pas, même par erreur, rendre visible un signal d'un autre
compte ou un signal d'avant les comptes : ceux-là ne lui parviennent pas.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa

from signals.billing import catalogue, discovery, service
from signals.billing.catalogue import PlanEntitlements
from signals.billing.paywall import within_history_window
from signals.feed.query import FeedSignal

#: Les niveaux de filtre, du plus pauvre au plus riche. Comparer des rangs vaut
#: mieux que comparer des chaînes : « advanced » n'est pas « supérieur » à
#: « basic » pour Python.
FILTER_RANK: dict[str, int] = {"minimum": 0, "basic": 1, "advanced": 2}

#: Le niveau exigé par chaque filtre de `GET /signals`. Aucun moteur de filtre
#: nouveau n'est introduit : ce sont ceux de SPEC-012 (§26).
FILTER_REQUIREMENTS: dict[str, str] = {
    "target_icp_id": "minimum",
    "freshness": "minimum",
    "date_from": "minimum",
    "date_to": "minimum",
    "country": "basic",
    "subdivision_code": "basic",
    "status": "basic",
    "primary_event": "basic",
    "cpv_prefix": "advanced",
    "winner": "advanced",
}


class FilterNotEntitled(service.BillingError):
    """§26 — un filtre hors du plan est refusé, jamais ignoré en silence.

    L'ignorer rendrait une page qui ne correspond pas à la demande, et le client
    croirait que son filtre ne trouve rien.
    """

    code = "filter_not_entitled"

    def __init__(self, name: str, required: str) -> None:
        super().__init__(f"le filtre {name!r} demande le niveau {required!r}")
        self.filter_name = name
        self.required_level = required


def check_filters(entitlements: PlanEntitlements, requested: dict[str, object]) -> None:
    """Refuse le premier filtre que le plan ne couvre pas."""
    available = FILTER_RANK.get(entitlements.filter_level, 0)
    for name, value in requested.items():
        if value is None:
            continue
        required = FILTER_REQUIREMENTS.get(name, "minimum")
        if FILTER_RANK.get(required, 0) > available:
            raise FilterNotEntitled(name, required)


def filter_is_available(entitlements: PlanEntitlements, filter_name: str) -> bool:
    """Whether the existing plan level grants one declared feed filter."""
    available = FILTER_RANK.get(entitlements.filter_level, 0)
    required = FILTER_REQUIREMENTS.get(filter_name, "minimum")
    return available >= FILTER_RANK.get(required, 0)


@dataclasses.dataclass(frozen=True)
class FeedAccess:
    """La décision d'accès, calculée une fois pour toute une page."""

    plan_code: str
    entitlements: PlanEntitlements
    #: Les signaux offerts à un compte Discovery, débloqués nominativement.
    granted: frozenset[str]
    as_of: dt.date

    @property
    def is_paid(self) -> bool:
        return self.entitlements.is_paid

    def is_unlocked(self, item: FeedSignal) -> bool:
        """Ce signal est-il ouvert pour ce compte, aujourd'hui ?

        Un signal offert le reste **quel que soit son âge** : il a été donné, pas
        prêté, et le reprendre parce qu'il a vieilli serait reprendre un cadeau.
        """
        if item.signal.signal_key in self.granted:
            return True
        if not self.is_paid:
            return False
        return within_history_window(
            item, history_days=self.entitlements.history_days, as_of=self.as_of
        )

    def as_plan(self, plan_code: str) -> FeedAccess:
        """La MÊME décision, posée avec les droits d'un autre plan.

        Les déblocages déjà acquis et la date de lecture sont conservés : c'est
        ce qui permet de répondre « et si ce compte payait tel plan ? » sans
        réécrire une seule règle d'accès.
        """
        return dataclasses.replace(
            self, plan_code=plan_code, entitlements=catalogue.entitlements_for(plan_code)
        )


def eligible_upgrade_plans(item: FeedSignal, *, access: FeedAccess) -> tuple[str, ...]:
    """Les plans achetables qui ouvriraient RÉELLEMENT ce signal (§27).

    Pourquoi rejouer la décision plutôt que comparer des fenêtres
    ─────────────────────────────────────────────────────────────
    On pourrait trier les plans par `history_days` et prendre ceux dont la
    fenêtre couvre l'âge du signal. Ce serait une SECONDE implémentation de la
    règle d'accès, et le jour où l'accès dépendrait d'autre chose que de l'âge,
    elle deviendrait fausse sans que rien n'échoue. Ici, chaque plan candidat
    passe par `is_unlocked` — la même fonction qui verrouille la carte.

    Un signal déjà ouvert ne rend RIEN : recommander un paiement pour ce qui est
    déjà accessible — un déblocage Discovery, par exemple — serait vendre du
    vent, et c'est précisément le piège que §20 interdit.
    """
    if access.is_unlocked(item):
        return ()
    return tuple(
        plan for plan in catalogue.PURCHASABLE_PLANS if access.as_plan(plan).is_unlocked(item)
    )


def feed_access(connection: sa.Connection, *, account_id: str, as_of: dt.date) -> FeedAccess:
    """L'accès du compte, lu une seule fois par requête."""
    state = service.billing_state(connection, account_id=account_id)
    return FeedAccess(
        plan_code=state.plan_code,
        entitlements=state.entitlements,
        granted=discovery.granted_signal_keys(connection, account_id=account_id),
        as_of=as_of,
    )
