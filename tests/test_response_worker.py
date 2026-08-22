from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from test_campaign_service import _keyring
from test_campaign_webhooks import RECEIVED, _official_events, _queued
from test_policy_persistence import control

from signals.acquisition.contracts import AcquisitionState
from signals.acquisition.store import AcquisitionStore
from signals.campaigns.contracts import ResponseIngressCapability
from signals.campaigns.webhooks import InstantlyWebhookService, WebhookFingerprintKeyring
from signals.persistence.schema import (
    acquisition_campaign_member,
    acquisition_event,
    acquisition_provider_event,
    acquisition_response_evaluation,
    policy_evaluation,
)
from signals.policy.contracts import AutonomyMode, BudgetUsage, OperationalReadiness
from signals.policy.store import PolicyStore
from signals.responses.contracts import (
    ContentFingerprintKeyring,
    ResponseClassification,
    ResponseClassifierOutput,
    ResponseReasonCode,
)
from signals.responses.instantly_email import InstantlyEmail, InstantlyEmailPage
from signals.responses.policy import GatewayResponsePolicyAuthorizer
from signals.responses.service import EmailResponseResolver, ResponseWebhookIngress
from signals.responses.store import ResponseStore
from signals.responses.worker import (
    ResponsePolicyAuthorization,
    ResponseWorker,
    ResponseWorkerStatus,
)

EMAIL_FIXTURE = Path(__file__).parent / "fixtures" / "instantly_v2_email_response_2026-08-22.json"
EMAIL_VALUES = json.loads(EMAIL_FIXTURE.read_text())["get"]
WORKSPACE_ID = "01a028e4-5069-7b56-ae56-b7e52c2329d7"
CAMPAIGN_ID = "01a028e4-5069-7b56-ae56-b7e622c7fbf1"
LEAD_ID = "01a028e4-5069-7b56-ae56-b7e9cb32ae4c"


class FakeEmailReader:
    def __init__(self, email: InstantlyEmail | None, *, multiple: bool = False):
        self.email = email
        self.multiple = multiple
        self.list_calls = 0
        self.get_calls = 0

    def list_emails(self, query):
        self.list_calls += 1
        if self.email is None:
            return InstantlyEmailPage(items=(), next_starting_after=None)
        items = (self.email,)
        if self.multiple:
            duplicate = self.email.model_copy(
                update={"id": "01a028e4-5069-7b56-ae56-b7e4352c53fb"}
            )
            items += (duplicate,)
        return InstantlyEmailPage(items=items, next_starting_after=None)

    def get_email(self, provider_email_id):
        self.get_calls += 1
        assert self.email is not None
        assert provider_email_id == self.email.id
        return self.email


class FakeClassifier:
    def __init__(self, output=None, *, error=None):
        self.classifier_version = "synthetic-classifier-v1"
        self.output = output
        self.error = error
        self.calls = 0

    def classify(self, value):
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert "buyer@example" not in repr(value)
        return self.output


class FakePolicy:
    def __init__(self, *, allowed=True):
        self.allowed = allowed
        self.calls = 0
        self.facts = []
        self.policy_evaluation_id = "unbound-policy-evaluation"

    def authorize(self, facts, *, now):
        self.calls += 1
        self.facts.append(facts)
        return ResponsePolicyAuthorization(
            allowed=self.allowed,
            policy_evaluation_id=self.policy_evaluation_id,
            policy_action_fingerprint="d" * 64,
            policy_status="APPROVED" if self.allowed else "DENIED",
        )


def _keys(label: str) -> ContentFingerprintKeyring:
    return ContentFingerprintKeyring(
        current_key_version=f"{label}-key-v1",
        keys={f"{label}-key-v1": f"synthetic-{label}-key".encode()},
    )


def _service(engine) -> InstantlyWebhookService:
    ingress = ResponseWebhookIngress(
        engine,
        suppression_keyring=_keyring(),
        source_keyring=_keys("source"),
        content_keyring=_keys("content"),
        classifier_version="synthetic-classifier-v1",
        estimated_classifier_cost="0.01",
    )
    return InstantlyWebhookService(
        engine,
        provider_workspace_ref=WORKSPACE_ID,
        fingerprint_keyring=WebhookFingerprintKeyring(
            current_key_version="webhook-key-v1",
            keys={"webhook-key-v1": b"synthetic-webhook-fingerprint-key"},
        ),
        suppression_keyring=_keyring(),
        response_ingress_capability=ResponseIngressCapability.SPEC027_V1,
        response_ingress=ingress,
    )


def _email(**updates) -> InstantlyEmail:
    values = dict(EMAIL_VALUES)
    values.update(
        organization_id=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        lead_id=LEAD_ID,
        lead="buyer@acme.example",
        from_address_email="buyer@acme.example",
        eaccount="sender@example.invalid",
        timestamp_created="2026-08-21T13:35:30Z",
        timestamp_email="2026-08-21T13:35:29Z",
        is_auto_reply=0,
    )
    values.update(updates)
    return InstantlyEmail.model_validate(values)


def _ordinary_context(tmp_path):
    engine, opportunity_id, _ = _queued(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            sa.update(acquisition_campaign_member).values(
                provider_lead_id=LEAD_ID
            )
        )
        from signals.persistence.schema import acquisition_campaign

        connection.execute(
            sa.update(acquisition_campaign).values(
                provider_workspace_ref=WORKSPACE_ID,
                provider_campaign_id=CAMPAIGN_ID,
            )
        )
    event = dict(_official_events()["reply_received"])
    event.update(
        workspace=WORKSPACE_ID,
        campaign_id=CAMPAIGN_ID,
        reply_subject="Re: synthetic inquiry",
        reply_text="Yes, please show me the examples.",
        reply_html="<p>Yes, please show me the examples.</p>",
    )
    ingress = _service(engine).ingest(event, received_at=RECEIVED)
    with engine.connect() as connection:
        evaluation_id = connection.scalar(
            sa.select(acquisition_response_evaluation.c.response_evaluation_id)
        )
    return engine, opportunity_id, evaluation_id, ingress


def _worker(engine, reader, classifier, policy) -> ResponseWorker:
    if isinstance(policy, FakePolicy):
        with engine.connect() as connection:
            policy.policy_evaluation_id = connection.scalar(
                sa.select(policy_evaluation.c.evaluation_id).limit(1)
            )
    return ResponseWorker(
        engine,
        resolver=EmailResponseResolver(reader, source_keyring=_keys("source")),
        classifier=classifier,
        policy_authorizer=policy,
        content_keyring=_keys("content"),
        suppression_keyring=_keyring(),
        mailbox_accounts={"mailbox:test": "sender@example.invalid"},
    )


def _positive() -> ResponseClassifierOutput:
    return ResponseClassifierOutput(
        classification=ResponseClassification.POSITIVE,
        confidence=Decimal("0.91"),
        reason_codes=(ResponseReasonCode.EXPLICIT_COMMERCIAL_INTEREST,),
        hot_lead=True,
        review_required=True,
        classifier_version="synthetic-classifier-v1",
        language="fr",
        human_response_confirmed=True,
    )


def _negative() -> ResponseClassifierOutput:
    return ResponseClassifierOutput(
        classification=ResponseClassification.NEGATIVE,
        confidence=Decimal("0.95"),
        reason_codes=(ResponseReasonCode.NEGATIVE_DECLINE,),
        hot_lead=False,
        review_required=False,
        classifier_version="synthetic-classifier-v1",
        language="fr",
        human_response_confirmed=True,
    )


def test_positive_reply_finalizes_hot_replied_and_human_review(tmp_path) -> None:
    engine, opportunity_id, evaluation_id, _ = _ordinary_context(tmp_path)
    classifier = FakeClassifier(_positive())
    policy = FakePolicy()

    result = _worker(engine, FakeEmailReader(_email()), classifier, policy).process(
        evaluation_id, worker_ref="response-worker-1", now=RECEIVED
    )

    assert result.status is ResponseWorkerStatus.FINALIZED
    row = result.row
    assert row["classification"] == "POSITIVE"
    assert row["hot_lead"] is True
    assert row["review_required"] is True
    assert row["next_action"] == "request_human_review"
    assert row["content_fingerprint"] is not None
    assert row["provider_email_id"] == _email().id
    opportunity = AcquisitionStore(engine).get_opportunity(opportunity_id)
    assert opportunity.state is AcquisitionState.REPLIED
    assert opportunity.next_action == "request_human_review"
    assert classifier.calls == policy.calls == 1


def test_negative_reply_is_replied_safe_close_and_not_hot(tmp_path) -> None:
    engine, opportunity_id, evaluation_id, _ = _ordinary_context(tmp_path)

    result = _worker(
        engine, FakeEmailReader(_email()), FakeClassifier(_negative()), FakePolicy()
    ).process(evaluation_id, worker_ref="response-worker-1", now=RECEIVED)

    assert result.row["classification"] == "NEGATIVE"
    assert result.row["hot_lead"] is False
    assert result.row["next_action"] is None
    opportunity = AcquisitionStore(engine).get_opportunity(opportunity_id)
    assert opportunity.state is AcquisitionState.REPLIED
    assert opportunity.next_action is None


def test_email_content_unsubscribe_bypasses_policy_and_classifier(tmp_path) -> None:
    engine, opportunity_id, evaluation_id, _ = _ordinary_context(tmp_path)
    classifier = FakeClassifier(_positive())
    policy = FakePolicy(allowed=False)
    email = _email(body={"text": "Please unsubscribe me.", "html": None})

    result = _worker(engine, FakeEmailReader(email), classifier, policy).process(
        evaluation_id, worker_ref="response-worker-1", now=RECEIVED
    )

    assert result.row["classification"] == "UNSUBSCRIBE"
    assert result.row["suppression_ref"] is not None
    assert classifier.calls == policy.calls == 0
    assert AcquisitionStore(engine).get_opportunity(opportunity_id).state is AcquisitionState.REPLIED


def test_policy_denial_never_calls_classifier_and_becomes_ambiguous_review(tmp_path) -> None:
    engine, _, evaluation_id, _ = _ordinary_context(tmp_path)
    classifier = FakeClassifier(_positive())
    policy = FakePolicy(allowed=False)

    result = _worker(engine, FakeEmailReader(_email()), classifier, policy).process(
        evaluation_id, worker_ref="response-worker-1", now=RECEIVED
    )

    assert result.row["classification"] == "AMBIGUOUS"
    assert result.row["review_required"] is True
    assert result.row["hot_lead"] is False
    assert result.row["policy_status"] == "DENIED"
    assert classifier.calls == 0


def test_classifier_failure_is_ambiguous_and_cannot_become_hot(tmp_path) -> None:
    engine, _, evaluation_id, _ = _ordinary_context(tmp_path)
    classifier = FakeClassifier(error=TimeoutError("synthetic timeout"))

    result = _worker(
        engine, FakeEmailReader(_email()), classifier, FakePolicy()
    ).process(evaluation_id, worker_ref="response-worker-1", now=RECEIVED)

    assert result.row["classification"] == "AMBIGUOUS"
    assert result.row["reason_codes"] == ["CLASSIFIER_UNAVAILABLE"]
    assert result.row["hot_lead"] is False


def test_classifier_malformed_output_is_ambiguous_review(tmp_path) -> None:
    engine, _, evaluation_id, _ = _ordinary_context(tmp_path)
    classifier = FakeClassifier(output={"classification": "POSITIVE"})

    result = _worker(
        engine, FakeEmailReader(_email()), classifier, FakePolicy()
    ).process(evaluation_id, worker_ref="response-worker-1", now=RECEIVED)

    assert result.row["classification"] == "AMBIGUOUS"
    assert result.row["reason_codes"] == ["CLASSIFIER_MALFORMED"]
    assert result.row["hot_lead"] is False


def test_zero_candidate_retries_and_multiple_candidates_fail_review(tmp_path) -> None:
    engine, _, evaluation_id, _ = _ordinary_context(tmp_path)
    first = _worker(
        engine, FakeEmailReader(None), FakeClassifier(_positive()), FakePolicy()
    ).process(evaluation_id, worker_ref="response-worker-1", now=RECEIVED)
    assert first.status is ResponseWorkerStatus.RETRY_WAIT

    multiple_path = tmp_path / "multiple"
    multiple_path.mkdir()
    engine2, _, evaluation_id2, _ = _ordinary_context(multiple_path)
    classifier = FakeClassifier(_positive())
    multiple = _worker(
        engine2, FakeEmailReader(_email(), multiple=True), classifier, FakePolicy()
    ).process(evaluation_id2, worker_ref="response-worker-2", now=RECEIVED)
    assert multiple.status is ResponseWorkerStatus.FINALIZED
    assert multiple.row["classification"] == "AMBIGUOUS"
    assert multiple.row["reason_codes"] == ["RESPONSE_IDENTITY_AMBIGUOUS"]
    assert classifier.calls == 0


def test_duplicate_worker_execution_replays_one_business_outcome(tmp_path) -> None:
    engine, _, evaluation_id, _ = _ordinary_context(tmp_path)
    classifier = FakeClassifier(_positive())
    worker = _worker(engine, FakeEmailReader(_email()), classifier, FakePolicy())

    first = worker.process(evaluation_id, worker_ref="worker-a", now=RECEIVED)
    replay = worker.process(
        evaluation_id,
        worker_ref="worker-b",
        now=RECEIVED + dt.timedelta(seconds=1),
    )

    assert first.status is ResponseWorkerStatus.FINALIZED
    assert replay.status is ResponseWorkerStatus.REPLAYED
    assert classifier.calls == 1
    with engine.connect() as connection:
        outcome_count = connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_event)
            .where(acquisition_event.c.event_type == "OUTCOME_RECORDED")
        )
    assert outcome_count == 1


def test_raw_email_and_model_markers_never_enter_durable_rows_or_policy_facts(
    tmp_path,
) -> None:
    engine, _, evaluation_id, _ = _ordinary_context(tmp_path)
    markers = {
        "subject": "SYNTHETIC-SUBJECT-PII",
        "body": "SYNTHETIC-BODY-PII",
        "html": "SYNTHETIC-HTML-PII",
        "message": "SYNTHETIC-MESSAGE-ID-PII",
    }
    email = _email(
        subject=markers["subject"],
        message_id=markers["message"],
        body={"text": markers["body"], "html": markers["html"]},
    )
    policy = FakePolicy()

    _worker(engine, FakeEmailReader(email), FakeClassifier(_negative()), policy).process(
        evaluation_id, worker_ref="response-worker-1", now=RECEIVED
    )

    with engine.connect() as connection:
        durable = str(
            [
                dict(row)
                for table in (
                    acquisition_response_evaluation,
                    acquisition_provider_event,
                    acquisition_event,
                )
                for row in connection.execute(sa.select(table)).mappings().all()
            ]
        )
    assert all(marker not in durable for marker in markers.values())
    assert all(marker not in str(policy.facts) for marker in markers.values())


def test_real_policy_gateway_dual_audits_exact_classify_response_authority(
    tmp_path,
) -> None:
    engine, _, evaluation_id, _ = _ordinary_context(tmp_path)
    evaluated_at = RECEIVED + dt.timedelta(minutes=16)
    PolicyStore(engine).append_control(
        control(
            5,
            autonomy_mode=AutonomyMode.AUTONOMOUS_CAPPED,
            allowed_commands=("classify_response",),
            allowed_countries=("FR",),
            allowed_languages=("fr",),
            allowed_wedges=("construction",),
            effective_at=evaluated_at - dt.timedelta(minutes=1),
        )
    )
    current_control = PolicyStore(engine).get_effective_control(evaluated_at)
    authorizer = GatewayResponsePolicyAuthorizer(
        engine,
        operational_provider=lambda facts, now: OperationalReadiness(
            runtime_revision="response-runtime-v1"
        ),
        budget_usage_provider=lambda facts, now: BudgetUsage(),
        currency=current_control.currency,
    )

    result = _worker(
        engine,
        FakeEmailReader(_email()),
        FakeClassifier(_negative()),
        authorizer,
    ).process(evaluation_id, worker_ref="response-worker-1", now=evaluated_at)

    assert result.row["policy_status"] == "APPROVED"
    with engine.connect() as connection:
        response_policy = connection.execute(
            sa.select(policy_evaluation).where(
                policy_evaluation.c.command == "classify_response"
            )
        ).mappings().one()
        audit = connection.execute(
            sa.select(acquisition_event).where(
                acquisition_event.c.idempotency_key
                == f"policy_evaluation:{response_policy['evaluation_id']}"
            )
        ).mappings().one()
    assert response_policy["proposed_volume"] == 0
    assert response_policy["estimated_cost"] == Decimal("0.01")
    assert audit["event_type"] == "POLICY_EVALUATED"


def test_crash_after_classifier_before_commit_reclaims_without_duplicate_outcome(
    tmp_path, monkeypatch
) -> None:
    engine, _, evaluation_id, _ = _ordinary_context(tmp_path)
    classifier = FakeClassifier(_positive())
    worker = _worker(engine, FakeEmailReader(_email()), classifier, FakePolicy())

    def crash_before_commit(*args, **kwargs):
        raise RuntimeError("synthetic process crash")

    monkeypatch.setattr(worker, "_finalize", crash_before_commit)
    with pytest.raises(RuntimeError, match="synthetic process crash"):
        worker.process(evaluation_id, worker_ref="worker-a", now=RECEIVED)

    with engine.connect() as connection:
        row = connection.execute(
            sa.select(acquisition_response_evaluation)
        ).mappings().one()
        assert row["processing_state"] == "IN_FLIGHT"
        assert row["classification"] is None
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_event)
            .where(acquisition_event.c.event_type == "OUTCOME_RECORDED")
        ) == 0

    recovered = _worker(
        engine, FakeEmailReader(_email()), classifier, FakePolicy()
    ).process(
        evaluation_id,
        worker_ref="worker-b",
        now=RECEIVED + dt.timedelta(minutes=6),
    )

    assert recovered.status is ResponseWorkerStatus.FINALIZED
    assert classifier.calls == 2
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_event)
            .where(acquisition_event.c.event_type == "OUTCOME_RECORDED")
        ) == 1


def test_crash_during_final_transaction_rolls_back_every_local_effect(
    tmp_path, monkeypatch
) -> None:
    engine, _, evaluation_id, _ = _ordinary_context(tmp_path)
    worker = _worker(
        engine, FakeEmailReader(_email()), FakeClassifier(_negative()), FakePolicy()
    )
    original = ResponseStore.finalize_in_transaction

    def fail_final_compare_and_set(*args, **kwargs):
        raise RuntimeError("synthetic final transaction crash")

    monkeypatch.setattr(
        ResponseStore,
        "finalize_in_transaction",
        staticmethod(fail_final_compare_and_set),
    )
    with pytest.raises(RuntimeError, match="final transaction"):
        worker.process(evaluation_id, worker_ref="worker-a", now=RECEIVED)
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_event)
            .where(acquisition_event.c.event_type == "OUTCOME_RECORDED")
        ) == 0
        assert connection.scalar(
            sa.select(acquisition_response_evaluation.c.classification)
        ) is None

    monkeypatch.setattr(
        ResponseStore, "finalize_in_transaction", staticmethod(original)
    )
    recovered = _worker(
        engine, FakeEmailReader(_email()), FakeClassifier(_negative()), FakePolicy()
    ).process(
        evaluation_id,
        worker_ref="worker-b",
        now=RECEIVED + dt.timedelta(minutes=6),
    )
    assert recovered.status is ResponseWorkerStatus.FINALIZED


def test_late_human_reply_is_audited_without_downgrading_higher_outcome(
    tmp_path,
) -> None:
    engine, opportunity_id, evaluation_id, _ = _ordinary_context(tmp_path)
    acquisition = AcquisitionStore(engine)
    current = acquisition.get_opportunity(opportunity_id)
    acquisition.record_outcome(
        opportunity_id,
        outcome_state=AcquisitionState.ACTIVATED,
        expected_version=current.stream_version,
        idempotency_key="synthetic-activation-before-response",
        occurred_at=RECEIVED,
    )

    _worker(
        engine, FakeEmailReader(_email()), FakeClassifier(_negative()), FakePolicy()
    ).process(evaluation_id, worker_ref="response-worker-1", now=RECEIVED)

    assert AcquisitionStore(engine).get_opportunity(
        opportunity_id
    ).state is AcquisitionState.ACTIVATED
    with engine.connect() as connection:
        replied_events = connection.execute(
            sa.select(acquisition_event).where(
                acquisition_event.c.event_type == "OUTCOME_RECORDED",
                acquisition_event.c.payload["outcome_state"].as_string() == "REPLIED",
            )
        ).mappings().all()
    assert len(replied_events) == 1
