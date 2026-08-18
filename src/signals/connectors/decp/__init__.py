"""Connecteur DECP — données essentielles de la commande publique française."""

from signals.connectors.decp.parser import (
    DECP_ADAPTER_VERSION,
    DECP_DATASET,
    DECP_DATE_SEMANTICS,
    DECP_LEGACY_DATASET,
    DECP_SOURCE_COUNTRY,
    DECP_SOURCE_SYSTEM,
    buyer_siret,
    parse_contract,
    winner_sirets,
)

__all__ = [
    "DECP_ADAPTER_VERSION",
    "DECP_DATASET",
    "DECP_DATE_SEMANTICS",
    "DECP_LEGACY_DATASET",
    "DECP_SOURCE_COUNTRY",
    "DECP_SOURCE_SYSTEM",
    "buyer_siret",
    "parse_contract",
    "winner_sirets",
]
