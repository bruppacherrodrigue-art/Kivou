"""Le mur payant — visible, mais qui ne donne pas le lead qu'il protège.

Un teaser qui nomme l'entreprise n'est pas un teaser (§21)
─────────────────────────────────────────────────────────
Le produit de Kivou EST la piste commerciale : quelle entreprise, sur quel
marché. Un aperçu verrouillé qui laisse voir le nom de l'attributaire, son
identifiant, l'intitulé exact du marché ou l'URL de la source rend le
paiement décoratif — il suffit de lire la liste.

Ce qui reste visible est donc du **contexte de conversion** : qu'il s'est
passé quelque chose, quand, dans quel pays, de quel ordre de grandeur, dans
quelle famille d'activité. Assez pour donner envie ; pas assez pour
contacter quiconque.

La construction est soustractive dans un seul sens
─────────────────────────────────────────────────
Le teaser n'est pas obtenu en retirant des champs de la carte complète — une
telle liste noire oublie le champ ajouté le mois prochain. Il est **construit
à partir de rien**, champ par champ, à partir des seules valeurs explicitement
autorisées.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from signals.feed import copy as feed_copy
from signals.feed import policy
from signals.feed.query import FeedSignal
from signals.feed.view import is_consortium_award

PAYWALL_VERSION = "kivou-paywall-v0.1"

#: Les paliers de grandeur affichés à la place du montant exact. Le montant
#: publié est un fait public, mais rendu au centime il identifie souvent le
#: marché à lui seul ; le palier informe sans désigner.
_MAGNITUDE_BANDS: tuple[tuple[Decimal, str], ...] = (
    (Decimal("50000"), "under_50k"),
    (Decimal("250000"), "50k_250k"),
    (Decimal("1000000"), "250k_1m"),
    (Decimal("5000000"), "1m_5m"),
)
_LARGEST_BAND = "over_5m"


def magnitude_band(amount: Decimal | None) -> str | None:
    """L'ordre de grandeur d'un montant, ou `None` si la source n'en publie pas."""
    if amount is None:
        return None
    for ceiling, label in _MAGNITUDE_BANDS:
        if amount < ceiling:
            return label
    return _LARGEST_BAND


#: La phrase d'un signal verrouillé — SANS sujet nommé.
#:
#: `recency.claim` reste l'autorité pour la phrase d'un signal débloqué, mais
#: ses gabarits parlent d'une entreprise nommée : les rendre avec un nom vide
#: produirait « vient de remporter un marché public. », une phrase sans sujet.
#: Le mur payant a donc ses propres formulations, qui décrivent l'ÉVÉNEMENT et
#: jamais l'entreprise. Aucune n'affirme davantage que le statut n'autorise.
LOCKED_HEADLINE: dict[str, dict[str, str]] = {
    "recent_award": {
        "fr": "Un marché public vient d'être attribué.",
        "en": "A public contract has recently been awarded.",
    },
    "recently_notified_contract": {
        "fr": "Un marché public vient d'être notifié.",
        "en": "A public contract has recently been notified.",
    },
    "recently_published_award": {
        "fr": "Une attribution vient d'être publiée.",
        "en": "An award notice has recently been published.",
    },
    "aging_award": {
        "fr": "Un marché public attribué récemment.",
        "en": "A recently attributed public contract.",
    },
    "stale_award": {
        "fr": "Un marché public déjà attribué.",
        "en": "An already attributed public contract.",
    },
    "award_date_unknown": {
        "fr": "Un avis d'attribution sans date de décision publiée.",
        "en": "An award notice with no published decision date.",
    },
    "invalid_award_date": {
        "fr": "Un avis d'attribution dont la date publiée est incohérente.",
        "en": "An award notice whose published date is inconsistent.",
    },
}


def locked_teaser(item: FeedSignal, *, lang: str, status: str) -> dict[str, Any]:
    """L'aperçu verrouillé — construit champ par champ, jamais par soustraction.

    `status` est le statut UNIFIÉ (`new | saved | ignored | contacted`) du
    signal pour ce compte — distinct du statut de récence de l'événement
    (`item.status`, rendu dans `event.status` ci-dessous). Un signal verrouillé
    reste jugeable de loin (§30 n'interdit que le jugement, pas l'affichage
    d'un jugement déjà donné).
    """
    feed_copy.check_language(lang)
    recency_status = item.status
    award = item.signal.award
    date = item.event_date
    return {
        "signal_id": item.signal.signal_key,
        "target_icp_id": item.signal.target_icp_id,
        "locked": True,
        "unlock_required": "paid_plan",
        "status": status,
        # PR2b §46 — fait PUBLIC (un groupement se lit dans l'avis lui-même),
        # jamais `band` ni `cpv_label` : ceux-ci restent des données protégées
        # tant que le signal n'est pas débloqué.
        "is_consortium": is_consortium_award(award.awardee_parties),
        "event": {
            "status": recency_status,
            "type": policy.customer_event_type(recency_status),
            "date": date.isoformat() if date else None,
            "why_now": feed_copy.WHY_NOW[recency_status][lang],
            "is_new_opportunity": recency_status in policy.NEW_OPPORTUNITY_STATUSES,
        },
        "context": {
            # Le pays de la SOURCE, pas la localité : une commune de mille
            # habitants et un code CPV suffisent souvent à retrouver le marché.
            "country": item.signal.event.source_country,
            "place_country": award.place_country,
            "sector": item.signal.inferred_sector,
            "contract_magnitude": magnitude_band(award.amount),
            "currency": award.currency,
            "plausible_need_count": len(item.signal.plausible_needs or []),
        },
        # La phrase décrit l'ÉVÉNEMENT, jamais l'entreprise.
        "headline": LOCKED_HEADLINE[recency_status][lang],
    }


def locked_detail(
    item: FeedSignal, *, lang: str, status: str, upgrade_to: Sequence[str]
) -> dict[str, Any]:
    """Le détail d'un signal verrouillé : le même aperçu, et rien de plus.

    Rendre 404 aurait été plus simple, et faux : le compte POSSÈDE ce signal, il
    ne l'a simplement pas payé. Confondre « pas à vous » et « pas encore
    accessible » empêcherait de dire au client ce qu'il obtiendrait en payant.

    §27 — `upgrade_to` arrive CALCULÉ par l'autorité d'accès
    ────────────────────────────────────────────────────────
    Ce module met en forme ; il ne décide pas de l'accès. La liste était
    autrefois écrite en dur (`essential / pro / scale`), ce qui promettait à un
    client qu'un plan Essential ouvrirait un signal de 400 jours — il ne
    l'ouvre pas. La calculer ici demanderait d'y importer les droits et la
    fenêtre d'historique, c'est-à-dire de dupliquer la règle d'accès dans la
    couche d'affichage.
    """
    teaser = locked_teaser(item, lang=lang, status=status)
    teaser["access"] = {
        "granted": False,
        "reason": "plan_entitlement_required",
        "upgrade_to": tuple(upgrade_to),
    }
    return teaser


def within_history_window(item: FeedSignal, *, history_days: int | None, as_of: dt.date) -> bool:
    """Le signal tombe-t-il dans la fenêtre d'historique du plan (§25) ?

    La mesure porte sur la date de l'événement COURANT — celle que le client
    lit. Un plan plus généreux n'autorise jamais une formulation de nouveauté
    sur un signal ancien : la fenêtre décide de ce qu'on montre, la politique de
    fraîcheur décide de ce qu'on en dit, et les deux restent séparées.
    """
    if history_days is None:
        return True
    date = item.event_date
    if date is None:
        # Aucune date exploitable : le signal ne peut pas prouver qu'il tombe
        # dans la fenêtre, donc il n'y tombe pas.
        return False
    return (as_of - date).days <= history_days
