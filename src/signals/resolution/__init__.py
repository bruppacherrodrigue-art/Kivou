"""Winner Resolution — de la mention publiée à l'entité juridique.

    OrganizationRef  (fait source, jamais modifié)
            │
            ▼
      CompanyResolver  ──▶  CompanyResolution  ──▶  Company ?
                              statut + trace

Le moteur est déterministe et fondé sur des preuves. Aucun LLM ne décide qu'une
entreprise en est une autre, et un nom approché ne fusionne jamais rien : il
appelle un humain.
"""

from signals.resolution.identifiers import (
    ClassifiedIdentifier,
    IdentifierStrength,
    classify,
)
from signals.resolution.model import (
    CompanyCandidate,
    CompanyResolution,
    MatchMethod,
    PartyResolution,
    ResolutionBasis,
    ResolutionStatus,
)
from signals.resolution.registries import (
    RegistryAuthRequiredError,
    RegistryError,
    VatCheck,
    ViesClient,
    ZefixClient,
    ZefixCredentials,
)
from signals.resolution.resolver import CANDIDATE_SIMILARITY, CompanyResolver, ResolverStats

__all__ = [
    "CANDIDATE_SIMILARITY",
    "ClassifiedIdentifier",
    "CompanyCandidate",
    "CompanyResolution",
    "CompanyResolver",
    "IdentifierStrength",
    "MatchMethod",
    "PartyResolution",
    "RegistryAuthRequiredError",
    "RegistryError",
    "ResolutionBasis",
    "ResolutionStatus",
    "ResolverStats",
    "VatCheck",
    "ViesClient",
    "ZefixClient",
    "ZefixCredentials",
    "classify",
]
