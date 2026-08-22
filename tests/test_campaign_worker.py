from __future__ import annotations

import datetime as dt
import threading

import pytest
import sqlalchemy as sa
from test_campaign_service import (
    NOW,
    _authorization,
    _deployment,
    _keyring,
    _prepared,
    _service,
)
from test_policy_persistence import control

from signals.acquisition.contracts import AcquisitionState
from signals.acquisition.store import AcquisitionStore
from signals.campaigns.contracts import (
    CampaignInputChanged,
    LeadRiskReductionContractProof,
    ProviderOperationKind,
    ProviderOperationState,
    TransportContractProof,
    WebhookEntitlement,
)
from signals.campaigns.instantly import (
    InstantlyErrorCode,
    InstantlyProviderError,
    ProviderCampaign,
    ProviderMutationResult,
)
from signals.campaigns.store import CampaignStore
from signals.campaigns.worker import CampaignWorker
from signals.compliance.contracts import SuppressionReasonCode, SuppressionSource
from signals.compliance.store import SuppressionStore
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_contact,
    acquisition_provider_operation,
)
from signals.policy.contracts import ApprovalGrant, ApprovalPurpose, AutonomyMode, BudgetUsage
from signals.policy.store import PolicyStore


class FakeInstantly:
    def __init__(
        self,
        *,
        create_timeout: bool = False,
        configure_timeout: bool = False,
        add_timeout: bool = False,
        activate_timeout: bool = False,
        pause_campaign_timeout: bool = False,
        pause_lead_timeout: bool = False,
    ) -> None:
        self.create_timeout = create_timeout
        self.configure_timeout = configure_timeout
        self.add_timeout = add_timeout
        self.activate_timeout = activate_timeout
        self.pause_campaign_timeout = pause_campaign_timeout
        self.pause_lead_timeout = pause_lead_timeout
        self.create_calls = 0
        self.configure_calls = 0
        self.add_calls = 0
        self.activate_calls = 0
        self.pause_campaign_calls = 0
        self.pause_lead_calls = 0
        self.leads = []
        self.campaign = ProviderCampaign(
            provider_campaign_id="provider-campaign-1",
            name="KIVOU-placeholder",
            status="draft",
            normalized_config=None,
        )

    def create_campaign(self, *, name, provider_config):
        self.create_calls += 1
        self.campaign = ProviderCampaign(
            provider_campaign_id="provider-campaign-1",
            name=name,
            status="draft",
            normalized_config=provider_config,
        )
        if self.create_timeout:
            self.create_timeout = False
            raise InstantlyProviderError(
                InstantlyErrorCode.TIMEOUT, reconciliation_required=True
            )
        return self.campaign

    def list_campaigns(self, *, search):
        return (self.campaign,) if self.campaign.name == search else ()

    def get_campaign(self, provider_campaign_id):
        assert provider_campaign_id == "provider-campaign-1"
        return self.campaign

    def configure_campaign(self, provider_campaign_id, *, provider_config):
        self.configure_calls += 1
        self.campaign = self.campaign.model_copy(
            update={"normalized_config": provider_config}
        )
        if self.configure_timeout:
            self.configure_timeout = False
            raise InstantlyProviderError(
                InstantlyErrorCode.TIMEOUT, reconciliation_required=True
            )
        return self.campaign

    def create_lead_or_batch(self, *, provider_campaign_id, leads):
        self.add_calls += 1
        assert len(leads) == 1
        value = {
            "id": "provider-lead-1",
            "status": 1,
            "campaign_id": provider_campaign_id,
            "email": leads[0]["email"],
            "custom_variables": leads[0]["custom_variables"],
        }
        self.leads = [value]
        if self.add_timeout:
            self.add_timeout = False
            raise InstantlyProviderError(
                InstantlyErrorCode.TIMEOUT, reconciliation_required=True
            )
        return value

    def list_leads(self, *, provider_campaign_id):
        return {"items": self.leads}

    def get_lead(self, provider_lead_id):
        return next(item for item in self.leads if item["id"] == provider_lead_id)

    def activate_campaign(self, provider_campaign_id):
        self.activate_calls += 1
        self.campaign = self.campaign.model_copy(update={"status": "active"})
        if self.activate_timeout:
            self.activate_timeout = False
            raise InstantlyProviderError(
                InstantlyErrorCode.TIMEOUT, reconciliation_required=True
            )
        return ProviderMutationResult(provider_identity=provider_campaign_id, status="active")

    def pause_campaign(self, provider_campaign_id):
        self.pause_campaign_calls += 1
        self.campaign = self.campaign.model_copy(update={"status": "paused"})
        if self.pause_campaign_timeout:
            self.pause_campaign_timeout = False
            raise InstantlyProviderError(
                InstantlyErrorCode.TIMEOUT, reconciliation_required=True
            )
        return ProviderMutationResult(provider_identity=provider_campaign_id, status="paused")

    def pause_lead(self, provider_lead_id):
        self.pause_lead_calls += 1
        self.leads = [
            {**lead, "status": 2} if lead["id"] == provider_lead_id else lead
            for lead in self.leads
        ]
        if self.pause_lead_timeout:
            self.pause_lead_timeout = False
            raise InstantlyProviderError(
                InstantlyErrorCode.TIMEOUT, reconciliation_required=True
            )
        return {"id": provider_lead_id, "status": 2}


def _planned(tmp_path, **provider_options):
    engine, opportunity_id, _, _ = _prepared(tmp_path)
    PolicyStore(engine).append_control(
        control(
            4,
            autonomy_mode=AutonomyMode.ASSISTED,
            allowed_commands=("schedule_campaign",),
            allowed_countries=("FR",),
            allowed_languages=("fr",),
            allowed_wedges=("construction",),
            effective_at=NOW - dt.timedelta(minutes=1),
        )
    )
    deployment = _deployment().model_copy(
        update={
            "transport_contract_proof": TransportContractProof.VERIFIED,
            "lead_risk_reduction_contract_proof": (
                LeadRiskReductionContractProof.VERIFIED
            ),
            "webhook_entitlement": WebhookEntitlement.VERIFIED,
        }
    )
    service = _service(engine, deployment)
    preview = service.preview(opportunity_id, captured_at=NOW)
    snapshot = PolicyStore(engine).get_effective_control(NOW)
    authorization = _authorization()
    grant = ApprovalGrant(
        approval_id="approval-worker-action",
        purpose=ApprovalPurpose.ACTION,
        command="schedule_campaign",
        target_ref=f"acquisition-opportunity:{opportunity_id}",
        acquisition_opportunity_id=opportunity_id,
        action_fingerprint=preview.action_fingerprint,
        policy_version=snapshot.policy_version,
        policy_snapshot_id=snapshot.policy_snapshot_id,
        control_revision=snapshot.control_revision,
        scope_fingerprint=authorization.scope.fingerprint(),
        issued_at=NOW - dt.timedelta(minutes=1),
        expires_at=NOW + dt.timedelta(hours=1),
        approved_by_actor_ref="supervisor:test",
    )
    result = service.schedule(
        opportunity_id,
        _authorization(approval_grants=(grant,)),
        budget_usage=BudgetUsage(),
    )
    provider = FakeInstantly(**provider_options)
    worker = CampaignWorker(
        engine,
        provider=provider,
        campaign_service=service,
        deployment=deployment,
        worker_ref="worker:test",
    )
    return engine, opportunity_id, service, provider, worker, result


def _operation(engine, kind: ProviderOperationKind):
    with engine.connect() as connection:
        return connection.execute(
            sa.select(acquisition_provider_operation).where(
                acquisition_provider_operation.c.kind == kind.value
            )
        ).mappings().one()


def test_worker_orders_create_configure_add_queue_then_activate(tmp_path) -> None:
    engine, opportunity_id, service, provider, worker, result = _planned(tmp_path)
    store = CampaignStore(engine)

    worker.process(_operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["operation_ref"], NOW)
    worker.process(_operation(engine, ProviderOperationKind.CONFIGURE_CAMPAIGN)["operation_ref"], NOW)
    worker.process(_operation(engine, ProviderOperationKind.ADD_LEAD)["operation_ref"], NOW)
    store.close_due_batches(NOW + dt.timedelta(minutes=15))
    activation_ref = service.queue_and_seal(
        result.campaign_ref, captured_at=NOW + dt.timedelta(minutes=16)
    )

    opportunity = AcquisitionStore(engine).get_opportunity(opportunity_id)
    assert opportunity.state is AcquisitionState.QUEUED
    assert opportunity.campaign_ref == result.campaign_ref
    assert opportunity.next_action is None
    with engine.connect() as connection:
        campaign = connection.execute(sa.select(acquisition_campaign)).mappings().one()
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
    assert campaign["lifecycle"] == "SEALED"
    assert member["execution_state"] == "QUEUED"
    assert provider.activate_calls == 0

    worker.process(activation_ref, NOW + dt.timedelta(minutes=16))

    assert provider.activate_calls == 1
    assert CampaignStore(engine).get_campaign(result.campaign_ref)["lifecycle"] == "ACTIVE"


def test_membership_closed_building_waits_for_reserved_enrollment(tmp_path) -> None:
    engine, _, service, _, worker, result = _planned(tmp_path)
    store = CampaignStore(engine)
    worker.process(_operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["operation_ref"], NOW)
    worker.process(_operation(engine, ProviderOperationKind.CONFIGURE_CAMPAIGN)["operation_ref"], NOW)
    store.close_due_batches(NOW + dt.timedelta(minutes=15))

    with pytest.raises(CampaignInputChanged, match="reconcile"):
        service.queue_and_seal(
            result.campaign_ref, captured_at=NOW + dt.timedelta(minutes=16)
        )

    assert store.get_campaign(result.campaign_ref)["lifecycle"] == "BUILDING"
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_provider_operation)
            .where(acquisition_provider_operation.c.kind == "ACTIVATE_CAMPAIGN")
        ) == 0


def test_create_timeout_reconciles_before_any_retry(tmp_path) -> None:
    engine, _, _, provider, worker, _ = _planned(tmp_path, create_timeout=True)
    operation_ref = _operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["operation_ref"]

    worker.process(operation_ref, NOW)

    assert provider.create_calls == 1
    assert CampaignStore(engine).get_operation(operation_ref).state is (
        ProviderOperationState.RECONCILE_REQUIRED
    )

    worker.process(operation_ref, NOW + dt.timedelta(minutes=1))

    assert provider.create_calls == 1
    assert CampaignStore(engine).get_operation(operation_ref).state is ProviderOperationState.CONFIRMED


def test_create_reconciliation_rejects_same_name_with_wrong_config(tmp_path) -> None:
    engine, _, _, provider, worker, _ = _planned(tmp_path, create_timeout=True)
    operation_ref = _operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["operation_ref"]

    assert worker.process(operation_ref, NOW) is ProviderOperationState.RECONCILE_REQUIRED
    provider.campaign = provider.campaign.model_copy(update={"normalized_config": {}})

    assert worker.process(operation_ref, NOW + dt.timedelta(minutes=1)) is (
        ProviderOperationState.TERMINAL_FAILED
    )
    assert provider.create_calls == 1


def test_create_success_rejects_wrong_remote_identity_before_binding(tmp_path) -> None:
    engine, _, _, provider, worker, _ = _planned(tmp_path)
    original_create = provider.create_campaign

    def wrong_name(*, name, provider_config):
        remote = original_create(name=name, provider_config=provider_config)
        return remote.model_copy(update={"name": "KIVOU-collision"})

    provider.create_campaign = wrong_name
    operation_ref = _operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["operation_ref"]

    assert worker.process(operation_ref, NOW) is ProviderOperationState.RECONCILE_REQUIRED
    assert CampaignStore(engine).get_campaign(
        _operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["campaign_ref"]
    )["provider_campaign_id"] is None


def test_configure_timeout_reconciles_by_exact_readback_without_second_patch(tmp_path) -> None:
    engine, _, _, provider, worker, _ = _planned(tmp_path, configure_timeout=True)
    worker.process(_operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["operation_ref"], NOW)
    operation_ref = _operation(engine, ProviderOperationKind.CONFIGURE_CAMPAIGN)["operation_ref"]

    assert worker.process(operation_ref, NOW) is ProviderOperationState.RECONCILE_REQUIRED
    assert worker.process(operation_ref, NOW + dt.timedelta(minutes=1)) is ProviderOperationState.CONFIRMED
    assert provider.configure_calls == 1


def test_add_lead_timeout_reconciles_exact_member_without_second_post(tmp_path) -> None:
    engine, _, _, provider, worker, _ = _planned(tmp_path, add_timeout=True)
    worker.process(_operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["operation_ref"], NOW)
    worker.process(_operation(engine, ProviderOperationKind.CONFIGURE_CAMPAIGN)["operation_ref"], NOW)
    operation_ref = _operation(engine, ProviderOperationKind.ADD_LEAD)["operation_ref"]

    assert worker.process(operation_ref, NOW) is ProviderOperationState.RECONCILE_REQUIRED
    assert worker.process(operation_ref, NOW + dt.timedelta(minutes=1)) is ProviderOperationState.CONFIRMED
    assert provider.add_calls == 1
    with engine.connect() as connection:
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
    assert member["provider_lead_id"] == "provider-lead-1"
    assert member["execution_state"] == "ENROLLED"


def test_activation_timeout_reconciles_active_campaign_with_already_queued_member(tmp_path) -> None:
    engine, _, service, provider, worker, result = _planned(tmp_path, activate_timeout=True)
    store = CampaignStore(engine)
    for kind in (
        ProviderOperationKind.CREATE_CAMPAIGN,
        ProviderOperationKind.CONFIGURE_CAMPAIGN,
        ProviderOperationKind.ADD_LEAD,
    ):
        worker.process(_operation(engine, kind)["operation_ref"], NOW)
    store.close_due_batches(NOW + dt.timedelta(minutes=15))
    activation_ref = service.queue_and_seal(
        result.campaign_ref, captured_at=NOW + dt.timedelta(minutes=16)
    )

    assert worker.process(activation_ref, NOW + dt.timedelta(minutes=16)) is (
        ProviderOperationState.RECONCILE_REQUIRED
    )
    assert _operation(engine, ProviderOperationKind.ACTIVATE_CAMPAIGN)["state"] == (
        "RECONCILE_REQUIRED"
    )
    assert worker.process(activation_ref, NOW + dt.timedelta(minutes=17)) is (
        ProviderOperationState.CONFIRMED
    )
    assert provider.activate_calls == 1
    assert store.get_campaign(result.campaign_ref)["lifecycle"] == "ACTIVE"


def test_activation_waits_for_unconfirmed_member_risk_reduction(tmp_path) -> None:
    engine, _, service, provider, worker, result = _planned(tmp_path)
    store = CampaignStore(engine)
    for kind in (
        ProviderOperationKind.CREATE_CAMPAIGN,
        ProviderOperationKind.CONFIGURE_CAMPAIGN,
        ProviderOperationKind.ADD_LEAD,
    ):
        worker.process(_operation(engine, kind)["operation_ref"], NOW)
    store.close_due_batches(NOW + dt.timedelta(minutes=15))
    activation_ref = service.queue_and_seal(
        result.campaign_ref, captured_at=NOW + dt.timedelta(minutes=16)
    )
    with engine.connect() as connection:
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
    store.plan_operation(
        ProviderOperationKind.PAUSE_LEAD,
        campaign_ref=result.campaign_ref,
        member_ref=member["member_ref"],
        desired_request_fingerprint=member["provider_binding_fingerprint"],
        correlation_id="excluded-member-risk-reduction",
        now=NOW + dt.timedelta(minutes=16),
    )

    assert worker.process(activation_ref, NOW + dt.timedelta(minutes=16)) is (
        ProviderOperationState.PLANNED
    )
    assert store.get_operation(activation_ref).state is ProviderOperationState.PLANNED
    assert provider.activate_calls == 0


def test_pause_campaign_timeout_reconciles_without_second_mutation(tmp_path) -> None:
    engine, _, service, provider, worker, result = _planned(
        tmp_path, pause_campaign_timeout=True
    )
    store = CampaignStore(engine)
    for kind in (
        ProviderOperationKind.CREATE_CAMPAIGN,
        ProviderOperationKind.CONFIGURE_CAMPAIGN,
        ProviderOperationKind.ADD_LEAD,
    ):
        worker.process(_operation(engine, kind)["operation_ref"], NOW)
    store.close_due_batches(NOW + dt.timedelta(minutes=15))
    activation_ref = service.queue_and_seal(
        result.campaign_ref, captured_at=NOW + dt.timedelta(minutes=16)
    )
    worker.process(activation_ref, NOW + dt.timedelta(minutes=16))
    campaign = store.get_campaign(result.campaign_ref)
    pause = store.plan_operation(
        ProviderOperationKind.PAUSE_CAMPAIGN,
        campaign_ref=result.campaign_ref,
        member_ref=None,
        desired_request_fingerprint=campaign["desired_provider_config_fingerprint"],
        correlation_id="pause-timeout",
        now=NOW + dt.timedelta(minutes=17),
    )

    assert worker.process(pause.operation_ref, NOW + dt.timedelta(minutes=17)) is (
        ProviderOperationState.RECONCILE_REQUIRED
    )
    assert worker.process(pause.operation_ref, NOW + dt.timedelta(minutes=18)) is (
        ProviderOperationState.CONFIRMED
    )
    assert provider.pause_campaign_calls == 1


def test_pause_lead_timeout_reconciles_without_second_mutation(tmp_path) -> None:
    engine, _, _, provider, worker, result = _planned(tmp_path, pause_lead_timeout=True)
    store = CampaignStore(engine)
    for kind in (
        ProviderOperationKind.CREATE_CAMPAIGN,
        ProviderOperationKind.CONFIGURE_CAMPAIGN,
        ProviderOperationKind.ADD_LEAD,
    ):
        worker.process(_operation(engine, kind)["operation_ref"], NOW)
    with engine.connect() as connection:
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
    pause = store.plan_operation(
        ProviderOperationKind.PAUSE_LEAD,
        campaign_ref=result.campaign_ref,
        member_ref=member["member_ref"],
        desired_request_fingerprint=member["provider_binding_fingerprint"],
        correlation_id="pause-lead-timeout",
        now=NOW + dt.timedelta(minutes=1),
    )

    assert worker.process(pause.operation_ref, NOW + dt.timedelta(minutes=1)) is (
        ProviderOperationState.RECONCILE_REQUIRED
    )
    assert worker.process(pause.operation_ref, NOW + dt.timedelta(minutes=2)) is (
        ProviderOperationState.CONFIRMED
    )
    assert provider.pause_lead_calls == 1


def test_pause_lead_two_hundred_active_state_never_confirms_risk_reduction(
    tmp_path,
) -> None:
    engine, _, _, provider, worker, result = _planned(tmp_path)
    store = CampaignStore(engine)
    for kind in (
        ProviderOperationKind.CREATE_CAMPAIGN,
        ProviderOperationKind.CONFIGURE_CAMPAIGN,
        ProviderOperationKind.ADD_LEAD,
    ):
        worker.process(_operation(engine, kind)["operation_ref"], NOW)
    with engine.connect() as connection:
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
    provider.pause_lead = lambda _provider_lead_id: {
        "id": "provider-lead-1",
        "status": 1,
    }
    pause = store.plan_operation(
        ProviderOperationKind.PAUSE_LEAD,
        campaign_ref=result.campaign_ref,
        member_ref=member["member_ref"],
        desired_request_fingerprint=member["provider_binding_fingerprint"],
        correlation_id="unsafe-pause-response",
        now=NOW + dt.timedelta(minutes=1),
    )

    assert worker.process(pause.operation_ref, NOW + dt.timedelta(minutes=1)) is (
        ProviderOperationState.RECONCILE_REQUIRED
    )
    assert store.get_operation(pause.operation_ref).state is (
        ProviderOperationState.RECONCILE_REQUIRED
    )


def test_pause_campaign_two_hundred_active_state_never_confirms_hold(tmp_path) -> None:
    engine, _, _, provider, worker, result = _planned(tmp_path)
    store = CampaignStore(engine)
    worker.process(_operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["operation_ref"], NOW)
    provider.pause_campaign = lambda _provider_campaign_id: ProviderMutationResult(
        provider_identity="provider-campaign-1", status="active"
    )
    pause = store.plan_operation(
        ProviderOperationKind.PAUSE_CAMPAIGN,
        campaign_ref=result.campaign_ref,
        member_ref=None,
        desired_request_fingerprint=store.get_campaign(result.campaign_ref)[
            "desired_provider_config_fingerprint"
        ],
        correlation_id="unsafe-campaign-pause-response",
        now=NOW + dt.timedelta(minutes=1),
    )

    assert worker.process(pause.operation_ref, NOW + dt.timedelta(minutes=1)) is (
        ProviderOperationState.RECONCILE_REQUIRED
    )


def test_window_expiry_never_rolls_step_one_or_step_two(tmp_path) -> None:
    engine, _, service, _, worker, result = _planned(tmp_path)
    store = CampaignStore(engine)
    for kind in (
        ProviderOperationKind.CREATE_CAMPAIGN,
        ProviderOperationKind.CONFIGURE_CAMPAIGN,
        ProviderOperationKind.ADD_LEAD,
    ):
        worker.process(_operation(engine, kind)["operation_ref"], NOW)
    store.close_due_batches(NOW + dt.timedelta(minutes=15))
    service.queue_and_seal(result.campaign_ref, captured_at=NOW + dt.timedelta(minutes=16))

    expired = worker.expire_authorization_windows(NOW + dt.timedelta(hours=4))

    assert expired == (1, 0)
    with engine.connect() as connection:
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
    assert member["execution_state"] == "FAILED"
    assert member["sequence_state"] == "FAILED"
    assert member["reason_code"] == "STEP1_WINDOW_EXPIRED"
    assert _operation(engine, ProviderOperationKind.PAUSE_LEAD)["state"] == "PLANNED"


def test_two_workers_cannot_claim_same_remote_mutation(tmp_path) -> None:
    engine, _, service, provider, worker_one, _ = _planned(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    original = provider.create_campaign

    def blocking_create(*, name, provider_config):
        entered.set()
        assert release.wait(timeout=5)
        return original(name=name, provider_config=provider_config)

    provider.create_campaign = blocking_create
    worker_two = CampaignWorker(
        engine,
        provider=provider,
        campaign_service=service,
        deployment=worker_one._deployment,
        worker_ref="worker:second",
    )
    operation_ref = _operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["operation_ref"]
    outcomes = []
    thread = threading.Thread(target=lambda: outcomes.append(worker_one.process(operation_ref, NOW)))
    thread.start()
    assert entered.wait(timeout=5)

    competing = worker_two.process(operation_ref, NOW + dt.timedelta(seconds=1))
    release.set()
    thread.join(timeout=5)

    assert competing is ProviderOperationState.IN_FLIGHT
    assert outcomes == [ProviderOperationState.CONFIRMED]
    assert provider.create_calls == 1


def test_suppression_before_add_lead_prevents_provider_exposure(tmp_path) -> None:
    engine, _, _, provider, worker, _ = _planned(tmp_path)
    worker.process(_operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["operation_ref"], NOW)
    worker.process(_operation(engine, ProviderOperationKind.CONFIGURE_CAMPAIGN)["operation_ref"], NOW)
    with engine.connect() as connection:
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
    SuppressionStore(engine, _keyring()).record_for_contact(
        member["contact_ref"],
        source=SuppressionSource.RECIPIENT_OBJECTION,
        reason_code=SuppressionReasonCode.RECIPIENT_OBJECTED,
        evidence_ref=f"suppression-evidence:{'6' * 64}",
        received_at=NOW,
    )
    operation_ref = _operation(engine, ProviderOperationKind.ADD_LEAD)["operation_ref"]

    with pytest.raises(CampaignInputChanged):
        worker.process(operation_ref, NOW + dt.timedelta(minutes=1))

    assert provider.add_calls == 0
    assert CampaignStore(engine).get_operation(operation_ref).state is (
        ProviderOperationState.TERMINAL_FAILED
    )
    with engine.connect() as connection:
        stopped = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
    assert stopped["execution_state"] == "STOPPED"
    assert AcquisitionStore(engine).get_opportunity(
        stopped["acquisition_opportunity_id"]
    ).next_action is None


def test_suppression_racing_remote_add_requires_reconciliation_without_local_binding(
    tmp_path,
) -> None:
    engine, _, _, provider, worker, _ = _planned(tmp_path)
    worker.process(_operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["operation_ref"], NOW)
    worker.process(_operation(engine, ProviderOperationKind.CONFIGURE_CAMPAIGN)["operation_ref"], NOW)
    with engine.connect() as connection:
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
    original_add = provider.create_lead_or_batch

    def add_then_suppress(*, provider_campaign_id, leads):
        result = original_add(provider_campaign_id=provider_campaign_id, leads=leads)
        SuppressionStore(engine, _keyring()).record_for_contact(
            member["contact_ref"],
            source=SuppressionSource.RECIPIENT_OBJECTION,
            reason_code=SuppressionReasonCode.RECIPIENT_OBJECTED,
            evidence_ref=f"suppression-evidence:{'5' * 64}",
            received_at=NOW,
        )
        return result

    provider.create_lead_or_batch = add_then_suppress
    operation_ref = _operation(engine, ProviderOperationKind.ADD_LEAD)["operation_ref"]

    assert worker.process(operation_ref, NOW) is ProviderOperationState.CONFIRMED

    assert CampaignStore(engine).get_operation(operation_ref).state is (
        ProviderOperationState.CONFIRMED
    )
    with engine.connect() as connection:
        persisted = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
    assert persisted["execution_state"] == "STOPPED"
    assert persisted["provider_lead_id"] == "provider-lead-1"
    assert _operation(engine, ProviderOperationKind.PAUSE_LEAD)["state"] == "PLANNED"
    assert _operation(engine, ProviderOperationKind.PAUSE_CAMPAIGN)["state"] == "PLANNED"


def test_add_lead_requires_exact_non_sending_campaign_and_mailbox_binding(tmp_path) -> None:
    engine, _, _, provider, worker, _ = _planned(tmp_path)
    worker.process(_operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["operation_ref"], NOW)
    worker.process(_operation(engine, ProviderOperationKind.CONFIGURE_CAMPAIGN)["operation_ref"], NOW)
    assert provider.campaign.normalized_config["email_list"] == [
        "provider-account:test"
    ]
    assert provider.campaign.normalized_config["daily_limit"] == 3
    assert provider.campaign.normalized_config["auto_variant_select"] is None
    provider.campaign = provider.campaign.model_copy(update={"status": "active"})
    operation_ref = _operation(engine, ProviderOperationKind.ADD_LEAD)["operation_ref"]

    with pytest.raises(CampaignInputChanged):
        worker.process(operation_ref, NOW)

    assert provider.add_calls == 0


def test_add_lead_readback_must_match_every_authorized_variable(tmp_path) -> None:
    engine, _, _, provider, worker, _ = _planned(tmp_path)
    worker.process(_operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["operation_ref"], NOW)
    worker.process(_operation(engine, ProviderOperationKind.CONFIGURE_CAMPAIGN)["operation_ref"], NOW)
    original_get = provider.get_lead

    def changed_get(provider_lead_id):
        value = dict(original_get(provider_lead_id))
        value["custom_variables"] = {
            **value["custom_variables"],
            "kivou_envelope": "provider-modified-copy",
        }
        return value

    provider.get_lead = changed_get
    operation_ref = _operation(engine, ProviderOperationKind.ADD_LEAD)["operation_ref"]

    with pytest.raises(CampaignInputChanged):
        worker.process(operation_ref, NOW)

    assert provider.add_calls == 1
    assert CampaignStore(engine).get_operation(operation_ref).state is (
        ProviderOperationState.RECONCILE_REQUIRED
    )
    with engine.connect() as connection:
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
    assert member["execution_state"] == "RESERVED"
    assert member["provider_lead_id"] is None


def test_contact_email_drift_before_add_is_caught_by_protected_identity_binding(
    tmp_path,
) -> None:
    engine, _, _, provider, worker, _ = _planned(tmp_path)
    worker.process(_operation(engine, ProviderOperationKind.CREATE_CAMPAIGN)["operation_ref"], NOW)
    worker.process(_operation(engine, ProviderOperationKind.CONFIGURE_CAMPAIGN)["operation_ref"], NOW)
    with engine.begin() as connection:
        connection.execute(
            sa.update(acquisition_contact).values(
                business_email="changed-contact@example.invalid"
            )
        )
    operation_ref = _operation(engine, ProviderOperationKind.ADD_LEAD)["operation_ref"]

    with pytest.raises(CampaignInputChanged):
        worker.process(operation_ref, NOW)

    assert provider.add_calls == 0
