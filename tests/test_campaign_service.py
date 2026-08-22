from __future__ import annotations

import datetime as dt
from decimal import Decimal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from test_campaign_store import _prepared
from test_compliance_service import sender
from test_policy_persistence import control

from signals.campaigns.contracts import (
    CampaignAuthorizationInput,
    CampaignDeploymentBlocked,
    CampaignDeploymentConfig,
    CampaignEvaluationRequiresFreshAttempt,
    CampaignIdempotencyConflict,
    CampaignInputChanged,
    FooterCatalog,
    FooterCatalogEntry,
    MailboxCatalog,
    MailboxCatalogEntry,
    MailboxReadiness,
    MailboxReadinessState,
    ResponseIngressCapability,
    TransportContractProof,
    WebhookEntitlement,
)
from signals.campaigns.service import CampaignService
from signals.compliance.contracts import SuppressionReasonCode, SuppressionSource
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.conversion.contracts import AttributionTokenPayload
from signals.conversion.link import AttributionLink, AttributionLinkBuilder
from signals.conversion.token import AttributionTokenKeyring
from signals.decision_engine.policy import semantic_fingerprint
from signals.persistence.schema import (
    acquisition_campaign_member,
    acquisition_compliance_assessment,
    acquisition_opportunity,
    acquisition_provider_operation,
    policy_evaluation,
)
from signals.policy.contracts import (
    POLICY_VERSION,
    ApprovalGrant,
    ApprovalPurpose,
    AutonomyMode,
    BudgetUsage,
    EvidenceReadiness,
    EvidenceStatus,
    OperationalReadiness,
    Scope,
)
from signals.policy.store import PolicyStore
from signals.supplier_discovery.seed import resolve_acquisition_seed

NOW = dt.datetime(2026, 8, 21, 13, tzinfo=dt.UTC)


class CapturingAttributionLinkBuilder:
    def __init__(self, keyring: AttributionTokenKeyring) -> None:
        self.delegate = AttributionLinkBuilder(
            public_site_url="https://kivou.example.invalid", keyring=keyring
        )
        self.payload: AttributionTokenPayload | None = None

    def build(self, payload: AttributionTokenPayload) -> AttributionLink:
        self.payload = payload
        return self.delegate.build(payload)


class FakeReadiness:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, provider_account_id: str, *, observed_at: dt.datetime) -> MailboxReadiness:
        self.calls += 1
        assert provider_account_id == "provider-account:test"
        return MailboxReadiness(
            state=MailboxReadinessState.READY,
            provider_daily_limit=2,
            sending_gap_seconds=300,
            observed_at=observed_at,
            valid_until=observed_at + dt.timedelta(hours=1),
        )


def _keyring() -> SuppressionIdentityKeyring:
    return SuppressionIdentityKeyring(
        current_key_version="key-v1", keys={"key-v1": b"campaign-test-key"}
    )


def _deployment() -> CampaignDeploymentConfig:
    return CampaignDeploymentConfig(
        provider_workspace_ref="workspace:test",
        wedge="construction",
        wedge_version="wedge-v1",
        mailbox_pool_version="mailbox-pool-test-v1",
        mailbox_catalog=MailboxCatalog(
            catalog_version="mailbox-catalog-test-v1",
            entries=(
                MailboxCatalogEntry(
                    mailbox_ref="mailbox:test",
                    provider_account_id="provider-account:test",
                    sender_profile_ref="sender-profile:acquisition-primary",
                    eligible_countries=("FR",),
                    eligible_languages=("fr",),
                    eligible_wedges=("construction",),
                    domain_ref="domain:test",
                    timezone="Europe/Paris",
                    kivou_daily_cap=3,
                    kivou_campaign_cap=10,
                    config_version="mailbox-test-v1",
                    config_fingerprint="a" * 64,
                    enabled=True,
                ),
            ),
        ),
        footer_catalog=FooterCatalog(
            catalog_version="footer-catalog-test-v1",
            entries=(
                FooterCatalogEntry(
                    language="fr",
                    sender_profile_ref="sender-profile:acquisition-primary",
                    sender_identity="Kivou Test",
                    source_notice="Contact professionnel issu d'une source de test.",
                    privacy_route="https://example.invalid/privacy",
                    visible_opt_out="Répondez STOP pour ne plus être contacté.",
                ),
            ),
        ),
        transport_contract_proof=TransportContractProof.UNVERIFIED,
        webhook_entitlement=WebhookEntitlement.UNVERIFIED,
        response_ingress_capability=ResponseIngressCapability.NONE,
    )


def _authorization(*, approval_grants=()) -> CampaignAuthorizationInput:
    return CampaignAuthorizationInput(
        evaluation_id="campaign-eval-1",
        request_id="campaign-request-1",
        actor_type="HERMES",
        actor_ref="kivou-supervisor",
        scope=Scope(country="FR", language="fr", wedge="construction"),
        currency="CHF",
        evidence=EvidenceReadiness(
            status=EvidenceStatus.READY,
            claims=("CALLER_CANNOT_SELECT_CAMPAIGN_CLAIMS",),
            assessment_version="campaign-evidence-v1",
            observed_at=NOW,
        ),
        operational=OperationalReadiness(
            runtime_revision="runtime-test-v1", valid_until=NOW + dt.timedelta(hours=1)
        ),
        expected_policy_version=POLICY_VERSION,
        approval_grants=approval_grants,
    )


def _service(
    engine,
    deployment=None,
    readiness=None,
    clock=None,
    sender_config=None,
    attribution_link_builder=None,
) -> CampaignService:
    if attribution_link_builder is None:
        attribution_link_builder = AttributionLinkBuilder(
            public_site_url="https://kivou.example.invalid",
            keyring=AttributionTokenKeyring(
                current_key_version="attribution-test-v1",
                keys={"attribution-test-v1": b"synthetic-attribution-secret"},
            ),
        )
    return CampaignService(
        engine,
        keyring=_keyring(),
        sender_config=sender_config or sender(),
        deployment=deployment or CampaignDeploymentConfig(),
        mailbox_readiness=readiness or FakeReadiness(),
        clock=clock or (lambda: NOW),
        attribution_link_builder=attribution_link_builder,
    )


def test_default_deployment_is_fail_closed_before_policy_or_provider(tmp_path) -> None:
    engine, opportunity_id, _, _ = _prepared(tmp_path)
    readiness = FakeReadiness()

    with pytest.raises(CampaignDeploymentBlocked, match="unconfigured|mailbox"):
        _service(engine, readiness=readiness).schedule(
            opportunity_id, _authorization(), budget_usage=BudgetUsage()
        )

    assert readiness.calls == 0
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(policy_evaluation)
            .where(policy_evaluation.c.evaluation_id == "campaign-eval-1")
        ) == 0


def test_shadow_records_policy_but_never_reserves_or_mutates_provider(tmp_path) -> None:
    engine, opportunity_id, _, _ = _prepared(tmp_path)
    PolicyStore(engine).append_control(
        control(
            4,
            autonomy_mode=AutonomyMode.SHADOW,
            shadow_target_mode=AutonomyMode.ASSISTED,
            allowed_commands=("schedule_campaign",),
            allowed_countries=("FR",),
            allowed_languages=("fr",),
            allowed_wedges=("construction",),
            effective_at=NOW - dt.timedelta(minutes=1),
        )
    )
    result = _service(engine, _deployment()).schedule(
        opportunity_id, _authorization(), budget_usage=BudgetUsage()
    )

    assert result.disposition == "POLICY_BLOCKED"
    assert result.policy_status == "APPROVAL_REQUIRED"
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_campaign_member)) == 0
        assert connection.scalar(sa.select(sa.func.count()).select_from(acquisition_provider_operation)) == 0


def test_assisted_approval_plans_one_member_sequence_without_provider_io(tmp_path) -> None:
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
    service = _service(engine, _deployment())
    proposal = service.preview(opportunity_id, captured_at=NOW)
    snapshot = PolicyStore(engine).get_effective_control(NOW)
    grant = ApprovalGrant(
        approval_id="approval-campaign-action",
        purpose=ApprovalPurpose.ACTION,
        command="schedule_campaign",
        target_ref=f"acquisition-opportunity:{opportunity_id}",
        acquisition_opportunity_id=opportunity_id,
        action_fingerprint=proposal.action_fingerprint,
        policy_version=snapshot.policy_version,
        policy_snapshot_id=snapshot.policy_snapshot_id,
        control_revision=snapshot.control_revision,
        scope_fingerprint=_authorization().scope.fingerprint(),
        issued_at=NOW - dt.timedelta(minutes=1),
        expires_at=NOW + dt.timedelta(minutes=30),
        approved_by_actor_ref="supervisor:test",
    )

    result = service.schedule(
        opportunity_id,
        _authorization(approval_grants=(grant,)),
        budget_usage=BudgetUsage(cost_used=Decimal("0"), volume_used=0),
    )

    assert result.disposition == "PLANNED"
    assert result.policy_status == "APPROVED"
    assert result.execution_state == "RESERVED"
    with engine.connect() as connection:
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
        operations = connection.execute(
            sa.select(acquisition_provider_operation).order_by(
                acquisition_provider_operation.c.created_at,
                acquisition_provider_operation.c.operation_ref,
            )
        ).mappings().all()
    assert member["policy_evaluation_id"] == "campaign-eval-1"
    assert member["policy_provenance"]["approval_refs"][0]["approval_id"] == (
        "approval-campaign-action"
    )
    assert "approved_by_actor_ref" not in str(member["policy_provenance"])
    assert {operation["kind"] for operation in operations} == {
        "CREATE_CAMPAIGN",
        "CONFIGURE_CAMPAIGN",
        "ADD_LEAD",
    }
    assert {operation["state"] for operation in operations} == {"PLANNED"}


def test_campaign_attribution_freezes_versioned_public_sector_dimension(tmp_path) -> None:
    engine, opportunity_id, _, _ = _prepared(tmp_path)
    token_keyring = AttributionTokenKeyring(
        current_key_version="attribution-test-v1",
        keys={"attribution-test-v1": b"synthetic-attribution-secret"},
    )
    link_builder = CapturingAttributionLinkBuilder(token_keyring)
    service = _service(
        engine,
        _deployment(),
        attribution_link_builder=link_builder,
    )

    preview = service.preview(opportunity_id, captured_at=NOW)
    token = urlsplit(preview.envelope.custom_variables["kivou_attribution_url"]).path.rsplit(
        "/", 1
    )[1]
    issuance = dt.datetime.combine(
        preview.plan.sequence_window.step_1_execution_date,
        dt.time(9),
        tzinfo=ZoneInfo(preview.plan.sequence_window.timezone),
    ).astimezone(dt.UTC)
    with engine.connect() as connection:
        signal_ref = connection.scalar(
            sa.select(acquisition_opportunity.c.signal_ref).where(
                acquisition_opportunity.c.acquisition_opportunity_id == opportunity_id
            )
        )
    assert isinstance(signal_ref, str)
    assert link_builder.payload is not None
    payload = token_keyring.verify(token, payload=link_builder.payload, at=issuance).payload
    opportunity_key = signal_ref.removeprefix("procurement-opportunity:")
    seed = resolve_acquisition_seed(engine, opportunity_key)

    assert payload.sector_ref == semantic_fingerprint(
        {
            "kind": "conversion-sector-ref-v1",
            "sector_code": seed.understanding.sector.value,
            "inference_version": seed.understanding.engine_version,
        }
    )


def _approved(service, engine, opportunity_id, *, evaluation_id="campaign-eval-1"):
    preview = service.preview(opportunity_id, captured_at=NOW)
    snapshot = PolicyStore(engine).get_effective_control(NOW)
    authorization = _authorization().model_copy(update={"evaluation_id": evaluation_id})
    grant = ApprovalGrant(
        approval_id=f"approval-{evaluation_id}",
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
        expires_at=NOW + dt.timedelta(minutes=30),
        approved_by_actor_ref="supervisor:test",
    )
    return authorization.model_copy(update={"approval_grants": (grant,)})


def _assisted(engine) -> None:
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


def test_exact_replay_is_zero_clock_and_preserves_historical_policy(tmp_path) -> None:
    engine, opportunity_id, _, _ = _prepared(tmp_path)
    _assisted(engine)
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        return NOW

    service = _service(engine, _deployment(), clock=clock)
    authorization = _approved(service, engine, opportunity_id)
    budget = BudgetUsage(cost_used=Decimal("2"), volume_used=3)
    first = service.schedule(opportunity_id, authorization, budget_usage=budget)
    calls = 0

    replay = service.schedule(opportunity_id, authorization, budget_usage=budget)

    assert replay.replayed is True
    assert replay.member_ref == first.member_ref
    assert calls == 0
    with engine.connect() as connection:
        row = connection.execute(
            sa.select(policy_evaluation).where(
                policy_evaluation.c.evaluation_id == "campaign-eval-1"
            )
        ).mappings().one()
        member = connection.execute(sa.select(acquisition_campaign_member)).mappings().one()
    assert row["cost_remaining"] == Decimal("98")
    assert row["volume_remaining"] == 97
    assert member["policy_provenance"]["budget_usage"] == {
        "cost_used": "2",
        "volume_used": 3,
    }


def test_changed_replay_semantics_conflict_before_clock(tmp_path) -> None:
    engine, opportunity_id, _, _ = _prepared(tmp_path)
    _assisted(engine)
    service = _service(engine, _deployment())
    authorization = _approved(service, engine, opportunity_id)
    service.schedule(opportunity_id, authorization, budget_usage=BudgetUsage())

    changed = authorization.model_copy(update={"actor_ref": "other-supervisor"})
    with pytest.raises(CampaignIdempotencyConflict):
        service.schedule(opportunity_id, changed, budget_usage=BudgetUsage())
    with pytest.raises(CampaignIdempotencyConflict):
        service.schedule(
            opportunity_id,
            authorization,
            budget_usage=BudgetUsage(volume_used=1),
        )


def test_policy_without_member_requires_fresh_attempt(tmp_path) -> None:
    engine, opportunity_id, _, _ = _prepared(tmp_path)
    _assisted(engine)
    service = _service(engine, _deployment())
    authorization = _approved(service, engine, opportunity_id)
    service._policy.evaluate_and_record(
        service._policy_request(
            authorization,
            service.preview(opportunity_id, captured_at=NOW),
            expected_version=service._acquisition.get_opportunity(opportunity_id).stream_version,
        ),
        evaluated_at=NOW,
        budget_usage=BudgetUsage(),
    )

    with pytest.raises(CampaignEvaluationRequiresFreshAttempt):
        service.schedule(opportunity_id, authorization, budget_usage=BudgetUsage())


def test_suppression_after_policy_rolls_back_member_and_operations(tmp_path) -> None:
    engine, opportunity_id, _, _ = _prepared(tmp_path)
    _assisted(engine)
    service = _service(engine, _deployment())
    authorization = _approved(service, engine, opportunity_id)
    with engine.connect() as connection:
        contact_ref = service._acquisition.get_opportunity_in_transaction(
            connection, opportunity_id
        ).contact_ref

    def suppress() -> None:
        SuppressionStore(engine, _keyring()).record_for_contact(
            contact_ref,
            source=SuppressionSource.RECIPIENT_OBJECTION,
            reason_code=SuppressionReasonCode.RECIPIENT_OBJECTED,
            evidence_ref=f"suppression-evidence:{'1' * 64}",
            received_at=NOW,
        )

    service._after_policy_hook = suppress
    with pytest.raises(CampaignInputChanged):
        service.schedule(opportunity_id, authorization, budget_usage=BudgetUsage())
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_campaign_member)
        ) == 0
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_provider_operation)
        ) == 0


def test_ruleset_validity_must_cover_step_two_deadline_before_policy(tmp_path) -> None:
    engine, opportunity_id, _, _ = _prepared(tmp_path)
    with engine.begin() as connection:
        row = connection.execute(
            sa.select(acquisition_compliance_assessment)
        ).mappings().one()
        snapshot = dict(row["input_snapshot"])
        snapshot["ruleset_valid_until"] = (NOW + dt.timedelta(days=2)).isoformat()
        connection.execute(
            sa.update(acquisition_compliance_assessment).values(input_snapshot=snapshot)
        )

    with pytest.raises(CampaignDeploymentBlocked, match="ruleset validity"):
        _service(engine, _deployment()).preview(opportunity_id, captured_at=NOW)


def test_sender_validity_must_cover_step_two_deadline_before_policy(tmp_path) -> None:
    engine, opportunity_id, _, _ = _prepared(tmp_path)
    sender_config = sender(valid_until=NOW + dt.timedelta(days=2))
    with engine.begin() as connection:
        row = connection.execute(
            sa.select(acquisition_compliance_assessment)
        ).mappings().one()
        snapshot = dict(row["input_snapshot"])
        snapshot["sender_config"] = sender_config.model_dump(mode="json")
        connection.execute(
            sa.update(acquisition_compliance_assessment).values(input_snapshot=snapshot)
        )

    with pytest.raises(CampaignDeploymentBlocked, match="sender validity"):
        _service(
            engine,
            _deployment(),
            sender_config=sender_config,
        ).preview(opportunity_id, captured_at=NOW)
