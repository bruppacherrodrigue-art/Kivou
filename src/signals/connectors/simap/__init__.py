"""Connecteur SIMAP (marchés publics suisses).

Chaîne : `client` (réseau) → `parser` (JSON SIMAP → modèle SIMAP) →
`mapping` (modèle SIMAP → `PublicEvent` + `ContractAward`).

Le parser et le mapping sont testables hors ligne : seul `client` sort.
"""

from signals.connectors.simap.client import PublicationRef, SimapClient
from signals.connectors.simap.errors import (
    SimapAuthRequiredError,
    SimapError,
    SimapHttpError,
    SimapMappingError,
    SimapParseError,
)
from signals.connectors.simap.mapping import (
    MappingWarning,
    PublicationExtraction,
    map_publication,
)
from signals.connectors.simap.parser import SimapPublication, parse_publication
from signals.connectors.simap.tender import extract_tender

__all__ = [
    "MappingWarning",
    "PublicationExtraction",
    "PublicationRef",
    "SimapAuthRequiredError",
    "SimapClient",
    "SimapError",
    "SimapHttpError",
    "SimapMappingError",
    "SimapParseError",
    "SimapPublication",
    "extract_tender",
    "map_publication",
    "parse_publication",
]


def extract(payload: object, *, search_entry: dict | None = None, **kwargs: object):
    """Raccourci JSON → faits canoniques, sans réseau."""
    return map_publication(parse_publication(payload, search_entry=search_entry), **kwargs)  # type: ignore[arg-type]
