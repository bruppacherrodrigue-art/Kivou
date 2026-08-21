from __future__ import annotations

import datetime as dt
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

from signals.acquisition.contracts import AcquisitionState
from signals.decision_engine.service import DecisionEngineService
from signals.persistence.schema import (
    acquisition_event,
    acquisition_personalization_artifact,
    policy_evaluation,
)
from signals.personalization.grounding import (
    PersonalizationDecisionNoLongerEligible,
    PersonalizationGroundingInsufficient,
)
from signals.personalization.service import PersonalizationService
from signals.personalization.store import PersonalizationArtifactIdempotencyConflict
from signals.policy.contracts import AutonomyMode, BudgetUsage, EvidenceReadiness
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
