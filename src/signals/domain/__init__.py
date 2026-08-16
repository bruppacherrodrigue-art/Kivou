"""Modèle canonique des faits publics d'adjudication.

Faits uniquement. Aucun besoin commercial inféré, aucun score, aucun matching ICP
ne doit apparaître ici : le moteur de signaux consommera ce modèle, il ne s'y
mélangera pas.
"""

from signals.domain.awards import (
    Awardee,
    AwardeeParty,
    AwardeeRole,
    ContractAward,
    LotRef,
    SourceIdentity,
    WinnerStatus,
)
from signals.domain.events import (
    EventRef,
    EventType,
    Provenance,
    PublicationInstant,
    PublicEvent,
    SourceSystem,
)
from signals.domain.values import (
    CanonicalModel,
    CpvCode,
    Duration,
    DurationUnit,
    Location,
    Money,
    OrganizationIdentifier,
    OrganizationRef,
    SubdivisionScheme,
    VatCategory,
)

__all__ = [
    "Awardee",
    "AwardeeParty",
    "AwardeeRole",
    "CanonicalModel",
    "ContractAward",
    "CpvCode",
    "Duration",
    "DurationUnit",
    "EventRef",
    "EventType",
    "Location",
    "LotRef",
    "Money",
    "OrganizationIdentifier",
    "OrganizationRef",
    "Provenance",
    "PublicEvent",
    "PublicationInstant",
    "SourceIdentity",
    "SourceSystem",
    "SubdivisionScheme",
    "VatCategory",
    "WinnerStatus",
]
