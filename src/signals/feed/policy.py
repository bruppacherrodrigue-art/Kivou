"""Ce que le feed montre, dans quel ordre, et jusqu'où il lit.

Le feed est temporel avant d'être pertinent (§5)
───────────────────────────────────────────────
Trier par `materialized_at DESC` classerait par date d'INGESTION : un lot
ancien ingéré ce matin passerait devant une attribution d'hier ingérée la
semaine dernière. Trier par score classerait par affinité, ce qui n'est pas
la promesse du MVP. L'ordre part donc de l'événement tel qu'il vaut
AUJOURD'HUI, puis de sa date, puis d'une clé stable.

Aucun nouveau modèle de classement n'est introduit : le rang ci-dessous
n'est que l'ordre de dérivation déjà écrit dans `recency.policy`, rendu
triable.
"""

from __future__ import annotations

from typing import Literal

from signals.recency import AGING_AWARD_DAYS, RECENT_AWARD_DAYS

FEED_POLICY_VERSION = "customer-feed-v0.1"

Freshness = Literal["new", "recent_or_aging", "all"]
FRESHNESS_MODES: tuple[str, ...] = ("new", "recent_or_aging", "all")
DEFAULT_FRESHNESS: Freshness = "new"

#: §5 — les trois seuls états qui décrivent une NOUVEAUTÉ exploitable.
NEW_OPPORTUNITY_STATUSES: tuple[str, ...] = (
    "recent_award",
    "recently_notified_contract",
    "recently_published_award",
)

#: `aging_award` reste exact, simplement plus neuf : récupérable, jamais par défaut.
AGING_STATUSES: tuple[str, ...] = ("aging_award",)

#: §5 — `stale_award` ne doit jamais apparaître dans le feed des nouveautés.
#: `award_date_unknown` et `invalid_award_date` ne sont pas nommés par la SPEC ;
#: ils sont traités comme `stale_award` parce qu'ils ne portent AUCUNE date
#: exploitable — les laisser entrer par `mvp_event_type`, qui les rattache à
#: `RECENTLY_PUBLISHED_AWARD`, ferait passer une parution ancienne pour une
#: nouveauté. Le feed se règle donc sur le STATUT, jamais sur le type dérivé.
HISTORY_ONLY_STATUSES: tuple[str, ...] = (
    "stale_award",
    "award_date_unknown",
    "invalid_award_date",
)

_STATUSES_BY_FRESHNESS: dict[str, tuple[str, ...] | None] = {
    "new": NEW_OPPORTUNITY_STATUSES,
    "recent_or_aging": NEW_OPPORTUNITY_STATUSES + AGING_STATUSES,
    #: `None` = aucun filtre de fraîcheur. La formulation reste sûre : elle vient
    #: de `recency.claim`, qui n'a pas de phrase de nouveauté pour ces états.
    "all": None,
}

#: L'ordre de mise en avant. Il reprend `_primary_status` de `recency.policy` :
#: décision récente, puis notification récente, puis parution récente, puis les
#: états datés mais anciens.
STATUS_RANK: dict[str, int] = {
    "recent_award": 0,
    "recently_notified_contract": 1,
    "recently_published_award": 2,
    "aging_award": 3,
    "stale_award": 4,
    "invalid_award_date": 5,
    "award_date_unknown": 6,
}

#: L'horloge qui a décidé du statut — donc la date que le client doit lire.
STATUS_CLOCK: dict[str, str] = {
    "recent_award": "award",
    "aging_award": "award",
    "stale_award": "award",
    "invalid_award_date": "award",
    "recently_notified_contract": "notification",
    "recently_published_award": "publication",
    "award_date_unknown": "publication",
}

DEFAULT_PAGE_SIZE = 20
MAXIMUM_PAGE_SIZE = 50
"""Plafond imposé par le serveur : un client ne peut pas demander tout d'un coup."""

CANDIDATE_SCAN_CAP = 500
"""Nombre maximal de lignes rechargées avant réévaluation de la fraîcheur.

La fraîcheur COURANTE se calcule en Python, depuis les dates brutes : elle ne
peut donc pas être triée en SQL sans figer un instantané, ce que SPEC-010
interdit précisément. La lecture est donc bornée en amont, et le dépassement
est ANNONCÉ (`scan_truncated`) plutôt que silencieux.
"""


def statuses_for(freshness: str) -> tuple[str, ...] | None:
    """Les statuts admis par un mode, ou `None` quand le mode n'en filtre aucun."""
    if freshness not in _STATUSES_BY_FRESHNESS:
        raise ValueError(f"mode de fraîcheur inconnu : {freshness!r} (attendu {FRESHNESS_MODES})")
    return _STATUSES_BY_FRESHNESS[freshness]


def candidate_window_days(freshness: str) -> int | None:
    """La largeur de la fenêtre SQL de présélection, ou `None` pour aucune.

    Elle est une condition NÉCESSAIRE, jamais suffisante : un statut ne peut être
    « nouveau » que si l'une des trois dates brutes tombe dans la fenêtre, mais y
    tomber ne suffit pas — une décision vieille de quarante jours reste
    `aging_award` même publiée hier. Le tri exact reste fait en Python ; la
    fenêtre ne sert qu'à ne pas relire toute la table.
    """
    if freshness == "new":
        return RECENT_AWARD_DAYS
    if freshness == "recent_or_aging":
        return AGING_AWARD_DAYS
    return None


#: CLOSEOUT §2 — le type d'événement TEL QUE LE CLIENT le lit.
#:
#: `recency.claim.mvp_event_type` rattache `award_date_unknown` et
#: `invalid_award_date` à `RECENTLY_PUBLISHED_AWARD` : à l'intérieur du moteur
#: c'est un raccourci de reporting sans conséquence, mais rendu tel quel il
#: étiquetterait « publication récente » une parution ancienne, voire un avis
#: dont aucune date n'est exploitable.
#:
#: La correction est faite ICI, à la frontière client, et non dans
#: `recency.claim` : cette fonction alimente `materialized_primary_event`, donc
#: la colonne persistée et l'empreinte de contenu. La corriger en amont
#: réécrirait des instantanés d'audit et la sémantique des bancs historiques.
#:
#: Aucun type n'est inventé : les trois valeurs rendues sont les statuts
#: eux-mêmes. Tout le reste ne porte AUCUN type d'événement MVP.
_CUSTOMER_EVENT_TYPE: dict[str, str] = {
    "recent_award": "recent_award",
    "recently_notified_contract": "recently_notified_contract",
    "recently_published_award": "recently_published_award",
}


def customer_event_type(status: str) -> str | None:
    """Le type d'événement exposé au client, ou `None` quand il n'y en a pas.

    `aging_award`, `stale_award`, `invalid_award_date` et `award_date_unknown`
    sont exacts et lisibles — ils ne sont simplement pas des nouveautés, et
    aucun type ne doit laisser croire l'inverse.
    """
    return _CUSTOMER_EVENT_TYPE.get(status)


def rank_of(status: str) -> int:
    """Le rang de mise en avant. Un statut inconnu passe en dernier, sans lever."""
    return STATUS_RANK.get(status, len(STATUS_RANK))
