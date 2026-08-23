from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from test_campaign_service import (
    NOW,
    _approved,
    _assisted,
    _deployment,
    _service,
)
from test_campaign_store import _prepared
from test_learning_store import NOW as LEARNING_NOW
from test_learning_store import _context

from signals.campaigns.contracts import CampaignDeploymentBlocked
from signals.learning.store import LearningConflict, LearningStore
from signals.operations.contracts import (
    BreakerScope,
    IncidentSeverity,
    IncidentTrigger,
    IncidentType,
)
from signals.operations.store import OperationsStore
from signals.persistence.schema import policy_evaluation
from signals.policy.contracts import BudgetUsage


def _open_global(engine, *, at: dt.datetime) -> None:
    OperationsStore(engine).open_incident(
        IncidentTrigger(
            incident_type=IncidentType.UNEXPECTED_TRANSPORT_TRUTH,
            severity=IncidentSeverity.CRITICAL,
            scope=BreakerScope(scope_type="GLOBAL", scope_ref="acquisition"),
            source_state_ref="synthetic-critical-event",
            triggered_at=at,
            reason_codes=("POST_STOP_SEND",),
            human_review_required=True,
            pause_required=True,
        )
    )


def test_open_breaker_blocks_new_campaign_before_policy_or_provider_planning(tmp_path) -> None:
    engine, opportunity_id, _, _ = _prepared(tmp_path)
    _assisted(engine)
    service = _service(engine, _deployment())
    authorization = _approved(service, engine, opportunity_id)
    _open_global(engine, at=NOW)

    with pytest.raises(CampaignDeploymentBlocked, match="circuit"):
        service.schedule(opportunity_id, authorization, budget_usage=BudgetUsage())

    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(policy_evaluation)
            .where(policy_evaluation.c.evaluation_id == authorization.evaluation_id)
        ) == 0


def test_open_breaker_blocks_learning_application_without_rewriting_proposal(tmp_path) -> None:
    engine, snapshot, envelope, candidates = _context(tmp_path)
    store = LearningStore(engine)
    store.save_snapshot(snapshot)
    store.save_candidates(candidates, envelope_fingerprint=envelope.fingerprint, created_at=LEARNING_NOW)
    shift = next(item for item in candidates if item.delta_units == 1)
    store.record_selection(
        shift.proposal_ref,
        source="HERMES",
        confidence=Decimal("0.9"),
        decided_at=LEARNING_NOW,
    )
    store.record_policy(
        shift.proposal_ref,
        evaluation_id="evaluation-breaker",
        action_fingerprint="f" * 64,
        status="APPROVED",
        counterfactual_status=None,
        state="PROPOSED",
        decided_at=LEARNING_NOW,
    )
    _open_global(engine, at=LEARNING_NOW)

    with pytest.raises(LearningConflict, match="circuit"):
        store.apply(shift.proposal_ref, applied_at=LEARNING_NOW)

    assert store.existing_cycle(
        window_end=snapshot.window.window_end,
        envelope_fingerprint=envelope.fingerprint,
    )[1]["state"] == "PROPOSED"

