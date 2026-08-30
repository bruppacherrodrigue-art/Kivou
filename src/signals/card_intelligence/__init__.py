"""Pre-generated customer copy for award and commercial-signal cards.

This is a production boundary, but it does not configure a model provider.
Callers must inject Card Intelligence and QA Signals implementations into the
offline service. HTTP GET handlers only read published database artifacts.

The experimental :mod:`signals.verification` package deliberately remains
isolated: it failed its own development gates. This package reuses the proven
architecture (closed contracts, evidence-bound claims, deterministic checks
and fail-closed publication), not that experimental model or policy.
"""

from signals.card_intelligence.contracts import (
    ArtifactKind,
    CardPresentationPayload,
    ClaimKind,
    PresentationClaim,
    PresentationInput,
    PresentationVariant,
    QaStatus,
    SourceFacts,
)

__all__ = [
    "ArtifactKind",
    "CardPresentationPayload",
    "ClaimKind",
    "PresentationClaim",
    "PresentationInput",
    "PresentationVariant",
    "QaStatus",
    "SourceFacts",
]
