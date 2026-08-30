"""Provider-neutral offline boundaries. No live provider is configured here."""

from __future__ import annotations

from typing import Protocol

from signals.card_intelligence.contracts import GenerationResponse, PresentationInput


class CardIntelligenceModel(Protocol):
    model_id: str
    provider: str
    prompt_version: str

    def generate(self, source: PresentationInput, *, attempt: int) -> GenerationResponse: ...
