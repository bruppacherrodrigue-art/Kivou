"""Append-only persistence for deterministic decision evaluations."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping

from signals.decision_engine.contracts import (
    DecisionEvaluationIdempotencyConflict,
    DecisionEvaluationRecord,
    DecisionEvaluationWrite,
)
from signals.persistence.schema import acquisition_decision_evaluation


def decision_evaluation_id(policy_evaluation_id: str) -> str:
    material = f"decision-evaluation-v1\0{policy_evaluation_id}".encode()
    return hashlib.sha256(material).hexdigest()


def _aware(value):
    if value is not None and getattr(value, "tzinfo", None) is None:
        return value.replace(tzinfo=dt.UTC)
    return value


def _semantic(value):
    if isinstance(value, dt.datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
        return aware.astimezone(dt.UTC).isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _semantic(nested) for key, nested in value.items()}
    if isinstance(value, (tuple, list)):
        return [_semantic(nested) for nested in value]
    return value


def _record(row: RowMapping) -> DecisionEvaluationRecord:
    values = dict(row)
    values["reason_codes"] = tuple(values["reason_codes"])
    values["evidence_refs"] = tuple(values["evidence_refs"])
    values["created_at"] = _aware(values["created_at"])
    values["proposed_next_review_at"] = _aware(values["proposed_next_review_at"])
    return DecisionEvaluationRecord.model_validate(values)


def _values(write: DecisionEvaluationWrite) -> dict[str, object]:
    decision_input = write.decision_input
    proposal = write.proposal
    return {
        "decision_evaluation_id": write.decision_evaluation_id,
        "acquisition_opportunity_id": write.acquisition_opportunity_id,
        "policy_evaluation_id": write.policy_evaluation_id,
        "decision_input_version": decision_input.input_version,
        "decision_input_fingerprint": decision_input.decision_input_fingerprint,
        "decision_input": decision_input.model_dump(mode="json"),
        "company_prebuild_fingerprint": decision_input.company_prebuild_fingerprint,
        "representative_award_key": decision_input.representative_award_key,
        "recency_basis": decision_input.recency_basis.value,
        "recency_date": decision_input.recency_date,
        "as_of_date": decision_input.as_of_date,
        "age_days": decision_input.age_days,
        "decision_policy_version": decision_input.decision_policy_version,
        "decision_policy_config_fingerprint": (
            decision_input.decision_policy_config_fingerprint
        ),
        "proposed_decision": proposal.proposed_decision.value,
        "reason_codes": list(proposal.reason_codes),
        "evidence_refs": list(proposal.evidence_refs),
        "proposed_next_action": proposal.next_action,
        "proposed_next_review_at": proposal.next_review_at,
        "proposal_fingerprint": proposal.proposal_fingerprint,
        "policy_status": write.policy_status.value,
        "policy_counterfactual_status": (
            write.policy_counterfactual_status.value
            if write.policy_counterfactual_status is not None
            else None
        ),
        "expected_post_policy_version": write.expected_post_policy_version,
        "disposition": write.disposition.value,
        "recorded_event_id": write.recorded_event_id,
        "created_at": write.created_at.astimezone(dt.UTC),
    }


class DecisionEvaluationStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_by_policy(self, policy_evaluation_id: str) -> DecisionEvaluationRecord | None:
        with self._engine.connect() as connection:
            return self.get_by_policy_in_transaction(connection, policy_evaluation_id)

    @staticmethod
    def get_by_policy_in_transaction(
        connection: Connection, policy_evaluation_id: str
    ) -> DecisionEvaluationRecord | None:
        row = (
            connection.execute(
                sa.select(acquisition_decision_evaluation).where(
                    acquisition_decision_evaluation.c.policy_evaluation_id
                    == policy_evaluation_id
                )
            )
            .mappings()
            .one_or_none()
        )
        return _record(row) if row is not None else None

    def append(self, write: DecisionEvaluationWrite) -> DecisionEvaluationRecord:
        with self._engine.begin() as connection:
            return self.append_in_transaction(connection, write)

    @staticmethod
    def append_in_transaction(
        connection: Connection, write: DecisionEvaluationWrite
    ) -> DecisionEvaluationRecord:
        values = _values(write)
        if connection.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        elif connection.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            raise RuntimeError("unsupported decision-evaluation persistence dialect")
        result = connection.execute(
            insert(acquisition_decision_evaluation)
            .values(values)
            .on_conflict_do_nothing()
        )
        row = (
            connection.execute(
                sa.select(acquisition_decision_evaluation).where(
                    acquisition_decision_evaluation.c.policy_evaluation_id
                    == write.policy_evaluation_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            collision = connection.execute(
                sa.select(acquisition_decision_evaluation).where(
                    acquisition_decision_evaluation.c.decision_evaluation_id
                    == write.decision_evaluation_id
                )
            ).first()
            if collision is not None:
                raise DecisionEvaluationIdempotencyConflict(write.decision_evaluation_id)
            raise RuntimeError("decision evaluation conflict was not durable")
        if result.rowcount == 1:
            return _record(row)
        semantic_fields = tuple(values)
        if any(
            _semantic(row[field]) != _semantic(values[field]) for field in semantic_fields
        ):
            raise DecisionEvaluationIdempotencyConflict(write.policy_evaluation_id)
        return _record(row)


__all__ = ["DecisionEvaluationStore", "decision_evaluation_id"]
