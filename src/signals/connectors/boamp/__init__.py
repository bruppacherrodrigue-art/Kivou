"""Connecteur BOAMP — avis d'attribution français."""

from signals.connectors.boamp.client import (
    BOAMP_DATASET_URL,
    PAGE_SIZE,
    AwardCursor,
    BoampClient,
    award_query,
)
from signals.connectors.boamp.errors import BoampError, BoampHttpError
from signals.connectors.boamp.parser import (
    AWARD_NATURES,
    BOAMP_ADAPTER_VERSION,
    BOAMP_SOURCE_COUNTRY,
    BOAMP_SOURCE_SYSTEM,
    BoampUnsupportedPayload,
    parse_award_notice,
    payload_kind,
    supported_payload,
)

__all__ = [
    "AWARD_NATURES",
    "BOAMP_ADAPTER_VERSION",
    "BOAMP_DATASET_URL",
    "BOAMP_SOURCE_COUNTRY",
    "BOAMP_SOURCE_SYSTEM",
    "PAGE_SIZE",
    "AwardCursor",
    "BoampClient",
    "BoampError",
    "BoampHttpError",
    "BoampUnsupportedPayload",
    "award_query",
    "parse_award_notice",
    "payload_kind",
    "supported_payload",
]
