"""Durable, replay-safe persistence for one bounded acquisition runtime."""

from __future__ import annotations

import datetime as dt
import hashlib
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeActionResult,
    RuntimeCycleSnapshot,
    RuntimeCycleStatus,
    RuntimeLeaseResult,
    RuntimeProposal,
    RuntimeStageStatus,
    require_aware,
)
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import (
    acquisition_runtime_cycle,
    acquisition_runtime_lease,
    acquisition_runtime_stage,
)

LEASE_NAME = "acquisition-run-once"
_TERMINAL_CYCLES = {
    RuntimeCycleStatus.SUCCEEDED.value,
    RuntimeCycleStatus.SUPPRESSED.value,
}


class AcquisitionRuntimeConflict(RuntimeError):
    """A durable runtime transition no longer matches its expected state."""


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def _cycle_ref(config_fingerprint: str, opportunity_key: str) -> str:
    material = f"acquisition-runtime-cycle-v1\0{config_fingerprint}\0{opportunity_key}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class AcquisitionRuntimeStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def acquire_lease(
        self,
        owner_ref: str,
        *,
        acquired_at: dt.datetime,
        lease_seconds: int,
    ) -> RuntimeLeaseResult:
        acquired_at = require_aware(acquired_at)
        expires_at = acquired_at + dt.timedelta(seconds=lease_seconds)
        with self.engine.begin() as connection:
            insert_if_absent(
                connection,
                acquisition_runtime_lease,
                {
                    "lease_name": LEASE_NAME,
                    "owner_ref": None,
                    "acquired_at": None,
                    "heartbeat_at": None,
                    "expires_at": None,
                    "generation": 0,
                },
                index_elements=[acquisition_runtime_lease.c.lease_name],
            )
            row = connection.execute(
                sa.select(acquisition_runtime_lease)
                .where(acquisition_runtime_lease.c.lease_name == LEASE_NAME)
                .with_for_update()
            ).mappings().one()
            previous_owner = row["owner_ref"]
            previous_expiry = row["expires_at"]
            expired = (
                previous_expiry is not None
                and _aware(previous_expiry) <= acquired_at
            )
            eligible = previous_owner in {None, owner_ref} or expired
            if not eligible:
                return RuntimeLeaseResult(owned=False, reclaimed=False)
            updated = connection.execute(
                sa.update(acquisition_runtime_lease)
                .where(
                    acquisition_runtime_lease.c.lease_name == LEASE_NAME,
                    acquisition_runtime_lease.c.generation == row["generation"],
                )
                .values(
                    owner_ref=owner_ref,
                    acquired_at=acquired_at,
                    heartbeat_at=acquired_at,
                    expires_at=expires_at,
                    generation=row["generation"] + 1,
                )
                .returning(acquisition_runtime_lease.c.lease_name)
            ).first()
            if updated is None:
                return RuntimeLeaseResult(owned=False, reclaimed=False)
            return RuntimeLeaseResult(
                owned=True,
                reclaimed=bool(
                    previous_owner is not None
                    and previous_owner != owner_ref
                    and expired
                ),
            )

    def heartbeat_lease(
        self,
        owner_ref: str,
        *,
        at: dt.datetime,
        lease_seconds: int,
    ) -> None:
        at = require_aware(at)
        with self.engine.begin() as connection:
            updated = connection.execute(
                sa.update(acquisition_runtime_lease)
                .where(
                    acquisition_runtime_lease.c.lease_name == LEASE_NAME,
                    acquisition_runtime_lease.c.owner_ref == owner_ref,
                    acquisition_runtime_lease.c.expires_at > at,
                )
                .values(
                    heartbeat_at=at,
                    expires_at=at + dt.timedelta(seconds=lease_seconds),
                )
                .returning(acquisition_runtime_lease.c.lease_name)
            ).first()
            if updated is None:
                raise AcquisitionRuntimeConflict("runtime lease ownership was lost")

    def release_lease(self, owner_ref: str, *, at: dt.datetime) -> None:
        require_aware(at)
        with self.engine.begin() as connection:
            connection.execute(
                sa.update(acquisition_runtime_lease)
                .where(
                    acquisition_runtime_lease.c.lease_name == LEASE_NAME,
                    acquisition_runtime_lease.c.owner_ref == owner_ref,
                )
                .values(
                    owner_ref=None,
                    acquired_at=None,
                    heartbeat_at=None,
                    expires_at=None,
                )
            )

    def resume_or_create_cycle(
        self,
        *,
        opportunity_keys: tuple[str, ...],
        config_fingerprint: str,
        at: dt.datetime,
    ) -> RuntimeCycleSnapshot:
        at = require_aware(at)
        if not opportunity_keys:
            raise ValueError("at least one runtime opportunity is required")
        with self.engine.begin() as connection:
            rows = connection.execute(
                sa.select(acquisition_runtime_cycle).where(
                    acquisition_runtime_cycle.c.config_fingerprint
                    == config_fingerprint,
                    acquisition_runtime_cycle.c.opportunity_key.in_(
                        opportunity_keys
                    ),
                )
            ).mappings().all()
            by_opportunity = {row["opportunity_key"]: row for row in rows}
            for opportunity_key in opportunity_keys:
                existing = by_opportunity.get(opportunity_key)
                if existing is not None and existing["status"] not in _TERMINAL_CYCLES:
                    return self._snapshot(existing)
            for opportunity_key in opportunity_keys:
                if opportunity_key not in by_opportunity:
                    return self._create_cycle(
                        connection,
                        opportunity_key=opportunity_key,
                        config_fingerprint=config_fingerprint,
                        at=at,
                    )
            return self._snapshot(by_opportunity[opportunity_keys[0]])

    def begin_stage(
        self,
        cycle_ref: str,
        stage: AcquisitionRuntimeStage,
        *,
        at: dt.datetime,
    ) -> None:
        at = require_aware(at)
        with self.engine.begin() as connection:
            row = self._stage(connection, cycle_ref, stage)
            if row["status"] in {
                RuntimeStageStatus.SUCCEEDED.value,
                RuntimeStageStatus.SUPPRESSED.value,
            }:
                raise AcquisitionRuntimeConflict("terminal runtime stage cannot restart")
            connection.execute(
                sa.update(acquisition_runtime_stage)
                .where(
                    acquisition_runtime_stage.c.cycle_ref == cycle_ref,
                    acquisition_runtime_stage.c.stage == stage.value,
                )
                .values(
                    status=RuntimeStageStatus.RUNNING.value,
                    attempt_count=row["attempt_count"] + 1,
                    plan_ref=None,
                    command=None,
                    argument_fingerprint=None,
                    result_refs=[],
                    reserved_cost=Decimal("0"),
                    observed_cost=Decimal("0"),
                    reason_codes=[],
                    started_at=at,
                    completed_at=None,
                    updated_at=at,
                )
            )
            connection.execute(
                sa.update(acquisition_runtime_cycle)
                .where(acquisition_runtime_cycle.c.cycle_ref == cycle_ref)
                .values(
                    status=RuntimeCycleStatus.RUNNING.value,
                    next_stage=stage.value,
                    last_reason_code=None,
                    completed_at=None,
                    updated_at=at,
                )
            )

    def finish_stage(
        self,
        cycle_ref: str,
        stage: AcquisitionRuntimeStage,
        result: RuntimeActionResult,
        *,
        at: dt.datetime,
        proposal: RuntimeProposal | None = None,
    ) -> None:
        at = require_aware(at)
        with self.engine.begin() as connection:
            row = self._stage(connection, cycle_ref, stage)
            if row["status"] != RuntimeStageStatus.RUNNING.value:
                raise AcquisitionRuntimeConflict("runtime stage is not owned for completion")
            connection.execute(
                sa.update(acquisition_runtime_stage)
                .where(
                    acquisition_runtime_stage.c.cycle_ref == cycle_ref,
                    acquisition_runtime_stage.c.stage == stage.value,
                )
                .values(
                    status=result.status.value,
                    plan_ref=proposal.plan_ref if proposal else None,
                    command=proposal.command if proposal else None,
                    argument_fingerprint=(
                        proposal.argument_fingerprint if proposal else None
                    ),
                    result_refs=list(result.result_refs),
                    reserved_cost=result.reserved_cost,
                    observed_cost=result.observed_cost,
                    reason_codes=list(result.reason_codes),
                    completed_at=at,
                    updated_at=at,
                )
            )
            next_stage = self._next_stage_after(stage, result.status)
            spent = self._spent_cost(connection, cycle_ref)
            reason = result.reason_codes[0] if result.reason_codes else None
            cycle_status = (
                RuntimeCycleStatus.RUNNING
                if result.status is RuntimeStageStatus.SUCCEEDED
                else RuntimeCycleStatus(result.status.value)
            )
            connection.execute(
                sa.update(acquisition_runtime_cycle)
                .where(acquisition_runtime_cycle.c.cycle_ref == cycle_ref)
                .values(
                    status=cycle_status.value,
                    next_stage=next_stage.value if next_stage else None,
                    spent_cost=spent,
                    last_reason_code=reason,
                    completed_at=(
                        at if result.status is RuntimeStageStatus.SUPPRESSED else None
                    ),
                    updated_at=at,
                )
            )

    def finish_cycle(
        self,
        cycle_ref: str,
        status: RuntimeCycleStatus,
        *,
        at: dt.datetime,
        reason_code: str | None = None,
    ) -> None:
        at = require_aware(at)
        with self.engine.begin() as connection:
            cycle = self._cycle(connection, cycle_ref)
            next_stage = cycle["next_stage"]
            if status is RuntimeCycleStatus.SUCCEEDED and next_stage is not None:
                raise AcquisitionRuntimeConflict("incomplete runtime cycle cannot succeed")
            terminal = status in {
                RuntimeCycleStatus.SUCCEEDED,
                RuntimeCycleStatus.SUPPRESSED,
            }
            connection.execute(
                sa.update(acquisition_runtime_cycle)
                .where(acquisition_runtime_cycle.c.cycle_ref == cycle_ref)
                .values(
                    status=status.value,
                    next_stage=None if terminal else next_stage,
                    last_reason_code=reason_code,
                    completed_at=at if terminal else None,
                    updated_at=at,
                )
            )

    @staticmethod
    def _create_cycle(
        connection: Connection,
        *,
        opportunity_key: str,
        config_fingerprint: str,
        at: dt.datetime,
    ) -> RuntimeCycleSnapshot:
        cycle_ref = _cycle_ref(config_fingerprint, opportunity_key)
        insert_if_absent(
            connection,
            acquisition_runtime_cycle,
            {
                "cycle_ref": cycle_ref,
                "opportunity_key": opportunity_key,
                "config_fingerprint": config_fingerprint,
                "status": RuntimeCycleStatus.PENDING.value,
                "next_stage": AcquisitionRuntimeStage.SIGNAL_SEED.value,
                "spent_cost": Decimal("0"),
                "last_reason_code": None,
                "started_at": at,
                "updated_at": at,
                "completed_at": None,
            },
            index_elements=[
                acquisition_runtime_cycle.c.opportunity_key,
                acquisition_runtime_cycle.c.config_fingerprint,
            ],
        )
        for stage in AcquisitionRuntimeStage:
            insert_if_absent(
                connection,
                acquisition_runtime_stage,
                {
                    "cycle_ref": cycle_ref,
                    "stage": stage.value,
                    "status": RuntimeStageStatus.PENDING.value,
                    "attempt_count": 0,
                    "plan_ref": None,
                    "command": None,
                    "argument_fingerprint": None,
                    "result_refs": [],
                    "reserved_cost": Decimal("0"),
                    "observed_cost": Decimal("0"),
                    "reason_codes": [],
                    "started_at": None,
                    "completed_at": None,
                    "updated_at": at,
                },
                index_elements=[
                    acquisition_runtime_stage.c.cycle_ref,
                    acquisition_runtime_stage.c.stage,
                ],
            )
        row = connection.execute(
            sa.select(acquisition_runtime_cycle).where(
                acquisition_runtime_cycle.c.cycle_ref == cycle_ref
            )
        ).mappings().one()
        return AcquisitionRuntimeStore._snapshot(row)

    @staticmethod
    def _snapshot(row: RowMapping) -> RuntimeCycleSnapshot:
        return RuntimeCycleSnapshot(
            cycle_ref=row["cycle_ref"],
            opportunity_key=row["opportunity_key"],
            status=RuntimeCycleStatus(row["status"]),
            next_stage=(
                AcquisitionRuntimeStage(row["next_stage"])
                if row["next_stage"] is not None
                else None
            ),
            spent_cost=Decimal(row["spent_cost"]),
            started_at=_aware(row["started_at"]),
        )

    @staticmethod
    def _cycle(connection: Connection, cycle_ref: str) -> RowMapping:
        row = connection.execute(
            sa.select(acquisition_runtime_cycle)
            .where(acquisition_runtime_cycle.c.cycle_ref == cycle_ref)
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise KeyError(cycle_ref)
        return row

    @staticmethod
    def _stage(
        connection: Connection,
        cycle_ref: str,
        stage: AcquisitionRuntimeStage,
    ) -> RowMapping:
        row = connection.execute(
            sa.select(acquisition_runtime_stage)
            .where(
                acquisition_runtime_stage.c.cycle_ref == cycle_ref,
                acquisition_runtime_stage.c.stage == stage.value,
            )
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise KeyError((cycle_ref, stage.value))
        return row

    @staticmethod
    def _spent_cost(connection: Connection, cycle_ref: str) -> Decimal:
        rows = connection.execute(
            sa.select(
                acquisition_runtime_stage.c.reserved_cost,
                acquisition_runtime_stage.c.observed_cost,
            ).where(
                acquisition_runtime_stage.c.cycle_ref == cycle_ref,
                acquisition_runtime_stage.c.status
                == RuntimeStageStatus.SUCCEEDED.value,
            )
        ).all()
        return sum(
            (max(Decimal(row[0]), Decimal(row[1])) for row in rows),
            start=Decimal("0"),
        )

    @staticmethod
    def _next_stage_after(
        stage: AcquisitionRuntimeStage,
        status: RuntimeStageStatus,
    ) -> AcquisitionRuntimeStage | None:
        if status is RuntimeStageStatus.SUPPRESSED:
            return None
        if status is not RuntimeStageStatus.SUCCEEDED:
            return stage
        stages = tuple(AcquisitionRuntimeStage)
        index = stages.index(stage) + 1
        return stages[index] if index < len(stages) else None

__all__ = [
    "LEASE_NAME",
    "AcquisitionRuntimeConflict",
    "AcquisitionRuntimeStore",
]
