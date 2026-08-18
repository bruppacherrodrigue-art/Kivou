"""Les libellés client — et ce qu'ils ne disent surtout pas.

La phrase d'événement n'est PAS écrite ici : elle vient de `recency.claim`, qui
reste la seule autorité sur ce que Kivou a le droit d'affirmer d'une date. Ce
module ne couvre que ce que la SPEC-012 ajoute : le nom d'une famille de besoin,
la raison temporelle (`why_now`), et le libellé d'adéquation.

    Pourquoi une table et pas une f-string dans la route
    ───────────────────────────────────────────────────
    Une formulation dispersée dans les routes est une formulation qu'aucun test
    ne surveille. SPEC-009D a montré ce que ça coûte : le feed disait « vient de
    gagner » sur une attribution de trois mois sans qu'aucun test ne s'en
    aperçoive, parce qu'aucun test ne portait sur la phrase.

Toutes les entrées existent en `fr` et en `en`. Une langue absente lève ; une
langue inconnue lève. Rien n'est traduit à la volée, et aucune plateforme de
traduction n'est introduite.
"""

from __future__ import annotations

from signals.recency.claim import LANGUAGES

COPY_VERSION = "customer-feed-copy-v0.1"

#: §10 — la raison est TEMPORELLE. Elle explique l'événement public, jamais une
#: intention d'achat. Aucune de ces phrases ne dit que l'entreprise achète.
WHY_NOW: dict[str, dict[str, str]] = {
    "recent_award": {
        "fr": "Décision d'attribution récente.",
        "en": "Recent award decision.",
    },
    # CLOSEOUT §1 — la phrase ne dit QUE ce que le statut garantit. Les horloges
    # étant indépendantes depuis `award-recency-v0.3`, une notification récente
    # coexiste très bien avec une date de décision connue mais ancienne : dire
    # « la date de décision n'est pas publiée » aurait été faux dans ce cas, qui
    # est justement le plus fréquent côté DECP.
    "recently_notified_contract": {
        "fr": "Notification récente du marché.",
        "en": "Recent contract notification.",
    },
    "recently_published_award": {
        "fr": "Publication récente d'une attribution dont la date de décision est inconnue.",
        "en": "Recent publication of an award whose decision date is unknown.",
    },
    "aging_award": {
        "fr": "Attribution datée, déjà ancienne.",
        "en": "Dated award, already some time ago.",
    },
    "stale_award": {
        "fr": "Attribution ancienne, conservée pour l'historique.",
        "en": "Old award, kept for history.",
    },
    "award_date_unknown": {
        "fr": "Aucune date exploitable n'est publiée pour cet avis.",
        "en": "No usable date is published for this notice.",
    },
    "invalid_award_date": {
        "fr": "La date publiée par la source est incohérente.",
        "en": "The date published by the source is inconsistent.",
    },
}

#: Les sept familles de `needs.model.NeedCategory`. Le code machine reste
#: neutre ; seul le libellé est traduit (§21).
NEED_LABELS: dict[str, dict[str, str]] = {
    "workforce_capacity": {"fr": "Capacité de main-d'œuvre", "en": "Workforce capacity"},
    "equipment_or_rental": {"fr": "Matériel ou location", "en": "Equipment or rental"},
    "materials_or_components": {"fr": "Matériaux ou composants", "en": "Materials or components"},
    "logistics_and_transport": {"fr": "Logistique et transport", "en": "Logistics and transport"},
    "specialist_subcontracting": {
        "fr": "Sous-traitance spécialisée",
        "en": "Specialist subcontracting",
    },
    "safety_and_ppe": {"fr": "Sécurité et EPI", "en": "Safety and PPE"},
    "waste_and_environment": {"fr": "Déchets et environnement", "en": "Waste and environment"},
}

NEED_TIMING_LABELS: dict[str, dict[str, str]] = {
    "immediate": {"fr": "immédiat", "en": "immediate"},
    "near_term": {"fr": "à court terme", "en": "near term"},
    "medium_term": {"fr": "à moyen terme", "en": "medium term"},
    "recurring": {"fr": "récurrent", "en": "recurring"},
    "unknown": {"fr": "non déterminé", "en": "undetermined"},
}

#: §12 — l'adéquation s'explique, elle ne se note pas. Aucun de ces libellés ne
#: contient de nombre : un score nu n'explique rien et se lit comme une promesse.
FIT_LABELS: dict[str, dict[str, str]] = {
    "matched_needs": {
        "fr": "Correspond aux besoins que vous ciblez",
        "en": "Matches the needs you target",
    },
    "territory_only": {
        "fr": "Situé dans un territoire que vous ciblez",
        "en": "Located in a territory you target",
    },
    "targeted_profile": {
        "fr": "Retenu par votre profil de ciblage",
        "en": "Selected by your targeting profile",
    },
}

FIT_REASONS: dict[str, dict[str, str]] = {
    "need": {"fr": "Besoin plausible ciblé : {value}", "en": "Targeted plausible need: {value}"},
    "territory": {"fr": "Marché exécuté en {value}", "en": "Contract performed in {value}"},
    "source_country": {"fr": "Marché publié en {value}", "en": "Contract published in {value}"},
}

#: CLOSEOUT §1 — le complément facultatif. Il n'est ajouté QUE si l'horloge
#: d'attribution le justifie vraiment : `award_clock.status` est inspecté, jamais
#: déduit du statut mis en avant. Aucune de ces phrases n'affirme l'absence d'une
#: date qui existe.
AWARD_CLOCK_NOTE: dict[str, dict[str, str]] = {
    "unknown": {
        "fr": "La date de décision d'attribution n'est pas publiée par la source.",
        "en": "The award decision date is not published by the source.",
    },
    "invalid": {
        "fr": "La date de décision publiée par la source est incohérente.",
        "en": "The award decision date published by the source is inconsistent.",
    },
    "recent": {
        "fr": "La décision d'attribution est récente.",
        "en": "The award decision is recent.",
    },
    "aging": {
        "fr": "La décision d'attribution est déjà datée.",
        "en": "The award decision already dates back some time.",
    },
    "stale": {
        "fr": "La décision d'attribution est ancienne.",
        "en": "The award decision is old.",
    },
}

#: §14 — le fait que chaque groupe de preuves étaye.
FACT_LABELS: dict[str, dict[str, str]] = {
    "winner": {"fr": "Attributaire", "en": "Awardee"},
    "amount": {"fr": "Montant", "en": "Amount"},
    "award_date": {"fr": "Date d'attribution", "en": "Award date"},
    "contract_notification_date": {
        "fr": "Date de notification",
        "en": "Contract notification date",
    },
    "procedure_buyers": {"fr": "Acheteur public", "en": "Public buyer"},
    "published_object": {"fr": "Objet publié", "en": "Published object"},
    "cpv": {"fr": "Code CPV", "en": "CPV code"},
    "lot": {"fr": "Lot", "en": "Lot"},
    "source_notice": {"fr": "Avis source", "en": "Source notice"},
}

#: §13, §27.9 — la mise en garde qui empêche une preuve d'être lue comme la
#: démonstration d'un besoin. Les preuves rattachées à une hypothèse étayent les
#: FAITS PUBLIÉS qui l'ont produite, jamais l'hypothèse elle-même.
ANALYSIS_INPUT_NOTE: dict[str, str] = {
    "fr": (
        "Ces sources prouvent les faits publiés utilisés par l'analyse. "
        "Elles ne démontrent pas que le besoin existera."
    ),
    "en": (
        "These sources prove the published facts used by the analysis. "
        "They do not demonstrate that the need will exist."
    ),
}

#: Le rappel porté par le bloc d'hypothèses lui-même.
PLAUSIBLE_NEEDS_NOTE: dict[str, str] = {
    "fr": "Hypothèses commerciales déduites des faits publiés — jamais un besoin confirmé.",
    "en": "Commercial hypotheses inferred from published facts — never a confirmed need.",
}

#: Le résumé de contrat est une LECTURE du moteur, pas une citation de la source.
ANALYSIS_SUMMARY_NOTE: dict[str, str] = {
    "fr": "Lecture automatique de l'avis — à vérifier sur la source.",
    "en": "Automated reading of the notice — verify against the source.",
}


def check_language(lang: str) -> str:
    """Refuse une langue non prise en charge plutôt que de retomber en anglais."""
    if lang not in LANGUAGES:
        raise ValueError(f"langue non prise en charge : {lang!r} (attendu {LANGUAGES})")
    return lang


def translate(table: dict[str, dict[str, str]], key: str, lang: str) -> str | None:
    """Le libellé d'une clé, ou `None` si la clé n'est pas au catalogue.

    `None` plutôt qu'une invention : un besoin dont la famille n'a pas de nom
    client doit se voir, pas se maquiller.
    """
    check_language(lang)
    entry = table.get(key)
    return None if entry is None else entry[lang]
