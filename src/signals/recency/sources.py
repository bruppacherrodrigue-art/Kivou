"""Ce que chaque portail publie comme date, et ce qu'il n'en publie pas.

SPEC-009D a mesuré une couverture de `award_date` allant de 100 % à zéro selon
la source. Cette variation n'est pas un défaut d'ingestion : c'est une
caractéristique des portails, et le produit doit la porter telle quelle plutôt
que de la lisser (§16).

Le registre sert deux usages, et un seul suffirait à le justifier :

* dire à un lecteur ce qu'une absence signifie — sur DECP, `award_date` vide
  n'est pas une lacune d'un avis, c'est l'état de toute la source ;
* nommer les **pièges**. `cac:TenderResult/cbc:AwardDate` du BOAMP porte le nom
  exact de ce qu'on cherche et vaut `2000-01-01` dans 96 % des cas. Un champ
  piégeux qui n'est écrit nulle part se remappe tôt ou tard.

Les couvertures citées sont mesurées, pas estimées, et chaque ligne dit sur
quel échantillon.
"""

from __future__ import annotations

from typing import Any

SOURCE_SEMANTICS_VERSION = "source-date-semantics-v0.1"

#: `published`           la source date la décision sur la quasi-totalité de ses avis
#: `sometimes_published` elle la date parfois — l'absence est un fait de l'avis
#: `not_published`       elle ne la date jamais — l'absence est un fait de la source
SOURCE_DATE_SEMANTICS: dict[str, dict[str, Any]] = {
    "simap": {
        "award_date_status": "published",
        "award_date_field": "publication.award_decision_date",
        "award_date_semantics": "date de la décision d'adjudication publiée dans l'avis",
        "publication_date_field": "publication.publication_date",
        "notification_date_field": None,
        "measured_award_date_coverage": 100.0,
        "measured_on": "SPEC-009D — 76 SHOW naturels SIMAP sur corpus frais 2026-08",
        "other_dates": {},
        "note": (
            "meilleur cas de référence pour un signal « vient de remporter » : "
            "délai de publication médian de 8 jours sur le banc SPEC-009D"
        ),
    },
    "ted": {
        "award_date_status": "sometimes_published",
        "award_date_field": "efac:SettledContract/cbc:AwardDate",
        "award_date_semantics": "BT-1451, décision de choix du titulaire",
        "publication_date_field": "cbc:IssueDate (avis)",
        "notification_date_field": None,
        "measured_award_date_coverage": 38.2,
        "measured_on": "SPEC-009D — 34 SHOW naturels TED, 13 datés",
        "other_dates": {
            "efac:SettledContract/cbc:IssueDate": {
                "official_semantics": "BT-145, conclusion du contrat",
                "canonical_field": "contract_signature_date",
                "can_represent_award_date": "AMBIGUOUS",
                "reason": "la conclusion suit la décision, parfois de plusieurs semaines (§7)",
            },
        },
        "note": (
            "une date absente ne rétrograde que l'avis concerné : les avis TED "
            "datés restent éligibles au statut `recent_award` (§18)"
        ),
    },
    "boamp": {
        "award_date_status": "sometimes_published",
        "award_date_field": "efac:SettledContract/cbc:AwardDate",
        "award_date_semantics": "BT-1451, décision de choix du titulaire — même norme que TED",
        "publication_date_field": "dateparution",
        "notification_date_field": None,
        "measured_award_date_coverage": 27.6,
        "measured_on": "SPEC-009E — 923 award-lots issus de 329 avis eForms, parution 2026-06→08",
        "other_dates": {
            "efac:SettledContract/cbc:IssueDate": {
                "official_semantics": "BT-145, conclusion du contrat",
                "canonical_field": "contract_signature_date",
                "can_represent_award_date": "AMBIGUOUS",
                "reason": "conclusion et décision sont deux actes distincts (§7)",
            },
            "cac:TenderResult/cbc:AwardDate": {
                "official_semantics": "champ UBL homonyme, non renseigné par le BOAMP",
                "canonical_field": "(jamais mappé)",
                "can_represent_award_date": "NO",
                "reason": (
                    "présent sur 100 % des avis eForms et rempli d'une sentinelle : "
                    "2000-01-01 sur 297 avis et 1970-01-01 sur 19, soit 96,0 % des 329 mesurés"
                ),
            },
        },
        "note": (
            "16,5 % des avis d'attribution du BOAMP ne sont pas en eForms "
            "(FNSimple, MAPA) et enferment leurs faits dans du texte libre : "
            "ils sont écartés, pas devinés"
        ),
    },
    "decp": {
        "award_date_status": "not_published",
        "award_date_field": None,
        "award_date_semantics": (
            "aucune date de décision dans le schéma de l'arrêté du 22 décembre 2022"
        ),
        "publication_date_field": "datepublicationdonnees",
        "notification_date_field": "datenotification",
        "measured_award_date_coverage": 0.0,
        "measured_on": (
            "SPEC-009E R1 — schéma et échantillon de decp-2022-marches-valides, "
            "689 062 marchés, 1 000 notifications du 2026-05-20 au 2026-08-18"
        ),
        "other_dates": {
            "datenotification": {
                "official_semantics": "« Date de notification »",
                "canonical_field": "contract_notification_date",
                "can_represent_award_date": "NO",
                "reason": (
                    "la notification rend le marché exécutoire pour le titulaire ; "
                    "elle suit la décision et ne la date pas (R1 §2)"
                ),
            },
            "datepublicationdonnees": {
                "official_semantics": (
                    "« Date de publication des données essentielles du marché public »"
                ),
                "canonical_field": "PublicEvent.published_at",
                "can_represent_award_date": "NO",
                "reason": "date de mise en ligne de la donnée ouverte",
            },
        },
        "note": (
            "SPEC-009E avait mesuré `decp-v3-marches-valides`, le jeu HÉRITÉ de "
            "l'arrêté du 22 mars 2019, figé à une notification du 2024-02-08 — d'où "
            "sa conclusion erronée « DECP ne peut pas dater une victoire récente ». "
            "Le jeu courant est mis à jour quotidiennement. Il reste vrai qu'il ne "
            "publie aucune date de DÉCISION : il ne date que la notification."
        ),
    },
}


def award_date_capability(source: str) -> str:
    """Ce que la source publie comme date de décision — jamais une supposition."""
    try:
        return SOURCE_DATE_SEMANTICS[source]["award_date_status"]
    except KeyError:
        raise ValueError(f"source inconnue du registre : {source!r}") from None


def source_date_field(source: str, canonical_field: str) -> str | None:
    """Le champ source qui alimente un champ canonique, ou `None` s'il n'existe pas."""
    spec = SOURCE_DATE_SEMANTICS.get(source)
    if spec is None:
        raise ValueError(f"source inconnue du registre : {source!r}")
    if canonical_field == "award_date":
        return spec["award_date_field"]
    if canonical_field == "publication_date":
        return spec["publication_date_field"]
    for field, description in spec["other_dates"].items():
        if description["canonical_field"] == canonical_field:
            return field
    return None
