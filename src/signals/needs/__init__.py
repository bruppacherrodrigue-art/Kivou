"""Need Graph V0 — d'un contrat compris vers des besoins commerciaux plausibles.

SPEC-007. Mode courant : `metadata_fallback` — SPEC-006 a désactivé
l'auto-acceptation documentaire, aucune exigence expérimentale n'est consommée.
"""

from signals.needs.engine import NeedGraphEngine
from signals.needs.model import (
    ENGINE_VERSION,
    MAX_NEEDS,
    Externalisability,
    NeedCategory,
    NeedConfidence,
    NeedGraphResult,
    NeedTiming,
    ResourceNeed,
    SourceMode,
    SuppressedCandidate,
)

__all__ = [
    "ENGINE_VERSION",
    "MAX_NEEDS",
    "Externalisability",
    "NeedCategory",
    "NeedConfidence",
    "NeedGraphEngine",
    "NeedGraphResult",
    "NeedTiming",
    "ResourceNeed",
    "SourceMode",
    "SuppressedCandidate",
]
