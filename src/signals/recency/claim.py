"""Ce que Kivou a le droit d'écrire, pour chaque état de fraîcheur.

Le texte client n'est pas un détail d'interface : c'est l'endroit exact où une
promesse devient vraie ou fausse. SPEC-009D a montré qu'un feed peut afficher
« vient de gagner » sur une attribution vieille de trois mois sans qu'aucun
test ne s'en aperçoive — parce qu'aucun test ne portait sur la phrase.

La table ci-dessous est donc du code, pas de la copie. Une seule ligne autorise
l'affirmation d'une victoire, et le test la vérifie sur les six états.
"""

from __future__ import annotations

from signals.recency.policy import AwardRecency

CLAIM_COPY_VERSION = "award-claim-copy-v0.1"

#: Les formulations qui affirment qu'une entreprise a gagné. Elles servent au
#: test de non-confusion : aucun état sauf `recent_award` ne doit en produire.
#: Elles sont en minuscules, la comparaison se faisant sur du texte replié.
JUST_WON_MARKERS: tuple[str, ...] = (
    "vient de remporter",
    "vient de gagner",
    "a remporté",
    "has recently won",
    "just won",
    "has won",
)

LANGUAGES: tuple[str, ...] = ("fr", "en")

#: `{company}` est le seul emplacement variable. Le statut choisit la phrase ;
#: aucune date n'entre dans le texte, ce qui rend impossible d'afficher une
#: valeur que `invalid_award_date` vient précisément de disqualifier.
CLAIM_TEMPLATES: dict[str, dict[str, str]] = {
    "recent_award": {
        "fr": "{company} vient de remporter un marché public.",
        "en": "{company} has recently won a public contract.",
    },
    "aging_award": {
        "fr": "{company} figure comme attributaire d'un marché public attribué récemment.",
        "en": "{company} is named as the awardee of a recently attributed public contract.",
    },
    "stale_award": {
        "fr": "{company} figure comme attributaire d'un marché public déjà attribué.",
        "en": "{company} is named as the awardee of an already attributed public contract.",
    },
    # R1 §3 — le contrat est notifié, la décision reste inconnue. La phrase parle
    # donc du MARCHÉ, pas de l'entreprise : « un marché attribué à X » énonce un
    # fait déjà acquis sans dater la victoire, ce que la source ne permet pas.
    "recently_notified_contract": {
        "fr": "Un marché attribué à {company} vient d'être notifié.",
        "en": "A public contract awarded to {company} has recently been notified.",
    },
    "recently_published_award": {
        "fr": "Une attribution concernant {company} vient d'être publiée.",
        "en": "An award notice concerning {company} has recently been published.",
    },
    "award_date_unknown": {
        "fr": "Un avis d'attribution mentionne {company}, sans date de décision publiée.",
        "en": "An award notice names {company}, with no published decision date.",
    },
    "invalid_award_date": {
        "fr": "Un avis d'attribution mentionne {company} ; la date publiée est incohérente.",
        "en": "An award notice names {company}; the published date is inconsistent.",
    },
}


def claim_for_status(status: str, *, company: str, lang: str = "fr") -> str:
    """La phrase autorisée pour un état donné — jamais une phrase devinée."""
    if lang not in LANGUAGES:
        raise ValueError(f"langue non prise en charge : {lang!r} (attendu {LANGUAGES})")
    try:
        template = CLAIM_TEMPLATES[status][lang]
    except KeyError:
        raise ValueError(f"statut de fraîcheur inconnu : {status!r}") from None
    return template.format(company=company)


def claim_for(recency: AwardRecency, *, company: str, lang: str = "fr") -> str:
    """La phrase d'un constat de fraîcheur.

    Elle passe par le **statut** et rien d'autre : le texte ne relit jamais les
    dates, donc il ne peut pas contredire la politique qui les a jugées.
    """
    return claim_for_status(recency.status, company=company, lang=lang)


# ─── §30 — les types d'événement que le MVP expose ──────────────────────────────

#: Trois depuis R1, et pas une de plus. `CONTRACT_SIGNED`, `CONTRACT_STARTING` et
#: `CONTRACT_MODIFIED` sont réservés pour plus tard : les déclarer maintenant,
#: même vides, ferait croire qu'ils sont alimentés.
MVP_EVENT_TYPES: tuple[str, ...] = (
    "RECENT_AWARD",
    "RECENTLY_NOTIFIED_CONTRACT",
    "RECENTLY_PUBLISHED_AWARD",
)

_EVENT_TYPE_BY_STATUS: dict[str, str] = {
    "recent_award": "RECENT_AWARD",
    "recently_notified_contract": "RECENTLY_NOTIFIED_CONTRACT",
    "recently_published_award": "RECENTLY_PUBLISHED_AWARD",
    "award_date_unknown": "RECENTLY_PUBLISHED_AWARD",
    "invalid_award_date": "RECENTLY_PUBLISHED_AWARD",
}


def mvp_event_type(status: str) -> str | None:
    """Le type d'événement d'un statut, ou `None` s'il n'entre pas dans le feed.

    `aging_award` et `stale_award` sont datés et exacts : ils ne sont simplement
    pas des nouveautés (§10, §11). Leur donner un type d'événement MVP les ferait
    remonter dans « nouvelles opportunités », ce que §11 interdit.
    """
    if status not in CLAIM_TEMPLATES:
        raise ValueError(f"statut de fraîcheur inconnu : {status!r}")
    return _EVENT_TYPE_BY_STATUS.get(status)
