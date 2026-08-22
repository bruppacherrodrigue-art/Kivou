from __future__ import annotations

import datetime as dt
import threading

import pytest
import sqlalchemy as sa
from test_compliance_service import (
    compliance_authorization,
    ready_context,
)
from test_compliance_service import (
    service as compliance_service,
)
from test_decision_engine_service import context as decision_context

from signals.acquisition.store import AcquisitionStore
from signals.campaigns.contracts import (
    CampaignFactoryInput,
    CampaignInputChanged,
    CampaignMemberReservation,
    CampaignPacingExceeded,
    ProviderOperationKind,
    ProviderOperationState,
)
from signals.campaigns.store import CampaignStore
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_compliance_assessment,
    acquisition_personalization_artifact,
    acquisition_provider_operation,
    policy_evaluation,
)
from signals.policy.contracts import BudgetUsage

NOW = dt.datetime(2026, 8, 24, 9, tzinfo=dt.UTC)
FP = "b" * 64


def _prepared(tmp_path):
    base = decision_context.__wrapped__(tmp_path)
    engine, _, opportunity_id, _ = ready_context(base)
    compliance_service(engine).assess(
        opportunity_id,
        compliance_authorization(),
        budget_usage=BudgetUsage(),
    )
    with engine.connect() as connection:
        artifact = connection.execute(
            sa.select(acquisition_personalization_artifact).where(
                acquisition_personalization_artifact.c.acquisition_opportunity_id
                == opportunity_id,
                acquisition_personalization_artifact.c.disposition == "READY",
            )
        ).mappings().one()
        assessment = connection.execute(
            sa.select(acquisition_compliance_assessment).where(
                acquisition_compliance_assessment.c.acquisition_opportunity_id
                == opportunity_id,
                acquisition_compliance_assessment.c.disposition == "RECORDED",
            )
        ).mappings().one()
    return engine, opportunity_id, artifact, assessment


def _factory_input() -> CampaignFactoryInput:
    return CampaignFactoryInput(
        wedge="construction",
        wedge_version="wedge-v1",
        jurisdiction="FR",
        country="FR",
        language="fr",
        selected_need_category="GROWTH",
        selected_need_version="need-v1",
        personalization_catalog_version="personalization-catalog-v1",
        personalization_template_version="personalization-template-v1",
        language_policy_version="personalization-language-v1",
        envelope_catalog_version="footer-test-v1",
        sender_profile_ref="sender-profile:test",
        mailbox_pool_version="mailbox-pool-test-v1",
        compliance_ruleset_fingerprint=FP,
        step_1_execution_date=dt.date(2026, 8, 24),
    )


def _reservation(
    opportunity_id,
    artifact,
    assessment,
    *,
    suffix: str = "",
    policy_evaluation_id: str | None = None,
):
    return CampaignMemberReservation(
        acquisition_opportunity_id=f"{opportunity_id}{suffix}",
        supplier_ref=artifact["supplier_ref"],
        contact_ref=artifact["contact_ref"],
        personalization_artifact_id=artifact["personalization_artifact_id"],
        personalization_artifact_fingerprint=artifact["artifact_fingerprint"],
        compliance_assessment_id=assessment["compliance_assessment_id"],
        compliance_assessment_fingerprint=assessment["proposal_fingerprint"],
        policy_evaluation_id=policy_evaluation_id or assessment["policy_evaluation_id"],
        policy_provenance={
            "policy_evaluation_id": policy_evaluation_id
            or assessment["policy_evaluation_id"]
        },
        input_fingerprint=FP,
        contact_provider_identity_binding="0" * 64,
        envelope_fingerprint="c" * 64,
        policy_action_fingerprint="d" * 64,
        ruleset_fingerprint=assessment["ruleset_config_fingerprint"],
        sender_config_fingerprint="e" * 64,
        mailbox_ref="mailbox:test",
        mailbox_readiness_fingerprint="f" * 64,
        sequence_authorization_fingerprint="1" * 64,
    )


def _additional_opportunity(engine, original_id: str, index: int) -> tuple[str, str]:
    acquisition = AcquisitionStore(engine, clock=lambda: NOW)
    original = acquisition.get_opportunity(original_id)
    created = acquisition.create_opportunity(
        identity_key=f"campaign-store-opportunity-{index}",
        signal_ref=original.signal_ref,
        supplier_ref=original.supplier_ref,
        idempotency_key=f"campaign-store-create-{index}",
    )
    evaluation_id = f"campaign-store-policy-{index}"
    with engine.begin() as connection:
        template = connection.execute(
            sa.select(policy_evaluation).where(
                policy_evaluation.c.evaluation_id == "compliance-eval-1"
            )
        ).mappings().one()
        values = dict(template)
        values.update(
            evaluation_id=evaluation_id,
            request_id=f"campaign-store-request-{index}",
            acquisition_opportunity_id=created.projection.acquisition_opportunity_id,
            semantic_fingerprint=f"{index + 10:064x}",
        )
        connection.execute(sa.insert(policy_evaluation).values(**values))
    return created.projection.acquisition_opportunity_id, evaluation_id


def test_first_reservation_sets_immutable_deadline(tmp_path) -> None:
    engine, opportunity_id, artifact, assessment = _prepared(tmp_path)
    store = CampaignStore(engine)
    first = store.reserve_member(
        _factory_input(),
        _reservation(opportunity_id, artifact, assessment),
        provider_workspace_ref="workspace:test",
        desired_provider_config_fingerprint="2" * 64,
        reserved_at=NOW,
    )
    row = store.get_campaign(first.campaign_ref)
    assert row["first_member_reserved_at"].replace(tzinfo=dt.UTC) == NOW
    assert row["membership_close_at"].replace(tzinfo=dt.UTC) == NOW + dt.timedelta(minutes=15)
    assert row["membership_closed_at"] is None
    assert row["reserved_member_count"] == 1


def test_due_partial_batch_closes_without_reopening(tmp_path) -> None:
    engine, opportunity_id, artifact, assessment = _prepared(tmp_path)
    store = CampaignStore(engine)
    reservation = store.reserve_member(
        _factory_input(),
        _reservation(opportunity_id, artifact, assessment),
        provider_workspace_ref="workspace:test",
        desired_provider_config_fingerprint="2" * 64,
        reserved_at=NOW,
    )

    assert store.close_due_batches(NOW + dt.timedelta(minutes=15)) == (reservation.campaign_ref,)
    assert store.close_due_batches(NOW + dt.timedelta(minutes=20)) == ()
    assert store.get_campaign(reservation.campaign_ref)["membership_closed_at"].replace(
        tzinfo=dt.UTC
    ) == NOW + dt.timedelta(minutes=15)
    assert store.get_campaign(reservation.campaign_ref)["lifecycle"] == "BUILDING"


def test_membership_closure_forbids_new_add_lead_operation(tmp_path) -> None:
    engine, opportunity_id, artifact, assessment = _prepared(tmp_path)
    store = CampaignStore(engine)
    reservation = store.reserve_member(
        _factory_input(),
        _reservation(opportunity_id, artifact, assessment),
        provider_workspace_ref="workspace:test",
        desired_provider_config_fingerprint="2" * 64,
        reserved_at=NOW,
    )
    store.close_due_batches(NOW + dt.timedelta(minutes=15))

    with pytest.raises(CampaignInputChanged, match="membership is closed"):
        store.plan_operation(
            ProviderOperationKind.ADD_LEAD,
            campaign_ref=reservation.campaign_ref,
            member_ref=reservation.member_ref,
            desired_request_fingerprint="3" * 64,
            correlation_id="late-add",
            now=NOW + dt.timedelta(minutes=16),
        )


def test_closed_generation_makes_next_plan_use_new_generation(tmp_path) -> None:
    engine, opportunity_id, artifact, assessment = _prepared(tmp_path)
    store = CampaignStore(engine)
    first = store.reserve_member(
        _factory_input(),
        _reservation(opportunity_id, artifact, assessment),
        provider_workspace_ref="workspace:test",
        desired_provider_config_fingerprint="2" * 64,
        reserved_at=NOW,
    )
    store.close_due_batches(NOW + dt.timedelta(minutes=15))

    next_plan = store.propose_plan(
        _factory_input(), at=NOW + dt.timedelta(minutes=16)
    )

    assert next_plan.batch_generation == 2
    assert next_plan.campaign_ref != first.campaign_ref


def test_operation_claim_is_unique_and_expired_lease_requires_reconciliation(tmp_path) -> None:
    engine, opportunity_id, artifact, assessment = _prepared(tmp_path)
    store = CampaignStore(engine)
    reservation = store.reserve_member(
        _factory_input(),
        _reservation(opportunity_id, artifact, assessment),
        provider_workspace_ref="workspace:test",
        desired_provider_config_fingerprint="2" * 64,
        reserved_at=NOW,
    )
    operation = store.plan_operation(
        ProviderOperationKind.CREATE_CAMPAIGN,
        campaign_ref=reservation.campaign_ref,
        member_ref=None,
        desired_request_fingerprint="3" * 64,
        correlation_id="correlation-1",
        now=NOW,
    )
    replay = store.plan_operation(
        ProviderOperationKind.CREATE_CAMPAIGN,
        campaign_ref=reservation.campaign_ref,
        member_ref=None,
        desired_request_fingerprint="3" * 64,
        correlation_id="correlation-1",
        now=NOW,
    )
    assert replay.operation_ref == operation.operation_ref

    claimed = store.claim_operation(
        operation.operation_ref, worker_ref="worker-1", now=NOW, lease_seconds=30
    )
    assert claimed.state is ProviderOperationState.IN_FLIGHT
    competing = store.claim_operation(
        operation.operation_ref,
        worker_ref="worker-2",
        now=NOW + dt.timedelta(seconds=1),
        lease_seconds=30,
    )
    assert competing.state is ProviderOperationState.IN_FLIGHT
    assert competing.lease_owner == "worker-1"
    expired = store.claim_operation(
        operation.operation_ref,
        worker_ref="worker-2",
        now=NOW + dt.timedelta(seconds=31),
        lease_seconds=30,
    )
    assert expired.state is ProviderOperationState.RECONCILE_REQUIRED
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_provider_operation)) == 1


def test_retryable_operation_honors_retry_after_then_has_one_new_claim(tmp_path) -> None:
    engine, opportunity_id, artifact, assessment = _prepared(tmp_path)
    store = CampaignStore(engine)
    reservation = store.reserve_member(
        _factory_input(),
        _reservation(opportunity_id, artifact, assessment),
        provider_workspace_ref="workspace:test",
        desired_provider_config_fingerprint="2" * 64,
        reserved_at=NOW,
    )
    operation = store.plan_operation(
        ProviderOperationKind.CREATE_CAMPAIGN,
        campaign_ref=reservation.campaign_ref,
        member_ref=None,
        desired_request_fingerprint="3" * 64,
        correlation_id="retryable-operation",
        now=NOW,
    )
    retry_at = NOW + dt.timedelta(seconds=30)
    store.set_operation_state(
        operation.operation_ref,
        ProviderOperationState.RETRYABLE_FAILED,
        now=NOW,
        retry_after=retry_at,
        error_code="RATE_LIMITED",
    )

    early = store.claim_operation(
        operation.operation_ref,
        worker_ref="worker-early",
        now=NOW + dt.timedelta(seconds=29),
        lease_seconds=30,
    )
    claimed = store.claim_operation(
        operation.operation_ref,
        worker_ref="worker-ready",
        now=retry_at,
        lease_seconds=30,
    )

    assert early.state is ProviderOperationState.RETRYABLE_FAILED
    assert claimed.state is ProviderOperationState.IN_FLIGHT
    assert claimed.lease_owner == "worker-ready"


def test_retryable_operation_has_bounded_attempt_budget(tmp_path) -> None:
    engine, opportunity_id, artifact, assessment = _prepared(tmp_path)
    store = CampaignStore(engine)
    reservation = store.reserve_member(
        _factory_input(),
        _reservation(opportunity_id, artifact, assessment),
        provider_workspace_ref="workspace:test",
        desired_provider_config_fingerprint="2" * 64,
        reserved_at=NOW,
    )
    operation = store.plan_operation(
        ProviderOperationKind.CREATE_CAMPAIGN,
        campaign_ref=reservation.campaign_ref,
        member_ref=None,
        desired_request_fingerprint="3" * 64,
        correlation_id="bounded-retry-operation",
        now=NOW,
    )
    for attempt in range(3):
        claimed = store.claim_operation(
            operation.operation_ref,
            worker_ref=f"worker-{attempt}",
            now=NOW + dt.timedelta(seconds=attempt),
            lease_seconds=30,
        )
        assert claimed.state is ProviderOperationState.IN_FLIGHT
        store.set_operation_state(
            operation.operation_ref,
            ProviderOperationState.RETRYABLE_FAILED,
            now=NOW + dt.timedelta(seconds=attempt),
            error_code="RATE_LIMITED",
        )

    exhausted = store.claim_operation(
        operation.operation_ref,
        worker_ref="worker-too-late",
        now=NOW + dt.timedelta(seconds=4),
        lease_seconds=30,
    )

    assert exhausted.state is ProviderOperationState.TERMINAL_FAILED
    assert exhausted.attempt == 3


def test_concurrent_same_reservation_converges(tmp_path) -> None:
    engine, opportunity_id, artifact, assessment = _prepared(tmp_path)
    results = []
    errors = []
    barrier = threading.Barrier(2)

    def reserve() -> None:
        try:
            barrier.wait()
            results.append(
                CampaignStore(engine).reserve_member(
                    _factory_input(),
                    _reservation(opportunity_id, artifact, assessment),
                    provider_workspace_ref="workspace:test",
                    desired_provider_config_fingerprint="2" * 64,
                    reserved_at=NOW,
                )
            )
        except (RuntimeError, ValueError, sa.exc.SQLAlchemyError) as exc:
            errors.append(exc)

    threads = [threading.Thread(target=reserve) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == 2
    assert {result.campaign_ref for result in results} == {results[0].campaign_ref}
    assert {result.member_ref for result in results} == {results[0].member_ref}
    assert {result.replayed for result in results} == {False, True}
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_campaign)) == 1
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_campaign_member)) == 1


def test_concurrent_distinct_members_share_one_building_generation(tmp_path) -> None:
    engine, opportunity_id, artifact, assessment = _prepared(tmp_path)
    second_id, second_eval = _additional_opportunity(engine, opportunity_id, 1)
    reservations = (
        _reservation(opportunity_id, artifact, assessment),
        _reservation(
            second_id,
            artifact,
            assessment,
            policy_evaluation_id=second_eval,
        ),
    )
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def reserve(member) -> None:
        try:
            barrier.wait()
            results.append(
                CampaignStore(engine).reserve_member(
                    _factory_input(),
                    member,
                    provider_workspace_ref="workspace:test",
                    desired_provider_config_fingerprint="2" * 64,
                    reserved_at=NOW,
                )
            )
        except (RuntimeError, ValueError, sa.exc.SQLAlchemyError) as exc:
            errors.append(exc)

    threads = [threading.Thread(target=reserve, args=(item,)) for item in reservations]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(results) == 2
    assert {result.campaign_ref for result in results} == {results[0].campaign_ref}
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_campaign)) == 1
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_campaign_member)) == 2


def test_tenth_slot_closes_generation_and_eleventh_uses_next_batch(tmp_path) -> None:
    engine, opportunity_id, artifact, assessment = _prepared(tmp_path)
    store = CampaignStore(engine)
    reservations = [_reservation(opportunity_id, artifact, assessment)]
    for index in range(1, 11):
        next_id, evaluation_id = _additional_opportunity(engine, opportunity_id, index)
        reservations.append(
            _reservation(
                next_id,
                artifact,
                assessment,
                policy_evaluation_id=evaluation_id,
            )
        )

    first_ten = [
        store.reserve_member(
            _factory_input(),
            item,
            provider_workspace_ref="workspace:test",
            desired_provider_config_fingerprint="2" * 64,
            reserved_at=NOW + dt.timedelta(seconds=index),
        )
        for index, item in enumerate(reservations[:10])
    ]
    eleventh = store.reserve_member(
        _factory_input(),
        reservations[10],
        provider_workspace_ref="workspace:test",
        desired_provider_config_fingerprint="2" * 64,
        reserved_at=NOW + dt.timedelta(seconds=11),
    )

    assert {item.batch_generation for item in first_ten} == {1}
    assert store.get_campaign(first_ten[0].campaign_ref)["membership_closed_at"] is not None
    assert eleventh.batch_generation == 2
    assert store.get_campaign(first_ten[0].campaign_ref)["reserved_member_count"] == 10
    assert store.get_campaign(eleventh.campaign_ref)["reserved_member_count"] == 1


def test_atomic_company_rolling_cap_rejects_second_contact_sequence(tmp_path) -> None:
    engine, opportunity_id, artifact, assessment = _prepared(tmp_path)
    second_id, second_eval = _additional_opportunity(engine, opportunity_id, 20)
    store = CampaignStore(engine)
    store.reserve_member(
        _factory_input(),
        _reservation(opportunity_id, artifact, assessment),
        provider_workspace_ref="workspace:test",
        desired_provider_config_fingerprint="2" * 64,
        reserved_at=NOW,
        effective_mailbox_daily_cap=3,
    )

    with pytest.raises(CampaignPacingExceeded, match="company"):
        store.reserve_member(
            _factory_input(),
            _reservation(
                second_id,
                artifact,
                assessment,
                policy_evaluation_id=second_eval,
            ),
            provider_workspace_ref="workspace:test",
            desired_provider_config_fingerprint="2" * 64,
            reserved_at=NOW,
            effective_mailbox_daily_cap=3,
        )
