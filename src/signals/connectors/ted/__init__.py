"""Connecteur TED (Tenders Electronic Daily, Union européenne).

Chaîne : `client` (réseau) → `parser` (XML eForms → graphe TED) →
`mapping` (graphe TED → `PublicEvent` + `ContractAward`).

Le parser et le mapping sont testables hors ligne : seul `client` sort.
"""

from signals.connectors.ted.client import NoticeRef, TedClient
from signals.connectors.ted.errors import (
    TedError,
    TedHttpError,
    TedMappingError,
    TedParseError,
)
from signals.connectors.ted.mapping import MappingWarning, NoticeExtraction, map_notice
from signals.connectors.ted.parser import TedNotice, parse_notice

__all__ = [
    "MappingWarning",
    "NoticeExtraction",
    "NoticeRef",
    "TedClient",
    "TedError",
    "TedHttpError",
    "TedMappingError",
    "TedNotice",
    "TedParseError",
    "map_notice",
    "parse_notice",
]


def extract(xml: str | bytes, **kwargs: object) -> NoticeExtraction:
    """Raccourci XML → faits canoniques, sans réseau."""
    return map_notice(parse_notice(xml), **kwargs)  # type: ignore[arg-type]
