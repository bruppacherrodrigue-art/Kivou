"""La frontière fournisseur (SPEC-009A §7).

Le domaine commercial ne connaît que ce protocole. Aucun nom de fournisseur,
aucun transport HTTP, aucune clé d'API n'apparaît au-delà de l'adaptateur :
c'est ce qui permet d'en changer sans toucher à une seule règle métier, et de
faire tourner toute la suite de tests hors ligne.
"""

from __future__ import annotations

import dataclasses
from typing import Protocol

from signals.verification.model import CommercialVerification
from signals.verification.view import VerifierInput


@dataclasses.dataclass(frozen=True)
class ModelResponse:
    """Ce qu'un fournisseur rend : une vérification, ou une panne nommée.

    Jamais les deux, jamais aucun des deux. `failure_kind` renseigné signifie
    que le modèle n'a pas tranché — pas qu'il a rejeté (§25).
    """

    verification: CommercialVerification | None = None
    failure_kind: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    schema_retried: bool = False

    def __post_init__(self) -> None:
        if (self.verification is None) == (self.failure_kind is None):
            raise ValueError(
                "une réponse porte soit une vérification, soit une panne nommée — "
                "jamais les deux, jamais aucune"
            )


class CommercialSignalVerificationModel(Protocol):
    """Un vérificateur commercial, quel que soit le fournisseur derrière."""

    model_id: str
    provider: str

    def verify(self, view: VerifierInput) -> ModelResponse:
        """Une vue, une réponse. Ne lève pas pour une panne : il la nomme."""
        ...
