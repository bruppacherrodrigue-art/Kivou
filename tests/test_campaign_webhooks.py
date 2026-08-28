from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_campaign_service import _keyring
from test_campaign_store import _additional_opportunity
from test_campaign_worker import _operation, _planned

from signals.acquisition.contracts import AcquisitionState
from signals.acquisition.store import AcquisitionStore
from signals.api.app import create_app
from signals.api.config import ApiConfig
from signals.campaigns.contracts import (
    PROVIDER_EVENT_FINGERPRINT_VERSION,
    ProviderOperationKind,
    ResponseIngressCapability,
)
from signals.campaigns.webhooks import (
    InstantlyWebhookService,
    ProviderEventType,
    WebhookBindingError,
    WebhookFingerprintKeyring,
    WebhookSubscriptionInvalid,
    normalize_instantly_webhook_payload,
    validate_webhook_subscription,
)
from signals.compliance.contracts import SuppressionMatchState
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_contact,
    acquisition_contact_suppression,
    acquisition_event,
    acquisition_provider_event,
    acquisition_provider_operation,
)

SECRET = "synthetic-webhook-secret"
RECEIVED = dt.datetime(2026, 8, 21, 13, 20, tzinfo=dt.UTC)
FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "instantly_v2_webhook_events_2026-08-22.json"
)


def _official_events() -> dict[str, dict[str, object]]:
    return json.loads(FIXTURE_PATH.read_text())["events"]


def _queued(tmp_path, *, recipient_override=None):
    engine, opportunity_id, campaign_service, _provider, worker, result = _planned(
        tmp_path, recipient_override=recipient_override
    )
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
    values = dict(_official_events()["email_sent"])
    values.update(overrides)
    return values


def test_official_payload_normalizes_workspace_and_drops_enrichment() -> None:
    raw = _official_events()["email_sent"]

    payload = normalize_instantly_webhook_payload(raw)

    assert payload.event_type is ProviderEventType.EMAIL_SENT
    assert payload.provider_workspace_ref == "workspace:test"
    assert payload.provider_campaign_id == "provider-campaign-1"
    assert payload.campaign_name_transport_only == "KIVOU-synthetic-fr"
    assert payload.lead_email_transient == "buyer@acme.example"
    assert payload.email_account_transient == "sender@example.invalid"
    assert payload.step_if_present == 1
    assert not hasattr(payload, "workspace_id")
    assert not hasattr(payload, "firstName")
    assert not hasattr(payload, "email_subject")


def test_official_fixture_covers_required_transport_vocabulary() -> None:
    assert set(_official_events()) == {
        "email_sent",
        "reply_received",
        "auto_reply_received",
        "lead_unsubscribed",
        "account_error",
        "campaign_completed",
    }


def test_step_one_transport_truth_is_atomic_and_duplicate_safe(tmp_path) -> None:
    engine, opportunity_id, result = _queued(tmp_path)
    service = _service(engine)

    first = service.ingest(_event(result), received_at=RECEIVED)
    duplicate = service.ingest(_event(result), received_at=RECEIVED + dt.timedelta(seconds=1))
    enriched_duplicate = service.ingest(
        _event(result, provider_added_field="must-have-no-effect"),
        received_at=RECEIVED + dt.timedelta(seconds=2),
    )

    assert first.replayed is False
    assert duplicate.replayed is True
    assert enriched_duplicate.replayed is True
    assert enriched_duplicate.event_fingerprint == first.event_fingerprint
    opportunity = AcquisitionStore(engine).get_opportunity(opportunity_id)
    assert opportunity.state is AcquisitionState.SENT
    with engine.connect() as connection:
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
        provider_events = connection.execute(
            sa.select(acquisition_provider_event)
        ).mappings().all()
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_provider_event)) == 1
    assert member["execution_state"] == "SENT"
    assert member["sequence_state"] == "WAITING_STEP2"
    assert member["step_1_sent_at"] is not None
    assert member["step_2_due_at"] is not None
    assert member["sequence_timing_fingerprint"] is not None
    serialized = str([dict(member), *[dict(row) for row in provider_events]])
    for forbidden in (
        "buyer@acme.example",
        "sender@example.invalid",
        "Synthetic subject",
        "Synthetic body",
        "Example Company",
        "+41000000000",
        "must-have-no-effect",
    ):
        assert forbidden not in serialized


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
            _event(result, workspace="workspace:other"), received_at=RECEIVED
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


def test_campaign_name_is_transport_only_not_binding_authority(tmp_path) -> None:
    engine, opportunity_id, result = _queued(tmp_path)

    _service(engine).ingest(
        _event(result, campaign_name="Provider-renamed transport label"),
        received_at=RECEIVED,
    )

    assert AcquisitionStore(engine).get_opportunity(opportunity_id).state is AcquisitionState.SENT


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
        row = connection.execute(sa.select(acquisition_provider_event)).mappings().one()
    assert row["fingerprint_key_version"] == "event-key-v7"
    assert row["fingerprint_version"] == PROVIDER_EVENT_FINGERPRINT_VERSION
    assert row["fingerprint_version"] == "provider-event-fingerprint-v2"


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


def test_official_payload_resolves_transient_email_without_persisting_it(
    tmp_path,
) -> None:
    engine, _, result = _queued(tmp_path)
    with engine.connect() as connection:
        business_email = connection.scalar(sa.select(acquisition_contact.c.business_email))

    outcome = _service(engine).ingest(
        _event(result, lead_email=business_email),
        received_at=RECEIVED,
    )

    assert outcome.replayed is False
    with engine.connect() as connection:
        rows = connection.execute(sa.select(acquisition_provider_event)).mappings().all()
    assert business_email not in str([dict(row) for row in rows])


def test_identical_documented_reply_redelivery_converges(tmp_path) -> None:
    engine, _, _result = _queued(tmp_path)
    service = _service(engine)

    first = service.ingest(_official_events()["reply_received"], received_at=RECEIVED)
    replay = service.ingest(
        _official_events()["reply_received"],
        received_at=RECEIVED + dt.timedelta(seconds=1),
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.event_fingerprint == first.event_fingerprint
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_provider_event)
        ) == 1


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("reply_text", "A second synthetic reply text."),
        ("reply_subject", "A second synthetic reply subject"),
        ("reply_html", "<p>A second synthetic reply HTML body.</p>"),
    ],
)
def test_documented_reply_content_change_is_a_distinct_event(
    tmp_path, field, replacement
) -> None:
    engine, _, _result = _queued(tmp_path)
    service = _service(engine)
    base = _official_events()["reply_received"]

    first = service.ingest(base, received_at=RECEIVED)
    distinct = service.ingest(
        {**base, field: replacement},
        received_at=RECEIVED + dt.timedelta(seconds=1),
    )

    assert first.incident_code == "UNEXPECTED_REPLY_WITHOUT_RESPONSE_INGRESS"
    assert distinct.incident_code == "UNEXPECTED_REPLY_WITHOUT_RESPONSE_INGRESS"
    assert distinct.replayed is False
    assert distinct.event_fingerprint != first.event_fingerprint
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_provider_event)
        ) == 2


def test_bodyless_reply_redelivery_is_accepted_and_converges(tmp_path) -> None:
    engine, _, _result = _queued(tmp_path)
    service = _service(engine)
    bodyless = dict(_official_events()["reply_received"])
    for field in ("reply_subject", "reply_text_snippet", "reply_text", "reply_html"):
        bodyless.pop(field)

    first = service.ingest(bodyless, received_at=RECEIVED)
    replay = service.ingest(
        bodyless,
        received_at=RECEIVED + dt.timedelta(seconds=1),
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.event_fingerprint == first.event_fingerprint


def test_unknown_reply_enrichment_does_not_change_identity(tmp_path) -> None:
    engine, _, _result = _queued(tmp_path)
    service = _service(engine)
    base = _official_events()["reply_received"]

    first = service.ingest(base, received_at=RECEIVED)
    replay = service.ingest(
        {**base, "provider_enrichment": "synthetic ignored value"},
        received_at=RECEIVED + dt.timedelta(seconds=1),
    )

    assert replay.replayed is True
    assert replay.event_fingerprint == first.event_fingerprint


def test_distinct_replies_after_stop_persist_separately_with_convergent_safety(
    tmp_path,
) -> None:
    engine, _, _result = _queued(tmp_path)
    service = _service(engine)
    base = _official_events()["reply_received"]

    first = service.ingest(base, received_at=RECEIVED)
    second = service.ingest(
        {**base, "reply_text": "A genuinely distinct synthetic second reply."},
        received_at=RECEIVED + dt.timedelta(seconds=1),
    )

    assert first.replayed is False
    assert second.replayed is False
    assert second.event_fingerprint != first.event_fingerprint
    member = _member_row(engine)
    assert member["execution_state"] == "STOPPED"
    assert member["sequence_state"] == "STOPPED"
    with engine.connect() as connection:
        events = connection.execute(sa.select(acquisition_provider_event)).mappings().all()
        operations = connection.execute(
            sa.select(acquisition_provider_operation.c.kind)
        ).scalars().all()
    assert len(events) == 2
    assert operations.count("PAUSE_LEAD") == 1
    assert operations.count("PAUSE_CAMPAIGN") == 1


def test_documented_reply_content_is_transient_hmac_input_only(tmp_path) -> None:
    engine, _, _result = _queued(tmp_path)
    documented = _official_events()["reply_received"]
    normalized = normalize_instantly_webhook_payload(documented)

    assert normalized.reply_subject_transient == documented["reply_subject"]
    assert normalized.reply_text_snippet_transient == documented["reply_text_snippet"]
    assert normalized.reply_text_transient == documented["reply_text"]
    assert normalized.reply_html_transient == documented["reply_html"]
    normalized_repr = repr(normalized)
    for field in ("reply_subject", "reply_text_snippet", "reply_text", "reply_html"):
        assert documented[field] not in normalized_repr

    _service(engine).ingest(documented, received_at=RECEIVED)

    with engine.connect() as connection:
        rows = connection.execute(sa.select(acquisition_provider_event)).mappings().all()
        durable_rows = [
            *connection.execute(sa.select(acquisition_campaign)).mappings().all(),
            *connection.execute(sa.select(acquisition_campaign_member)).mappings().all(),
            *connection.execute(sa.select(acquisition_provider_operation)).mappings().all(),
            *connection.execute(sa.select(acquisition_event)).mappings().all(),
            *rows,
        ]
    serialized = str([dict(row) for row in durable_rows])
    for field in ("reply_subject", "reply_text_snippet", "reply_text", "reply_html"):
        assert documented[field] not in serialized
    assert "reply_content_digest" not in rows[0]
    assert "reply_subject" not in rows[0]
    assert "reply_text" not in rows[0]


def test_invalid_reply_content_is_not_exposed_by_normalization_error() -> None:
    sensitive = "SYNTHETIC-REPLY-CONTENT-MUST-NOT-ENTER-ERRORS"
    raw = {
        **_official_events()["reply_received"],
        "reply_text": sensitive + ("x" * 65536),
    }

    with pytest.raises(ValueError) as captured:
        normalize_instantly_webhook_payload(raw)

    assert sensitive not in str(captured.value)
    assert captured.value.__cause__ is None


def test_auto_reply_content_differentiates_transport_without_classification(
    tmp_path,
) -> None:
    engine, opportunity_id, _ = _queued(tmp_path)
    service = _service(engine)
    base = _official_events()["auto_reply_received"]

    first = service.ingest(
        {**base, "reply_text": "Synthetic automatic response one."},
        received_at=RECEIVED,
    )
    second = service.ingest(
        {**base, "reply_text": "Synthetic automatic response two."},
        received_at=RECEIVED + dt.timedelta(seconds=1),
    )

    assert first.replayed is False
    assert second.replayed is False
    assert first.event_fingerprint != second.event_fingerprint
    assert _member_row(engine)["sequence_state"] == "STOPPED"
    assert AcquisitionStore(engine).get_opportunity(opportunity_id).state is AcquisitionState.QUEUED
    with engine.connect() as connection:
        rows = connection.execute(sa.select(acquisition_provider_event)).mappings().all()
    assert len(rows) == 2
    assert all(row["incident_code"] is None for row in rows)


def test_auto_reply_is_safety_only_and_stops_remaining_sequence(tmp_path) -> None:
    engine, opportunity_id, _ = _queued(tmp_path)

    outcome = _service(engine).ingest(
        _official_events()["auto_reply_received"], received_at=RECEIVED
    )

    member = _member_row(engine)
    assert outcome.incident_code is None
    assert member["execution_state"] == "STOPPED"
    assert member["sequence_state"] == "STOPPED"
    assert member["reason_code"] == "AUTO_REPLY_RECEIVED"
    assert AcquisitionStore(engine).get_opportunity(opportunity_id).state is AcquisitionState.QUEUED


def test_account_error_is_official_campaign_safety_event(tmp_path) -> None:
    engine, _, _ = _queued(tmp_path)

    outcome = _service(engine).ingest(
        _official_events()["account_error"], received_at=RECEIVED
    )

    assert outcome.replayed is False
    with engine.connect() as connection:
        row = connection.execute(sa.select(acquisition_provider_event)).mappings().one()
    assert row["provider_event_type"] == "account_error"


def test_non_official_email_account_error_is_not_subscription_vocabulary() -> None:
    with pytest.raises(WebhookSubscriptionInvalid, match="unknown"):
        validate_webhook_subscription(
            ("email_account_error",),
            response_ingress_capability=ResponseIngressCapability.SPEC027_V1,
        )


def test_unknown_event_type_is_quarantined_without_workflow_effect(tmp_path) -> None:
    engine, opportunity_id, result = _queued(tmp_path)

    outcome = _service(engine).ingest(
        _event(result, event_type="lead_interested", email_id=None),
        received_at=RECEIVED,
    )

    assert outcome.incident_code == "UNKNOWN_PROVIDER_EVENT_TYPE"
    assert AcquisitionStore(engine).get_opportunity(opportunity_id).state is AcquisitionState.QUEUED
    assert _member_row(engine)["execution_state"] == "QUEUED"
    with engine.connect() as connection:
        row = connection.execute(sa.select(acquisition_provider_event)).mappings().one()
    assert row["provider_event_type"] == "unknown"
    assert row["resolution_state"] == "QUARANTINED"


def test_ambiguous_transient_email_binding_fails_safe(tmp_path) -> None:
    engine, opportunity_id, result = _queued(tmp_path)
    second_opportunity_id, second_policy_id = _additional_opportunity(
        engine, opportunity_id, 91
    )
    with engine.begin() as connection:
        original = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
        duplicate = dict(original)
        duplicate.update(
            member_ref="f" * 64,
            acquisition_opportunity_id=second_opportunity_id,
            policy_evaluation_id=second_policy_id,
            provider_lead_id=None,
            queue_event_id=None,
            action_clear_event_id=None,
            sent_event_id=None,
        )
        connection.execute(sa.insert(acquisition_campaign_member).values(**duplicate))

    with pytest.raises(WebhookBindingError, match="ambiguous"):
        _service(engine).ingest(_event(result), received_at=RECEIVED)

    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_provider_event)
        ) == 0


def test_unmatched_transient_email_binding_fails_safe(tmp_path) -> None:
    engine, _, result = _queued(tmp_path)

    with pytest.raises(WebhookBindingError, match="lead binding"):
        _service(engine).ingest(
            _event(result, lead_email="unmatched@example.invalid"),
            received_at=RECEIVED,
        )

    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_provider_event)
        ) == 0


def test_qa_transport_identity_binds_webhook_without_persisting_address(tmp_path) -> None:
    from test_campaign_worker import _ControlledRecipientOverride

    override = _ControlledRecipientOverride()
    engine, opportunity_id, result = _queued(
        tmp_path, recipient_override=override
    )

    outcome = _service(engine).ingest(
        _event(result, lead_email="qa-controlled@example.com"),
        received_at=RECEIVED,
    )

    assert outcome.replayed is False
    assert AcquisitionStore(engine).get_opportunity(opportunity_id).state is AcquisitionState.SENT
    with engine.connect() as connection:
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
        provider_event = connection.execute(sa.select(acquisition_provider_event)).mappings().one()
    assert member["transport_recipient_identity"] == override.transport_recipient_identity
    assert member["transport_recipient_key_version"] == override.transport_key_version
    assert "qa-controlled@example.com" not in repr(dict(member))
    assert "qa-controlled@example.com" not in repr(dict(provider_event))


def test_retained_suppression_key_still_matches_existing_transport_binding(
    tmp_path,
) -> None:
    from test_campaign_worker import _ControlledRecipientOverride

    engine, _, result = _queued(
        tmp_path, recipient_override=_ControlledRecipientOverride()
    )
    rotated = InstantlyWebhookService(
        engine,
        provider_workspace_ref="workspace:test",
        fingerprint_keyring=WebhookFingerprintKeyring(
            current_key_version="webhook-key-v1",
            keys={"webhook-key-v1": b"synthetic-webhook-fingerprint-key"},
        ),
        suppression_keyring=SuppressionIdentityKeyring(
            current_key_version="key-v2",
            keys={
                "key-v1": b"campaign-test-key",
                "key-v2": b"campaign-test-key-rotated",
            },
        ),
        response_ingress_capability=ResponseIngressCapability.NONE,
    )

    outcome = rotated.ingest(
        _event(result, lead_email="qa-controlled@example.com"),
        received_at=RECEIVED,
    )

    assert outcome.replayed is False


def test_qa_webhook_member_lookup_is_hmac_filtered_and_bounded_in_large_campaign(
    tmp_path,
) -> None:
    from test_campaign_worker import _ControlledRecipientOverride

    override = _ControlledRecipientOverride()
    engine, original_opportunity_id, result = _queued(
        tmp_path, recipient_override=override
    )
    with engine.begin() as connection:
        template = connection.execute(
            sa.select(acquisition_campaign_member)
        ).mappings().one()
    for index in range(1, 102):
        opportunity_id, evaluation_id = _additional_opportunity(
            engine, original_opportunity_id, 2_000 + index
        )
        decoy = dict(template)
        decoy.update(
            member_ref=f"{20_000 + index:064x}",
            acquisition_opportunity_id=opportunity_id,
            policy_evaluation_id=evaluation_id,
            provider_lead_id=f"provider-decoy-{index}",
            transport_recipient_identity=f"{30_000 + index:064x}",
            transport_recipient_key_version=override.transport_key_version,
        )
        with engine.begin() as connection:
            connection.execute(sa.insert(acquisition_campaign_member).values(**decoy))

    observed_member_queries: list[str] = []

    def observe_member_query(
        _connection, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        normalized = " ".join(statement.split()).upper()
        if (
            "FROM ACQUISITION_CAMPAIGN_MEMBER" in normalized
            and "TRANSPORT_RECIPIENT_KEY_VERSION =" in normalized
        ):
            observed_member_queries.append(normalized)

    sa.event.listen(engine, "before_cursor_execute", observe_member_query)
    try:
        outcome = _service(engine).ingest(
            _event(result, lead_email="qa-controlled@example.com"),
            received_at=RECEIVED,
        )
    finally:
        sa.event.remove(engine, "before_cursor_execute", observe_member_query)

    assert outcome.replayed is False
    assert len(observed_member_queries) == 1
    statement = observed_member_queries[0]
    assert "JOIN ACQUISITION_CONTACT" not in statement
    assert "BUSINESS_EMAIL" not in statement
    assert "TRANSPORT_RECIPIENT_KEY_VERSION =" in statement
    assert "TRANSPORT_RECIPIENT_IDENTITY =" in statement
    assert " LIMIT " in f" {statement} "


def test_qa_unsubscribe_never_suppresses_discovered_real_contact(tmp_path) -> None:
    from test_campaign_worker import _ControlledRecipientOverride

    engine, _, result = _queued(
        tmp_path, recipient_override=_ControlledRecipientOverride()
    )

    outcome = _service(engine).ingest(
        _event(
            result,
            event_type="lead_unsubscribed",
            email_id="provider-qa-unsubscribe-1",
            lead_email="qa-controlled@example.com",
        ),
        received_at=RECEIVED,
    )

    with engine.connect() as connection:
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
        suppression_count = connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_contact_suppression)
        )
    assert outcome.incident_code == "QA_TRANSPORT_SUPPRESSION_NOT_PROPAGATED"
    assert suppression_count == 0
    assert member["execution_state"] == "STOPPED"
    assert member["sequence_state"] == "STOPPED"


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
    client = TestClient(
        create_app(
            engine,
            config,
            now_override=lambda: RECEIVED,
            instantly_webhook_service=_service(engine),
        )
    )
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
    client = TestClient(
        create_app(
            engine,
            config,
            now_override=lambda: RECEIVED,
            instantly_webhook_service=_service(engine),
        )
    )
    sensitive = "SYNTHETIC-REPLY-CONTENT-MUST-NOT-BE-REFLECTED"
    payload = _event(None, unsupported_reply_payload=sensitive)

    response = client.post(
        "/webhooks/instantly",
        json=payload,
        headers={"x-kivou-instantly-secret": SECRET},
    )

    assert response.status_code == 200
    assert sensitive not in response.text
    with engine.connect() as connection:
        rows = connection.execute(sa.select(acquisition_provider_event)).mappings().all()
    assert sensitive not in str([dict(row) for row in rows])


def test_webhook_ingress_never_calls_instantly_or_email_api(tmp_path, monkeypatch) -> None:
    engine, _, _ = _queued(tmp_path)

    def forbidden_network(*args, **kwargs):
        raise AssertionError("webhook ingestion attempted provider network I/O")

    monkeypatch.setattr("httpx.Client.request", forbidden_network)
    monkeypatch.setattr("httpx.AsyncClient.request", forbidden_network)

    outcome = _service(engine).ingest(
        _official_events()["reply_received"], received_at=RECEIVED
    )

    assert outcome.incident_code == "UNEXPECTED_REPLY_WITHOUT_RESPONSE_INGRESS"
