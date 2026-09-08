"""Replay-safe snapshot, proposal, and future allocation persistence."""

from __future__ import annotations

import contextlib
import datetime as dt
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping

from signals.learning.contracts import (
    LEARNING_PROPOSAL_VERSION,
    LearningAllocationEnvelope,
    LearningCandidate,
    LearningSnapshot,
    canonical_fingerprint,
)
from signals.operations.circuit_breakers import AcquisitionCircuitOpen, AcquisitionExecutionGuard
from signals.operations.contracts import BreakerScope
from signals.operations.store import OperationsStore
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import (
    acquisition_allocation_proposal,
    acquisition_learning_snapshot,
)


class LearningConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class SaveResult:
    row: RowMapping
    replayed: bool


@dataclass(frozen=True)
class ApplyResult:
    row: RowMapping
    applied: bool
    replayed: bool


@dataclass(frozen=True)
class CurrentAllocation:
    authority_ref: str
    allocation: dict[str, int]
    allocation_fingerprint: str


def _semantic(value: object) -> object:
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.UTC)
        return value.astimezone(dt.UTC).isoformat()
    if isinstance(value, Decimal):
        return "0" if value == 0 else format(value.normalize(), "f")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _semantic(nested) for key, nested in value.items()}
    if isinstance(value, (tuple, list)):
        return [_semantic(nested) for nested in value]
    return value


def _insert(connection: Connection, table: sa.Table):
    if connection.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    elif connection.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        raise RuntimeError("unsupported learning persistence dialect")
    return insert(table)


class LearningStore:
    _POSTGRES_APPLICATION_LOCK = 0x4B49564F5529029

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._execution_guard = AcquisitionExecutionGuard(OperationsStore(engine))

    @contextlib.contextmanager
    def _serialized(self) -> Iterator[Connection]:
        connection = self.engine.connect()
        transaction: sa.Transaction | None = None
        try:
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                transaction = connection.begin()
                if connection.dialect.name == "postgresql":
                    connection.execute(
                        sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
                        {"lock_key": self._POSTGRES_APPLICATION_LOCK},
                    )
            yield connection
            transaction.commit() if transaction is not None else connection.commit()
        except Exception:
            transaction.rollback() if transaction is not None else connection.rollback()
            raise
        finally:
            connection.close()

    def save_snapshot(self, snapshot: LearningSnapshot) -> SaveResult:
        values = {
            "snapshot_ref": snapshot.snapshot_ref,
            "window_start": snapshot.window.window_start,
            "window_end": snapshot.window.window_end,
            "captured_at": snapshot.window.captured_at,
            "learning_version": snapshot.learning_version,
            "formula_version": snapshot.formula_version,
            "formula_fingerprint": snapshot.formula_fingerprint,
            "risk_policy_version": snapshot.risk_policy_version,
            "risk_policy_fingerprint": snapshot.risk_policy_fingerprint,
            "cost_policy_version": snapshot.cost_policy_version,
            "cost_policy_fingerprint": snapshot.cost_policy_fingerprint,
            "input_fingerprint": snapshot.input_fingerprint,
            "cell_metrics": {
                "metrics": [item.model_dump(mode="json") for item in snapshot.cell_metrics],
                "scores": [item.model_dump(mode="json") for item in snapshot.economic_scores],
            },
            "allocation_envelope_version": snapshot.allocation_envelope_version,
            "allocation_envelope_fingerprint": snapshot.allocation_envelope_fingerprint,
            "current_allocation_fingerprint": snapshot.current_allocation_fingerprint,
            "previous_applied_proposal_ref": snapshot.previous_applied_proposal_ref,
            "created_at": snapshot.created_at,
        }
        with self.engine.begin() as connection:
            inserted = insert_if_absent(
                connection,
                acquisition_learning_snapshot,
                values,
                index_elements=[acquisition_learning_snapshot.c.snapshot_ref],
            )
            row = (
                connection.execute(
                    sa.select(acquisition_learning_snapshot).where(
                        acquisition_learning_snapshot.c.snapshot_ref == snapshot.snapshot_ref
                    )
                )
                .mappings()
                .one()
            )
            comparable = dict(values)
            if not inserted:
                # captured_at is operational observation time, deliberately excluded
                # from the semantic snapshot identity. A retry keeps the first durable
                # capture timestamp while every authority-bearing fact remains exact.
                comparable.pop("captured_at")
                comparable.pop("created_at")
            self._require_exact(row, comparable, snapshot.snapshot_ref)
            return SaveResult(row=row, replayed=not inserted)

    def save_candidates(
        self,
        candidates: tuple[LearningCandidate, ...],
        *,
        envelope_fingerprint: str,
        created_at: dt.datetime,
    ) -> tuple[SaveResult, ...]:
        results: list[SaveResult] = []
        with self.engine.begin() as connection:
            for candidate in candidates:
                current = [item.model_dump(mode="json") for item in candidate.current_allocation]
                proposed = [item.model_dump(mode="json") for item in candidate.proposed_allocation]
                values = {
                    "proposal_ref": candidate.proposal_ref,
                    "snapshot_ref": candidate.snapshot_ref,
                    "proposal_version": LEARNING_PROPOSAL_VERSION,
                    "candidate_version": candidate.candidate_version,
                    "allocation_envelope_fingerprint": envelope_fingerprint,
                    "baseline_authority_ref": candidate.baseline_authority_ref,
                    "current_allocation_fingerprint": canonical_fingerprint(
                        "learning-allocation-vector:v1", current
                    ),
                    "proposed_allocation_fingerprint": canonical_fingerprint(
                        "learning-allocation-vector:v1", proposed
                    ),
                    "current_allocation": current,
                    "proposed_allocation": proposed,
                    "from_country": candidate.from_cell.country if candidate.from_cell else None,
                    "from_wedge": candidate.from_cell.wedge if candidate.from_cell else None,
                    "to_country": candidate.to_cell.country if candidate.to_cell else None,
                    "to_wedge": candidate.to_cell.wedge if candidate.to_cell else None,
                    "delta_units": candidate.delta_units,
                    "expected_score_delta": candidate.expected_score_delta,
                    "reason_codes": list(candidate.reason_codes),
                    "state": "PROPOSED",
                    "created_at": created_at,
                }
                inserted = insert_if_absent(
                    connection,
                    acquisition_allocation_proposal,
                    values,
                    index_elements=[acquisition_allocation_proposal.c.proposal_ref],
                )
                row = self._proposal(connection, candidate.proposal_ref)
                self._require_exact(row, values, candidate.proposal_ref)
                results.append(SaveResult(row=row, replayed=not inserted))
        return tuple(results)

    def record_selection(
        self,
        proposal_ref: str,
        *,
        source: str,
        confidence: Decimal,
        decided_at: dt.datetime,
        reason_codes: tuple[str, ...] = ("SELECTION_RECORDED",),
    ) -> RowMapping:
        if source not in {"KIVOU_NO_CHANGE", "HERMES"}:
            raise ValueError("invalid learning selection source")
        with self._serialized() as connection:
            row = self._proposal(connection, proposal_ref, lock=True)
            if row["selection_source"] is not None:
                if (
                    _semantic(row["selection_source"]) != source
                    or _semantic(row["confidence"]) != _semantic(confidence)
                    or _semantic(row["selection_reason_codes"]) != _semantic(reason_codes)
                ):
                    raise LearningConflict(proposal_ref)
                return row
            winner = self._selected_proposal(
                connection, snapshot_ref=row["snapshot_ref"], lock=True
            )
            if winner is not None:
                return winner
            try:
                with connection.begin_nested():
                    connection.execute(
                        sa.update(acquisition_allocation_proposal)
                        .where(
                            acquisition_allocation_proposal.c.proposal_ref == proposal_ref,
                            acquisition_allocation_proposal.c.selection_source.is_(None),
                        )
                        .values(
                            selection_source=source,
                            confidence=confidence,
                            selection_reason_codes=list(reason_codes),
                            decided_at=decided_at,
                        )
                    )
            except sa.exc.IntegrityError:
                winner = self._selected_proposal(
                    connection, snapshot_ref=row["snapshot_ref"], lock=True
                )
                if winner is None:
                    raise
                return winner
            selected = self._proposal(connection, proposal_ref, lock=True)
            if selected["selection_source"] is None:
                winner = self._selected_proposal(
                    connection, snapshot_ref=row["snapshot_ref"], lock=True
                )
                if winner is None:
                    raise LearningConflict("selection did not persist")
                return winner
            return selected

    def record_policy(
        self,
        proposal_ref: str,
        *,
        evaluation_id: str,
        action_fingerprint: str,
        status: str,
        counterfactual_status: str | None,
        state: str,
        decided_at: dt.datetime,
    ) -> RowMapping:
        if state not in {"PROPOSED", "SHADOW_ONLY", "POLICY_DENIED"}:
            raise ValueError("invalid policy decision state")
        values = {
            "policy_evaluation_id": evaluation_id,
            "policy_action_fingerprint": action_fingerprint,
            "policy_status": status,
            "policy_counterfactual_status": counterfactual_status,
            "state": state,
            "decided_at": decided_at,
        }
        with self.engine.begin() as connection:
            row = self._proposal(connection, proposal_ref)
            if row["policy_evaluation_id"] is not None:
                self._require_exact(row, values, proposal_ref)
                return row
            connection.execute(
                sa.update(acquisition_allocation_proposal)
                .where(
                    acquisition_allocation_proposal.c.proposal_ref == proposal_ref,
                    acquisition_allocation_proposal.c.state == "PROPOSED",
                )
                .values(values)
            )
            return self._proposal(connection, proposal_ref)

    def apply(self, proposal_ref: str, *, applied_at: dt.datetime) -> ApplyResult:
        with self._serialized() as connection:
            row = self._proposal(connection, proposal_ref, lock=True)
            if row["state"] == "APPLIED":
                return ApplyResult(row=row, applied=False, replayed=True)
            if row["state"] != "PROPOSED" or row["policy_status"] != "APPROVED":
                raise LearningConflict("proposal is not executable")
            scopes = [BreakerScope(scope_type="GLOBAL", scope_ref="acquisition")]
            for prefix in ("from", "to"):
                country = row[f"{prefix}_country"]
                wedge = row[f"{prefix}_wedge"]
                if country is not None:
                    scopes.append(BreakerScope(scope_type="COUNTRY", scope_ref=country))
                if wedge is not None:
                    scopes.append(BreakerScope(scope_type="WEDGE", scope_ref=wedge))
            try:
                self._execution_guard.require_allowed(*scopes)
            except AcquisitionCircuitOpen as exc:
                raise LearningConflict("acquisition execution circuit is open") from exc
            current = self._current_allocation(
                connection,
                row["allocation_envelope_fingerprint"],
                initial_allocation=row["current_allocation"],
            )
            if (
                current.authority_ref != row["baseline_authority_ref"]
                or current.allocation_fingerprint != row["current_allocation_fingerprint"]
            ):
                connection.execute(
                    sa.update(acquisition_allocation_proposal)
                    .where(acquisition_allocation_proposal.c.proposal_ref == proposal_ref)
                    .values(
                        state="REJECTED",
                        decision_reason="STALE_ALLOCATION_BASELINE",
                        decided_at=applied_at,
                    )
                )
                return ApplyResult(
                    row=self._proposal(connection, proposal_ref), applied=False, replayed=False
                )
            connection.execute(
                sa.update(acquisition_allocation_proposal)
                .where(
                    acquisition_allocation_proposal.c.proposal_ref == proposal_ref,
                    acquisition_allocation_proposal.c.state == "PROPOSED",
                )
                .values(
                    state="APPLIED",
                    decision_reason="POLICY_APPROVED_APPLICATION",
                    decided_at=applied_at,
                    applied_at=applied_at,
                )
            )
            return ApplyResult(
                row=self._proposal(connection, proposal_ref), applied=True, replayed=False
            )

    def current_allocation(self, envelope_fingerprint: str) -> CurrentAllocation:
        with self.engine.connect() as connection:
            tip = self._applied_chain_tip(connection, envelope_fingerprint)
            if tip is None:
                raise KeyError(envelope_fingerprint)
            return CurrentAllocation(
                authority_ref=tip["proposal_ref"],
                allocation=self._allocation_dict(tip["proposed_allocation"]),
                allocation_fingerprint=tip["proposed_allocation_fingerprint"],
            )

    def resolve_current_allocation(self, envelope: LearningAllocationEnvelope) -> CurrentAllocation:
        try:
            return self.current_allocation(envelope.fingerprint)
        except KeyError:
            values = [
                {
                    "cell": item.cell.model_dump(mode="json"),
                    "units": item.current_units,
                }
                for item in sorted(envelope.cells, key=lambda item: item.cell.key)
            ]
            return CurrentAllocation(
                authority_ref="INITIAL:" + envelope.fingerprint,
                allocation=self._allocation_dict(values),
                allocation_fingerprint=canonical_fingerprint(
                    "learning-allocation-vector:v1", values
                ),
            )

    def existing_cycle(
        self,
        *,
        window_end: dt.datetime,
        envelope_fingerprint: str,
    ) -> tuple[RowMapping, RowMapping | None] | None:
        with self.engine.connect() as connection:
            snapshot = (
                connection.execute(
                    sa.select(acquisition_learning_snapshot).where(
                        acquisition_learning_snapshot.c.window_end == window_end,
                        acquisition_learning_snapshot.c.allocation_envelope_fingerprint
                        == envelope_fingerprint,
                    )
                )
                .mappings()
                .one_or_none()
            )
            if snapshot is None:
                return None
            selected = (
                connection.execute(
                    sa.select(acquisition_allocation_proposal)
                    .where(
                        acquisition_allocation_proposal.c.snapshot_ref == snapshot["snapshot_ref"],
                        acquisition_allocation_proposal.c.selection_source.is_not(None),
                    )
                    .order_by(acquisition_allocation_proposal.c.proposal_ref)
                )
                .mappings()
                .one_or_none()
            )
            return snapshot, selected

    @staticmethod
    def _current_allocation(
        connection: Connection,
        envelope_fingerprint: str,
        *,
        initial_allocation: list[dict],
    ) -> CurrentAllocation:
        tip = LearningStore._applied_chain_tip(connection, envelope_fingerprint, lock=True)
        if tip is None:
            return CurrentAllocation(
                authority_ref="INITIAL:" + envelope_fingerprint,
                allocation=LearningStore._allocation_dict(initial_allocation),
                allocation_fingerprint=canonical_fingerprint(
                    "learning-allocation-vector:v1", initial_allocation
                ),
            )
        return CurrentAllocation(
            authority_ref=tip["proposal_ref"],
            allocation=LearningStore._allocation_dict(tip["proposed_allocation"]),
            allocation_fingerprint=tip["proposed_allocation_fingerprint"],
        )

    @staticmethod
    def _applied_chain_tip(
        connection: Connection,
        envelope_fingerprint: str,
        *,
        lock: bool = False,
    ) -> RowMapping | None:
        authority_ref = "INITIAL:" + envelope_fingerprint
        tip: RowMapping | None = None
        visited: set[str] = set()
        while True:
            statement = sa.select(acquisition_allocation_proposal).where(
                acquisition_allocation_proposal.c.allocation_envelope_fingerprint
                == envelope_fingerprint,
                acquisition_allocation_proposal.c.baseline_authority_ref == authority_ref,
                acquisition_allocation_proposal.c.state == "APPLIED",
            )
            if lock:
                statement = statement.with_for_update()
            successor = connection.execute(statement).mappings().one_or_none()
            if successor is None:
                return tip
            proposal_ref = successor["proposal_ref"]
            if proposal_ref in visited:
                raise LearningConflict("allocation authority cycle")
            visited.add(proposal_ref)
            tip = successor
            authority_ref = proposal_ref

    @staticmethod
    def _allocation_dict(value: list[dict]) -> dict[str, int]:
        return {
            f"{item['cell']['country']}:{item['cell']['wedge']}": int(item["units"])
            for item in value
        }

    @staticmethod
    def _proposal(connection: Connection, proposal_ref: str, *, lock: bool = False) -> RowMapping:
        statement = sa.select(acquisition_allocation_proposal).where(
            acquisition_allocation_proposal.c.proposal_ref == proposal_ref
        )
        if lock:
            statement = statement.with_for_update()
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise KeyError(proposal_ref)
        return row

    @staticmethod
    def _selected_proposal(
        connection: Connection, *, snapshot_ref: str, lock: bool = False
    ) -> RowMapping | None:
        statement = sa.select(acquisition_allocation_proposal).where(
            acquisition_allocation_proposal.c.snapshot_ref == snapshot_ref,
            acquisition_allocation_proposal.c.selection_source.is_not(None),
        )
        if lock:
            statement = statement.with_for_update()
        return connection.execute(statement).mappings().one_or_none()

    @staticmethod
    def _require_exact(row: RowMapping, values: dict[str, object], ref: str) -> None:
        for key, value in values.items():
            if _semantic(row[key]) != _semantic(value):
                raise LearningConflict(ref)


__all__ = [
    "ApplyResult",
    "CurrentAllocation",
    "LearningConflict",
    "LearningStore",
    "SaveResult",
]
