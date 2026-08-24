"""Explicit, no-autostart wiring for the acquisition SHADOW connectivity smoke."""

from signals.acquisition_connectivity.config import load_connectivity_config
from signals.acquisition_connectivity.contracts import (
    AcquisitionConnectivityConfig,
    ConnectivityErrorCode,
    ConnectivityFailure,
    ShadowConnectivityDocument,
)

__all__ = [
    "AcquisitionConnectivityConfig",
    "ConnectivityErrorCode",
    "ConnectivityFailure",
    "ShadowConnectivityDocument",
    "load_connectivity_config",
]
