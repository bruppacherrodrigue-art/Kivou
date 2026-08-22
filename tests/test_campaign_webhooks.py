from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_campaign_service import _keyring
from test_campaign_worker import _operation, _planned

from signals.acquisition.contracts import AcquisitionState
from signals.acquisition.store import AcquisitionStore
from signals.api.app import create_app
from signals.api.config import ApiConfig
from signals.campaigns.contracts import ProviderOperationKind, ResponseIngressCapability
from signals.campaigns.webhooks import (
    InstantlyWebhookService,
    WebhookBindingError,
    WebhookFingerprintKeyring,
    WebhookSubscriptionInvalid,
    validate_webhook_subscription,
)
from signals.compliance.contracts import SuppressionMatchState
from signals.compliance.store import SuppressionStore
from signals.persistence.schema import (
    acquisition_campaign_member,
    acquisition_contact,
    acquisition_contact_suppression,
    acquisition_provider_event,
)

SECRET = "synthetic-webhook-secret"
RECEIVED = dt.datetime(2026, 8, 21, 13, 20, tzinfo=dt.UTC)


def _queued(tmp_path):
    engine, opportunity_id, campaign_service, _provider, worker, result = _planned(tmp_path)
    worker.process(_operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["operation_ref"], RECEIVED)
    worker.process(_operation(engine, ProviderOperationKind.CONFIGURE_CAMPAIGN)["operation_ref"], RECEIVED)
    worker.process(_operation(engine, ProviderOperationKind.ADD_LEAD)["operation_ref"], RECEIVED)
    from signals.campaigns.store import CampaignStore

    CampaignStore(engine).close_due_batches(RECEIVED + dt.timedelta(minutes=15))
    campaign_service.queue_and_seal(
        result.campaign_ref, captured_at=RECEIVED + dt.timedelta(minutes=16)
    )
    return engine, opportunity_id, result


def _service(engine) -> InstantlyWebhookService:
    return InstantlyWebhookService(
        engine,
        provider_workspace_ref="workspace:test",
        fingerprint_keyring=WebhookFingerprintKeyring(
            current_key_version="webhook-key-v1",
            keys={"webhook-key-v1": b"synthetic-webhook-fingerprint-key"},
        ),
        suppression_keyring=_keyring(),
        response_ingress_capability=ResponseIngressCapability.NONE,
    )


def _event(result, **overrides):
    values = {
        "event_type": "email_sent",
        "timestamp": "2026-08-21T13:30:00+00:00",
        "workspace_id": "workspace:test",
        "campaign_id": "provider-campaign-1",
        "lead_id": "provider-lead-1",
        "email_id": "provider-email-1",
        "step": 1,
        "status": "sent",
    }
    values.update(overrides)
    return values


def test_step_one_transport_truth_is_atomic_and_duplicate_safe(tmp_path) -> None:
    engine, opportunity_id, result = _queued(tmp_path)
    service = _service(engine)

    first = service.ingest(_event(result), received_at=RECEIVED)
    duplicate = service.ingest(_event(result), received_at=RECEIVED + dt.timedelta(seconds=1))

    assert first.replayed is False
    assert duplicate.replayed is True
    opportunity = AcquisitionStore(engine).get_opportunity(opportunity_id)
    assert opportunity.state is AcquisitionState.SENT
    with engine.connect() as connection:
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_provider_event)) == 1
    assert member["execution_state"] == "SENT"
    assert member["sequence_state"] == "WAITING_STEP2"
    assert member["step_1_sent_at"] is not None
    assert member["step_2_due_at"] is not None
    assert member["sequence_timing_fingerprint"] is not None


def test_conflicting_step_one_transport_timestamp_preserves_first_timing(tmp_path) -> None:
    engine, _, result = _queued(tmp_path)
    service = _service(engine)
    service.ingest(_event(result), received_at=RECEIVED)
    before = _member_row(engine)

    conflict = service.ingest(
        _event(
            result,
            email_id="provider-email-conflict",
            timestamp="2026-08-21T13:31:00+00:00",
        ),
        received_at=RECEIVED + dt.timedelta(minutes=1),
    )

    after = _member_row(engine)
    assert conflict.incident_code == "CONFLICTING_STEP1_TRANSPORT_TRUTH"
    assert after["step_1_sent_at"] == before["step_1_sent_at"]
    assert after["step_2_due_at"] == before["step_2_due_at"]
    assert after["sequence_timing_fingerprint"] == before["sequence_timing_fingerprint"]
    assert after["sequence_state"] == "STOPPED"


def test_step_one_before_authorized_window_is_real_sent_but_stops_sequence(tmp_path) -> None:
    engine, opportunity_id, result = _queued(tmp_path)
    service = _service(engine)

    outcome = service.ingest(
        _event(
            result,
            timestamp="2026-08-21T06:59:00+00:00",
            email_id="provider-early-step-one",
        ),
        received_at=dt.datetime(2026, 8, 21, 7, tzinfo=dt.UTC),
    )

    member = _member_row(engine)
    assert AcquisitionStore(engine).get_opportunity(opportunity_id).state is AcquisitionState.SENT
    assert outcome.incident_code == "STEP1_SENT_OUTSIDE_AUTHORIZED_WINDOW"
    assert member["execution_state"] == "SENT"
    assert member["sequence_state"] == "STOPPED"
    assert member["sequence_timing_fingerprint"] is None


def test_step_one_after_hard_stop_preserves_sent_truth_without_authorizing_step_two(
    tmp_path,
) -> None:
    engine, opportunity_id, result = _queued(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            sa.update(acquisition_campaign_member).values(
                execution_state="STOPPED",
                sequence_state="STOPPED",
                reason_code="SUPPRESSION_NOT_CLEAR",
            )
        )

    outcome = _service(engine).ingest(_event(result), received_at=RECEIVED)

    member = _member_row(engine)
    assert AcquisitionStore(engine).get_opportunity(opportunity_id).state is AcquisitionState.SENT
    assert outcome.incident_code == "UNEXPECTED_EMAIL_SENT_AFTER_STOP"
    assert member["execution_state"] == "SENT"
    assert member["sequence_state"] == "STOPPED"
    assert member["step_2_due_at"] is None
    assert member["sequence_timing_fingerprint"] is None


def _member_row(engine):
    with engine.connect() as connection:
        return connection.execute(sa.select(acquisition_campaign_member)).mappings().one()


@pytest.mark.parametrize(
    ("timestamp", "incident"),
    [
        ("2026-08-25T13:29:59+00:00", "STEP2_SENT_BEFORE_AUTHORIZED_WINDOW"),
        ("2026-08-25T15:00:00+00:00", "STEP2_SENT_OUTSIDE_AUTHORIZED_WINDOW"),
        ("2026-08-25T15:01:00+00:00", "STEP2_SENT_OUTSIDE_AUTHORIZED_WINDOW"),
    ],
)
def test_step_two_provider_truth_is_kept_with_bounded_incident(
    tmp_path, timestamp, incident
) -> None:
    engine, _, result = _queued(tmp_path)
    service = _service(engine)
    service.ingest(_event(result), received_at=RECEIVED)

    outcome = service.ingest(
        _event(
            result,
            timestamp=timestamp,
            email_id=f"step-two-{timestamp}",
            step=2,
        ),
        received_at=dt.datetime.fromisoformat(timestamp) + dt.timedelta(seconds=1),
    )

    member = _member_row(engine)
    assert outcome.incident_code == incident
    assert member["sequence_state"] == "COMPLETED"
    assert member["incident_code"] == incident


def test_wrong_workspace_and_unknown_campaign_fail_without_audit(tmp_path) -> None:
    engine, _, result = _queued(tmp_path)
    service = _service(engine)

    with pytest.raises(WebhookBindingError, match="workspace"):
        service.ingest(
            _event(result, workspace_id="workspace:other"), received_at=RECEIVED
        )
    with pytest.raises(WebhookBindingError, match="campaign"):
        service.ingest(
            _event(result, campaign_id="provider-campaign-missing"),
            received_at=RECEIVED,
        )
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_provider_event)
        ) == 0


def test_persisted_event_records_injected_fingerprint_key_version(tmp_path) -> None:
    engine, _, result = _queued(tmp_path)
    service = InstantlyWebhookService(
        engine,
        provider_workspace_ref="workspace:test",
        fingerprint_keyring=WebhookFingerprintKeyring(
            current_key_version="event-key-v7",
            keys={"event-key-v7": b"synthetic-event-key-v7"},
        ),
        suppression_keyring=_keyring(),
        response_ingress_capability=ResponseIngressCapability.NONE,
    )

    service.ingest(_event(result), received_at=RECEIVED)

    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(acquisition_provider_event.c.fingerprint_key_version)
        ) == "event-key-v7"


def test_provider_event_redelivery_converges_across_retained_key_rotation(tmp_path) -> None:
    engine, _, result = _queued(tmp_path)
    old = InstantlyWebhookService(
        engine,
        provider_workspace_ref="workspace:test",
        fingerprint_keyring=WebhookFingerprintKeyring(
            current_key_version="event-key-old",
            keys={"event-key-old": b"synthetic-event-key-old"},
        ),
        suppression_keyring=_keyring(),
        response_ingress_capability=ResponseIngressCapability.NONE,
    )
    rotated = InstantlyWebhookService(
        engine,
        provider_workspace_ref="workspace:test",
        fingerprint_keyring=WebhookFingerprintKeyring(
            current_key_version="event-key-new",
            keys={
                "event-key-old": b"synthetic-event-key-old",
                "event-key-new": b"synthetic-event-key-new",
            },
        ),
        suppression_keyring=_keyring(),
        response_ingress_capability=ResponseIngressCapability.NONE,
    )

    first = old.ingest(_event(result), received_at=RECEIVED)
    replay = rotated.ingest(_event(result), received_at=RECEIVED + dt.timedelta(seconds=1))

    assert replay.replayed is True
    assert replay.event_fingerprint == first.event_fingerprint
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_provider_event)
        ) == 1


def test_missing_provider_lead_id_resolves_transient_email_without_persisting_it(
    tmp_path,
) -> None:
    engine, _, result = _queued(tmp_path)
    with engine.connect() as connection:
        business_email = connection.scalar(sa.select(acquisition_contact.c.business_email))

    outcome = _service(engine).ingest(
        _event(result, lead_id=None, lead_email=business_email),
        received_at=RECEIVED,
    )

    assert outcome.replayed is False
    with engine.connect() as connection:
        rows = connection.execute(sa.select(acquisition_provider_event)).mappings().all()
    assert business_email not in str([dict(row) for row in rows])


def test_reply_fingerprint_distinguishes_transient_content_without_persisting_it(tmp_path) -> None:
    engine, _, result = _queued(tmp_path)
    service = _service(engine)

    one = service.ingest(
        _event(
            result,
            event_type="reply_received",
            email_id=None,
            reply_text="Synthetic reply one",
            reply_html="<p>Synthetic reply one</p>",
        ),
        received_at=RECEIVED,
    )
    two = service.ingest(
        _event(
            result,
            event_type="reply_received",
            email_id=None,
            reply_text="Synthetic reply two",
            reply_html="<p>Synthetic reply two</p>",
        ),
        received_at=RECEIVED,
    )

    assert one.event_fingerprint != two.event_fingerprint
    with engine.connect() as connection:
        rows = connection.execute(sa.select(acquisition_provider_event)).mappings().all()
    serialized = str([dict(row) for row in rows])
    assert "Synthetic reply" not in serialized
    assert "<p>" not in serialized
    assert all(row["incident_code"] == "UNEXPECTED_REPLY_WITHOUT_RESPONSE_INGRESS" for row in rows)


def test_unsubscribe_creates_hard_suppression_before_stopping_sequence(tmp_path) -> None:
    engine, _, result = _queued(tmp_path)
    service = _service(engine)

    service.ingest(
        _event(
            result,
            event_type="lead_unsubscribed",
            email_id="provider-unsubscribe-1",
        ),
        received_at=RECEIVED,
    )

    with engine.connect() as connection:
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_contact_suppression)
        ) == 1
    assert member["execution_state"] == "STOPPED"
    assert member["sequence_state"] == "STOPPED"
    assert SuppressionStore(engine, _keyring()).match_contact(
        member["contact_ref"]
    ).state is SuppressionMatchState.MATCHED


def test_reply_subscription_is_rejected_until_spec027() -> None:
    try:
        validate_webhook_subscription(
            ("email_sent", "reply_received"),
            response_ingress_capability=ResponseIngressCapability.NONE,
        )
    except WebhookSubscriptionInvalid:
        pass
    else:  # pragma: no cover
        raise AssertionError("reply_received subscription must fail closed")


def test_route_is_json_bounded_and_constant_time_secret_authenticated(tmp_path) -> None:
    engine, _, _ = _queued(tmp_path)
    config = ApiConfig(
        instantly_webhook_secret=SECRET,
        instantly_webhook_workspace_ref="workspace:test",
    )
    client = TestClient(create_app(engine, config, instantly_webhook_service=_service(engine)))
    payload = _event(None)

    assert client.post("/webhooks/instantly", content=b"{}", headers={
        "content-type": "text/plain",
        "x-kivou-instantly-secret": SECRET,
    }).status_code == 415
    assert client.post("/webhooks/instantly", json=payload, headers={
        "x-kivou-instantly-secret": "wrong",
    }).status_code == 401
    assert client.post("/webhooks/instantly", content=b"{" + b"x" * 65536, headers={
        "content-type": "application/json",
        "x-kivou-instantly-secret": SECRET,
    }).status_code == 413
    assert client.post("/webhooks/instantly", json=payload, headers={
        "x-kivou-instantly-secret": SECRET,
    }).status_code == 200


def test_route_never_reflects_sensitive_invalid_event_values(tmp_path) -> None:
    engine, _, _ = _queued(tmp_path)
    config = ApiConfig(
        instantly_webhook_secret=SECRET,
        instantly_webhook_workspace_ref="workspace:test",
    )
    client = TestClient(create_app(engine, config, instantly_webhook_service=_service(engine)))
    sensitive = "SYNTHETIC-REPLY-CONTENT-MUST-NOT-BE-REFLECTED"
    payload = _event(None, unsupported_reply_payload=sensitive)

    response = client.post(
        "/webhooks/instantly",
        json=payload,
        headers={"x-kivou-instantly-secret": SECRET},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_instantly_event"
    assert sensitive not in response.text
