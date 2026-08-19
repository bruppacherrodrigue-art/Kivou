"""Append-only SQLAlchemy Core persistence for policy controls and audits."""

from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping

from signals.persistence.schema import acquisition_policy_snapshot, policy_evaluation
from signals.policy.contracts import (
    PolicyControlSnapshot,
    PolicyControlUnavailable,
    PolicyDecision,
)


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=dt.UTC)
    return value


def _control_values(control: PolicyControlSnapshot) -> dict[str, object]:
    values = control.model_dump(mode="python")
    values["autonomy_mode"] = control.autonomy_mode.value
    values["shadow_target_mode"] = (
        control.shadow_target_mode.value if control.shadow_target_mode else None
    )
    for field in (
        "allowed_commands",
        "allowed_countries",
        "allowed_languages",
        "allowed_wedges",
        "reason_codes",
    ):
        values[field] = list(values[field])
    return values


def _control_from_row(row: RowMapping) -> PolicyControlSnapshot:
    values = dict(row)
    for field in ("effective_at", "expires_at", "created_at"):
        values[field] = _aware(values[field])
    for field in (
        "allowed_commands",
        "allowed_countries",
        "allowed_languages",
        "allowed_wedges",
        "reason_codes",
    ):
        values[field] = tuple(values[field])
    return PolicyControlSnapshot.model_validate(values)


def decision_values(decision: PolicyDecision, semantic_fingerprint: str) -> dict[str, object]:
    return {
        "evaluation_id": decision.evaluation_id,
        "request_id": decision.request_id,
        "acquisition_opportunity_id": decision.acquisition_opportunity_id,
        "command": decision.command,
        "target_ref": decision.target_ref,
        "action_fingerprint": decision.action_fingerprint,
        "status": decision.status.value,
        "counterfactual_status": decision.counterfactual_status.value
        if decision.counterfactual_status
        else None,
        "executable": decision.executable,
        "reason_codes": list(decision.reason_codes),
        "policy_version": decision.policy_version,
        "policy_snapshot_id": decision.policy_snapshot_id,
        "control_revision": decision.control_revision,
        "runtime_revision": decision.runtime_revision,
        "evidence_refs": list(decision.evidence_refs),
        "currency": decision.currency,
        "estimated_cost": decision.estimated_cost,
        "proposed_volume": decision.proposed_volume,
        "cost_remaining": decision.cost_remaining,
        "volume_remaining": decision.volume_remaining,
        "approval_ids": list(decision.approval_ids),
        "evaluated_at": decision.evaluated_at,
        "valid_until": decision.valid_until,
        "retry_after": decision.retry_after,
        "requires_revalidation": decision.requires_revalidation,
        "semantic_fingerprint": semantic_fingerprint,
    }


def decision_from_row(row: RowMapping) -> PolicyDecision:
    values = dict(row)
    values.pop("semantic_fingerprint")
    for field in ("evaluated_at", "valid_until", "retry_after"):
        values[field] = _aware(values[field])
    for field in ("reason_codes", "evidence_refs", "approval_ids"):
        values[field] = tuple(values[field])
    return PolicyDecision.model_validate(values)


class PolicyStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append_control(self, control: PolicyControlSnapshot) -> None:
        with self._engine.begin() as connection:
            maximum = connection.scalar(
                sa.select(sa.func.max(acquisition_policy_snapshot.c.control_revision))
            )
            if maximum is not None and control.control_revision <= maximum:
                raise ValueError("control_revision must be greater than current maximum")
            connection.execute(
                sa.insert(acquisition_policy_snapshot).values(_control_values(control))
            )

    def get_effective_control(self, at: dt.datetime) -> PolicyControlSnapshot:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("selection timestamp must be timezone-aware")
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(acquisition_policy_snapshot)
                    .where(
                        acquisition_policy_snapshot.c.effective_at <= at,
                        sa.or_(
                            acquisition_policy_snapshot.c.expires_at.is_(None),
                            acquisition_policy_snapshot.c.expires_at > at,
                        ),
                    )
                    .order_by(acquisition_policy_snapshot.c.control_revision.desc())
                    .limit(1)
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise PolicyControlUnavailable("no effective policy control snapshot")
        return _control_from_row(row)

    @staticmethod
    def evaluation_row(connection: Connection, evaluation_id: str) -> RowMapping | None:
        return (
            connection.execute(
                sa.select(policy_evaluation).where(
                    policy_evaluation.c.evaluation_id == evaluation_id
                )
            )
            .mappings()
            .one_or_none()
        )
