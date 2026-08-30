"""Provider-neutral dependency-injection boundary for offline generation."""

from __future__ import annotations

from typing import Protocol

from signals.card_intelligence.contracts import GenerationResponse, PresentationInput


class CardGenerator(Protocol):
    """An injected generator; this protocol does not configure an implementation."""

    provider: str
    model_id: str
    prompt_version: str

    def generate(self, source: PresentationInput, *, attempt: int) -> GenerationResponse: ...
