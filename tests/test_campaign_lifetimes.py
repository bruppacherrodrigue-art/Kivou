from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from test_campaign_service import NOW, FakeReadiness, _deployment, _keyring, _service
from test_campaign_worker import _operation, _planned
from test_policy_persistence import control

from signals.campaigns.contracts import (
    CampaignDeploymentBlocked,
    CampaignInputChanged,
    LeadRiskReductionContractProof,
    MailboxReadiness,
    MailboxReadinessState,
    ProviderOperationKind,
    TransportContractProof,
    WebhookEntitlement,
)
from signals.campaigns.store import CampaignStore
from signals.campaigns.webhooks import InstantlyWebhookService, WebhookFingerprintKeyring
from signals.compliance.contracts import (
    SuppressionReasonCode,
    SuppressionSource,
)
from signals.compliance.store import SuppressionStore
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_event,
    acquisition_policy_snapshot,
    acquisition_provider_operation,
    policy_evaluation,
)
from signals.policy.contracts import AutonomyMode
from signals.policy.store import PolicyStore


def _waiting_step_2(tmp_path):
    engine, opportunity_id, service, _provider, worker, result = _planned(tmp_path)
    for kind in (
        ProviderOperationKind.CREATE_CAMPAIGN,
        ProviderOperationKind.CONFIGURE_CAMPAIGN,
        ProviderOperationKind.ADD_LEAD,
    ):
        worker.process(_operation(engine, kind)["operation_ref"], NOW)
    CampaignStore(engine).close_due_batches(NOW + dt.timedelta(minutes=15))
    activation_ref = service.queue_and_seal(
        result.campaign_ref, captured_at=NOW + dt.timedelta(minutes=16)
    )
    worker.process(activation_ref, NOW + dt.timedelta(minutes=16))
    webhook = InstantlyWebhookService(
        engine,
        provider_workspace_ref="workspace:test",
        fingerprint_keyring=WebhookFingerprintKeyring(
            current_key_version="webhook-test-v1",
            keys={"webhook-test-v1": b"synthetic-event-key"},
        ),
        suppression_keyring=_keyring(),
        response_ingress_capability="NONE",
    )
    webhook.ingest(
        {
            "event_type": "email_sent",
            "timestamp": "2026-08-21T13:30:00+00:00",
            "workspace_id": "workspace:test",
            "campaign_id": "provider-campaign-1",
            "lead_id": "provider-lead-1",
            "email_id": "step-one-event",
            "step": 1,
            "status": "sent",
        },
        received_at=NOW + dt.timedelta(minutes=31),
    )
    worker.process(
        _operation(engine, ProviderOperationKind.PAUSE_CAMPAIGN)["operation_ref"],
        NOW + dt.timedelta(minutes=32),
    )
    return engine, opportunity_id, service, result, worker


def _member(engine):
    with engine.connect() as connection:
        return connection.execute(sa.select(acquisition_campaign_member)).mappings().one()


def _queued_before_activation(tmp_path):
    engine, _, service, _provider, worker, result = _planned(tmp_path)
    for kind in (
        ProviderOperationKind.CREATE_CAMPAIGN,
        ProviderOperationKind.CONFIGURE_CAMPAIGN,
        ProviderOperationKind.ADD_LEAD,
    ):
        worker.process(_operation(engine, kind)["operation_ref"], NOW)
    CampaignStore(engine).close_due_batches(NOW + dt.timedelta(minutes=15))
    service.queue_and_seal(result.campaign_ref, captured_at=NOW + dt.timedelta(minutes=16))
    return engine, service, result


def test_suppression_after_queue_stops_member_before_activation(tmp_path) -> None:
    engine, service, result = _queued_before_activation(tmp_path)
    member = _member(engine)
    SuppressionStore(engine, _keyring()).record_for_contact(
        member["contact_ref"],
        source=SuppressionSource.UNSUBSCRIBE,
        reason_code=SuppressionReasonCode.UNSUBSCRIBED,
        evidence_ref=f"suppression-evidence:{'8' * 64}",
        received_at=NOW + dt.timedelta(minutes=17),
    )

    with pytest.raises(CampaignInputChanged, match="queued member"):
        service.require_activation(
            result.campaign_ref, captured_at=NOW + dt.timedelta(minutes=18)
        )

    member = _member(engine)
    assert member["execution_state"] == "STOPPED"
    assert member["sequence_state"] == "STOPPED"
    assert member["reason_code"] == "PRE_ACTIVATION_AUTHORIZATION_CHANGED"
    assert _operation(engine, ProviderOperationKind.PAUSE_LEAD)["state"] == "PLANNED"


def test_suppression_after_enrollment_removes_only_member_and_fails_batch(tmp_path) -> None:
    engine, _, service, _provider, worker, result = _planned(tmp_path)
    for kind in (
        ProviderOperationKind.CREATE_CAMPAIGN,
        ProviderOperationKind.CONFIGURE_CAMPAIGN,
        ProviderOperationKind.ADD_LEAD,
    ):
        worker.process(_operation(engine, kind)["operation_ref"], NOW)
    CampaignStore(engine).close_due_batches(NOW + dt.timedelta(minutes=15))
    member = _member(engine)
    SuppressionStore(engine, _keyring()).record_for_contact(
        member["contact_ref"],
        source=SuppressionSource.UNSUBSCRIBE,
        reason_code=SuppressionReasonCode.UNSUBSCRIBED,
        evidence_ref=f"suppression-evidence:{'7' * 64}",
        received_at=NOW + dt.timedelta(minutes=15),
    )

    with pytest.raises(CampaignInputChanged, match="no eligible"):
        service.queue_and_seal(
            result.campaign_ref, captured_at=NOW + dt.timedelta(minutes=16)
        )

    with engine.connect() as connection:
        campaign = connection.execute(sa.select(acquisition_campaign)).mappings().one()
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
        queued_events = connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_event).where(
                acquisition_event.c.event_type == "STATE_TRANSITIONED",
                acquisition_event.c.reason_codes == ["CAMPAIGN_MEMBER_QUEUED"],
            )
        )
    assert campaign["lifecycle"] == "FAILED"
    assert member["execution_state"] == "STOPPED"
    assert queued_events == 0


def test_expired_policy_before_activation_stops_member(tmp_path) -> None:
    engine, service, result = _queued_before_activation(tmp_path)

    with pytest.raises(CampaignInputChanged, match="Policy freshness"):
        service.require_activation(
            result.campaign_ref, captured_at=NOW + dt.timedelta(hours=1, minutes=30)
        )

    assert _member(engine)["execution_state"] == "STOPPED"


def test_historical_policy_and_compliance_expiry_do_not_reauthorize_step_2(tmp_path) -> None:
    engine, _, service, result, _worker = _waiting_step_2(tmp_path)
    with engine.connect() as connection:
        before = connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation))

    service.require_step_2_safety(
        result.campaign_ref,
        captured_at=NOW + dt.timedelta(days=4, minutes=31),
    )

    assert _member(engine)["sequence_state"] == "WAITING_STEP2"
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == before


def test_step_two_release_requires_durable_pause_and_live_safety_without_new_policy(
    tmp_path,
) -> None:
    engine, _, _, result, worker = _waiting_step_2(tmp_path)
    captured_at = NOW + dt.timedelta(days=4, minutes=31)
    with engine.connect() as connection:
        before = connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation))

    operation_ref = worker.plan_step_2_release(result.campaign_ref, captured_at)
    state = worker.process(operation_ref, captured_at)

    assert state.value == "CONFIRMED"
    assert CampaignStore(engine).get_campaign(result.campaign_ref)["lifecycle"] == "ACTIVE"
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == before


@pytest.mark.parametrize("hard_stop", ["kill_switch", "read_only"])
def test_current_policy_hard_stop_stops_step_2(tmp_path, hard_stop) -> None:
    engine, _, service, result, _worker = _waiting_step_2(tmp_path)
    PolicyStore(engine).append_control(
        control(
            5,
            autonomy_mode=AutonomyMode.ASSISTED,
            allowed_commands=("schedule_campaign",),
            allowed_countries=("FR",),
            allowed_languages=("fr",),
            allowed_wedges=("construction",),
            effective_at=NOW + dt.timedelta(days=4),
            created_at=NOW + dt.timedelta(days=4),
            **{hard_stop: True},
        )
    )

    with pytest.raises(CampaignDeploymentBlocked, match=hard_stop):
        service.require_step_2_safety(
            result.campaign_ref,
            captured_at=NOW + dt.timedelta(days=4, minutes=31),
        )

    assert _member(engine)["sequence_state"] == "STOPPED"
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_provider_operation).where(
                acquisition_provider_operation.c.kind == "PAUSE_CAMPAIGN"
            )
        ) == 2


def test_unavailable_live_policy_control_fails_closed(tmp_path) -> None:
    engine, _, service, result, _worker = _waiting_step_2(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            sa.update(acquisition_policy_snapshot).values(
                expires_at=NOW + dt.timedelta(days=1)
            )
        )

    with pytest.raises(CampaignDeploymentBlocked, match="control unavailable"):
        service.require_step_2_safety(
            result.campaign_ref,
            captured_at=NOW + dt.timedelta(days=4, minutes=31),
        )

    assert _member(engine)["sequence_state"] == "STOPPED"


def test_new_ordinary_control_revision_does_not_rewrite_sequence(tmp_path) -> None:
    engine, _, service, result, _worker = _waiting_step_2(tmp_path)
    PolicyStore(engine).append_control(
        control(
            6,
            autonomy_mode=AutonomyMode.ASSISTED,
            allowed_commands=("schedule_campaign",),
            allowed_countries=("FR",),
            allowed_languages=("fr",),
            allowed_wedges=("construction",),
            effective_at=NOW + dt.timedelta(days=4),
            created_at=NOW + dt.timedelta(days=4),
        )
    )

    service.require_step_2_safety(
        result.campaign_ref,
        captured_at=NOW + dt.timedelta(days=4, minutes=31),
    )

    assert _member(engine)["sequence_state"] == "WAITING_STEP2"


def test_new_suppression_after_step_one_stops_step_two(tmp_path) -> None:
    engine, _, service, result, _worker = _waiting_step_2(tmp_path)
    member = _member(engine)
    SuppressionStore(engine, _keyring()).record_for_contact(
        member["contact_ref"],
        source=SuppressionSource.RECIPIENT_OBJECTION,
        reason_code=SuppressionReasonCode.RECIPIENT_OBJECTED,
        evidence_ref=f"suppression-evidence:{'9' * 64}",
        received_at=NOW + dt.timedelta(days=1),
    )

    with pytest.raises(CampaignDeploymentBlocked, match="suppression"):
        service.require_step_2_safety(
            result.campaign_ref,
            captured_at=NOW + dt.timedelta(days=4, minutes=31),
        )

    assert _member(engine)["execution_state"] == "SENT"
    assert _member(engine)["sequence_state"] == "STOPPED"


class UnknownReadiness(FakeReadiness):
    def get(self, provider_account_id: str, *, observed_at: dt.datetime) -> MailboxReadiness:
        return MailboxReadiness(
            state=MailboxReadinessState.UNKNOWN,
            provider_daily_limit=0,
            sending_gap_seconds=0,
            observed_at=observed_at,
        )


class TemporaryReadiness(FakeReadiness):
    def get(self, provider_account_id: str, *, observed_at: dt.datetime) -> MailboxReadiness:
        return MailboxReadiness(
            state=MailboxReadinessState.TEMPORARILY_UNAVAILABLE,
            provider_daily_limit=1,
            sending_gap_seconds=300,
            observed_at=observed_at,
        )


def test_unknown_mailbox_at_step_two_fails_closed(tmp_path) -> None:
    engine, _, _, result, _worker = _waiting_step_2(tmp_path)
    deployment = _deployment().model_copy(
        update={
            "transport_contract_proof": TransportContractProof.VERIFIED,
            "lead_risk_reduction_contract_proof": (
                LeadRiskReductionContractProof.VERIFIED
            ),
            "webhook_entitlement": WebhookEntitlement.VERIFIED,
        }
    )
    service = _service(engine, deployment, readiness=UnknownReadiness())

    with pytest.raises(CampaignDeploymentBlocked, match="mailbox UNKNOWN"):
        service.require_step_2_safety(
            result.campaign_ref,
            captured_at=NOW + dt.timedelta(days=4, minutes=31),
        )

    assert _member(engine)["sequence_state"] == "STOPPED"


def test_temporary_mailbox_unavailability_pauses_without_false_stop(tmp_path) -> None:
    engine, _, _, result, _worker = _waiting_step_2(tmp_path)
    deployment = _deployment().model_copy(
        update={
            "transport_contract_proof": TransportContractProof.VERIFIED,
            "lead_risk_reduction_contract_proof": (
                LeadRiskReductionContractProof.VERIFIED
            ),
            "webhook_entitlement": WebhookEntitlement.VERIFIED,
        }
    )
    service = _service(engine, deployment, readiness=TemporaryReadiness())

    with pytest.raises(CampaignDeploymentBlocked, match="temporarily"):
        service.require_step_2_safety(
            result.campaign_ref,
            captured_at=NOW + dt.timedelta(days=4, minutes=31),
        )

    assert _member(engine)["sequence_state"] == "WAITING_STEP2"
    with engine.connect() as connection:
        pause_states = connection.execute(
            sa.select(acquisition_provider_operation.c.state).where(
                acquisition_provider_operation.c.kind == "PAUSE_CAMPAIGN"
            )
        ).scalars().all()
    assert sorted(pause_states) == ["CONFIRMED", "PLANNED"]


def test_step_two_window_expiry_fails_sequence_without_new_campaign(tmp_path) -> None:
    engine, _, _, _result, worker = _waiting_step_2(tmp_path)

    expired = worker.expire_authorization_windows(
        dt.datetime(2026, 8, 25, 15, tzinfo=dt.UTC)
    )

    assert expired == (0, 1)
    member = _member(engine)
    assert member["execution_state"] == "SENT"
    assert member["sequence_state"] == "FAILED"
    assert member["reason_code"] == "STEP2_WINDOW_EXPIRED"
