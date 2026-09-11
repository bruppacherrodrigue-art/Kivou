"""Production-only composition for bounded Founder prospection mutations."""

from __future__ import annotations

import httpx
from sqlalchemy.engine import Engine

from signals.acquisition_connectivity.config import load_connectivity_config
from signals.acquisition_runtime.execution import load_runtime_link_config
from signals.campaigns.instantly import HttpInstantlyProvider
from signals.campaigns.runtime_webhook import load_instantly_webhook_runtime_config
from signals.contact_discovery.deliverability import EmailMxVerifier
from signals.conversion.token import AttributionTokenKeyring
from signals.prospection_actions.attribution import AttributionProspectLinkIssuer
from signals.prospection_actions.delivery import AssistedInstantlyDelivery
from signals.prospection_actions.service import ProspectionActions
from signals.prospection_actions.suppression import EmailSuppressionChecker


def build_prospection_actions(
    engine: Engine,
    *,
    client: httpx.Client,
) -> ProspectionActions:
    connectivity = load_connectivity_config()
    if connectivity.environment != "PRODUCTION":
        raise RuntimeError("les actions Founder ne s'exécutent qu'en production")
    webhook = load_instantly_webhook_runtime_config(required=True)
    assert webhook is not None
    links = load_runtime_link_config()
    mailbox = connectivity.deployment.mailboxes[0]
    provider = HttpInstantlyProvider(
        api_key=connectivity.instantly_api_key.get_secret_value(),
        client=client,
    )
    return ProspectionActions(
        engine,
        email_verifier=EmailMxVerifier(),
        link_issuer=AttributionProspectLinkIssuer(
            public_site_url=links.public_app_url,
            keyring=AttributionTokenKeyring(
                current_key_version=links.attribution_key_version,
                keys={links.attribution_key_version: links.attribution_hmac_key},
            ),
        ),
        suppression_checker=EmailSuppressionChecker(webhook.suppression_keyring),
        delivery_provider=AssistedInstantlyDelivery(
            provider=provider,
            provider_account_id=str(mailbox.provider_account_id),
        ),
    )


__all__ = ["build_prospection_actions"]
