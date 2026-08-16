"""Contract Understanding — comprendre le contrat à partir du seul avis.

    ContractAward  (fait brut, jamais modifié)
            │
            ▼
    ContractUnderstandingEngine  ──▶  ContractUnderstanding
                                        Claim + Evidence

Trois frontières tenues par construction : un fait publié n'est pas une
interprétation ; une interprétation n'est pas un besoin commercial ; aucun
document de marché n'est lu — cela reviendra à SPEC-006.
"""

from signals.understanding.cpv import (
    CPV_SECTOR_RULES,
    CPV_TYPE_RULES,
    ContractType,
    Sector,
    contract_type_for_cpv,
    sector_for_cpv,
)
from signals.understanding.engine import (
    ENGINE_VERSION,
    ContractUnderstandingEngine,
    UnderstandingModel,
)
from signals.understanding.model import (
    Claim,
    Confidence,
    ContractGeography,
    ContractTiming,
    ContractUnderstanding,
    OperationalCharacteristic,
)
from signals.understanding.text import looks_like_html, plain_text

__all__ = [
    "CPV_SECTOR_RULES",
    "CPV_TYPE_RULES",
    "ENGINE_VERSION",
    "Claim",
    "Confidence",
    "ContractGeography",
    "ContractTiming",
    "ContractType",
    "ContractUnderstanding",
    "ContractUnderstandingEngine",
    "OperationalCharacteristic",
    "Sector",
    "UnderstandingModel",
    "contract_type_for_cpv",
    "looks_like_html",
    "plain_text",
    "sector_for_cpv",
]
