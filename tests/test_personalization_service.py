from __future__ import annotations

import datetime as dt
import threading
from dataclasses import replace
from decimal import Decimal

import pytest
import sqlalchemy as sa
from test_decision_engine_service import (
    EVALUATED_AT,
    authorization,
)
from test_decision_engine_service import (
    context as decision_context,
)
from test_policy_persistence import control

from signals.acquisition.contracts import AcquisitionState, OpportunityConcurrencyConflict
from signals.decision_engine.service import DecisionEngineService
from signals.persistence.schema import (
    acquisition_company_profile,
    acquisition_contact,
    acquisition_event,
    acquisition_personalization_artifact,
    acquisition_supplier,
    contract_award,
    policy_evaluation,
)
from signals.personalization.catalog import PersonalizationLanguageUnsupported
from signals.personalization.grounding import (
    PersonalizationDecisionNoLongerEligible,
    PersonalizationGroundingInsufficient,
)
from signals.personalization.service import (
    PersonalizationConvergenceInvariantViolated,
    PersonalizationEvaluationRequiresFreshAttempt,
    PersonalizationInputChanged,
    PersonalizationService,
)
from signals.personalization.store import PersonalizationArtifactIdempotencyConflict
from signals.personalization.validator import PersonalizationValidationError
from signals.policy.contracts import (
    AutonomyMode,
    BudgetUsage,
    EvidenceReadiness,
    PolicyEvaluationIdempotencyConflict,
    Scope,
)
from signals.policy.store import PolicyStore


class CountingClock:
    def __init__(self, value: dt.datetime) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> dt.datetime:
        self.calls += 1
        return self.value


@pytest.fixture
def context(tmp_path):
    return decision_context.__wrapped__(tmp_path)


def personalization_authorization(evaluation_id: str = "personalization-eval-1"):
    base = authorization(evaluation_id)
    return base.model_copy(
        update={
            "actor_ref": "kivou-personalization",
            "evidence": EvidenceReadiness(
                status=base.evidence.status,
                claims=("CALLER_CANNOT_SELECT_PERSONALIZATION_CLAIMS",),
                assessment_version="personalization-evidence-v1",
                observed_at=base.evidence.observed_at,
            ),
        }
    )


def test_service_creates_one_ready_artifact_and_advances_next_action(context) -> None:
    engine, acquisition, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(
            2,
            allowed_commands=("prepare_campaign",),
            effective_at=EVALUATED_AT - dt.timedelta(seconds=1),
        )
    )
    clock = CountingClock(EVALUATED_AT)

    artifact = PersonalizationService(engine, clock=clock).personalize(
        opportunity_id,
        "fr",
        personalization_authorization(),
        budget_usage=BudgetUsage(cost_used=Decimal("5")),
    )

    assert clock.calls == 1
    assert artifact["disposition"] == "READY"
    assert artifact["greeting"] == "Bonjour,"
    current = acquisition.get_opportunity(opportunity_id)
    assert current.state is AcquisitionState.SEND
    assert current.next_action == "assess_campaign_compliance"


def test_ready_artifact_persists_safe_need_and_public_provenance(context) -> None:
    engine, _, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(2, allowed_commands=("prepare_campaign",), effective_at=EVALUATED_AT)
    )
    artifact = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT)).personalize(
        opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
    )
    snapshot = artifact["input_snapshot"]
    for key in (
        "representative_award_key",
        "source_event_key",
        "public_evidence_refs",
        "recency_basis",
        "recency_date",
        "decision_policy_config_fingerprint",
        "selected_need_category",
        "selected_need_confidence",
        "selected_need_fingerprint",
    ):
        assert key in snapshot
    claims = {claim["claim_id"]: claim for claim in artifact["claim_map"]}
    assert claims["PUBLIC_EVENT"]["kind"] == "PUBLIC_FACT"
    assert claims["PLAUSIBLE_NEED"]["kind"] == "KIVOU_INFERENCE"
    need_ref = (
        f"need-graph:{artifact['need_engine_version']}:"
        f"{artifact['selected_need_fingerprint']}"
    )
    assert need_ref in claims["PLAUSIBLE_NEED"]["evidence_refs"]
    assert set(claims["PUBLIC_EVENT"]["evidence_refs"]) != set(
        claims["PLAUSIBLE_NEED"]["evidence_refs"]
    )
    assert claims["KIVOU_CTA"]["kind"] == "KIVOU_PRODUCT_COPY"
    expected_evidence = tuple(
        dict.fromkeys(ref for claim in artifact["claim_map"] for ref in claim["evidence_refs"])
    )
    with engine.connect() as connection:
        stored_evidence = connection.scalar(
            sa.select(policy_evaluation.c.evidence_refs).where(
                policy_evaluation.c.evaluation_id == "personalization-eval-1"
            )
        )
    assert tuple(stored_evidence) == expected_evidence
    serialized = repr(snapshot)
    assert "business_email" not in serialized
    assert "first_name" not in serialized


def test_day_sixty_one_historical_send_fails_before_personalization_policy(context) -> None:
    engine, _, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    clock = CountingClock(EVALUATED_AT + dt.timedelta(days=1))

    with pytest.raises(PersonalizationDecisionNoLongerEligible):
        PersonalizationService(engine, clock=clock).personalize(
            opportunity_id,
            "fr",
            personalization_authorization(),
            budget_usage=BudgetUsage(),
        )

    assert clock.calls == 1
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == 1
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_personalization_artifact)
        )
            == 0
        )


def test_current_zero_need_grounding_fails_before_policy(context, monkeypatch) -> None:
    engine, _, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )

    from signals.needs import NeedGraphEngine as ActualNeedGraphEngine

    class EmptyNeedGraph:
        def derive(self, understanding):
            return ActualNeedGraphEngine().derive(understanding).model_copy(update={"needs": ()})

    monkeypatch.setattr("signals.personalization.service.NeedGraphEngine", EmptyNeedGraph)
    with pytest.raises(PersonalizationGroundingInsufficient):
        PersonalizationService(engine, clock=CountingClock(EVALUATED_AT)).personalize(
            opportunity_id,
            "fr",
            personalization_authorization(),
            budget_usage=BudgetUsage(),
        )

    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == 1
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_personalization_artifact)
        )
            == 0
        )


def test_service_rejects_renderer_copy_that_differs_from_frozen_catalog(context, monkeypatch) -> None:
    """The validator's independent catalog renderer guards the real service boundary."""
    engine, _, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(2, allowed_commands=("prepare_campaign",), effective_at=EVALUATED_AT)
    )

    from signals.personalization.catalog import render_catalog_message as frozen_renderer

    def altered_renderer(**kwargs):
        return replace(frozen_renderer(**kwargs), cta="Unapproved CTA")

    monkeypatch.setattr("signals.personalization.service.render_catalog_message", altered_renderer)
    with pytest.raises(PersonalizationValidationError):
        PersonalizationService(engine, clock=CountingClock(EVALUATED_AT)).personalize(
            opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
        )

    with engine.connect() as connection:
        # Only the historical SPEC-023 policy evaluation exists: catalog failure is pre-Policy.
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == 1
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_personalization_artifact)
            )
            == 0
        )


def test_completed_artifact_replays_with_historical_budget_not_caller_budget(context) -> None:
    engine, acquisition, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(
            2,
            allowed_commands=("prepare_campaign",),
            effective_at=EVALUATED_AT - dt.timedelta(seconds=1),
        )
    )
    first = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT)).personalize(
        opportunity_id,
        "fr",
        personalization_authorization(),
        budget_usage=BudgetUsage(cost_used=Decimal("7.50"), volume_used=12),
    )
    stream_version = acquisition.get_opportunity(opportunity_id).stream_version
    replay_clock = CountingClock(EVALUATED_AT + dt.timedelta(days=30))
    replay = PersonalizationService(engine, clock=replay_clock).personalize(
        opportunity_id,
        "fr",
        personalization_authorization(),
        budget_usage=BudgetUsage(cost_used=Decimal("71.25"), volume_used=73),
    )

    assert replay["personalization_artifact_id"] == first["personalization_artifact_id"]
    assert replay_clock.calls == 0
    assert acquisition.get_opportunity(opportunity_id).stream_version == stream_version
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(policy_evaluation)) == 2
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_personalization_artifact)
            )
            == 1
        )
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_event)
            .where(acquisition_event.c.event_type == "NEXT_ACTION_SET")
        ) == 3


def test_changed_actor_for_completed_artifact_conflicts(context) -> None:
    engine, _, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(2, allowed_commands=("prepare_campaign",), effective_at=EVALUATED_AT)
    )
    service = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT))
    service.personalize(
        opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
    )
    with pytest.raises(PersonalizationArtifactIdempotencyConflict):
        service.personalize(
            opportunity_id,
            "fr",
            personalization_authorization().model_copy(update={"actor_ref": "different"}),
            budget_usage=BudgetUsage(),
        )


@pytest.mark.parametrize(
    "changed_authorization",
    (
        lambda value: value.model_copy(
            update={"scope": Scope(country="FR", language="fr", wedge="construction")}
        ),
        lambda value: value.model_copy(
            update={
                "evidence": value.evidence.model_copy(
                    update={"assessment_version": "personalization-evidence-v2"}
                )
            }
        ),
    ),
    ids=("scope", "material_evidence"),
)
def test_completed_artifact_replay_rejects_changed_authorization_semantics(
    context, changed_authorization
) -> None:
    engine, _, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(2, allowed_commands=("prepare_campaign",), effective_at=EVALUATED_AT)
    )
    PersonalizationService(engine, clock=CountingClock(EVALUATED_AT)).personalize(
        opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
    )
    replay_clock = CountingClock(EVALUATED_AT)
    with pytest.raises(PersonalizationArtifactIdempotencyConflict):
        PersonalizationService(engine, clock=replay_clock).personalize(
            opportunity_id,
            "fr",
            changed_authorization(personalization_authorization()),
            budget_usage=BudgetUsage(cost_used=Decimal("100"), volume_used=100),
        )
    assert replay_clock.calls == 0
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(policy_evaluation)
            .where(policy_evaluation.c.evaluation_id == "personalization-eval-1")
        ) == 1
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(acquisition_personalization_artifact)
                .where(
                    acquisition_personalization_artifact.c.policy_evaluation_id
                    == "personalization-eval-1"
                )
            )
            == 1
        )
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_event)
            .where(
                acquisition_event.c.event_type == "NEXT_ACTION_SET",
                acquisition_event.c.causation_id == "personalization-eval-1",
            )
        ) == 1


def test_completed_artifact_replay_conflicts_on_requested_language(context) -> None:
    engine, _, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(2, allowed_commands=("prepare_campaign",), effective_at=EVALUATED_AT)
    )
    service = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT))
    service.personalize(
        opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
    )
    replay_clock = CountingClock(EVALUATED_AT)
    with pytest.raises(PersonalizationArtifactIdempotencyConflict):
        PersonalizationService(engine, clock=replay_clock).personalize(
            opportunity_id, "en", personalization_authorization(), budget_usage=BudgetUsage()
        )
    assert replay_clock.calls == 0


def test_completed_artifact_replay_rejects_unsupported_language_before_clock(context) -> None:
    engine, _, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(2, allowed_commands=("prepare_campaign",), effective_at=EVALUATED_AT)
    )
    PersonalizationService(engine, clock=CountingClock(EVALUATED_AT)).personalize(
        opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
    )
    clock = CountingClock(EVALUATED_AT)
    with pytest.raises(PersonalizationLanguageUnsupported):
        PersonalizationService(engine, clock=clock).personalize(
            opportunity_id, "de", personalization_authorization(), budget_usage=BudgetUsage()
        )
    assert clock.calls == 0


def test_policy_without_artifact_requires_a_fresh_evaluation_without_clock(context) -> None:
    engine, acquisition, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(2, allowed_commands=("prepare_campaign",), effective_at=EVALUATED_AT)
    )
    service = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT))
    authorization_input = personalization_authorization()
    values = service._build_values(service._load(opportunity_id), "fr", EVALUATED_AT.date())
    request = service._request(
        authorization_input, values, expected_version=acquisition.get_opportunity(opportunity_id).stream_version
    )
    service._policy.evaluate_and_record(
        request, evaluated_at=EVALUATED_AT, budget_usage=BudgetUsage()
    )

    replay_clock = CountingClock(EVALUATED_AT)
    with pytest.raises(PersonalizationEvaluationRequiresFreshAttempt):
        PersonalizationService(engine, clock=replay_clock).personalize(
            opportunity_id, "fr", authorization_input, budget_usage=BudgetUsage()
        )
    assert replay_clock.calls == 0
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(policy_evaluation)
            .where(policy_evaluation.c.evaluation_id == authorization_input.evaluation_id)
        ) == 1
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(acquisition_personalization_artifact)
                .where(
                    acquisition_personalization_artifact.c.policy_evaluation_id
                    == authorization_input.evaluation_id
                )
            )
            == 0
        )
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_event)
            .where(
                acquisition_event.c.event_type == "NEXT_ACTION_SET",
                acquisition_event.c.causation_id == authorization_input.evaluation_id,
            )
        ) == 0


def test_post_policy_company_profile_drift_is_a_single_typed_input_change(context) -> None:
    engine, _, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(2, allowed_commands=("prepare_campaign",), effective_at=EVALUATED_AT)
    )
    service = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT))

    def drift_profile() -> None:
        with engine.begin() as connection:
            connection.execute(
                sa.update(acquisition_company_profile)
                .where(acquisition_company_profile.c.acquisition_opportunity_id == opportunity_id)
                .values(prebuild_fingerprint="f" * 64)
            )

    service._after_policy_hook = drift_profile
    with pytest.raises(PersonalizationInputChanged):
        service.personalize(
            opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
        )

    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_personalization_artifact)
            )
            == 0
        )
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_event)
            .where(acquisition_event.c.event_type == "NEXT_ACTION_SET")
        ) == 2


def _service_after_send(context):
    engine, _, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(2, allowed_commands=("prepare_campaign",), effective_at=EVALUATED_AT)
    )
    return engine, opportunity_id, PersonalizationService(engine, clock=CountingClock(EVALUATED_AT))


def _assert_post_policy_drift_has_no_personalization_terminal_write(engine, evaluation_id: str) -> None:
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_personalization_artifact)
            )
            == 0
        )
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_event)
            .where(
                acquisition_event.c.event_type == "NEXT_ACTION_SET",
                acquisition_event.c.causation_id == evaluation_id,
                acquisition_event.c.payload["next_action"].as_string()
                == "assess_campaign_compliance",
            )
        ) == 0


def test_post_policy_supplier_identity_drift_is_input_changed(context) -> None:
    engine, opportunity_id, service = _service_after_send(context)

    def drift_supplier() -> None:
        with engine.begin() as connection:
            connection.execute(
                sa.update(acquisition_supplier).values(identity_status="DOMAIN_CONFLICT")
            )

    service._after_policy_hook = drift_supplier
    with pytest.raises(PersonalizationInputChanged):
        service.personalize(
            opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
        )
    _assert_post_policy_drift_has_no_personalization_terminal_write(
        engine, "personalization-eval-1"
    )


def test_post_policy_contact_binding_drift_is_input_changed(context) -> None:
    engine, opportunity_id, service = _service_after_send(context)

    def drift_contact() -> None:
        with engine.begin() as connection:
            connection.execute(sa.update(acquisition_contact).values(role_tier=4))

    service._after_policy_hook = drift_contact
    with pytest.raises(PersonalizationInputChanged):
        service.personalize(
            opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
        )
    _assert_post_policy_drift_has_no_personalization_terminal_write(
        engine, "personalization-eval-1"
    )


def test_post_policy_public_context_drift_is_input_changed(context) -> None:
    engine, opportunity_id, service = _service_after_send(context)

    def drift_award() -> None:
        with engine.begin() as connection:
            connection.execute(sa.update(contract_award).values(award_date=dt.date(2026, 7, 17)))

    service._after_policy_hook = drift_award
    with pytest.raises(PersonalizationInputChanged):
        service.personalize(
            opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
        )
    _assert_post_policy_drift_has_no_personalization_terminal_write(
        engine, "personalization-eval-1"
    )


def test_post_policy_need_graph_zero_need_drift_is_input_changed(context, monkeypatch) -> None:
    engine, opportunity_id, service = _service_after_send(context)
    from signals.needs import NeedGraphEngine as ActualNeedGraphEngine

    phase = {"after_policy": False}

    class SwitchableNeedGraph:
        def derive(self, understanding):
            result = ActualNeedGraphEngine().derive(understanding)
            return result.model_copy(update={"needs": ()}) if phase["after_policy"] else result

    monkeypatch.setattr("signals.personalization.service.NeedGraphEngine", SwitchableNeedGraph)
    service._after_policy_hook = lambda: phase.__setitem__("after_policy", True)
    with pytest.raises(PersonalizationInputChanged):
        service.personalize(
            opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
        )
    _assert_post_policy_drift_has_no_personalization_terminal_write(
        engine, "personalization-eval-1"
    )


def test_concurrent_same_evaluation_converges_to_one_artifact_and_next_action(context) -> None:
    engine, _, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(2, allowed_commands=("prepare_campaign",), effective_at=EVALUATED_AT)
    )
    barrier = threading.Barrier(2)
    results = []
    errors = []
    result_lock = threading.Lock()

    def run() -> None:
        try:
            barrier.wait(timeout=5)
            result = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT)).personalize(
                opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
            )
            with result_lock:
                results.append(result)
        except (RuntimeError, sa.exc.SQLAlchemyError, ValueError) as error:
            with result_lock:
                errors.append(error)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors
    assert len(results) == 2
    assert {result["personalization_artifact_id"] for result in results} == {
        results[0]["personalization_artifact_id"]
    }
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(policy_evaluation)
            .where(policy_evaluation.c.evaluation_id == "personalization-eval-1")
        ) == 1
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(acquisition_personalization_artifact)
            )
            == 1
        )
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_event)
            .where(
                acquisition_event.c.event_type == "NEXT_ACTION_SET",
                acquisition_event.c.causation_id == "personalization-eval-1",
            )
        ) == 1


def test_concurrent_languages_cannot_create_two_personalization_outcomes(context) -> None:
    engine, _, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(2, allowed_commands=("prepare_campaign",), effective_at=EVALUATED_AT)
    )
    barrier = threading.Barrier(2)
    results = []
    errors = []
    result_lock = threading.Lock()

    def run(language: str) -> None:
        try:
            barrier.wait(timeout=5)
            result = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT)).personalize(
                opportunity_id, language, personalization_authorization(), budget_usage=BudgetUsage()
            )
            with result_lock:
                results.append(result)
        except (
            PersonalizationArtifactIdempotencyConflict,
            PolicyEvaluationIdempotencyConflict,
            RuntimeError,
            sa.exc.SQLAlchemyError,
            ValueError,
        ) as error:
            with result_lock:
                errors.append(error)

    threads = [threading.Thread(target=run, args=(language,)) for language in ("fr", "en")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert len(results) == 1
    assert len(errors) == 1
    assert isinstance(
        errors[0], (PersonalizationArtifactIdempotencyConflict, PolicyEvaluationIdempotencyConflict)
    )
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(policy_evaluation)
            .where(policy_evaluation.c.evaluation_id == "personalization-eval-1")
        ) == 1
        artifact = connection.execute(sa.select(acquisition_personalization_artifact)).mappings().one()
        assert artifact["language"] == results[0]["language"]
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_event)
            .where(
                acquisition_event.c.event_type == "NEXT_ACTION_SET",
                acquisition_event.c.causation_id == "personalization-eval-1",
            )
        ) == 1


def test_shadow_persists_pii_minimized_blocked_artifact_without_workflow_event(context) -> None:
    engine, acquisition, opportunity_id = context
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(
            2,
            autonomy_mode=AutonomyMode.SHADOW,
            shadow_target_mode=AutonomyMode.AUTONOMOUS_CAPPED,
            allowed_commands=("prepare_campaign",),
            effective_at=EVALUATED_AT - dt.timedelta(seconds=1),
        )
    )
    before = acquisition.get_opportunity(opportunity_id).stream_version
    artifact = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT)).personalize(
        opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
    )

    assert artifact["disposition"] == "POLICY_BLOCKED"
    assert all(artifact[field] is None for field in ("subject", "greeting", "body", "cta"))
    current = acquisition.get_opportunity(opportunity_id)
    assert current.stream_version == before + 1  # POLICY_EVALUATED only
    assert current.next_action == "prepare_campaign"


# ─── #33 — la frontière atomique, et la convergence du perdant ────────────────
#
# Une évaluation concurrente doit produire EXACTEMENT un artefact et une seule
# prochaine action. Auparavant, la convergence n'était tentée que sur
# `PersonalizationInputChanged` : la même course pouvait surgir en
# `OpportunityConcurrencyConflict` ou `PolicyEvaluationIdempotencyConflict`, et
# le perdant remontait alors l'exception au lieu de l'artefact du gagnant.


def _prepared(engine, opportunity_id):
    """Amène l'opportunité au point où la personnalisation est possible."""
    DecisionEngineService(engine, clock=lambda: EVALUATED_AT).evaluate(
        opportunity_id, authorization(), budget_usage=BudgetUsage()
    )
    PolicyStore(engine).append_control(
        control(2, allowed_commands=("prepare_campaign",), effective_at=EVALUATED_AT)
    )


def _counts(engine):
    """(évaluations de personnalisation, artefacts, prochaines actions)."""
    with engine.connect() as connection:
        evaluations = connection.scalar(
            sa.select(sa.func.count())
            .select_from(policy_evaluation)
            .where(policy_evaluation.c.evaluation_id == "personalization-eval-1")
        )
        artifacts = connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_personalization_artifact)
        )
        next_actions = connection.scalar(
            sa.select(sa.func.count())
            .select_from(acquisition_event)
            .where(
                acquisition_event.c.idempotency_key
                == "personalization_next_action:personalization-eval-1"
            )
        )
    return evaluations, artifacts, next_actions


def test_a_loser_converges_deterministically_on_the_winner_artifact(context) -> None:
    """Course FORCÉE, sans fil ni horloge : l'ordre est imposé, pas espéré.

    Le point d'ancrage post-politique fait tourner une seconde
    personnalisation ENTIÈRE — qui valide — avant que la première n'ouvre sa
    transaction. La première se retrouve donc systématiquement perdante.
    """
    engine, _, opportunity_id = context
    _prepared(engine, opportunity_id)

    loser = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT))
    winner_result = {}

    def let_the_winner_commit() -> None:
        if not winner_result:
            winner_result["artifact"] = PersonalizationService(
                engine, clock=CountingClock(EVALUATED_AT)
            ).personalize(
                opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
            )

    loser._after_policy_hook = let_the_winner_commit

    converged = loser.personalize(
        opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
    )

    assert winner_result, "le gagnant doit avoir validé avant le perdant"
    assert (
        converged["personalization_artifact_id"]
        == winner_result["artifact"]["personalization_artifact_id"]
    )
    assert _counts(engine) == (1, 1, 1), "un artefact, une évaluation, une prochaine action"


def test_the_loser_writes_nothing_at_all(context) -> None:
    """Le perdant doit voir sa transaction ENTIÈREMENT annulée avant de lire.

    Un rollback partiel laisserait un événement ou une évaluation orphelins :
    les comptages sont donc pris avant et après la course perdue.
    """
    engine, _, opportunity_id = context
    _prepared(engine, opportunity_id)

    winner = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT)).personalize(
        opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
    )
    after_winner = _counts(engine)

    loser = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT))
    converged = loser.personalize(
        opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
    )

    assert converged["personalization_artifact_id"] == winner["personalization_artifact_id"]
    assert _counts(engine) == after_winner, "le perdant n'a rien écrit"


@pytest.mark.parametrize(
    "conflict",
    [OpportunityConcurrencyConflict, PolicyEvaluationIdempotencyConflict],
    ids=["opportunity-version", "policy-idempotency"],
)
def test_each_atomic_conflict_converges_on_the_concurrent_artifact(context, conflict) -> None:
    """Les deux conflits qui GARANTISSENT un gagnant doivent converger.

    Auparavant seul `PersonalizationInputChanged` était rattrapé : ces deux-là
    remontaient à l'appelant, qui recevait une exception au lieu de l'artefact
    déjà écrit.

    L'ordre est imposé, pas espéré : le perdant franchit ses gardes d'entrée
    AVANT que le gagnant ne valide — c'est la vraie forme de la course, et la
    seule où ces conflits sont observables. Le type de conflit, lui, est injecté
    pour couvrir les deux sans dépendre de l'ordonnancement du système.
    """
    engine, _, opportunity_id = context
    _prepared(engine, opportunity_id)

    loser = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT))
    winner_result = {}

    def let_the_winner_commit() -> None:
        if winner_result:
            return
        winner_result["artifact"] = PersonalizationService(
            engine, clock=CountingClock(EVALUATED_AT)
        ).personalize(
            opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
        )

        def raise_conflict(*_args, **_kwargs):
            raise conflict(opportunity_id)

        loser._policy.record_in_transaction = raise_conflict

    loser._after_policy_hook = let_the_winner_commit

    converged = loser.personalize(
        opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
    )

    assert winner_result, "le gagnant doit avoir validé avant le perdant"
    assert (
        converged["personalization_artifact_id"]
        == winner_result["artifact"]["personalization_artifact_id"]
    )
    assert _counts(engine) == (1, 1, 1)


@pytest.mark.parametrize(
    "conflict",
    [OpportunityConcurrencyConflict, PolicyEvaluationIdempotencyConflict],
    ids=["opportunity-version", "policy-idempotency"],
)
def test_an_atomic_conflict_without_any_artifact_is_an_invariant_error(context, conflict) -> None:
    """Ne rien trouver après un conflit atomique n'est PAS une course à retenter.

    Depuis que les cinq écritures partagent une transaction, voir l'un de ces
    conflits prouve qu'un gagnant a validé. L'artefact introuvable signale donc
    une corruption — et doit être dit, jamais absorbé par une attente ou un
    nouvel essai.
    """
    engine, _, opportunity_id = context
    _prepared(engine, opportunity_id)

    service = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT))
    service._artifacts.get_by_policy = lambda _evaluation_id: None

    def raise_conflict(*_args, **_kwargs):
        raise conflict(opportunity_id)

    service._policy.record_in_transaction = raise_conflict

    with pytest.raises(PersonalizationConvergenceInvariantViolated):
        service.personalize(
            opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
        )


def test_the_policy_evaluation_and_the_artifact_share_one_transaction(context) -> None:
    """Aucun état intermédiaire ne doit survivre à un échec d'écriture.

    L'évaluation de politique était inscrite dans SA transaction, donc un échec
    ultérieur laissait une évaluation sans artefact — et c'est ce résidu qui
    rendait le conflit du perdant non concluant.
    """
    engine, _, opportunity_id = context
    _prepared(engine, opportunity_id)

    service = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT))
    boom = RuntimeError("échec après inscription de l'évaluation")

    def explode(*_args, **_kwargs):
        raise boom

    service._artifacts.append_in_transaction = explode

    with pytest.raises(RuntimeError):
        service.personalize(
            opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
        )

    assert _counts(engine) == (0, 0, 0), "l'évaluation doit être annulée avec l'artefact"


@pytest.mark.parametrize("attempt", range(6))
def test_two_concurrent_threads_always_converge(context, attempt: int) -> None:
    """La course réelle, répétée : deux appels, un seul artefact, aucun échec."""
    engine, _, opportunity_id = context
    _prepared(engine, opportunity_id)

    barrier = threading.Barrier(2)
    results, errors = [], []
    lock = threading.Lock()

    def run() -> None:
        try:
            barrier.wait(timeout=5)
            result = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT)).personalize(
                opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
            )
            with lock:
                results.append(result)
        except BaseException as error:  # noqa: BLE001 - aucune exception n'est acceptable
            with lock:
                errors.append(error)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors, f"aucun appelant ne doit échouer : {errors}"
    assert len(results) == 2
    assert len({result["personalization_artifact_id"] for result in results}) == 1
    assert _counts(engine) == (1, 1, 1)


# ─── Les deux fenêtres que seul PostgreSQL sous contention a révélées ─────────


def test_a_winner_committing_between_the_two_entry_guards_still_converges(context) -> None:
    """Les gardes d'entrée sont DEUX lectures, à deux instants.

    Un gagnant qui valide entre elles laisse le perdant voir son évaluation sans
    avoir vu son artefact — d'où un `RequiresFreshAttempt` alors qu'il s'agit
    d'une course. Les deux étant écrits dans la même transaction, une relecture
    postérieure trouve nécessairement l'artefact.

    Constaté sur PostgreSQL sous contention ; SQLite sérialise assez pour que la
    fenêtre ne s'ouvre jamais. L'ordre est ici imposé, donc le test vaut sur les
    deux moteurs.
    """
    engine, _, opportunity_id = context
    _prepared(engine, opportunity_id)

    loser = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT))
    winner = {}
    real = loser._artifacts.get_by_policy

    def get_by_policy(evaluation_id):
        if not winner:
            # Première garde : rien encore. Le gagnant valide JUSTE APRÈS.
            winner["artifact"] = PersonalizationService(
                engine, clock=CountingClock(EVALUATED_AT)
            ).personalize(
                opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
            )
            return None
        return real(evaluation_id)

    loser._artifacts.get_by_policy = get_by_policy

    converged = loser.personalize(
        opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
    )

    assert (
        converged["personalization_artifact_id"]
        == winner["artifact"]["personalization_artifact_id"]
    )
    assert _counts(engine) == (1, 1, 1)


def test_an_opportunity_advanced_by_the_winner_is_a_race_not_a_dead_end(context) -> None:
    """Le chargement des valeurs est HORS transaction, donc rattrapable.

    Le gagnant fait avancer l'opportunité ; le perdant la recharge et la trouve
    « non actionnable » — pour une raison qui n'en est pas une. Si l'artefact du
    gagnant existe, c'est une course, et l'on converge.
    """
    engine, _, opportunity_id = context
    _prepared(engine, opportunity_id)

    winner = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT)).personalize(
        opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
    )

    loser = PersonalizationService(engine, clock=CountingClock(EVALUATED_AT))
    seen = {"guards": 0}
    real = loser._artifacts.get_by_policy

    def get_by_policy(evaluation_id):
        seen["guards"] += 1
        # La garde d'entrée est aveugle : le perdant descend jusqu'au
        # chargement, où l'opportunité a déjà avancé.
        return None if seen["guards"] <= 1 else real(evaluation_id)

    loser._artifacts.get_by_policy = get_by_policy

    # Seule la GARDE D'ENTRÉE est aveuglée : `_require_existing` s'appuie
    # légitimement sur la même lecture pour valider la convergence.
    real_evaluation_row = loser._policy_store.evaluation_row
    entry = {"seen": False}

    def evaluation_row(connection, evaluation_id):
        if not entry["seen"]:
            entry["seen"] = True
            return None
        return real_evaluation_row(connection, evaluation_id)

    loser._policy_store.evaluation_row = evaluation_row

    converged = loser.personalize(
        opportunity_id, "fr", personalization_authorization(), budget_usage=BudgetUsage()
    )

    assert converged["personalization_artifact_id"] == winner["personalization_artifact_id"]
    assert _counts(engine) == (1, 1, 1)
