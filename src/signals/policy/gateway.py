"""Policy orchestration: select controls, evaluate purely, and audit atomically."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition.contracts import ActorType, EventType
from signals.acquisition.store import AcquisitionStore
from signals.persistence.schema import acquisition_event
from signals.policy.contracts import (
    BudgetEnvelope,
    BudgetUsage,
    PolicyDecision,
    PolicyEvaluationIdempotencyConflict,
    PolicyRequest,
    PolicySnapshot,
    approval_binding_fingerprint,
)
from signals.policy.evaluator import evaluate_policy
from signals.policy.store import PolicyStore, decision_from_row, decision_values


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _canonical(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(nested) for nested in value]
    return value


def _fingerprint(
    request: PolicyRequest,
    snapshot: PolicySnapshot,
    budget_usage: BudgetUsage,
    evaluated_at: dt.datetime,
) -> str:
    approval_bindings = sorted(
        {
            (
                grant.approval_id,
                grant.purpose.value,
                approval_binding_fingerprint(grant),
            )
            for grant in request.approval_grants
        }
    )
    payload = {
        "evaluation_id": request.evaluation_id,
        "request": {
            "request_id": request.request_id,
            "command": request.command,
            "target_ref": request.target_ref,
            "acquisition_opportunity_id": request.acquisition_opportunity_id,
            "expected_opportunity_version": request.expected_opportunity_version,
            "actor_type": request.actor_type,
            "actor_ref": request.actor_ref,
            "action_fingerprint": request.action_fingerprint,
            "scope": request.scope.model_dump(mode="python"),
            "proposed_cost": request.proposed_cost,
            "currency": request.currency,
            "proposed_volume": request.proposed_volume,
            "reason_codes": request.reason_codes,
            "evidence_refs": request.evidence_refs,
            "evidence": request.evidence.model_dump(mode="python"),
            "compliance": request.compliance.model_dump(mode="python"),
            "operational": request.operational.model_dump(mode="python"),
            "expected_policy_version": request.expected_policy_version,
            "approval_bindings": approval_bindings,
            "supervisor_plan_id": request.supervisor_plan_id,
            "supervisor_action_index": request.supervisor_action_index,
            "supervisor_version": request.supervisor_version,
            "skill_version": request.skill_version,
        },
        "selected_policy_snapshot": snapshot.model_dump(mode="python"),
        "budget_usage": budget_usage.model_dump(mode="python"),
        "evaluated_at": evaluated_at,
    }
    encoded = json.dumps(
        _canonical(payload), allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class PolicyGateway:
    def __init__(
        self, engine: Engine, *, acquisition_store: AcquisitionStore | None = None
    ) -> None:
        self._engine = engine
        self._store = PolicyStore(engine)
        self._acquisition = acquisition_store or AcquisitionStore(engine)

    def evaluate_and_record(
        self,
        request: PolicyRequest,
        *,
        evaluated_at: dt.datetime,
        budget_usage: BudgetUsage,
    ) -> PolicyDecision:
        control = self._store.get_effective_control(evaluated_at)
        day_start = evaluated_at.replace(hour=0, minute=0, second=0, microsecond=0)
        snapshot = PolicySnapshot(
            policy_snapshot_id=control.policy_snapshot_id,
            control_revision=control.control_revision,
            policy_version=control.policy_version,
            captured_at=evaluated_at,
            expires_at=control.expires_at,
            autonomy_mode=control.autonomy_mode,
            shadow_target_mode=control.shadow_target_mode,
            read_only=control.read_only,
            kill_switch=control.kill_switch,
            allowed_commands=control.allowed_commands,
            allowed_countries=control.allowed_countries,
            allowed_languages=control.allowed_languages,
            allowed_wedges=control.allowed_wedges,
            budget=BudgetEnvelope(
                period_start=day_start,
                period_end=day_start + dt.timedelta(days=1),
                currency=control.currency,
                cost_cap=control.daily_cost_cap,
                cost_used=budget_usage.cost_used,
                volume_cap=control.daily_volume_cap,
                volume_used=budget_usage.volume_used,
            ),
            runtime_revision=request.operational.runtime_revision,
        )
        semantic_fingerprint = _fingerprint(request, snapshot, budget_usage, evaluated_at)
        with self._engine.connect() as connection:
            existing = self._store.evaluation_row(connection, request.evaluation_id)
            if existing is not None:
                return self._validated_existing(
                    connection, request, semantic_fingerprint, existing
                )

        decision = evaluate_policy(request, snapshot, evaluated_at)

        with self._engine.begin() as connection:
            existing = self._store.evaluation_row(connection, request.evaluation_id)
            if existing is not None:
                return self._validated_existing(
                    connection, request, semantic_fingerprint, existing
                )

            inserted = self._store.insert_evaluation_if_absent(
                connection,
                decision_values(decision, semantic_fingerprint),
            )
            if not inserted:
                existing = self._store.evaluation_row(connection, request.evaluation_id)
                if existing is None:
                    raise RuntimeError("policy evaluation conflict was not durable")
                return self._validated_existing(
                    connection, request, semantic_fingerprint, existing
                )
            if request.acquisition_opportunity_id is not None:
                if request.expected_opportunity_version is None:
                    raise ValueError("opportunity audit requires expected version")
                self._acquisition.append_in_transaction(
                    connection,
                    request.acquisition_opportunity_id,
                    event_type=EventType.POLICY_EVALUATED,
                    expected_version=request.expected_opportunity_version,
                    idempotency_key=f"policy_evaluation:{request.evaluation_id}",
                    actor_type=ActorType.SYSTEM,
                    actor_ref="kivou-policy-gateway",
                    reason_codes=decision.reason_codes,
                    evidence_refs=decision.evidence_refs,
                    policy_version=decision.policy_version,
                    estimated_cost=decision.estimated_cost,
                    payload={
                        "evaluation_id": decision.evaluation_id,
                        "command": decision.command,
                        "target_ref": decision.target_ref,
                        "status": decision.status.value,
                        "control_revision": decision.control_revision,
                        "approval_refs": [
                            item.model_dump(mode="json") for item in decision.approval_refs
                        ],
                    },
                    occurred_at=evaluated_at,
                )
        return decision

    @staticmethod
    def _validated_existing(
        connection,
        request: PolicyRequest,
        semantic_fingerprint: str,
        existing,
    ) -> PolicyDecision:
        if existing["semantic_fingerprint"] != semantic_fingerprint:
            raise PolicyEvaluationIdempotencyConflict(request.evaluation_id)
        if request.acquisition_opportunity_id is not None:
            event_exists = connection.scalar(
                sa.select(sa.func.count())
                .select_from(acquisition_event)
                .where(
                    acquisition_event.c.acquisition_opportunity_id
                    == request.acquisition_opportunity_id,
                    acquisition_event.c.idempotency_key
                    == f"policy_evaluation:{request.evaluation_id}",
                )
            )
            if event_exists != 1:
                raise RuntimeError("policy dual-audit invariant violated")
        return decision_from_row(existing)
