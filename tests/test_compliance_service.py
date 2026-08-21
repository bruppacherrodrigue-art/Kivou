from __future__ import annotations

import datetime as dt
import threading
from decimal import Decimal

import pytest
import sqlalchemy as sa
from test_decision_engine_service import EVALUATED_AT, authorization
from test_decision_engine_service import context as decision_context
from test_personalization_service import personalization_authorization
from test_policy_persistence import control

from signals.acquisition.contracts import AcquisitionState
from signals.compliance.contracts import (
    ComplianceAuthorizationInput,
    SenderComplianceConfig,
    SuppressionReasonCode,
    SuppressionSource,
)
from signals.compliance.service import (
    ComplianceAssessmentIdempotencyConflict,
    ComplianceBindingConflict,
    ComplianceEvaluationRequiresFreshAttempt,
    ComplianceInputChanged,
    ComplianceNotActionable,
    ComplianceService,
)
from signals.compliance.store import SuppressionStore
from signals.compliance.suppression import (
    SuppressionIdentityKeyring,
    suppression_evidence_ref,
)
from signals.decision_engine.policy import semantic_fingerprint
from signals.decision_engine.service import DecisionEngineService
from signals.persistence.schema import (
    acquisition_company_profile,
    acquisition_compliance_assessment,
    acquisition_contact,
    acquisition_contact_suppression,
    acquisition_event,
    acquisition_supplier,
    policy_evaluation,
)
from signals.personalization.service import PersonalizationService
from signals.policy.contracts import (
    AutonomyMode,
    BudgetUsage,
    EvidenceReadiness,
    Scope,
)
from signals.policy.store import PolicyStore

COMPLIANCE_ASSESSED_AT = dt.datetime(2026, 8, 21, 12, 30, tzinfo=dt.UTC)


class CountingClock:
    def __init__(self, value: dt.datetime = COMPLIANCE_ASSESSED_AT) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> dt.datetime:
        self.calls += 1
        return self.value


def keyring() -> SuppressionIdentityKeyring:
    return SuppressionIdentityKeyring(
        current_key_version="key-v1", keys={"key-v1": b"compliance-test-key"}
    )


def sender(**overrides: object) -> SenderComplianceConfig:
    values: dict[str, object] = {
        "sender_profile_ref": "sender-profile:acquisition-primary",
        "sender_identity_ready": True,
        "opt_out_ready": True,
        "privacy_notice_ready": True,
        "source_notice_ready": True,
    }
    values.update(overrides)
    return SenderComplianceConfig.model_validate(values)


def compliance_authorization(
    evaluation_id: str = "compliance-eval-1", *, country: str | None = "FR"
) -> ComplianceAuthorizationInput:
    base = authorization(evaluation_id)
    return ComplianceAuthorizationInput(
        evaluation_id=evaluation_id,
        request_id=f"request-{evaluation_id}",
        actor_type=base.actor_type,
        actor_ref="kivou-compliance",
        scope=Scope(country=country, language="fr", wedge="construction"),
        currency=base.currency,
        evidence=EvidenceReadiness(
            status=base.evidence.status,
            claims=("CALLER_CANNOT_SELECT_COMPLIANCE_CLAIMS",),
            assessment_version="compliance-evidence-v1",
            observed_at=COMPLIANCE_ASSESSED_AT,
        ),
        operational=base.operational,
        expected_policy_version=base.expected_policy_version,
    )


@pytest.fixture
def prepared(tmp_path):
    engine, acquisition, opportunity_id = decision_context.__wrapped__(tmp_path)
    return engine, acquisition, opportunity_id


def ready_context(
    prepared,
    *,
    supplier_country: str | None = "FR",
    provider_country: str | None = "France",
    role_tier: int = 1,
    shadow: bool = False,
):
    engine, acquisition, opportunity_id = prepared
    profile_fingerprint = semantic_fingerprint(
        {
            "kind": "test-profile-country-v1",
            "supplier_country": supplier_country,
            "provider_country": provider_country,
            "role_tier": role_tier,
        }
    )
    with engine.begin() as connection:
        connection.execute(sa.update(acquisition_supplier).values(country_code=supplier_country))
        connection.execute(
            sa.update(acquisition_company_profile).values(
                provider_country=provider_country,
                contact_role_tier=role_tier,
                prebuild_fingerprint=profile_fingerprint,
            )
        )
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    scope_country = supplier_country or None
    PolicyStore(engine).append_control(
        control(
            2,
            allowed_commands=("prepare_campaign",),
            allowed_countries=(scope_country,) if scope_country else (),
            allowed_languages=("fr",),
            effective_at=EVALUATED_AT - dt.timedelta(seconds=1),
        )
    )
    personalization_auth = personalization_authorization().model_copy(
        update={"scope": Scope(country=scope_country, language="fr", wedge="construction")}
    )
    PersonalizationService(engine, clock=CountingClock(EVALUATED_AT)).personalize(
        opportunity_id, "fr", personalization_auth, budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(
            3,
            autonomy_mode=AutonomyMode.SHADOW if shadow else AutonomyMode.AUTONOMOUS_CAPPED,
            shadow_target_mode=(AutonomyMode.AUTONOMOUS_CAPPED if shadow else None),
            allowed_commands=("assess_campaign_compliance",),
            allowed_countries=(scope_country,) if scope_country else (),
            allowed_languages=("fr",),
            effective_at=EVALUATED_AT - dt.timedelta(seconds=1),
        )
    )
    return engine, acquisition, opportunity_id, scope_country


def service(engine, clock=None, sender_config=None) -> ComplianceService:
    return ComplianceService(
        engine,
        keyring=keyring(),
        sender_config=sender_config or sender(),
        clock=clock or CountingClock(COMPLIANCE_ASSESSED_AT),
    )


def _count_terminal_events(engine, evaluation_id: str) -> int:
    with engine.connect() as connection:
        return connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_event)
            .where(
                acquisition_event.c.event_type == "NEXT_ACTION_SET",
                acquisition_event.c.causation_id == evaluation_id,
            )
        )


def test_fr_tier_one_records_allowed_and_advances_to_schedule(prepared) -> None:
    engine, acquisition, opportunity_id, country = ready_context(prepared)
    clock = CountingClock(COMPLIANCE_ASSESSED_AT)

    assessment = service(engine, clock).assess(
        opportunity_id,
        compliance_authorization(country=country),
        budget_usage=BudgetUsage(cost_used=Decimal("5")),
    )

    assert clock.calls == 1
    assert assessment["state"] == "ALLOWED"
    assert assessment["disposition"] == "RECORDED"
    assert assessment["valid_until"].replace(tzinfo=dt.UTC) == (
        COMPLIANCE_ASSESSED_AT + dt.timedelta(hours=24)
    )
    current = acquisition.get_opportunity(opportunity_id)
    assert current.state is AcquisitionState.SEND
    assert current.next_action == "schedule_campaign"


def test_wrong_workflow_action_fails_before_clock_and_policy(prepared) -> None:
    engine, _, opportunity_id = prepared
    clock = CountingClock(COMPLIANCE_ASSESSED_AT)

    with pytest.raises(ComplianceNotActionable):
        service(engine, clock).assess(
            opportunity_id,
            compliance_authorization(),
            budget_usage=BudgetUsage(),
        )

    assert clock.calls == 1
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(policy_evaluation)
                .where(policy_evaluation.c.evaluation_id == "compliance-eval-1")
            )
            == 0
        )


def test_contact_binding_drift_fails_before_policy(prepared) -> None:
    engine, _, opportunity_id, country = ready_context(prepared)
    with engine.begin() as connection:
        connection.execute(sa.text("UPDATE acquisition_contact SET role_tier = 4"))
    clock = CountingClock(COMPLIANCE_ASSESSED_AT)

    with pytest.raises(ComplianceBindingConflict):
        service(engine, clock).assess(
            opportunity_id,
            compliance_authorization(country=country),
            budget_usage=BudgetUsage(),
        )

    assert clock.calls == 1
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(policy_evaluation)
                .where(policy_evaluation.c.evaluation_id == "compliance-eval-1")
            )
            == 0
        )


def test_unsupported_equal_role_profile_versions_fail_before_policy(prepared) -> None:
    engine, _, opportunity_id, country = ready_context(prepared)
    with engine.begin() as connection:
        connection.execute(
            sa.update(acquisition_contact).values(
                role_profile_version="decision-maker-search-v0"
            )
        )
        connection.execute(
            sa.update(acquisition_company_profile).values(
                contact_role_profile_version="decision-maker-search-v0"
            )
        )
    clock = CountingClock(COMPLIANCE_ASSESSED_AT)

    with pytest.raises(ComplianceBindingConflict):
        service(engine, clock).assess(
            opportunity_id,
            compliance_authorization(country=country),
            budget_usage=BudgetUsage(),
        )

    assert clock.calls == 1
    assert _count_terminal_events(engine, "compliance-eval-1") == 0
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(policy_evaluation)
                .where(policy_evaluation.c.evaluation_id == "compliance-eval-1")
            )
            == 0
        )
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_compliance_assessment)
            )
            == 0
        )


def test_authorization_scope_must_bind_current_country_and_artifact_language(prepared) -> None:
    engine, _, opportunity_id, _ = ready_context(prepared)
    mismatched = compliance_authorization(country="CH").model_copy(
        update={"scope": Scope(country="CH", language="en", wedge="construction")}
    )

    with pytest.raises(ComplianceBindingConflict):
        service(engine).assess(
            opportunity_id,
            mismatched,
            budget_usage=BudgetUsage(),
        )

    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(policy_evaluation)
                .where(policy_evaluation.c.evaluation_id == "compliance-eval-1")
            )
            == 0
        )


def test_current_cold_ch_contact_requires_review_not_automatic_allow(prepared) -> None:
    engine, acquisition, opportunity_id, country = ready_context(
        prepared, supplier_country="CH", provider_country="Switzerland"
    )

    assessment = service(engine).assess(
        opportunity_id,
        compliance_authorization(country=country),
        budget_usage=BudgetUsage(),
    )

    assert assessment["state"] == "REVIEW_REQUIRED"
    assert "LEGAL_BASIS_UNRESOLVED" in assessment["reason_codes"]
    assert acquisition.get_opportunity(opportunity_id).next_action == "request_human_review"


@pytest.mark.parametrize(
    ("supplier_country", "provider_country", "state", "next_action"),
    (
        ("DE", "Germany", "REVIEW_REQUIRED", "request_human_review"),
        ("US", "United States", "BLOCKED", None),
        (None, None, "UNKNOWN", "request_human_review"),
    ),
)
def test_jurisdiction_workflow_mapping(
    prepared, supplier_country, provider_country, state, next_action
) -> None:
    engine, acquisition, opportunity_id, country = ready_context(
        prepared,
        supplier_country=supplier_country,
        provider_country=provider_country,
    )

    assessment = service(engine).assess(
        opportunity_id,
        compliance_authorization(country=country),
        budget_usage=BudgetUsage(),
    )

    assert assessment["state"] == state
    assert assessment["next_action"] == next_action
    assert acquisition.get_opportunity(opportunity_id).next_action == next_action


def test_suppression_is_a_non_overridable_hard_block(prepared) -> None:
    engine, acquisition, opportunity_id, country = ready_context(prepared)
    contact_ref = acquisition.get_opportunity(opportunity_id).contact_ref
    assert contact_ref is not None
    SuppressionStore(engine, keyring()).record_for_contact(
        contact_ref,
        source=SuppressionSource.RECIPIENT_OBJECTION,
        reason_code=SuppressionReasonCode.RECIPIENT_OBJECTED,
        evidence_ref=suppression_evidence_ref("recipient-objection", "synthetic-service"),
        received_at=EVALUATED_AT,
    )

    assessment = service(engine).assess(
        opportunity_id,
        compliance_authorization(country=country),
        budget_usage=BudgetUsage(),
    )

    assert assessment["state"] == "BLOCKED"
    assert assessment["next_action"] is None
    assert assessment["reason_codes"][0] == "SUPPRESSION_MATCH"
    assert acquisition.get_opportunity(opportunity_id).next_action is None


def test_incomplete_suppression_key_coverage_clears_action_fail_closed(prepared) -> None:
    engine, acquisition, opportunity_id, country = ready_context(prepared)
    contact_ref = acquisition.get_opportunity(opportunity_id).contact_ref
    assert contact_ref is not None
    complete_keyring = SuppressionIdentityKeyring(
        current_key_version="new-key",
        keys={"old-key": b"retained-old-key", "new-key": b"current-new-key"},
    )
    SuppressionStore(engine, complete_keyring).record_for_contact(
        contact_ref,
        source=SuppressionSource.SYSTEM_IMPORT,
        reason_code=SuppressionReasonCode.IMPORTED_SUPPRESSION,
        evidence_ref=suppression_evidence_ref("system-import", "retained"),
        received_at=EVALUATED_AT,
        key_version="old-key",
    )
    incomplete = ComplianceService(
        engine,
        keyring=SuppressionIdentityKeyring(
            current_key_version="new-key", keys={"new-key": b"current-new-key"}
        ),
        sender_config=sender(),
        clock=CountingClock(COMPLIANCE_ASSESSED_AT),
    )

    assessment = incomplete.assess(
        opportunity_id,
        compliance_authorization(country=country),
        budget_usage=BudgetUsage(),
    )

    assert assessment["state"] == "UNKNOWN"
    assert assessment["next_action"] is None
    assert assessment["reason_codes"] == ["SUPPRESSION_KEY_COVERAGE_UNSAFE"]
    assert acquisition.get_opportunity(opportunity_id).next_action is None


def test_shadow_persists_policy_blocked_without_workflow_mutation(prepared) -> None:
    engine, acquisition, opportunity_id, country = ready_context(prepared, shadow=True)
    before = acquisition.get_opportunity(opportunity_id)

    assessment = service(engine).assess(
        opportunity_id,
        compliance_authorization(country=country),
        budget_usage=BudgetUsage(),
    )

    assert assessment["disposition"] == "POLICY_BLOCKED"
    current = acquisition.get_opportunity(opportunity_id)
    assert current.next_action == "assess_campaign_compliance"
    assert current.stream_version == before.stream_version + 1
    assert _count_terminal_events(engine, "compliance-eval-1") == 0


def test_completed_replay_uses_historical_budget_and_zero_clock(prepared) -> None:
    engine, acquisition, opportunity_id, country = ready_context(prepared)
    first = service(engine).assess(
        opportunity_id,
        compliance_authorization(country=country),
        budget_usage=BudgetUsage(cost_used=Decimal("7.5"), volume_used=12),
    )
    before = acquisition.get_opportunity(opportunity_id).stream_version
    replay_clock = CountingClock(COMPLIANCE_ASSESSED_AT + dt.timedelta(days=30))

    replay = service(engine, replay_clock).assess(
        opportunity_id,
        compliance_authorization(country=country),
        budget_usage=BudgetUsage(cost_used=Decimal("75"), volume_used=75),
    )

    assert replay["compliance_assessment_id"] == first["compliance_assessment_id"]
    assert replay_clock.calls == 0
    assert acquisition.get_opportunity(opportunity_id).stream_version == before
    assert _count_terminal_events(engine, "compliance-eval-1") == 1


def test_completed_replay_changed_scope_conflicts_before_clock(prepared) -> None:
    engine, _, opportunity_id, country = ready_context(prepared)
    service(engine).assess(
        opportunity_id,
        compliance_authorization(country=country),
        budget_usage=BudgetUsage(),
    )
    replay_clock = CountingClock(COMPLIANCE_ASSESSED_AT)

    with pytest.raises(ComplianceAssessmentIdempotencyConflict):
        service(engine, replay_clock).assess(
            opportunity_id,
            compliance_authorization(country="CH"),
            budget_usage=BudgetUsage(),
        )

    assert replay_clock.calls == 0


@pytest.mark.parametrize(
    "authorization_change",
    (
        lambda value: value.model_copy(update={"actor_ref": "different-actor"}),
        lambda value: value.model_copy(
            update={
                "evidence": value.evidence.model_copy(
                    update={"assessment_version": "compliance-evidence-v2"}
                )
            }
        ),
    ),
    ids=("actor", "material-evidence"),
)
def test_completed_replay_rejects_changed_authorization_semantics_before_clock(
    prepared, authorization_change
) -> None:
    engine, _, opportunity_id, country = ready_context(prepared)
    original = compliance_authorization(country=country)
    service(engine).assess(opportunity_id, original, budget_usage=BudgetUsage())
    replay_clock = CountingClock(COMPLIANCE_ASSESSED_AT)

    with pytest.raises(ComplianceAssessmentIdempotencyConflict):
        service(engine, replay_clock).assess(
            opportunity_id,
            authorization_change(original),
            budget_usage=BudgetUsage(cost_used=Decimal("99"), volume_used=99),
        )

    assert replay_clock.calls == 0
    assert _count_terminal_events(engine, original.evaluation_id) == 1
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(policy_evaluation)
                .where(policy_evaluation.c.evaluation_id == original.evaluation_id)
            )
            == 1
        )
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_compliance_assessment)
            )
            == 1
        )


def test_policy_without_assessment_requires_fresh_attempt_before_clock(prepared) -> None:
    engine, acquisition, opportunity_id, country = ready_context(prepared)
    assessment_service = service(engine)
    auth = compliance_authorization(country=country)
    captured = COMPLIANCE_ASSESSED_AT
    values = assessment_service._build_values(
        assessment_service._load(opportunity_id, captured), captured
    )
    request = assessment_service._request(
        auth, values, expected_version=acquisition.get_opportunity(opportunity_id).stream_version
    )
    assert request.compliance.state.value == "UNKNOWN"
    assert request.compliance.assessment_version == "policy-compliance-pending-v1"
    assert request.compliance.observed_at == captured
    assert request.evidence.claims == (
        "ACQUISITION_DECISION",
        "PUBLIC_EVIDENCE",
        "VERIFIED_CONTACT",
        "ACQUISITION_PROSPECT_PREBUILD",
        "PERSONALIZATION_ARTIFACT",
        "COMPLIANCE_INPUT",
    )
    assessment_service._policy.evaluate_and_record(
        request, evaluated_at=captured, budget_usage=BudgetUsage()
    )
    replay_clock = CountingClock(COMPLIANCE_ASSESSED_AT)

    with pytest.raises(ComplianceEvaluationRequiresFreshAttempt):
        service(engine, replay_clock).assess(opportunity_id, auth, budget_usage=BudgetUsage())

    assert replay_clock.calls == 0
    assert _count_terminal_events(engine, auth.evaluation_id) == 0
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(policy_evaluation)
                .where(policy_evaluation.c.evaluation_id == auth.evaluation_id)
            )
            == 1
        )
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_compliance_assessment)
            )
            == 0
        )


def test_assessment_insert_failure_rolls_back_event_and_projection(prepared, monkeypatch) -> None:
    engine, acquisition, opportunity_id, country = ready_context(prepared)
    assessment_service = service(engine)

    def fail_insert(connection, write):
        raise RuntimeError("injected assessment insert failure")

    monkeypatch.setattr(assessment_service._assessments, "append_in_transaction", fail_insert)

    with pytest.raises(RuntimeError, match="injected assessment insert failure"):
        assessment_service.assess(
            opportunity_id,
            compliance_authorization(country=country),
            budget_usage=BudgetUsage(),
        )

    assert acquisition.get_opportunity(opportunity_id).next_action == ("assess_campaign_compliance")
    assert _count_terminal_events(engine, "compliance-eval-1") == 0
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_compliance_assessment)
            )
            == 0
        )


def test_suppression_inserted_after_policy_prevents_stale_allowed(prepared) -> None:
    engine, acquisition, opportunity_id, country = ready_context(prepared)
    assessment_service = service(engine)
    contact_ref = acquisition.get_opportunity(opportunity_id).contact_ref
    assert contact_ref is not None

    def suppress() -> None:
        SuppressionStore(engine, keyring()).record_for_contact(
            contact_ref,
            source=SuppressionSource.SYSTEM_IMPORT,
            reason_code=SuppressionReasonCode.IMPORTED_SUPPRESSION,
            evidence_ref=suppression_evidence_ref("system-import", "race"),
            received_at=EVALUATED_AT + dt.timedelta(seconds=1),
        )

    assessment_service._after_policy_hook = suppress

    with pytest.raises(ComplianceInputChanged):
        assessment_service.assess(
            opportunity_id,
            compliance_authorization(country=country),
            budget_usage=BudgetUsage(),
        )

    assert _count_terminal_events(engine, "compliance-eval-1") == 0
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_compliance_assessment)
            )
            == 0
        )
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_contact_suppression)
            )
            == 1
        )


def test_suppression_writer_cannot_commit_between_final_read_and_commit(prepared) -> None:
    engine, acquisition, opportunity_id, country = ready_context(prepared)
    assessment_service = service(engine)
    contact_ref = acquisition.get_opportunity(opportunity_id).contact_ref
    assert contact_ref is not None
    duplicate_contact_ref = "7" * 64
    with engine.begin() as connection:
        original = (
            connection.execute(
                sa.select(acquisition_contact).where(
                    acquisition_contact.c.contact_ref == contact_ref
                )
            )
            .mappings()
            .one()
        )
        duplicate = dict(original)
        duplicate.update(
            contact_ref=duplicate_contact_ref,
            provider_person_id="apollo-person-same-email",
            source_fingerprint="6" * 64,
        )
        connection.execute(sa.insert(acquisition_contact).values(duplicate))
    started = threading.Event()
    committed = threading.Event()
    errors: list[Exception] = []
    worker: threading.Thread | None = None

    def insert_suppression() -> None:
        started.set()
        try:
            SuppressionStore(engine, keyring()).record_for_contact(
                duplicate_contact_ref,
                source=SuppressionSource.RECIPIENT_OBJECTION,
                reason_code=SuppressionReasonCode.RECIPIENT_OBJECTED,
                evidence_ref=suppression_evidence_ref(
                    "recipient-objection", "serialized-race"
                ),
                received_at=EVALUATED_AT + dt.timedelta(seconds=1),
            )
            committed.set()
        except Exception as error:  # noqa: BLE001 - thread failure asserted below
            errors.append(error)

    def race() -> None:
        nonlocal worker
        worker = threading.Thread(target=insert_suppression)
        worker.start()
        assert started.wait(timeout=2)
        assert not committed.wait(timeout=0.1)

    assessment_service._after_revalidation_hook = race
    assessment = assessment_service.assess(
        opportunity_id,
        compliance_authorization(country=country),
        budget_usage=BudgetUsage(),
    )
    assert worker is not None
    worker.join(timeout=5)

    assert not errors
    assert committed.is_set()
    assert assessment["state"] == "ALLOWED"
    assert _count_terminal_events(engine, "compliance-eval-1") == 1


def test_database_rejects_allowed_assessment_without_schedule_action(prepared) -> None:
    engine, _, opportunity_id, country = ready_context(prepared)
    service(engine).assess(
        opportunity_id,
        compliance_authorization(country=country),
        budget_usage=BudgetUsage(),
    )

    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
        connection.execute(
            sa.update(acquisition_compliance_assessment)
            .where(
                acquisition_compliance_assessment.c.policy_evaluation_id
                == "compliance-eval-1"
            )
            .values(next_action=None)
        )


@pytest.mark.parametrize(
    "drift_kind",
    (
        "opportunity",
        "supplier",
        "contact",
        "profile",
        "artifact",
        "jurisdiction",
        "sender_config",
    ),
)
def test_post_policy_material_drift_is_one_typed_input_change(prepared, drift_kind) -> None:
    engine, _, opportunity_id, country = ready_context(prepared)
    assessment_service = service(engine)

    def drift() -> None:
        if drift_kind == "sender_config":
            assessment_service._sender_config = sender(source_notice_ready=False)
            return
        with engine.begin() as connection:
            if drift_kind == "opportunity":
                connection.execute(
                    sa.text(
                        "UPDATE acquisition_opportunity SET next_action = "
                        "'request_human_review' WHERE acquisition_opportunity_id = :opportunity"
                    ),
                    {"opportunity": opportunity_id},
                )
            elif drift_kind == "supplier":
                connection.execute(
                    sa.update(acquisition_supplier).values(identity_status="DOMAIN_CONFLICT")
                )
            elif drift_kind == "contact":
                connection.execute(sa.text("UPDATE acquisition_contact SET role_tier = 4"))
            elif drift_kind == "profile":
                connection.execute(
                    sa.update(acquisition_company_profile).values(prebuild_fingerprint="9" * 64)
                )
            elif drift_kind == "artifact":
                from signals.persistence.schema import acquisition_personalization_artifact

                connection.execute(
                    sa.update(acquisition_personalization_artifact).values(
                        artifact_fingerprint="8" * 64
                    )
                )
            else:
                connection.execute(sa.update(acquisition_supplier).values(country_code="CH"))

    assessment_service._after_policy_hook = drift

    with pytest.raises(ComplianceInputChanged):
        assessment_service.assess(
            opportunity_id,
            compliance_authorization(country=country),
            budget_usage=BudgetUsage(),
        )

    assert _count_terminal_events(engine, "compliance-eval-1") == 0
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_compliance_assessment)
            )
            == 0
        )


def test_same_evaluation_concurrency_converges_without_duplicate_terminal_writes(prepared) -> None:
    engine, _, opportunity_id, country = ready_context(prepared)
    barrier = threading.Barrier(2)
    results = []
    errors = []
    lock = threading.Lock()

    def run() -> None:
        try:
            barrier.wait(timeout=5)
            result = service(engine).assess(
                opportunity_id,
                compliance_authorization(country=country),
                budget_usage=BudgetUsage(),
            )
            with lock:
                results.append(result)
        except Exception as error:  # noqa: BLE001 - public behavior is asserted below
            with lock:
                errors.append(error)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors
    assert len(results) == 2
    assert len({row["compliance_assessment_id"] for row in results}) == 1
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(policy_evaluation)
                .where(policy_evaluation.c.evaluation_id == "compliance-eval-1")
            )
            == 1
        )
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_compliance_assessment)
            )
            == 1
        )
    assert _count_terminal_events(engine, "compliance-eval-1") == 1


def test_concurrent_same_evaluation_changed_sender_semantics_conflicts(prepared) -> None:
    engine, _, opportunity_id, country = ready_context(prepared)
    barrier = threading.Barrier(2)
    results = []
    errors = []
    lock = threading.Lock()

    def run(config: SenderComplianceConfig) -> None:
        try:
            barrier.wait(timeout=5)
            result = service(engine, sender_config=config).assess(
                opportunity_id,
                compliance_authorization(country=country),
                budget_usage=BudgetUsage(),
            )
            with lock:
                results.append(result)
        except Exception as error:  # noqa: BLE001 - typed outcome asserted below
            with lock:
                errors.append(error)

    threads = [
        threading.Thread(target=run, args=(sender(),)),
        threading.Thread(target=run, args=(sender(source_notice_ready=False),)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], ComplianceAssessmentIdempotencyConflict)
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_compliance_assessment)
            )
            == 1
        )
    assert _count_terminal_events(engine, "compliance-eval-1") == 1


def test_persisted_compliance_data_is_pii_and_copy_minimized(prepared) -> None:
    engine, _, opportunity_id, country = ready_context(prepared)
    assessment = service(engine).assess(
        opportunity_id,
        compliance_authorization(country=country),
        budget_usage=BudgetUsage(),
    )

    serialized = repr(dict(assessment)).casefold()
    snapshot = assessment["input_snapshot"]
    assert {
        "personalization_artifact_id",
        "personalization_artifact_fingerprint",
        "jurisdiction",
        "sender_config",
        "suppression_match_state",
        "suppression_key_versions_considered",
        "ruleset_version",
        "ruleset_config_fingerprint",
        "ruleset_legal_review_ref",
        "ruleset_effective_from",
        "ruleset_valid_until",
        "assessed_at",
        "as_of_date",
    } <= set(snapshot)
    for forbidden in (
        "buyer@",
        "business_email",
        "first_name",
        "last_name",
        "display_name",
        "bonjour",
        "subject",
        "body",
        "compliance-test-key",
    ):
        assert forbidden not in serialized
    with engine.connect() as connection:
        policy_row = (
            connection.execute(
                sa.select(policy_evaluation).where(
                    policy_evaluation.c.evaluation_id == "compliance-eval-1"
                )
            )
            .mappings()
            .one()
        )
        events = tuple(
            connection.execute(
                sa.select(acquisition_event).where(
                    acquisition_event.c.causation_id == "compliance-eval-1"
                )
            ).mappings()
        )
    generic_audit = repr((dict(policy_row), tuple(dict(row) for row in events))).casefold()
    for forbidden in (
        "buyer@",
        "business_email",
        "first_name",
        "last_name",
        "display_name",
        "bonjour",
        "subject",
        "body",
        "compliance-test-key",
    ):
        assert forbidden not in generic_audit
