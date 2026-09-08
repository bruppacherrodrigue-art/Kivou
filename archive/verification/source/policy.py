"""La politique finale V0 (SPEC-009A §23, §24).

Elle est **séparée du modèle** et entièrement déterministe : c'est elle, et non
le LLM, qui décide ce qui atteint le feed. Le modèle ne fait que remplir un
formulaire ; la politique lit ce formulaire avec des exigences fixées d'avance.

Un candidat initialement `borderline` passe **exactement** la même politique
qu'un candidat initialement `show` (§24). Aucune règle plus souple n'existe pour
promouvoir : un signal promu doit être aussi bon qu'un signal conservé, sinon la
promotion ne serait qu'une façon détournée d'abaisser le seuil.

Pour le MVP, `downgrade`, `reject`, `insufficient_context`, l'échec de schéma,
la panne d'API et la langue non supportée sont tous cachés. Il n'y a pas de file
de revue humaine obligatoire.
"""

from __future__ import annotations

import dataclasses

from signals.verification.model import CommercialVerification
from signals.verification.validation import ValidationOutcome
from signals.verification.view import VerifierInput

FINAL_SHOW = "final_show"
HIDE = "hide"

#: Les valeurs admises pour chaque dimension, côté FINAL SHOW (§23).
ALLOWED = {
    "verdict": ("approve",),
    "factual_consistency": ("consistent",),
    "need_credibility": ("credible",),
    "icp_fit": ("strong", "plausible"),
    "actionability": ("actionable", "worth_investigating"),
    "specificity": ("specific", "acceptable"),
    "timing_status": ("current", "unknown"),
    "deliverable_overlap": ("none",),
    "winner_already_provides_need": ("no", "unknown"),
}


@dataclasses.dataclass(frozen=True)
class FinalDecision:
    """Ce que le feed montre, et pourquoi il ne montre pas le reste."""

    decision: str
    reason: str | None = None

    @property
    def shows(self) -> bool:
        return self.decision == FINAL_SHOW


def apply_final_policy(
    verification: CommercialVerification | None,
    view: VerifierInput,
    validation: ValidationOutcome | None = None,
    *,
    failure_kind: str | None = None,
) -> FinalDecision:
    """Applique §23 à la lettre. Tout ce qui n'est pas explicitement montrable est caché."""
    if not view.language_supported:
        return FinalDecision(HIDE, "unsupported_language")
    if failure_kind is not None:
        # §25 — une panne n'est pas un rejet du signal, mais elle ne le montre pas.
        return FinalDecision(HIDE, failure_kind)
    if verification is None:
        return FinalDecision(HIDE, "no_verification")
    if validation is not None and not validation.valid:
        return FinalDecision(HIDE, "validation_failure")

    for field, allowed in ALLOWED.items():
        value = getattr(verification, field)
        if value not in allowed:
            return FinalDecision(HIDE, f"{field}={value}")

    if verification.blockers:
        return FinalDecision(HIDE, f"blockers={list(verification.blockers)}")
    if not verification.supporting_fact_ids:
        return FinalDecision(HIDE, "no_supporting_facts")
    unknown = set(verification.supporting_fact_ids) | set(verification.limiting_fact_ids)
    if not unknown <= view.fact_ids:
        return FinalDecision(HIDE, "invalid_fact_reference")

    return FinalDecision(FINAL_SHOW)
