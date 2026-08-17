"""Compter honnêtement un pipeline à trois états.

Un système à trois états peut tricher d'une façon qu'un système binaire ne peut
pas : tout mettre en `review_required`. Sa précision devient parfaite, son
rappel automatique tombe à zéro, et il ne sert plus à rien. Les dénominateurs
d'ici sont écrits pour que ce cas soit visible plutôt que flatteur :

- la **précision** ne compte que les `auto_accepted` — un candidat en revue
  n'est pas une affirmation, il ne peut donc ni la sauver ni la salir ;
- le **rappel automatique** dit ce que le système affirme tout seul ;
- le **candidate recall** dit ce qu'il n'a pas perdu, revue comprise.

Les deux derniers doivent être lus ensemble : le premier seul récompense la
prudence, le second seul récompense l'imprudence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from signals.documents.consensus import ConsensusDecision

GATE_THRESHOLDS: dict[str, float] = {
    "auto_accepted_precision": 0.95,
    "candidate_recall": 0.85,
    # Le plancher qui interdit un système qui met tout en revue.
    "auto_accepted_recall": 0.60,
    "evidence_coverage": 1.0,
}
"""Les seuils de SPEC-006R4 §16. `high_confidence_false_auto_accepted` et
`excerpts_invented` ne sont pas des seuils : ils doivent valoir exactement 0."""


def _ratio(numerator: int, denominator: int) -> float | None:
    """Un dénominateur nul ne vaut pas 100 % — il ne vaut rien."""
    if denominator == 0:
        return None
    return numerator / denominator


@dataclass(frozen=True)
class PipelineMetrics:
    """Ce qu'un run a produit, dimension par dimension."""

    gold_execution_requirements: int

    auto_accepted: int
    true_auto_accepted: int
    false_auto_accepted: int
    high_confidence_false_auto_accepted: int

    review_required: int
    true_retained_for_review: int
    false_retained_for_review: int

    rejected: int
    true_requirements_lost: int
    technical_failures: int

    accepted_with_exact_evidence: int
    excerpts_invented: int

    auto_accepted_precision: float | None = None
    auto_accepted_recall: float | None = None
    candidate_recall: float | None = None
    evidence_coverage: float | None = None

    def as_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def score(
    *,
    decisions: Mapping[int, ConsensusDecision],
    gold: Mapping[int, bool],
    evidence_exact: Mapping[int, bool] | None = None,
    excerpts_invented: int = 0,
) -> PipelineMetrics:
    """Confronte les verdicts au gold. Un verdict sans gold est une erreur.

    `evidence_exact` dit, pour chaque candidat accepté, si son extrait a bien été
    retrouvé dans les blocs sources. Par défaut il vaut vrai : c'est au harnais
    de run de le renseigner à partir des blocs réels, pas au calcul de le supposer.
    """
    exact = evidence_exact or {}

    auto = [cid for cid, d in decisions.items() if d.outcome == "auto_accepted"]
    review = [cid for cid, d in decisions.items() if d.outcome == "review_required"]
    rejected = [cid for cid, d in decisions.items() if d.outcome == "rejected"]

    # `gold[cid]` et non `gold.get` : un candidat non étiqueté doit interrompre
    # la mesure, jamais compter comme un rejet correct.
    true_auto = sum(1 for cid in auto if gold[cid])
    true_review = sum(1 for cid in review if gold[cid])
    lost = sum(1 for cid in rejected if gold[cid])

    total_gold = sum(1 for cid in decisions if gold[cid])
    with_evidence = sum(1 for cid in auto if exact.get(cid, True))

    return PipelineMetrics(
        gold_execution_requirements=total_gold,
        auto_accepted=len(auto),
        true_auto_accepted=true_auto,
        false_auto_accepted=len(auto) - true_auto,
        high_confidence_false_auto_accepted=sum(
            1 for cid in auto if not gold[cid] and decisions[cid].confidence == "high"
        ),
        review_required=len(review),
        true_retained_for_review=true_review,
        false_retained_for_review=len(review) - true_review,
        rejected=len(rejected),
        true_requirements_lost=lost,
        technical_failures=sum(1 for d in decisions.values() if d.technical_failure),
        accepted_with_exact_evidence=with_evidence,
        excerpts_invented=excerpts_invented,
        auto_accepted_precision=_ratio(true_auto, len(auto)),
        auto_accepted_recall=_ratio(true_auto, total_gold),
        candidate_recall=_ratio(true_auto + true_review, total_gold),
        evidence_coverage=_ratio(with_evidence, len(auto)),
    )


@dataclass(frozen=True)
class GateResult:
    """Le verdict du gate, et le nom exact de chaque critère tombé."""

    passed: bool
    failures: tuple[str, ...] = field(default_factory=tuple)


def evaluate_gate(metrics: PipelineMetrics) -> GateResult:
    """Applique SPEC-006R4 §16. Une mesure absente est un échec, pas un succès."""
    failures: list[str] = []

    if metrics.high_confidence_false_auto_accepted != 0:
        failures.append("high_confidence_false_auto_accepted")
    if metrics.excerpts_invented != 0:
        failures.append("excerpts_invented")

    for name in ("auto_accepted_precision", "candidate_recall", "auto_accepted_recall"):
        value = getattr(metrics, name)
        if value is None or value < GATE_THRESHOLDS[name]:
            failures.append(name)

    # La couverture de preuve est exigée exacte, pas « suffisante ».
    coverage = metrics.evidence_coverage
    if metrics.auto_accepted and (coverage is None or coverage < 1.0):
        failures.append("evidence_coverage")

    return GateResult(passed=not failures, failures=tuple(failures))
