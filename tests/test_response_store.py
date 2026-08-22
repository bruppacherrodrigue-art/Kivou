from __future__ import annotations

import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from test_campaign_webhooks import _queued, _service

from signals.persistence.schema import (
    acquisition_provider_event,
    acquisition_response_evaluation,
)
from signals.responses.contracts import (
    CONTENT_FINGERPRINT_VERSION,
    RESPONSE_CONTENT_NORMALIZER_VERSION,
    RESPONSE_EMAIL_RESOLUTION_VERSION,
    RESPONSE_SAFETY_VERSION,
    RESPONSE_TAXONOMY_VERSION,
    ResponseClassification,
    ResponseFinalization,
    ResponseInputSource,
    ResponseReasonCode,
    ResponseReservation,
    response_evaluation_id,
    response_ref,
)
from signals.responses.store import (
    ResponseEvaluationConflict,
    ResponseStore,
)

NOW = dt.datetime(2026, 8, 22, 10, tzinfo=dt.UTC)
FIXTURE = Path(__file__).parent / "fixtures" / "instantly_v2_webhook_events_2026-08-22.json"


def _context(tmp_path):
    engine, _, _ = _queued(tmp_path)
    payload = json.loads(FIXTURE.read_text())["events"]["reply_received"]
    _service(engine).ingest(payload, received_at=NOW)
    with engine.connect() as connection:
        event = connection.execute(sa.select(acquisition_provider_event)).mappings().one()
    return engine, event


def _reservation(event, classifier_version="synthetic-classifier-v1", **updates):
    response = response_ref(
        provider_event_ref=event["provider_event_ref"],
        campaign_ref=event["campaign_ref"],
        member_ref=event["member_ref"],
    )
    values = {
        "response_evaluation_id": response_evaluation_id(response, classifier_version),
        "response_ref": response,
        "provider_event_ref": event["provider_event_ref"],
        "campaign_ref": event["campaign_ref"],
        "member_ref": event["member_ref"],
        "acquisition_opportunity_id": event["acquisition_opportunity_id"],
        "contact_ref": event["contact_ref"],
        "input_source": ResponseInputSource.WEBHOOK_V2,
        "source_fingerprint": event["canonical_event_fingerprint"],
        "classifier_version": classifier_version,
        "estimated_cost": Decimal("0.01"),
        "received_at": event["received_at"].replace(tzinfo=dt.UTC)
        if event["received_at"].tzinfo is None
        else event["received_at"],
        "created_at": NOW,
    }
    values.update(updates)
    return ResponseReservation.model_validate(values)


def _finalization(**updates):
    values = {
        "input_source": ResponseInputSource.INSTANTLY_EMAIL_V2,
        "source_fingerprint": "1" * 64,
        "provider_email_id": "01a028e4-5069-7b56-ae56-b7e4352c53fa",
        "provider_thread_id": "01a028e4-5069-7b56-ae56-b7ea2c81292b",
        "content_fingerprint": "2" * 64,
        "content_fingerprint_version": CONTENT_FINGERPRINT_VERSION,
        "content_fingerprint_key_version": "response-key-v1",
        "classification": ResponseClassification.NEGATIVE,
        "confidence": Decimal("0.95"),
        "reason_codes": (ResponseReasonCode.NEGATIVE_DECLINE,),
        "human_response_confirmed": True,
        "hot_lead": False,
        "review_required": False,
        "next_action": None,
        "disposition": "SEMANTIC_CLASSIFIED",
        "actual_cost": Decimal("0.002"),
        "input_tokens": 22,
        "output_tokens": 8,
        "evaluated_at": NOW + dt.timedelta(minutes=1),
        "finalized_at": NOW + dt.timedelta(minutes=1),
    }
    values.update(updates)
    return ResponseFinalization.model_validate(values)


def test_reservation_is_deterministic_and_replays_exact_semantics(tmp_path) -> None:
    engine, event = _context(tmp_path)
    store = ResponseStore(engine)
    reservation = _reservation(event)

    first = store.reserve(reservation)
    replay = store.reserve(reservation)

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.row["response_evaluation_id"] == reservation.response_evaluation_id
    assert replay.row["classifier_version"] == "synthetic-classifier-v1"
    assert replay.row["processing_state"] == "PLANNED"
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_response_evaluation)
        ) == 1


def test_same_event_new_classifier_version_is_explicit_append_only_reclassification(
    tmp_path,
) -> None:
    engine, event = _context(tmp_path)
    store = ResponseStore(engine)
    original = store.reserve(_reservation(event)).row
    replacement = _reservation(
        event,
        classifier_version="synthetic-classifier-v2",
        supersedes_response_evaluation_id=original["response_evaluation_id"],
        reclassification_reason="CLASSIFIER_VERSION_UPGRADE",
    )

    new = store.reserve(replacement)

    assert new.replayed is False
    assert new.row["response_ref"] == original["response_ref"]
    assert new.row["response_evaluation_id"] != original["response_evaluation_id"]
    with engine.connect() as connection:
        rows = connection.execute(
            sa.select(acquisition_response_evaluation).order_by(
                acquisition_response_evaluation.c.classifier_version
            )
        ).mappings().all()
    assert len(rows) == 2
    assert rows[0]["supersedes_response_evaluation_id"] is None
    assert rows[1]["supersedes_response_evaluation_id"] == original["response_evaluation_id"]


def test_single_claimant_and_expired_lease_is_reclaimed_as_unknown_work(tmp_path) -> None:
    engine, event = _context(tmp_path)
    store = ResponseStore(engine)
    evaluation_id = store.reserve(_reservation(event)).row["response_evaluation_id"]

    first = store.claim(
        evaluation_id,
        worker_ref="worker-a",
        now=NOW,
        lease_duration=dt.timedelta(minutes=1),
    )
    blocked = store.claim(
        evaluation_id,
        worker_ref="worker-b",
        now=NOW + dt.timedelta(seconds=30),
        lease_duration=dt.timedelta(minutes=1),
    )
    reclaimed = store.claim(
        evaluation_id,
        worker_ref="worker-b",
        now=NOW + dt.timedelta(minutes=2),
        lease_duration=dt.timedelta(minutes=1),
    )

    assert first.claimed is True
    assert blocked.claimed is False
    assert reclaimed.claimed is True
    assert reclaimed.row["lease_owner"] == "worker-b"
    assert reclaimed.row["attempt"] == 2


def test_concurrent_claims_have_one_winner(tmp_path) -> None:
    engine, event = _context(tmp_path)
    evaluation_id = ResponseStore(engine).reserve(_reservation(event)).row[
        "response_evaluation_id"
    ]

    def claim(worker):
        return ResponseStore(engine).claim(
            evaluation_id,
            worker_ref=worker,
            now=NOW,
            lease_duration=dt.timedelta(minutes=1),
        ).claimed

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(claim, ("worker-a", "worker-b")))

    assert sorted(outcomes) == [False, True]


def test_retry_wait_is_bounded_and_reclaimable_only_when_due(tmp_path) -> None:
    engine, event = _context(tmp_path)
    store = ResponseStore(engine)
    evaluation_id = store.reserve(_reservation(event)).row["response_evaluation_id"]
    store.claim(
        evaluation_id,
        worker_ref="worker-a",
        now=NOW,
        lease_duration=dt.timedelta(minutes=1),
    )
    retry_at = NOW + dt.timedelta(minutes=5)

    store.mark_retry(
        evaluation_id,
        worker_ref="worker-a",
        now=NOW + dt.timedelta(seconds=1),
        retry_at=retry_at,
        failure_code="RESPONSE_CONTENT_PENDING",
    )

    assert store.claim(
        evaluation_id,
        worker_ref="worker-b",
        now=retry_at - dt.timedelta(microseconds=1),
        lease_duration=dt.timedelta(minutes=1),
    ).claimed is False
    assert store.claim(
        evaluation_id,
        worker_ref="worker-b",
        now=retry_at,
        lease_duration=dt.timedelta(minutes=1),
    ).claimed is True


def test_finalization_is_write_once_and_exact_replay(tmp_path) -> None:
    engine, event = _context(tmp_path)
    store = ResponseStore(engine)
    evaluation_id = store.reserve(_reservation(event)).row["response_evaluation_id"]
    store.claim(
        evaluation_id,
        worker_ref="worker-a",
        now=NOW,
        lease_duration=dt.timedelta(minutes=2),
    )
    finalization = _finalization()

    first = store.finalize(evaluation_id, worker_ref="worker-a", value=finalization)
    replay = store.finalize(evaluation_id, worker_ref="worker-a", value=finalization)

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.row["processing_state"] == "FINALIZED"
    assert replay.row["classification"] == "NEGATIVE"
    assert replay.row["lease_owner"] is None
    with pytest.raises(ResponseEvaluationConflict):
        store.finalize(
            evaluation_id,
            worker_ref="worker-a",
            value=_finalization(classification=ResponseClassification.AMBIGUOUS),
        )


def test_frozen_contract_versions_are_persisted_on_reservation(tmp_path) -> None:
    engine, event = _context(tmp_path)
    row = ResponseStore(engine).reserve(_reservation(event)).row

    assert row["resolver_version"] == RESPONSE_EMAIL_RESOLUTION_VERSION
    assert row["normalizer_version"] == RESPONSE_CONTENT_NORMALIZER_VERSION
    assert row["safety_version"] == RESPONSE_SAFETY_VERSION
    assert row["taxonomy_version"] == RESPONSE_TAXONOMY_VERSION
