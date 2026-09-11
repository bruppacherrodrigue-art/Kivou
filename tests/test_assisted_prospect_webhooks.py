from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from test_assisted_prospect_preparation import NOW, Links, seed_directory, signal

from signals.campaigns.contracts import ResponseIngressCapability
from signals.campaigns.webhooks import InstantlyWebhookService, WebhookFingerprintKeyring
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.persistence.schema import (
    acquisition_contact_suppression,
    prospect_target,
    supplier_directory,
)
from signals.prospection_actions.preparation import ProspectPreparationService
from signals.prospection_actions.webhook import AssistedProspectWebhookProjector


def _service(engine) -> InstantlyWebhookService:
    fingerprints = WebhookFingerprintKeyring(
        current_key_version="v1", keys={"v1": b"fingerprint" * 4}
    )
    suppressions = SuppressionIdentityKeyring(
        current_key_version="v1", keys={"v1": b"suppression" * 4}
    )
    return InstantlyWebhookService(
        engine,
        provider_workspace_ref="workspace-prod",
        fingerprint_keyring=fingerprints,
        suppression_keyring=suppressions,
        response_ingress_capability=ResponseIngressCapability.NONE,
        assisted_prospect_ingress=AssistedProspectWebhookProjector(
            engine,
            provider_workspace_ref="workspace-prod",
            fingerprint_keyring=fingerprints,
            suppression_keyring=suppressions,
        ),
    )


def _sent_target(engine) -> dict[str, object]:
    seed_directory(engine, 2)
    ProspectPreparationService(engine, link_issuer=Links(), clock=lambda: NOW).prepare(
        signal(), cycle_ref="cycle-assisted"
    )
    with engine.begin() as connection:
        row = dict(connection.execute(sa.select(prospect_target)).mappings().first())
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.target_id == row["target_id"])
            .values(
                status="sent",
                delivery_status="sent",
                sent_at=NOW,
                provider_campaign_id="assisted-campaign-1",
                instantly_id="lead-1",
            )
        )
    return row


def _event(kind: str, email: str) -> dict[str, object]:
    return {
        "event_type": kind,
        "timestamp": (NOW + dt.timedelta(minutes=5)).isoformat(),
        "workspace": "workspace-prod",
        "campaign_id": "assisted-campaign-1",
        "campaign_name": "Kivou assisted",
        "lead_email": email,
        "email_id": f"email-{kind}",
    }


def test_assisted_bounce_invalidates_directory_email(migrated_sqlite_engine) -> None:
    row = _sent_target(migrated_sqlite_engine)

    result = _service(migrated_sqlite_engine).ingest(
        _event("email_bounced", str(row["email_address"])), received_at=NOW
    )

    assert not result.replayed
    with migrated_sqlite_engine.connect() as connection:
        target = connection.execute(sa.select(prospect_target)).mappings().first()
        directory = connection.execute(
            sa.select(supplier_directory).where(supplier_directory.c.siren == row["siren"])
        ).mappings().one()
    assert target["delivery_status"] == "bounced"
    assert directory["email_verification_status"] == "mx_failed"
    assert directory["reverification_reason"] == "instantly_bounce"


def test_assisted_unsubscribe_propagates_suppression(migrated_sqlite_engine) -> None:
    row = _sent_target(migrated_sqlite_engine)
    service = _service(migrated_sqlite_engine)

    first = service.ingest(
        _event("lead_unsubscribed", str(row["email_address"])), received_at=NOW
    )
    replay = service.ingest(
        _event("lead_unsubscribed", str(row["email_address"])), received_at=NOW
    )

    assert not first.replayed and replay.replayed
    with migrated_sqlite_engine.connect() as connection:
        target = connection.execute(sa.select(prospect_target)).mappings().first()
        count = connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_contact_suppression)
        )
    assert target["delivery_status"] == "unsubscribed"
    assert count == 1


def test_assisted_reply_is_classified_without_legacy_campaign(migrated_sqlite_engine) -> None:
    row = _sent_target(migrated_sqlite_engine)

    _service(migrated_sqlite_engine).ingest(
        _event("reply_received", str(row["email_address"])), received_at=NOW
    )

    with migrated_sqlite_engine.connect() as connection:
        target = connection.execute(sa.select(prospect_target)).mappings().first()
    assert target["delivery_status"] == "replied"
    assert target["reply_classification"] == "human_reply"
