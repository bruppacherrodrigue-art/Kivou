"""Provider-neutral QA Signals protocol, called only by the offline service."""

from __future__ import annotations

from typing import Protocol

from signals.card_intelligence.contracts import CardPresentationPayload, PresentationInput
from signals.qa_signals.contracts import QaResponse


class QaSignalsModel(Protocol):
    model_id: str
    provider: str
    policy_version: str

    def review(
        self, source: PresentationInput, payload: CardPresentationPayload
    ) -> QaResponse: ...
