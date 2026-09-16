from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from test_assisted_prospect_preparation import NOW, Links, seed_directory, signal

from signals.campaigns.contracts import ResponseIngressCapability
from signals.campaigns.webhooks import InstantlyWebhookService, WebhookFingerprintKeyring
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.persistence.schema import (
    acquisition_contact_suppression,
    prospect_delivery_event,
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


def _accepted_target(engine) -> dict[str, object]:
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
                delivery_status="not_sent",
                instantly_accepted_at=NOW,
                provider_campaign_id="assisted-campaign-1",
                instantly_id="lead-1",
            )
        )
    return row


def _event(
    kind: str,
    email: str,
    *,
    occurred_at: dt.datetime = NOW + dt.timedelta(minutes=5),
    email_id: str | None = None,
) -> dict[str, object]:
    return {
        "event_type": kind,
        "timestamp": occurred_at.isoformat(),
        "workspace": "workspace-prod",
        "campaign_id": "assisted-campaign-1",
        "campaign_name": "Kivou assisted",
        "lead_email": email,
        "email_id": email_id or f"email-{kind}",
    }


def _ingest(
    engine,
    kind: str,
    email: str,
    *,
    occurred_at: dt.datetime = NOW + dt.timedelta(minutes=5),
    email_id: str | None = None,
):
    return _service(engine).ingest(
        _event(kind, email, occurred_at=occurred_at, email_id=email_id), received_at=NOW
    )


def _target_row(engine) -> dict[str, object]:
    with engine.connect() as connection:
        return dict(connection.execute(sa.select(prospect_target)).mappings().one())


def _utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value.astimezone(dt.UTC)


def test_assisted_bounce_invalidates_directory_email(migrated_sqlite_engine) -> None:
    row = _accepted_target(migrated_sqlite_engine)

    result = _service(migrated_sqlite_engine).ingest(
        _event("email_bounced", str(row["email_address"])), received_at=NOW
    )

    assert not result.replayed
    with migrated_sqlite_engine.connect() as connection:
        target = connection.execute(sa.select(prospect_target)).mappings().first()
        directory = (
            connection.execute(
                sa.select(supplier_directory).where(supplier_directory.c.siren == row["siren"])
            )
            .mappings()
            .one()
        )
    assert target["delivery_status"] == "bounced"
    assert directory["email_verification_status"] == "mx_failed"
    assert directory["reverification_reason"] == "instantly_bounce"


def test_assisted_unsubscribe_propagates_suppression(migrated_sqlite_engine) -> None:
    row = _accepted_target(migrated_sqlite_engine)
    service = _service(migrated_sqlite_engine)

    first = service.ingest(_event("lead_unsubscribed", str(row["email_address"])), received_at=NOW)
    replay = service.ingest(_event("lead_unsubscribed", str(row["email_address"])), received_at=NOW)

    assert not first.replayed and replay.replayed
    with migrated_sqlite_engine.connect() as connection:
        target = connection.execute(sa.select(prospect_target)).mappings().first()
        count = connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_contact_suppression)
        )
    assert target["delivery_status"] == "unsubscribed"
    assert count == 1


def test_assisted_reply_is_classified_without_legacy_campaign(migrated_sqlite_engine) -> None:
    row = _accepted_target(migrated_sqlite_engine)

    _service(migrated_sqlite_engine).ingest(
        _event("reply_received", str(row["email_address"])), received_at=NOW
    )

    with migrated_sqlite_engine.connect() as connection:
        target = connection.execute(sa.select(prospect_target)).mappings().first()
    assert target["delivery_status"] == "replied"
    assert target["reply_classification"] == "human_reply"


def test_email_sent_webhook_sets_delivery_without_changing_acceptance(
    migrated_sqlite_engine,
) -> None:
    row = _accepted_target(migrated_sqlite_engine)

    _ingest(migrated_sqlite_engine, "email_sent", str(row["email_address"]))

    target = _target_row(migrated_sqlite_engine)
    assert target["status"] == "sent"
    assert _utc(target["instantly_accepted_at"]) == NOW
    assert target["delivery_status"] == "delivered"
    assert _utc(target["sent_at"]) == NOW + dt.timedelta(minutes=5)


def test_open_without_prior_sent_still_proves_delivery(migrated_sqlite_engine) -> None:
    row = _accepted_target(migrated_sqlite_engine)

    _ingest(migrated_sqlite_engine, "email_opened", str(row["email_address"]))

    target = _target_row(migrated_sqlite_engine)
    assert target["delivery_status"] == "opened"
    assert target["opened_at"] is not None


def test_delivery_events_are_idempotent_without_changing_their_fingerprint(
    migrated_sqlite_engine,
) -> None:
    row = _accepted_target(migrated_sqlite_engine)
    payload = _event("email_opened", str(row["email_address"]))
    service = _service(migrated_sqlite_engine)

    first = service.ingest(payload, received_at=NOW)
    replay = service.ingest(payload, received_at=NOW)

    with migrated_sqlite_engine.connect() as connection:
        fingerprints = connection.scalars(
            sa.select(prospect_delivery_event.c.event_fingerprint)
        ).all()
    assert not first.replayed
    assert replay.replayed
    assert first.event_fingerprint == replay.event_fingerprint
    assert fingerprints == [first.event_fingerprint]


def test_late_email_sent_cannot_downgrade_delivery_or_acceptance(migrated_sqlite_engine) -> None:
    row = _accepted_target(migrated_sqlite_engine)
    email = str(row["email_address"])

    for minute, event_type, expected_status in (
        (1, "email_opened", "opened"),
        (2, "email_link_clicked", "clicked"),
        (3, "reply_received", "replied"),
        (4, "email_bounced", "bounced"),
        (5, "lead_unsubscribed", "unsubscribed"),
    ):
        _ingest(
            migrated_sqlite_engine,
            event_type,
            email,
            occurred_at=NOW + dt.timedelta(minutes=minute),
        )
        _ingest(
            migrated_sqlite_engine,
            "email_sent",
            email,
            occurred_at=NOW + dt.timedelta(minutes=minute + 10),
        )
        target = _target_row(migrated_sqlite_engine)
        assert target["delivery_status"] == expected_status
        assert _utc(target["instantly_accepted_at"]) == NOW


def test_out_of_order_events_preserve_monotonic_delivery_and_event_timestamps(
    migrated_sqlite_engine,
) -> None:
    row = _accepted_target(migrated_sqlite_engine)
    email = str(row["email_address"])
    opened_at = NOW + dt.timedelta(minutes=1)
    clicked_at = NOW + dt.timedelta(minutes=2)
    sent_at = NOW + dt.timedelta(minutes=3)

    _ingest(migrated_sqlite_engine, "email_link_clicked", email, occurred_at=clicked_at)
    _ingest(migrated_sqlite_engine, "email_opened", email, occurred_at=opened_at)
    _ingest(migrated_sqlite_engine, "email_sent", email, occurred_at=sent_at)

    target = _target_row(migrated_sqlite_engine)
    assert target["delivery_status"] == "clicked"
    assert _utc(target["sent_at"]) == sent_at
    assert _utc(target["opened_at"]) == opened_at
    assert _utc(target["clicked_at"]) == clicked_at
