"""Durable human approval boundary for the bounded acquisition runtime."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from enum import StrEnum

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from sqlalchemy.engine import Engine, RowMapping

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    CommandName,
    Fingerprint,
    OpaqueRef,
    require_aware,
)
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import acquisition_runtime_approval
from signals.policy.contracts import (
    ApprovalGrant,
    ApprovalPurpose,
    Identifier,
    ShortCode,
)


class ApprovalError(RuntimeError):
    """Base class for fail-closed durable approval failures."""


class ApprovalNotFound(ApprovalError):
    """The opaque approval identifier has no durable request."""


class ApprovalBindingConflict(ApprovalError):
    """A logical request was replayed with a different immutable binding."""


class ApprovalStateConflict(ApprovalError):
    """A transition conflicts with an already committed actor or consumer."""


class ApprovalExpired(ApprovalError):
    """The bound authorization window is no longer open."""


class RuntimeApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CONSUMED = "CONSUMED"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class RuntimeApprovalBinding(_FrozenModel):
    request_ref: OpaqueRef
    cycle_ref: OpaqueRef
    stage: AcquisitionRuntimeStage
    purpose: ApprovalPurpose
    command: CommandName
    target_ref: OpaqueRef
    acquisition_opportunity_id: OpaqueRef
    action_fingerprint: Fingerprint
    policy_version: OpaqueRef
    policy_snapshot_id: OpaqueRef
    control_revision: int = Field(ge=1)
    scope_fingerprint: Fingerprint
    requested_at: dt.datetime
    expires_at: dt.datetime

    @model_validator(mode="after")
    def valid_window(self) -> RuntimeApprovalBinding:
        requested_at = require_aware(self.requested_at)
        expires_at = require_aware(self.expires_at)
        if expires_at <= requested_at:
            raise ValueError("approval expiry must follow request time")
        if self.command != self.stage.command:
            raise ValueError("approval command must match its runtime stage")
        TypeAdapter(Identifier).validate_python(self.acquisition_opportunity_id)
        TypeAdapter(Identifier).validate_python(self.policy_snapshot_id)
        TypeAdapter(ShortCode).validate_python(self.policy_version)
        return self


class RuntimeApprovalSnapshot(_FrozenModel):
    approval_id: Fingerprint
    binding: RuntimeApprovalBinding
    status: RuntimeApprovalStatus
    approved_by_actor_ref: OpaqueRef | None = None
    approved_at: dt.datetime | None = None
    consumed_by_ref: OpaqueRef | None = None
    consumed_at: dt.datetime | None = None


class AcquisitionRuntimeApprovalStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def request_approval(self, binding: RuntimeApprovalBinding) -> RuntimeApprovalSnapshot:
        values = _binding_values(binding)
        approval_id = _approval_id(binding.request_ref)
        fingerprint = _binding_fingerprint(binding)
        with self.engine.begin() as connection:
            insert_if_absent(
                connection,
                acquisition_runtime_approval,
                {
                    "approval_id": approval_id,
                    **values,
                    "binding_fingerprint": fingerprint,
                    "state": RuntimeApprovalStatus.PENDING.value,
                    "approved_by_actor_ref": None,
                    "approved_at": None,
                    "consumed_by_ref": None,
                    "consumed_at": None,
                    "updated_at": values["requested_at"],
                },
                index_elements=[acquisition_runtime_approval.c.approval_id],
            )
            row = _row_for(connection, approval_id)
            if (
                row is None
                or row["request_ref"] != binding.request_ref
                or row["binding_fingerprint"] != fingerprint
            ):
                raise ApprovalBindingConflict(approval_id)
            return _snapshot(row)

    def approve(
        self,
        approval_id: str,
        *,
        approved_by_actor_ref: str,
        at: dt.datetime,
    ) -> RuntimeApprovalSnapshot:
        approval_id = _validated_fingerprint(approval_id)
        actor_ref = _validated_opaque(approved_by_actor_ref)
        at = require_aware(at)
        with self.engine.begin() as connection:
            updated = connection.execute(
                sa.update(acquisition_runtime_approval)
                .where(
                    acquisition_runtime_approval.c.approval_id == approval_id,
                    acquisition_runtime_approval.c.state == RuntimeApprovalStatus.PENDING.value,
                    acquisition_runtime_approval.c.requested_at <= at,
                    acquisition_runtime_approval.c.expires_at > at,
                )
                .values(
                    state=RuntimeApprovalStatus.APPROVED.value,
                    approved_by_actor_ref=actor_ref,
                    approved_at=at,
                    updated_at=at,
                )
                .returning(acquisition_runtime_approval.c.approval_id)
            ).first()
            row = _row_for(connection, approval_id)
            if row is None:
                raise ApprovalNotFound(approval_id)
            if updated is not None:
                return _snapshot(row)
            _require_open(row, at)
            if (
                row["state"]
                in {
                    RuntimeApprovalStatus.APPROVED.value,
                    RuntimeApprovalStatus.CONSUMED.value,
                }
                and row["approved_by_actor_ref"] == actor_ref
            ):
                return _snapshot(row)
            raise ApprovalStateConflict(approval_id)

    def consume_grant(
        self,
        approval_id: str,
        *,
        consumer_ref: str,
        at: dt.datetime,
    ) -> ApprovalGrant:
        """Atomically claim one grant for one opaque, replay-safe consumer.

        The durable row is marked ``CONSUMED`` before this call returns.  The
        transient grant keeps ``consumed_at=None`` because the existing policy
        evaluator accepts only a grant claimed for the evaluation in progress.
        A crash may replay that exact consumer ref; another consumer cannot.
        """
        approval_id = _validated_fingerprint(approval_id)
        consumer_ref = _validated_opaque(consumer_ref)
        at = require_aware(at)
        with self.engine.begin() as connection:
            updated = connection.execute(
                sa.update(acquisition_runtime_approval)
                .where(
                    acquisition_runtime_approval.c.approval_id == approval_id,
                    acquisition_runtime_approval.c.state == RuntimeApprovalStatus.APPROVED.value,
                    acquisition_runtime_approval.c.approved_at <= at,
                    acquisition_runtime_approval.c.expires_at > at,
                )
                .values(
                    state=RuntimeApprovalStatus.CONSUMED.value,
                    consumed_by_ref=consumer_ref,
                    consumed_at=at,
                    updated_at=at,
                )
                .returning(acquisition_runtime_approval.c.approval_id)
            ).first()
            row = _row_for(connection, approval_id)
            if row is None:
                raise ApprovalNotFound(approval_id)
            _require_open(row, at)
            if updated is None and not (
                row["state"] == RuntimeApprovalStatus.CONSUMED.value
                and row["consumed_by_ref"] == consumer_ref
            ):
                raise ApprovalStateConflict(approval_id)
            return _grant(row)

    def list_approvals(
        self,
        *,
        status: RuntimeApprovalStatus | None = None,
        limit: int = 100,
    ) -> tuple[RuntimeApprovalSnapshot, ...]:
        """Return bounded approval metadata for the internal operator CLI."""

        if not 1 <= limit <= 100:
            raise ValueError("runtime approval limit must be between 1 and 100")
        statement = sa.select(acquisition_runtime_approval)
        if status is not None:
            statement = statement.where(
                acquisition_runtime_approval.c.state == status.value
            )
        statement = statement.order_by(
            acquisition_runtime_approval.c.requested_at,
            acquisition_runtime_approval.c.approval_id,
        ).limit(limit)
        with self.engine.connect() as connection:
            return tuple(
                _snapshot(row)
                for row in connection.execute(statement).mappings().all()
            )


def _approval_id(request_ref: str) -> str:
    material = f"acquisition-runtime-approval-v1\0{request_ref}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _binding_values(binding: RuntimeApprovalBinding) -> dict[str, object]:
    return {
        "request_ref": binding.request_ref,
        "cycle_ref": binding.cycle_ref,
        "stage": binding.stage.value,
        "purpose": binding.purpose.value,
        "command": binding.command,
        "target_ref": binding.target_ref,
        "acquisition_opportunity_id": binding.acquisition_opportunity_id,
        "action_fingerprint": binding.action_fingerprint,
        "policy_version": binding.policy_version,
        "policy_snapshot_id": binding.policy_snapshot_id,
        "control_revision": binding.control_revision,
        "scope_fingerprint": binding.scope_fingerprint,
        "requested_at": require_aware(binding.requested_at),
        "expires_at": require_aware(binding.expires_at),
    }


def _binding_fingerprint(binding: RuntimeApprovalBinding) -> str:
    values = _binding_values(binding)
    canonical = {
        key: value.isoformat() if isinstance(value, dt.datetime) else value
        for key, value in values.items()
    }
    encoded = json.dumps(
        canonical,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validated_fingerprint(value: str) -> str:
    return TypeAdapter(Fingerprint).validate_python(value)


def _validated_opaque(value: str) -> str:
    return TypeAdapter(OpaqueRef).validate_python(value)


def _stored_time(value: object) -> dt.datetime:
    if not isinstance(value, dt.datetime):
        raise ApprovalStateConflict("approval timestamp is unavailable")
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def _optional_time(value: object) -> dt.datetime | None:
    return None if value is None else _stored_time(value)


def _row_for(connection: sa.Connection, approval_id: str) -> RowMapping | None:
    return (
        connection.execute(
            sa.select(acquisition_runtime_approval).where(
                acquisition_runtime_approval.c.approval_id == approval_id
            )
        )
        .mappings()
        .one_or_none()
    )


def _require_open(row: RowMapping, at: dt.datetime) -> None:
    requested_at = _stored_time(row["requested_at"])
    expires_at = _stored_time(row["expires_at"])
    if at < requested_at:
        raise ApprovalStateConflict(str(row["approval_id"]))
    if at >= expires_at:
        raise ApprovalExpired(str(row["approval_id"]))


def _binding_from_row(row: RowMapping) -> RuntimeApprovalBinding:
    return RuntimeApprovalBinding(
        request_ref=row["request_ref"],
        cycle_ref=row["cycle_ref"],
        stage=row["stage"],
        purpose=row["purpose"],
        command=row["command"],
        target_ref=row["target_ref"],
        acquisition_opportunity_id=row["acquisition_opportunity_id"],
        action_fingerprint=row["action_fingerprint"],
        policy_version=row["policy_version"],
        policy_snapshot_id=row["policy_snapshot_id"],
        control_revision=row["control_revision"],
        scope_fingerprint=row["scope_fingerprint"],
        requested_at=_stored_time(row["requested_at"]),
        expires_at=_stored_time(row["expires_at"]),
    )


def _snapshot(row: RowMapping) -> RuntimeApprovalSnapshot:
    return RuntimeApprovalSnapshot(
        approval_id=row["approval_id"],
        binding=_binding_from_row(row),
        status=row["state"],
        approved_by_actor_ref=row["approved_by_actor_ref"],
        approved_at=_optional_time(row["approved_at"]),
        consumed_by_ref=row["consumed_by_ref"],
        consumed_at=_optional_time(row["consumed_at"]),
    )


def _grant(row: RowMapping) -> ApprovalGrant:
    approved_at = _optional_time(row["approved_at"])
    approved_by = row["approved_by_actor_ref"]
    if (
        row["state"] != RuntimeApprovalStatus.CONSUMED.value
        or approved_at is None
        or approved_by is None
    ):
        raise ApprovalStateConflict(str(row["approval_id"]))
    binding = _binding_from_row(row)
    return ApprovalGrant(
        approval_id=row["approval_id"],
        purpose=binding.purpose,
        command=binding.command,
        target_ref=binding.target_ref,
        acquisition_opportunity_id=binding.acquisition_opportunity_id,
        action_fingerprint=binding.action_fingerprint,
        policy_version=binding.policy_version,
        policy_snapshot_id=binding.policy_snapshot_id,
        control_revision=binding.control_revision,
        scope_fingerprint=binding.scope_fingerprint,
        issued_at=approved_at,
        expires_at=binding.expires_at,
        one_shot=True,
        consumed_at=None,
        approved_by_actor_ref=approved_by,
    )


__all__ = [
    "AcquisitionRuntimeApprovalStore",
    "ApprovalBindingConflict",
    "ApprovalError",
    "ApprovalExpired",
    "ApprovalNotFound",
    "ApprovalStateConflict",
    "RuntimeApprovalBinding",
    "RuntimeApprovalSnapshot",
    "RuntimeApprovalStatus",
]
