"""AUTO DOCUMENT REQUIREMENTS DISABLED — la politique MVP issue de la clôture SPEC-006.

Le benchmark FR-DCE-FINAL (17 août 2026, run unique sur pipeline gelé) est
l'EVAL permanente de référence de SPEC-006 : 63 auto-acceptations dont 11
fausses, précision 82,54 % contre 95 % exigés — évidence 100 %, zéro extrait
inventé, rappel diagnostique 78,8 %. Le mécanisme déterministe tient ; c'est la
précision sémantique qui manque, et le protocole interdit toute optimisation
supplémentaire.

Décision superviseur : dans le chemin MVP, **aucun** résultat du classifieur
documentaire n'est exposé comme fait certain au client, ni utilisé comme fait
fort par le Need Graph. Kivou fonctionne avec le fallback

    Award + ContractUnderstanding → Need Graph (confiance réduite)

et, tant qu'aucune exigence documentaire validée par une future version
éligible n'existe :

    document_requirement = unavailable

Les DCE continuent d'être archivés pour exploitation ultérieure, et les briques
validées (acquisition, LogicalTextSpan, évidence multi-bloc, validation exacte,
taxonomie de pannes API, phase guard, corpus/golds/evals) restent en place pour
une reprise. Réactiver l'auto-acceptation exige de changer CE contrat — et de
battre l'EVAL de référence — jamais un oubli silencieux.
"""

from __future__ import annotations

AUTO_DOCUMENT_REQUIREMENTS_ENABLED = False
"""L'auto-acceptation des ExecutionRequirement dans le chemin MVP. Désactivée
par la clôture SPEC-006 ; sa remise à True est une décision superviseur, pas un
réglage."""

DOCUMENT_REQUIREMENT_UNAVAILABLE = "unavailable"


def document_requirement_status() -> str:
    """Le statut des exigences documentaires pour tout consommateur MVP.

    Toujours `unavailable` : c'est la valeur que le Need Graph doit porter tant
    qu'aucune exigence documentaire validée par une version éligible n'existe.
    """
    return DOCUMENT_REQUIREMENT_UNAVAILABLE
