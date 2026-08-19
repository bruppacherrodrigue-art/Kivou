"""Connecteur DECP — données essentielles de la commande publique française."""

from signals.connectors.decp.client import (
    DECP_DATASET_URL,
    DECP_RESULT_CEILING,
    PAGE_SIZE,
    DecpClient,
    DecpCursor,
    decp_query,
)
from signals.connectors.decp.errors import DecpError, DecpHttpError, DecpWindowLimitError
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
    "DECP_DATASET_URL",
    "DECP_DATE_SEMANTICS",
    "DECP_LEGACY_DATASET",
    "DECP_RESULT_CEILING",
    "DECP_SOURCE_COUNTRY",
    "DECP_SOURCE_SYSTEM",
    "PAGE_SIZE",
    "DecpClient",
    "DecpCursor",
    "DecpError",
    "DecpHttpError",
    "DecpWindowLimitError",
    "buyer_siret",
    "decp_query",
    "parse_contract",
    "winner_sirets",
]
