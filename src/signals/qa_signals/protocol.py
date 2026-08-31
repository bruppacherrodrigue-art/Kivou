"""Provider-neutral dependency-injection boundary for offline QA review."""

from __future__ import annotations

from typing import Protocol

from signals.card_intelligence.contracts import CardPresentationPayload, PresentationInput
from signals.qa_signals.contracts import QaDecision


class QaSignals(Protocol):
    """An injected reviewer that returns only a decision, never rewritten copy."""

    provider: str
    model_id: str
    policy_version: str

    def review(
        self,
        source: PresentationInput,
        payload: CardPresentationPayload,
    ) -> QaDecision: ...
