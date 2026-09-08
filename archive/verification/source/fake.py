"""Un vérificateur déterministe pour les tests (SPEC-009A §7, §50).

Aucun test de la suite normale n'appelle Internet. Ce double implémente le même
protocole que l'adaptateur réel, ce qui permet de tester la vue, le validateur,
la politique et l'orchestration sans clé, sans réseau et sans coût.

Il ne simule pas l'intelligence du modèle : il rejoue des réponses écrites à la
main. C'est délibéré — un faux modèle « malin » masquerait les défauts que le
validateur doit attraper.
"""

from __future__ import annotations

import dataclasses

from signals.verification.model import CommercialVerification
from signals.verification.protocol import ModelResponse
from signals.verification.view import VerifierInput


def approving_verification(view: VerifierInput, **overrides: object) -> CommercialVerification:
    """Une réponse cohérente qui passe la politique — le point de départ des tests."""
    base: dict[str, object] = {
        "verdict": "approve",
        "factual_consistency": "consistent",
        "need_credibility": "credible",
        "deliverable_overlap": "none",
        "winner_already_provides_need": "no",
        "icp_fit": "strong",
        "actionability": "actionable",
        "specificity": "specific",
        "timing_status": "current",
        "blockers": (),
        "supporting_fact_ids": tuple(sorted(view.fact_ids))[:2],
        "limiting_fact_ids": (),
        "confidence": "high",
        "commercial_reason": "Un besoin de capacité pourrait devenir pertinent pour ce chantier.",
    }
    base.update(overrides)
    return CommercialVerification.model_validate(base)


@dataclasses.dataclass
class FakeVerificationModel:
    """Rejoue des réponses préprogrammées, par identifiant de candidat."""

    responses: dict[str, ModelResponse] = dataclasses.field(default_factory=dict)
    default: ModelResponse | None = None
    model_id: str = "fake/deterministic-verifier"
    provider: str = "fake"
    calls: int = 0
    seen: list[str] = dataclasses.field(default_factory=list)

    def verify(self, view: VerifierInput) -> ModelResponse:
        self.calls += 1
        self.seen.append(view.signal_candidate_id)
        response = self.responses.get(view.signal_candidate_id)
        if response is not None:
            return response
        if self.default is not None:
            return self.default
        return ModelResponse(
            verification=approving_verification(view),
            input_tokens=1000,
            output_tokens=200,
            cost_usd=0.0001,
            latency_ms=120.0,
        )
