"""Durable, replay-safe persistence for one bounded acquisition runtime."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeActionResult,
    RuntimeCapabilityEvidence,
    RuntimeCycleSnapshot,
    RuntimeCycleStatus,
    RuntimeHealthObservation,
    RuntimeHermesIdentityEvidence,
    RuntimeLeaseResult,
    RuntimeProposal,
    RuntimeStageDependency,
    RuntimeStageReservation,
    RuntimeStageSnapshot,
    RuntimeStageStatus,
    require_aware,
)
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import (
    acquisition_runtime_cycle,
    acquisition_runtime_lease,
    acquisition_runtime_observation,
    acquisition_runtime_stage,
    acquisition_runtime_stage_attempt,
)

LEASE_NAME = "acquisition-run-once"
RUNTIME_OBSERVATION_NAME = "acquisition-run-once"
_TERMINAL_CYCLES = {
    RuntimeCycleStatus.SUCCEEDED.value,
    RuntimeCycleStatus.SUPPRESSED.value,
}
_MACHINE_REASON = re.compile(r"[A-Z][A-Z0-9_]{0,127}")


class AcquisitionRuntimeConflict(RuntimeError):
    """A durable runtime transition no longer matches its expected state."""


@dataclass(frozen=True)
class AcquisitionRuntimeExecutionGuard:
    """Fence one business action while its provider and persistence complete."""

    store: AcquisitionRuntimeStore
    owner_ref: str
    fencing_token: int
    lease_seconds: int

    @contextmanager
    def protect(self) -> Iterator[dt.datetime]:
        with self.store.engine.begin() as connection:
            row = self.store._lease_row(connection)
            fallback = _aware(row["heartbeat_at"]) if row["heartbeat_at"] else None
            observed_at = self.store._database_now(
                connection,
                fallback=fallback,
            )
            if (
                row["owner_ref"] != self.owner_ref
                or row["generation"] != self.fencing_token
                or row["expires_at"] is None
                or _aware(row["expires_at"]) <= observed_at
            ):
                raise AcquisitionRuntimeConflict(
                    "runtime business action lost its fencing lease"
                )
            connection.execute(
                sa.update(acquisition_runtime_lease)
                .where(
                    acquisition_runtime_lease.c.lease_name == LEASE_NAME,
                    acquisition_runtime_lease.c.owner_ref == self.owner_ref,
                    acquisition_runtime_lease.c.generation == self.fencing_token,
                )
                .values(
                    heartbeat_at=observed_at,
                    expires_at=(
                        observed_at + dt.timedelta(seconds=self.lease_seconds)
                    ),
                )
            )
            yield observed_at


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

    def execution_guard(
        self,
        owner_ref: str,
        *,
        fencing_token: int,
        lease_seconds: int,
    ) -> AcquisitionRuntimeExecutionGuard:
        return AcquisitionRuntimeExecutionGuard(
            store=self,
            owner_ref=owner_ref,
            fencing_token=fencing_token,
            lease_seconds=lease_seconds,
        )

    def acquire_lease(
        self,
        owner_ref: str,
        *,
        acquired_at: dt.datetime,
        lease_seconds: int,
    ) -> RuntimeLeaseResult:
        acquired_at = require_aware(acquired_at)
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
            row = self._lease_row(connection)
            observed_at = self._database_now(
                connection,
                fallback=acquired_at,
            )
            expires_at = observed_at + dt.timedelta(seconds=lease_seconds)
            previous_owner = row["owner_ref"]
            previous_expiry = row["expires_at"]
            expired = (
                previous_expiry is not None
                and _aware(previous_expiry) <= observed_at
            )
            eligible = previous_owner in {None, owner_ref} or expired
            if not eligible:
                return RuntimeLeaseResult(owned=False, reclaimed=False)
            generation = row["generation"] + 1
            updated = connection.execute(
                sa.update(acquisition_runtime_lease)
                .where(
                    acquisition_runtime_lease.c.lease_name == LEASE_NAME,
                    acquisition_runtime_lease.c.generation == row["generation"],
                )
                .values(
                    owner_ref=owner_ref,
                    acquired_at=observed_at,
                    heartbeat_at=observed_at,
                    expires_at=expires_at,
                    generation=generation,
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
                fencing_token=generation,
            )

    def heartbeat_lease(
        self,
        owner_ref: str,
        *,
        fencing_token: int,
        at: dt.datetime,
        lease_seconds: int,
    ) -> None:
        at = require_aware(at)
        with self.engine.begin() as connection:
            row = self._lease_row(connection)
            observed_at = self._database_now(connection, fallback=at)
            if (
                row["owner_ref"] != owner_ref
                or row["generation"] != fencing_token
                or row["expires_at"] is None
                or _aware(row["expires_at"]) <= observed_at
            ):
                raise AcquisitionRuntimeConflict("runtime lease ownership was lost")
            updated = connection.execute(
                sa.update(acquisition_runtime_lease)
                .where(
                    acquisition_runtime_lease.c.lease_name == LEASE_NAME,
                    acquisition_runtime_lease.c.owner_ref == owner_ref,
                    acquisition_runtime_lease.c.generation == fencing_token,
                    acquisition_runtime_lease.c.expires_at > observed_at,
                )
                .values(
                    heartbeat_at=observed_at,
                    expires_at=observed_at + dt.timedelta(seconds=lease_seconds),
                )
                .returning(acquisition_runtime_lease.c.lease_name)
            ).first()
            if updated is None:
                raise AcquisitionRuntimeConflict("runtime lease ownership was lost")

    def release_lease(
        self,
        owner_ref: str,
        *,
        fencing_token: int,
        at: dt.datetime,
    ) -> None:
        require_aware(at)
        with self.engine.begin() as connection:
            connection.execute(
                sa.update(acquisition_runtime_lease)
                .where(
                    acquisition_runtime_lease.c.lease_name == LEASE_NAME,
                    acquisition_runtime_lease.c.owner_ref == owner_ref,
                    acquisition_runtime_lease.c.generation == fencing_token,
                )
                .values(
                    owner_ref=None,
                    acquired_at=None,
                    heartbeat_at=None,
                    expires_at=None,
                )
            )

    def record_runtime_observation(
        self,
        owner_ref: str,
        capability: RuntimeCapabilityEvidence,
        *,
        fencing_token: int,
        at: dt.datetime,
    ) -> RuntimeHealthObservation:
        at = require_aware(at)
        values = self._capability_values(capability)
        with self.engine.begin() as connection:
            self._require_active_lease(
                connection,
                owner_ref,
                fencing_token=fencing_token,
                at=at,
            )
            inserted = insert_if_absent(
                connection,
                acquisition_runtime_observation,
                {
                    "runtime_name": RUNTIME_OBSERVATION_NAME,
                    **values,
                    "observed_at": at,
                    "heartbeat_at": at,
                    "last_cycle_ref": None,
                    "last_cycle_status": None,
                    "last_cycle_at": None,
                    "updated_at": at,
                },
                index_elements=[acquisition_runtime_observation.c.runtime_name],
            )
            if not inserted:
                updated = connection.execute(
                    sa.update(acquisition_runtime_observation)
                    .where(
                        acquisition_runtime_observation.c.runtime_name
                        == RUNTIME_OBSERVATION_NAME,
                        acquisition_runtime_observation.c.heartbeat_at <= at,
                    )
                    .values(
                        **values,
                        observed_at=at,
                        heartbeat_at=at,
                        last_cycle_ref=None,
                        last_cycle_status=None,
                        last_cycle_at=None,
                        updated_at=at,
                    )
                    .returning(acquisition_runtime_observation.c.runtime_name)
                ).first()
                if updated is None:
                    raise AcquisitionRuntimeConflict(
                        "runtime observation timestamp moved backwards"
                    )
            row = self._runtime_observation_row(connection)
            return self._runtime_observation(row)

    def record_cycle_observation(
        self,
        owner_ref: str,
        cycle_ref: str,
        *,
        fencing_token: int,
        at: dt.datetime,
    ) -> RuntimeHealthObservation:
        at = require_aware(at)
        with self.engine.begin() as connection:
            self._require_active_lease(
                connection,
                owner_ref,
                fencing_token=fencing_token,
                at=at,
            )
            self._runtime_observation_row(connection)
            cycle = self._cycle(connection, cycle_ref)
            cycle_at = _aware(cycle["updated_at"])
            if cycle_at > at:
                raise AcquisitionRuntimeConflict(
                    "runtime cycle observation follows its heartbeat"
                )
            updated = connection.execute(
                sa.update(acquisition_runtime_observation)
                .where(
                    acquisition_runtime_observation.c.runtime_name
                    == RUNTIME_OBSERVATION_NAME,
                    acquisition_runtime_observation.c.heartbeat_at <= at,
                )
                .values(
                    heartbeat_at=at,
                    last_cycle_ref=cycle_ref,
                    last_cycle_status=cycle["status"],
                    last_cycle_at=at,
                    updated_at=at,
                )
                .returning(acquisition_runtime_observation)
            ).mappings().one_or_none()
            if updated is None:
                raise AcquisitionRuntimeConflict(
                    "runtime cycle observation timestamp moved backwards"
                )
            return self._runtime_observation(updated)

    def read_runtime_observation(self) -> RuntimeHealthObservation | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                sa.select(acquisition_runtime_observation).where(
                    acquisition_runtime_observation.c.runtime_name
                    == RUNTIME_OBSERVATION_NAME
                )
            ).mappings().one_or_none()
        return None if row is None else self._runtime_observation(row)

    def read_cycle_reason_code(self, cycle_ref: str) -> str | None:
        """Return one bounded machine reason without exposing arbitrary row text."""

        with self.engine.connect() as connection:
            value = connection.scalar(
                sa.select(acquisition_runtime_cycle.c.last_reason_code).where(
                    acquisition_runtime_cycle.c.cycle_ref == cycle_ref
                )
            )
        if value is None:
            return None
        if not isinstance(value, str) or _MACHINE_REASON.fullmatch(value) is None:
            return "RUNTIME_CYCLE_REASON_INVALID"
        return value

    def resume_or_create_cycle(
        self,
        *,
        owner_ref: str,
        fencing_token: int,
        opportunity_keys: tuple[str, ...],
        config_fingerprint: str,
        at: dt.datetime,
    ) -> RuntimeCycleSnapshot:
        at = require_aware(at)
        if not opportunity_keys:
            raise ValueError("at least one runtime opportunity is required")
        with self.engine.begin() as connection:
            self._require_active_lease(
                connection,
                owner_ref,
                fencing_token=fencing_token,
                at=at,
            )
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
        owner_ref: str,
        fencing_token: int,
        at: dt.datetime,
    ) -> RuntimeStageSnapshot:
        at = require_aware(at)
        with self.engine.begin() as connection:
            self._require_active_lease(
                connection,
                owner_ref,
                fencing_token=fencing_token,
                at=at,
            )
            row = self._stage(connection, cycle_ref, stage)
            retry_at = row["retry_at"]
            if (
                row["status"] == RuntimeStageStatus.WAITING.value
                and retry_at is not None
                and _aware(retry_at) > at
            ):
                return self._stage_snapshot(row)
            if row["status"] in {
                RuntimeStageStatus.SUCCEEDED.value,
                RuntimeStageStatus.SUPPRESSED.value,
            }:
                raise AcquisitionRuntimeConflict("terminal runtime stage cannot restart")
            if row["status"] == RuntimeStageStatus.RUNNING.value:
                return self._stage_snapshot(row)
            if (
                row["status"] == RuntimeStageStatus.WAITING.value
                and row["replay_same_attempt"]
            ):
                attempt = connection.execute(
                    sa.select(acquisition_runtime_stage_attempt)
                    .where(
                        acquisition_runtime_stage_attempt.c.cycle_ref == cycle_ref,
                        acquisition_runtime_stage_attempt.c.stage == stage.value,
                        acquisition_runtime_stage_attempt.c.attempt_count
                        == row["attempt_count"],
                    )
                    .with_for_update()
                ).mappings().one()
                if (
                    attempt["status"] != RuntimeStageStatus.WAITING.value
                    or not attempt["replay_same_attempt"]
                ):
                    raise AcquisitionRuntimeConflict(
                        "runtime same-attempt replay checkpoint drifted"
                    )
                connection.execute(
                    sa.update(acquisition_runtime_stage_attempt)
                    .where(
                        acquisition_runtime_stage_attempt.c.cycle_ref == cycle_ref,
                        acquisition_runtime_stage_attempt.c.stage == stage.value,
                        acquisition_runtime_stage_attempt.c.attempt_count
                        == row["attempt_count"],
                    )
                    .values(
                        status=RuntimeStageStatus.RUNNING.value,
                        retry_at=None,
                        replay_same_attempt=False,
                        completed_at=None,
                    )
                )
                updated = connection.execute(
                    sa.update(acquisition_runtime_stage)
                    .where(
                        acquisition_runtime_stage.c.cycle_ref == cycle_ref,
                        acquisition_runtime_stage.c.stage == stage.value,
                    )
                    .values(
                        status=RuntimeStageStatus.RUNNING.value,
                        reason_codes=[],
                        retry_at=None,
                        replay_same_attempt=False,
                        completed_at=None,
                        updated_at=at,
                    )
                    .returning(acquisition_runtime_stage)
                ).mappings().one()
                connection.execute(
                    sa.update(acquisition_runtime_cycle)
                    .where(acquisition_runtime_cycle.c.cycle_ref == cycle_ref)
                    .values(
                        status=RuntimeCycleStatus.RUNNING.value,
                        last_reason_code=None,
                        updated_at=at,
                    )
                )
                return self._stage_snapshot(updated)
            updated = connection.execute(
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
                    reserved_cost=Decimal("0"),
                    observed_cost=Decimal("0"),
                    reason_codes=[],
                    retry_at=None,
                    replay_same_attempt=False,
                    started_at=at,
                    completed_at=None,
                    updated_at=at,
                )
                .returning(acquisition_runtime_stage)
            ).mappings().one()
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
            return self._stage_snapshot(updated)

    def reserve_stage_cost(
        self,
        cycle_ref: str,
        stage: AcquisitionRuntimeStage,
        stage_snapshot: RuntimeStageSnapshot,
        reserved_cost: Decimal,
        *,
        maximum_cycle_cost: Decimal,
        owner_ref: str,
        fencing_token: int,
        at: dt.datetime,
    ) -> RuntimeStageReservation:
        """Atomically reserve one deterministic envelope before Hermes or providers."""

        at = require_aware(at)
        with self.engine.begin() as connection:
            self._require_active_lease(
                connection,
                owner_ref,
                fencing_token=fencing_token,
                at=at,
            )
            row = self._stage(connection, cycle_ref, stage)
            self._cycle(connection, cycle_ref)
            if (
                row["status"] != RuntimeStageStatus.RUNNING.value
                or row["attempt_count"] != stage_snapshot.attempt_count
            ):
                raise AcquisitionRuntimeConflict("runtime attempt cannot reserve cost")
            attempt = connection.execute(
                sa.select(acquisition_runtime_stage_attempt)
                .where(
                    acquisition_runtime_stage_attempt.c.cycle_ref == cycle_ref,
                    acquisition_runtime_stage_attempt.c.stage == stage.value,
                    acquisition_runtime_stage_attempt.c.attempt_count
                    == stage_snapshot.attempt_count,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if attempt is not None:
                unreserved_interruption = (
                    attempt["status"] == RuntimeStageStatus.RUNNING.value
                    and Decimal(attempt["reserved_cost"]) == Decimal("0")
                    and reserved_cost > Decimal("0")
                    and Decimal(attempt["observed_cost"]) == Decimal("0")
                    and attempt["proposal"] is None
                    and attempt["retry_at"] is None
                    and attempt["completed_at"] is None
                )
                if unreserved_interruption:
                    total_before = self._spent_cost(connection, cycle_ref)
                    if total_before + reserved_cost > maximum_cycle_cost:
                        return RuntimeStageReservation(
                            accepted=False,
                            created=False,
                            reserved_cost=reserved_cost,
                            total_cycle_cost=total_before,
                        )
                    connection.execute(
                        sa.update(acquisition_runtime_stage_attempt)
                        .where(
                            acquisition_runtime_stage_attempt.c.cycle_ref
                            == cycle_ref,
                            acquisition_runtime_stage_attempt.c.stage
                            == stage.value,
                            acquisition_runtime_stage_attempt.c.attempt_count
                            == stage_snapshot.attempt_count,
                            acquisition_runtime_stage_attempt.c.status
                            == RuntimeStageStatus.RUNNING.value,
                            acquisition_runtime_stage_attempt.c.reserved_cost
                            == Decimal("0"),
                        )
                        .values(reserved_cost=reserved_cost)
                    )
                    connection.execute(
                        sa.update(acquisition_runtime_stage)
                        .where(
                            acquisition_runtime_stage.c.cycle_ref == cycle_ref,
                            acquisition_runtime_stage.c.stage == stage.value,
                        )
                        .values(reserved_cost=reserved_cost, updated_at=at)
                    )
                    connection.execute(
                        sa.update(acquisition_runtime_cycle)
                        .where(acquisition_runtime_cycle.c.cycle_ref == cycle_ref)
                        .values(
                            spent_cost=total_before + reserved_cost,
                            updated_at=at,
                        )
                    )
                    return RuntimeStageReservation(
                        accepted=True,
                        created=True,
                        reserved_cost=reserved_cost,
                        total_cycle_cost=total_before + reserved_cost,
                    )
                if (
                    attempt["status"] != RuntimeStageStatus.RUNNING.value
                    or Decimal(attempt["reserved_cost"]) != reserved_cost
                    or Decimal(attempt["observed_cost"]) != Decimal("0")
                    or attempt["retry_at"] is not None
                    or attempt["completed_at"] is not None
                ):
                    raise AcquisitionRuntimeConflict(
                        "runtime attempt reservation is not replay safe"
                    )
                total = self._spent_cost(connection, cycle_ref)
                return RuntimeStageReservation(
                    accepted=True,
                    created=False,
                    reserved_cost=reserved_cost,
                    total_cycle_cost=total,
                    proposal=(
                        RuntimeProposal.model_validate(attempt["proposal"])
                        if attempt["proposal"] is not None
                        else None
                    ),
                )
            total_before = self._spent_cost(connection, cycle_ref)
            if total_before + reserved_cost > maximum_cycle_cost:
                return RuntimeStageReservation(
                    accepted=False,
                    created=False,
                    reserved_cost=reserved_cost,
                    total_cycle_cost=total_before,
                )
            values = {
                "cycle_ref": cycle_ref,
                "stage": stage.value,
                "attempt_count": stage_snapshot.attempt_count,
                "status": RuntimeStageStatus.RUNNING.value,
                "reserved_cost": reserved_cost,
                "observed_cost": Decimal("0"),
                "proposal": None,
                "retry_at": None,
                "replay_same_attempt": False,
                "completed_at": None,
            }
            inserted = insert_if_absent(
                connection,
                acquisition_runtime_stage_attempt,
                values,
                index_elements=[
                    acquisition_runtime_stage_attempt.c.cycle_ref,
                    acquisition_runtime_stage_attempt.c.stage,
                    acquisition_runtime_stage_attempt.c.attempt_count,
                ],
            )
            if not inserted:
                raise AcquisitionRuntimeConflict(
                    "runtime attempt reservation raced its fencing transaction"
                )
            connection.execute(
                sa.update(acquisition_runtime_stage)
                .where(
                    acquisition_runtime_stage.c.cycle_ref == cycle_ref,
                    acquisition_runtime_stage.c.stage == stage.value,
                )
                .values(
                    reserved_cost=reserved_cost,
                    updated_at=at,
                )
            )
            connection.execute(
                sa.update(acquisition_runtime_cycle)
                .where(acquisition_runtime_cycle.c.cycle_ref == cycle_ref)
                .values(
                    spent_cost=total_before + reserved_cost,
                    updated_at=at,
                )
            )
            return RuntimeStageReservation(
                accepted=True,
                created=True,
                reserved_cost=reserved_cost,
                total_cycle_cost=total_before + reserved_cost,
            )

    def bind_stage_proposal(
        self,
        cycle_ref: str,
        stage: AcquisitionRuntimeStage,
        stage_snapshot: RuntimeStageSnapshot,
        proposal: RuntimeProposal,
        *,
        owner_ref: str,
        fencing_token: int,
        at: dt.datetime,
    ) -> RuntimeProposal:
        at = require_aware(at)
        with self.engine.begin() as connection:
            self._require_active_lease(
                connection,
                owner_ref,
                fencing_token=fencing_token,
                at=at,
            )
            row = self._stage(connection, cycle_ref, stage)
            attempt = connection.execute(
                sa.select(acquisition_runtime_stage_attempt)
                .where(
                    acquisition_runtime_stage_attempt.c.cycle_ref == cycle_ref,
                    acquisition_runtime_stage_attempt.c.stage == stage.value,
                    acquisition_runtime_stage_attempt.c.attempt_count
                    == stage_snapshot.attempt_count,
                )
                .with_for_update()
            ).mappings().one()
            if (
                row["status"] != RuntimeStageStatus.RUNNING.value
                or row["attempt_count"] != stage_snapshot.attempt_count
                or attempt["status"] != RuntimeStageStatus.RUNNING.value
                or Decimal(attempt["reserved_cost"]) != proposal.estimated_cost
            ):
                raise AcquisitionRuntimeConflict(
                    "runtime proposal does not match its reserved attempt"
                )
            stored = attempt["proposal"]
            if stored is not None:
                replay = RuntimeProposal.model_validate(stored)
                if replay != proposal:
                    raise AcquisitionRuntimeConflict(
                        "runtime proposal changed during replay"
                    )
                return replay
            encoded = proposal.model_dump(mode="json")
            connection.execute(
                sa.update(acquisition_runtime_stage_attempt)
                .where(
                    acquisition_runtime_stage_attempt.c.cycle_ref == cycle_ref,
                    acquisition_runtime_stage_attempt.c.stage == stage.value,
                    acquisition_runtime_stage_attempt.c.attempt_count
                    == stage_snapshot.attempt_count,
                )
                .values(proposal=encoded)
            )
            connection.execute(
                sa.update(acquisition_runtime_stage)
                .where(
                    acquisition_runtime_stage.c.cycle_ref == cycle_ref,
                    acquisition_runtime_stage.c.stage == stage.value,
                )
                .values(
                    plan_ref=proposal.plan_ref,
                    command=proposal.command,
                    argument_fingerprint=proposal.argument_fingerprint,
                    updated_at=at,
                )
            )
            return proposal

    def finish_stage(
        self,
        cycle_ref: str,
        stage: AcquisitionRuntimeStage,
        result: RuntimeActionResult,
        *,
        owner_ref: str,
        fencing_token: int,
        at: dt.datetime,
        proposal: RuntimeProposal | None = None,
    ) -> None:
        at = require_aware(at)
        with self.engine.begin() as connection:
            self._require_active_lease(
                connection,
                owner_ref,
                fencing_token=fencing_token,
                at=at,
            )
            row = self._stage(connection, cycle_ref, stage)
            if row["status"] != RuntimeStageStatus.RUNNING.value:
                raise AcquisitionRuntimeConflict("runtime stage is not owned for completion")
            attempt = connection.execute(
                sa.select(acquisition_runtime_stage_attempt).where(
                    acquisition_runtime_stage_attempt.c.cycle_ref == cycle_ref,
                    acquisition_runtime_stage_attempt.c.stage == stage.value,
                    acquisition_runtime_stage_attempt.c.attempt_count
                    == row["attempt_count"],
                )
            ).mappings().one_or_none()
            if attempt is None:
                reserved_cost = result.reserved_cost
                insert_if_absent(
                    connection,
                    acquisition_runtime_stage_attempt,
                    {
                        "cycle_ref": cycle_ref,
                        "stage": stage.value,
                        "attempt_count": row["attempt_count"],
                        "status": result.status.value,
                        "reserved_cost": reserved_cost,
                        "observed_cost": result.observed_cost,
                        "proposal": (
                            proposal.model_dump(mode="json")
                            if proposal is not None
                            else None
                        ),
                        "retry_at": result.retry_at,
                        "replay_same_attempt": result.replay_same_attempt,
                        "completed_at": at,
                    },
                    index_elements=[
                        acquisition_runtime_stage_attempt.c.cycle_ref,
                        acquisition_runtime_stage_attempt.c.stage,
                        acquisition_runtime_stage_attempt.c.attempt_count,
                    ],
                )
            else:
                if attempt["status"] != RuntimeStageStatus.RUNNING.value:
                    raise AcquisitionRuntimeConflict(
                        "runtime attempt was already finalized"
                    )
                reserved_cost = Decimal(attempt["reserved_cost"])
                if result.reserved_cost not in {Decimal("0"), reserved_cost}:
                    raise AcquisitionRuntimeConflict(
                        "runtime attempt reserved cost changed"
                    )
                if proposal is not None and (
                    attempt["proposal"] is None
                    or RuntimeProposal.model_validate(attempt["proposal"])
                    != proposal
                ):
                    raise AcquisitionRuntimeConflict(
                        "runtime attempt proposal changed"
                    )
                connection.execute(
                    sa.update(acquisition_runtime_stage_attempt)
                    .where(
                        acquisition_runtime_stage_attempt.c.cycle_ref == cycle_ref,
                        acquisition_runtime_stage_attempt.c.stage == stage.value,
                        acquisition_runtime_stage_attempt.c.attempt_count
                        == row["attempt_count"],
                        acquisition_runtime_stage_attempt.c.status
                        == RuntimeStageStatus.RUNNING.value,
                    )
                    .values(
                        status=result.status.value,
                        observed_cost=result.observed_cost,
                        retry_at=result.retry_at,
                        replay_same_attempt=result.replay_same_attempt,
                        completed_at=at,
                    )
                )
            connection.execute(
                sa.update(acquisition_runtime_stage)
                .where(
                    acquisition_runtime_stage.c.cycle_ref == cycle_ref,
                    acquisition_runtime_stage.c.stage == stage.value,
                )
                .values(
                    status=result.status.value,
                    plan_ref=proposal.plan_ref if proposal else row["plan_ref"],
                    command=proposal.command if proposal else row["command"],
                    argument_fingerprint=(
                        proposal.argument_fingerprint
                        if proposal
                        else row["argument_fingerprint"]
                    ),
                    result_refs=list(result.result_refs),
                    reserved_cost=reserved_cost,
                    observed_cost=result.observed_cost,
                    reason_codes=list(result.reason_codes),
                    retry_at=result.retry_at,
                    replay_same_attempt=result.replay_same_attempt,
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
        owner_ref: str,
        fencing_token: int,
        at: dt.datetime,
        reason_code: str | None = None,
    ) -> None:
        at = require_aware(at)
        with self.engine.begin() as connection:
            self._require_active_lease(
                connection,
                owner_ref,
                fencing_token=fencing_token,
                at=at,
            )
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
                    "retry_at": None,
                    "replay_same_attempt": False,
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
    def _stage_snapshot(row: RowMapping) -> RuntimeStageSnapshot:
        return RuntimeStageSnapshot(
            cycle_ref=row["cycle_ref"],
            stage=AcquisitionRuntimeStage(row["stage"]),
            status=RuntimeStageStatus(row["status"]),
            attempt_count=row["attempt_count"],
            result_refs=tuple(row["result_refs"]),
            retry_at=(
                _aware(row["retry_at"]) if row["retry_at"] is not None else None
            ),
            replay_same_attempt=bool(row["replay_same_attempt"]),
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
                acquisition_runtime_stage_attempt.c.reserved_cost,
                acquisition_runtime_stage_attempt.c.observed_cost,
            ).where(acquisition_runtime_stage_attempt.c.cycle_ref == cycle_ref)
        ).all()
        return sum(
            (max(Decimal(row[0]), Decimal(row[1])) for row in rows),
            start=Decimal("0"),
        )

    @staticmethod
    def _require_active_lease(
        connection: Connection,
        owner_ref: str,
        *,
        fencing_token: int,
        at: dt.datetime,
    ) -> None:
        row = AcquisitionRuntimeStore._lease_row(connection)
        observed_at = AcquisitionRuntimeStore._database_now(
            connection,
            fallback=at,
        )
        if (
            row["owner_ref"] != owner_ref
            or row["generation"] != fencing_token
            or row["expires_at"] is None
            or _aware(row["expires_at"]) <= observed_at
        ):
            raise AcquisitionRuntimeConflict(
                "runtime observation requires the active lease owner"
            )

    @staticmethod
    def _lease_row(connection: Connection) -> RowMapping:
        row = connection.execute(
            sa.select(acquisition_runtime_lease)
            .where(acquisition_runtime_lease.c.lease_name == LEASE_NAME)
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise AcquisitionRuntimeConflict("runtime lease is unavailable")
        return row

    @staticmethod
    def _database_now(
        connection: Connection,
        *,
        fallback: dt.datetime | None,
    ) -> dt.datetime:
        if connection.dialect.name == "postgresql":
            value = connection.scalar(sa.select(sa.func.current_timestamp()))
            if not isinstance(value, dt.datetime):
                raise AcquisitionRuntimeConflict("database clock is unavailable")
            return _aware(value)
        if fallback is None:
            raise AcquisitionRuntimeConflict("runtime lease clock is unavailable")
        return require_aware(fallback)

    @staticmethod
    def _capability_values(
        capability: RuntimeCapabilityEvidence,
    ) -> dict[str, object]:
        return {
            "capability_fingerprint": capability.fingerprint,
            "environment": capability.environment,
            "mode": capability.mode.value,
            "qa_only": capability.qa_only,
            "hermes_repository": capability.hermes.repository,
            "hermes_tag": capability.hermes.tag,
            "hermes_commit": capability.hermes.commit,
            "hermes_version": capability.hermes.version,
            "hermes_python_contract": capability.hermes.python_contract,
            "registry_identity": capability.registry_identity,
            "native_tools": capability.native_tools,
            "commands": list(capability.commands),
            "dependencies": [
                item.model_dump(mode="json") for item in capability.dependencies
            ],
        }

    @staticmethod
    def _runtime_observation_row(connection: Connection) -> RowMapping:
        row = connection.execute(
            sa.select(acquisition_runtime_observation)
            .where(
                acquisition_runtime_observation.c.runtime_name
                == RUNTIME_OBSERVATION_NAME
            )
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise AcquisitionRuntimeConflict("runtime observation is unavailable")
        return row

    @staticmethod
    def _runtime_observation(row: RowMapping) -> RuntimeHealthObservation:
        capability = RuntimeCapabilityEvidence(
            environment=row["environment"],
            mode=row["mode"],
            qa_only=row["qa_only"],
            hermes=RuntimeHermesIdentityEvidence(
                repository=row["hermes_repository"],
                tag=row["hermes_tag"],
                commit=row["hermes_commit"],
                version=row["hermes_version"],
                python_contract=row["hermes_python_contract"],
            ),
            registry_identity=row["registry_identity"],
            native_tools=row["native_tools"],
            commands=tuple(row["commands"]),
            dependencies=tuple(
                RuntimeStageDependency.model_validate(item)
                for item in row["dependencies"]
            ),
        )
        if capability.fingerprint != row["capability_fingerprint"]:
            raise AcquisitionRuntimeConflict(
                "runtime capability fingerprint mismatch"
            )
        return RuntimeHealthObservation(
            capability=capability,
            observed_at=_aware(row["observed_at"]),
            heartbeat_at=_aware(row["heartbeat_at"]),
            last_cycle_ref=row["last_cycle_ref"],
            last_cycle_status=row["last_cycle_status"],
            last_cycle_at=(
                _aware(row["last_cycle_at"])
                if row["last_cycle_at"] is not None
                else None
            ),
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
    "RUNTIME_OBSERVATION_NAME",
    "AcquisitionRuntimeConflict",
    "AcquisitionRuntimeStore",
]
