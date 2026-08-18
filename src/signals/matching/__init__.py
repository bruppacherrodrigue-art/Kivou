"""ICP Matching & Signal Score — relier un signal à ce qu'un client vend.

SPEC-008. Frontière d'architecture non négociable : ce package est le **produit
client**. La découverte de fournisseurs, les contacts et les campagnes
appartiennent à l'Acquisition Engine, qui n'est jamais importé ici.
"""

from signals.matching.engine import MatchingEngine
from signals.matching.icp import (
    MATCH_POLICY_VERSION,
    MAX_SIGNAL_AGE_DAYS,
    GeographyBasis,
    GeographyPolicy,
    TargetICP,
    Territory,
    UnknownValuePolicy,
    ValueThreshold,
)
from signals.matching.model import (
    SCORE_POLICY_VERSION,
    HardFilterResult,
    MatchDecision,
    ScoreBand,
    ScoredSignalMatch,
    SignalConfidence,
    SignalScoreComponent,
)
from signals.matching.reference import (
    CONSTRUCTION_INPUTS_ICP,
    REFERENCE_ICP_LIBRARY_VERSION,
    REFERENCE_ICPS,
    WEDGE_ICP_LIBRARY_VERSION,
)

__all__ = [
    "CONSTRUCTION_INPUTS_ICP",
    "MATCH_POLICY_VERSION",
    "MAX_SIGNAL_AGE_DAYS",
    "REFERENCE_ICPS",
    "REFERENCE_ICP_LIBRARY_VERSION",
    "SCORE_POLICY_VERSION",
    "WEDGE_ICP_LIBRARY_VERSION",
    "GeographyBasis",
    "GeographyPolicy",
    "HardFilterResult",
    "MatchDecision",
    "MatchingEngine",
    "ScoreBand",
    "ScoredSignalMatch",
    "SignalConfidence",
    "SignalScoreComponent",
    "TargetICP",
    "Territory",
    "UnknownValuePolicy",
    "ValueThreshold",
]
