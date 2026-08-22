from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from test_campaign_service import _keyring
from test_campaign_webhooks import RECEIVED, _official_events, _queued

from signals.acquisition.contracts import AcquisitionState
from signals.acquisition.store import AcquisitionStore
from signals.campaigns.contracts import ResponseIngressCapability
from signals.campaigns.webhooks import (
    InstantlyWebhookService,
    WebhookFingerprintKeyring,
)
from signals.compliance.contracts import SuppressionMatchState
from signals.compliance.store import SuppressionStore
from signals.persistence.schema import (
    acquisition_campaign_member,
    acquisition_provider_event,
    acquisition_response_evaluation,
)
from signals.responses.contracts import ContentFingerprintKeyring
from signals.responses.service import ResponseWebhookIngress


def _response_ingress(engine) -> ResponseWebhookIngress:
    return ResponseWebhookIngress(
        engine,
        suppression_keyring=_keyring(),
        source_keyring=ContentFingerprintKeyring(
            current_key_version="response-source-key-v1",
            keys={"response-source-key-v1": b"synthetic-response-source-key"},
        ),
        content_keyring=ContentFingerprintKeyring(
            current_key_version="response-content-key-v1",
            keys={"response-content-key-v1": b"synthetic-response-content-key"},
        ),
        classifier_version="synthetic-classifier-v1",
        estimated_classifier_cost="0.01",
    )


def _service(engine) -> InstantlyWebhookService:
    return InstantlyWebhookService(
        engine,
        provider_workspace_ref="workspace:test",
        fingerprint_keyring=WebhookFingerprintKeyring(
            current_key_version="webhook-key-v1",
            keys={"webhook-key-v1": b"synthetic-webhook-fingerprint-key"},
        ),
        suppression_keyring=_keyring(),
        response_ingress_capability=ResponseIngressCapability.SPEC027_V1,
        response_ingress=_response_ingress(engine),
    )


def _rows(engine):
    with engine.connect() as connection:
        evaluations = connection.execute(
            sa.select(acquisition_response_evaluation)
        ).mappings().all()
        provider_events = connection.execute(
            sa.select(acquisition_provider_event)
        ).mappings().all()
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
    return evaluations, provider_events, member


def test_authenticated_reply_reserves_one_evaluation_without_waiting_for_classifier(
    tmp_path, monkeypatch
) -> None:
    engine, _, _ = _queued(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("webhook acknowledgement attempted external execution")

    monkeypatch.setattr("httpx.Client.request", forbidden)
    first = _service(engine).ingest(
        _official_events()["reply_received"], received_at=RECEIVED
    )
    replay = _service(engine).ingest(
        _official_events()["reply_received"],
        received_at=RECEIVED + dt.timedelta(seconds=1),
    )

    evaluations, _, member = _rows(engine)
    assert first.response_ref is not None
    assert replay.replayed is True
    assert len(evaluations) == 1
    assert evaluations[0]["processing_state"] == "PLANNED"
    assert evaluations[0]["classifier_version"] == "synthetic-classifier-v1"
    assert member["sequence_state"] == "STOPPED"


def test_explicit_unsubscribe_is_suppressed_and_finalized_before_policy_or_model(
    tmp_path,
) -> None:
    engine, opportunity_id, _ = _queued(tmp_path)
    event = dict(_official_events()["reply_received"])
    event.update(
        reply_subject="SYNTHETIC-UNSUBJECT-MUST-NOT-PERSIST",
        reply_text="Please unsubscribe me. SYNTHETIC-UNSUB-BODY-MUST-NOT-PERSIST",
        reply_html="<p>SYNTHETIC-UNSUB-HTML-MUST-NOT-PERSIST</p>",
    )

    outcome = _service(engine).ingest(event, received_at=RECEIVED)

    evaluations, provider_events, member = _rows(engine)
    row = evaluations[0]
    assert outcome.response_ref == row["response_ref"]
    assert row["processing_state"] == "FINALIZED"
    assert row["classification"] == "UNSUBSCRIBE"
    assert row["classifier_version"] == "response-safety-rules-v1"
    assert row["policy_evaluation_id"] is None
    assert row["hot_lead"] is False
    assert row["suppression_ref"] is not None
    assert AcquisitionStore(engine).get_opportunity(opportunity_id).state is AcquisitionState.REPLIED
    assert member["sequence_state"] == "STOPPED"
    assert SuppressionStore(engine, _keyring()).match_contact(
        member["contact_ref"]
    ).state is SuppressionMatchState.MATCHED
    persisted = str([dict(row), *[dict(value) for value in provider_events]])
    for marker in (
        "SYNTHETIC-UNSUBJECT-MUST-NOT-PERSIST",
        "SYNTHETIC-UNSUB-BODY-MUST-NOT-PERSIST",
        "SYNTHETIC-UNSUB-HTML-MUST-NOT-PERSIST",
    ):
        assert marker not in persisted


def test_explicit_complaint_suppresses_and_requests_review(tmp_path) -> None:
    engine, opportunity_id, _ = _queued(tmp_path)
    event = dict(_official_events()["reply_received"])
    event["reply_text"] = "This is spam."
    event.pop("reply_html", None)

    _service(engine).ingest(event, received_at=RECEIVED)

    row = _rows(engine)[0][0]
    opportunity = AcquisitionStore(engine).get_opportunity(opportunity_id)
    assert row["classification"] == "COMPLAINT"
    assert row["review_required"] is True
    assert row["next_action"] == "request_human_review"
    assert row["suppression_ref"] is not None
    assert opportunity.state is AcquisitionState.REPLIED
    assert opportunity.next_action == "request_human_review"


def test_bodyless_auto_reply_finalizes_safety_without_replied_outcome(tmp_path) -> None:
    engine, opportunity_id, _ = _queued(tmp_path)
    event = dict(_official_events()["auto_reply_received"])
    for key in ("reply_subject", "reply_text_snippet", "reply_text", "reply_html"):
        event.pop(key, None)

    _service(engine).ingest(event, received_at=RECEIVED)

    row = _rows(engine)[0][0]
    opportunity = AcquisitionStore(engine).get_opportunity(opportunity_id)
    assert row["processing_state"] == "FINALIZED"
    assert row["classification"] == "AUTO_REPLY"
    assert row["human_response_confirmed"] is False
    assert row["outcome_event_ref"] is None
    assert opportunity.state is AcquisitionState.QUEUED
    assert opportunity.next_action is None


def test_capability_requires_transactional_response_handoff(tmp_path) -> None:
    engine, _, _ = _queued(tmp_path)

    try:
        InstantlyWebhookService(
            engine,
            provider_workspace_ref="workspace:test",
            fingerprint_keyring=WebhookFingerprintKeyring(
                current_key_version="webhook-key-v1",
                keys={"webhook-key-v1": b"synthetic-webhook-fingerprint-key"},
            ),
            suppression_keyring=_keyring(),
            response_ingress_capability=ResponseIngressCapability.SPEC027_V1,
        )
    except ValueError as exc:
        assert "response ingress" in str(exc)
    else:
        raise AssertionError("SPEC027_V1 accepted without durable response handoff")


def test_second_distinct_reply_after_stop_keeps_separate_transport_truth(tmp_path) -> None:
    engine, _, _ = _queued(tmp_path)
    first = dict(_official_events()["reply_received"])
    second = dict(first)
    first["reply_text"] = "Synthetic first substantive response."
    second["reply_text"] = "Synthetic distinct second substantive response."
    service = _service(engine)

    first_result = service.ingest(first, received_at=RECEIVED)
    second_result = service.ingest(
        second, received_at=RECEIVED + dt.timedelta(seconds=1)
    )

    assert first_result.event_fingerprint != second_result.event_fingerprint
    assert first_result.response_ref != second_result.response_ref
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_provider_event)
        ) == 2
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_response_evaluation)
        ) == 2
    assert _rows(engine)[2]["sequence_state"] == "STOPPED"
