"""Provider-free executable root for ASSISTED catalog preparation."""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Callable, Mapping

from signals.acquisition_runtime.catalog_selection import select_assisted_catalog_signals
from signals.acquisition_runtime.config import load_runtime_config
from signals.acquisition_runtime.contracts import (
    RuntimeExecutionConfigurationError,
    RuntimeExecutionMode,
)
from signals.acquisition_runtime.links import load_runtime_link_config
from signals.conversion.token import AttributionTokenKeyring
from signals.persistence.database import create_database_engine
from signals.prospection_actions.attribution import (
    CANONICAL_PRODUCT_ORIGIN,
    AttributionProspectLinkIssuer,
)
from signals.prospection_actions.catalog_preparation import (
    AssistedCatalogPreparationService,
    CatalogPreparationResult,
)


def execute_assisted_catalog_preparation(
    *,
    environ: Mapping[str, str] | None = None,
    clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
) -> CatalogPreparationResult:
    source = os.environ if environ is None else environ
    runtime_config = load_runtime_config(source)
    selection = runtime_config.deployment.selection
    if (
        runtime_config.environment != "PRODUCTION"
        or runtime_config.deployment.mode is not RuntimeExecutionMode.ASSISTED
        or selection is None
        or selection.mode != "catalog"
        or selection.region is None
        or selection.email_source != "site"
    ):
        raise RuntimeExecutionConfigurationError("CATALOG_MODE_NOT_CONFIGURED")
    disabled_file = source.get(
        "KIVOU_ACQUISITION_DISABLED_FILE", "/etc/kivou/acquisition.disabled"
    )
    if os.path.exists(disabled_file):
        raise RuntimeExecutionConfigurationError("ACQUISITION_DISABLED")
    links = load_runtime_link_config(source)
    if links.public_app_url != CANONICAL_PRODUCT_ORIGIN:
        raise RuntimeExecutionConfigurationError("PRODUCT_ATTRIBUTION_ORIGIN_NOT_CANONICAL")
    observed_at = clock()
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise RuntimeExecutionConfigurationError("CLOCK_NOT_CONFIGURED")
    engine = create_database_engine()
    try:
        inventory = select_assisted_catalog_signals(
            engine,
            country=runtime_config.deployment.qa_scope.country,
            region=selection.region,
            observed_at=observed_at,
        )
        return AssistedCatalogPreparationService(
            engine,
            link_issuer=AttributionProspectLinkIssuer(
                public_site_url=CANONICAL_PRODUCT_ORIGIN,
                keyring=AttributionTokenKeyring(
                    current_key_version=links.attribution_key_version,
                    keys={links.attribution_key_version: links.attribution_hmac_key},
                ),
            ),
            clock=lambda: observed_at,
        ).prepare(inventory)
    finally:
        engine.dispose()


__all__ = ["execute_assisted_catalog_preparation"]
