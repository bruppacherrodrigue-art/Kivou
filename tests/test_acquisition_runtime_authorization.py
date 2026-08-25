from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import importlib.util

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from signals.acquisition_runtime import authorization
from signals.acquisition_runtime.authorization import (
    AcquisitionRuntimeApprovalStore,
    ApprovalBindingConflict,
    ApprovalExpired,
    ApprovalStateConflict,
    RuntimeApprovalBinding,
    RuntimeApprovalStatus,
)
from signals.acquisition_runtime.contracts import AcquisitionRuntimeStage
from signals.acquisition_runtime.store import AcquisitionRuntimeStore
from signals.persistence.database import create_database_engine
from signals.persistence.schema import (
    METADATA,
    acquisition_runtime_cycle,
    acquisition_runtime_lease,
    acquisition_runtime_stage,
)
from signals.policy.contracts import POLICY_VERSION, ApprovalPurpose

NOW = dt.datetime(2026, 8, 25, 10, tzinfo=dt.UTC)


def test_runtime_authorization_boundary_exists() -> None:
    assert importlib.util.find_spec("signals.acquisition_runtime.authorization") is not None
    assert {
        "AcquisitionRuntimeApprovalStore",
        "ApprovalBindingConflict",
        "ApprovalExpired",
        "ApprovalNotFound",
        "ApprovalStateConflict",
        "RuntimeApprovalBinding",
        "RuntimeApprovalSnapshot",
        "RuntimeApprovalStatus",
    } <= set(dir(authorization))


def _prepared_store(
    tmp_path, name: str = "approval.db"
) -> tuple[AcquisitionRuntimeApprovalStore, RuntimeApprovalBinding]:
    engine = create_database_engine(
        f"sqlite+pysqlite:///{tmp_path / name}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    tables = [
        acquisition_runtime_lease,
        acquisition_runtime_cycle,
        acquisition_runtime_stage,
    ]
    approval_table = METADATA.tables.get("acquisition_runtime_approval")
    if approval_table is not None:
        tables.append(approval_table)
    METADATA.create_all(engine, tables=tables)
    runtime = AcquisitionRuntimeStore(engine)
    lease = runtime.acquire_lease(
        "test-owner",
        acquired_at=NOW,
        lease_seconds=120,
    )
    assert lease.fencing_token is not None
    cycle = runtime.resume_or_create_cycle(
        owner_ref="test-owner",
        fencing_token=lease.fencing_token,
        opportunity_keys=("signal-qa-001",),
        config_fingerprint="1" * 64,
        at=NOW,
    )
    binding = RuntimeApprovalBinding(
        request_ref="qa-approval-request-001",
        cycle_ref=cycle.cycle_ref,
        stage=AcquisitionRuntimeStage.PERSONALIZATION,
        purpose=ApprovalPurpose.ACTION,
        command="prepare_campaign",
        target_ref="opportunity-qa-001",
        acquisition_opportunity_id="opportunity-qa-001",
        action_fingerprint="a" * 64,
        policy_version=POLICY_VERSION,
        policy_snapshot_id="policy-snapshot-qa-001",
        control_revision=7,
        scope_fingerprint="b" * 64,
        requested_at=NOW,
        expires_at=NOW + dt.timedelta(minutes=30),
    )
    return AcquisitionRuntimeApprovalStore(engine), binding


def test_request_is_pending_durable_and_exact_replay_is_idempotent(tmp_path) -> None:
    store, binding = _prepared_store(tmp_path)

    first = store.request_approval(binding)
    replay = store.request_approval(binding)

    assert first == replay
    assert first.status is RuntimeApprovalStatus.PENDING
    assert first.approved_by_actor_ref is None
    assert first.consumed_by_ref is None
    expected_id = hashlib.sha256(
        f"acquisition-runtime-approval-v1\0{binding.request_ref}".encode()
    ).hexdigest()
    assert first.approval_id == expected_id
    with store.engine.connect() as connection:
        row = (
            connection.execute(
                sa.text(
                    "SELECT state, binding_fingerprint, approved_by_actor_ref, "
                    "consumed_by_ref FROM acquisition_runtime_approval"
                )
            )
            .mappings()
            .one()
        )
    assert row["state"] == RuntimeApprovalStatus.PENDING.value
    assert len(row["binding_fingerprint"]) == 64
    assert row["approved_by_actor_ref"] is None
    assert row["consumed_by_ref"] is None


def test_request_replay_rejects_any_binding_drift(tmp_path) -> None:
    store, binding = _prepared_store(tmp_path)
    store.request_approval(binding)
    base = binding.model_dump(mode="python")
    variants = (
        {"cycle_ref": "different-cycle"},
        {
            "stage": AcquisitionRuntimeStage.CAMPAIGN,
            "command": "schedule_campaign",
        },
        {"purpose": ApprovalPurpose.COMPLIANCE_REVIEW},
        {"target_ref": "different-target"},
        {"acquisition_opportunity_id": "different-opportunity"},
        {"action_fingerprint": "c" * 64},
        {"policy_version": "acquisition-policy-v2"},
        {"policy_snapshot_id": "different-snapshot"},
        {"control_revision": 8},
        {"scope_fingerprint": "d" * 64},
        {"requested_at": NOW + dt.timedelta(seconds=1)},
        {"expires_at": NOW + dt.timedelta(minutes=31)},
    )

    for updates in variants:
        drifted = RuntimeApprovalBinding.model_validate({**base, **updates})
        with pytest.raises(ApprovalBindingConflict):
            store.request_approval(drifted)


def test_binding_rejects_a_command_outside_its_exact_runtime_stage(tmp_path) -> None:
    _store, binding = _prepared_store(tmp_path)

    with pytest.raises(ValidationError):
        RuntimeApprovalBinding.model_validate(
            {
                **binding.model_dump(mode="python"),
                "command": "schedule_campaign",
            }
        )


def test_binding_cannot_exceed_existing_policy_grant_contracts(tmp_path) -> None:
    _store, binding = _prepared_store(tmp_path)

    with pytest.raises(ValidationError):
        RuntimeApprovalBinding.model_validate(
            {
                **binding.model_dump(mode="python"),
                "policy_version": "p" * 101,
            }
        )
    with pytest.raises(ValidationError):
        RuntimeApprovalBinding.model_validate(
            {
                **binding.model_dump(mode="python"),
                "acquisition_opportunity_id": "o" * 129,
            }
        )


def test_approval_is_explicit_and_exact_actor_replay_is_idempotent(tmp_path) -> None:
    store, binding = _prepared_store(tmp_path)
    pending = store.request_approval(binding)

    approved = store.approve(
        pending.approval_id,
        approved_by_actor_ref="operator-qa-001",
        at=NOW + dt.timedelta(minutes=1),
    )
    replay = store.approve(
        pending.approval_id,
        approved_by_actor_ref="operator-qa-001",
        at=NOW + dt.timedelta(minutes=2),
    )

    assert approved == replay
    assert approved.status is RuntimeApprovalStatus.APPROVED
    assert approved.approved_by_actor_ref == "operator-qa-001"
    assert approved.approved_at == NOW + dt.timedelta(minutes=1)
    with pytest.raises(ApprovalStateConflict):
        store.approve(
            pending.approval_id,
            approved_by_actor_ref="operator-qa-002",
            at=NOW + dt.timedelta(minutes=2),
        )


def test_two_concurrent_approvers_cannot_both_commit(tmp_path) -> None:
    store, binding = _prepared_store(tmp_path, "approval-concurrency.db")
    pending = store.request_approval(binding)

    def attempt(actor_ref: str) -> tuple[str, str]:
        try:
            approved = AcquisitionRuntimeApprovalStore(store.engine).approve(
                pending.approval_id,
                approved_by_actor_ref=actor_ref,
                at=NOW + dt.timedelta(minutes=1),
            )
        except ApprovalStateConflict:
            return ("CONFLICT", actor_ref)
        return (approved.status.value, approved.approved_by_actor_ref or "")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ("operator-qa-a", "operator-qa-b")))

    assert sorted(result[0] for result in results) == ["APPROVED", "CONFLICT"]
    with store.engine.connect() as connection:
        approver = connection.scalar(
            sa.text("SELECT approved_by_actor_ref FROM acquisition_runtime_approval")
        )
    assert approver in {"operator-qa-a", "operator-qa-b"}


def test_pending_request_cannot_forge_a_grant(tmp_path) -> None:
    store, binding = _prepared_store(tmp_path)
    pending = store.request_approval(binding)

    with pytest.raises(ApprovalStateConflict):
        store.consume_grant(
            pending.approval_id,
            consumer_ref="attempt-qa-001",
            at=NOW + dt.timedelta(minutes=1),
        )


def test_approved_request_is_consumed_once_and_builds_exact_policy_grant(
    tmp_path,
) -> None:
    store, binding = _prepared_store(tmp_path)
    pending = store.request_approval(binding)
    approved = store.approve(
        pending.approval_id,
        approved_by_actor_ref="operator-qa-001",
        at=NOW + dt.timedelta(minutes=1),
    )

    grant = store.consume_grant(
        pending.approval_id,
        consumer_ref="attempt-qa-001",
        at=NOW + dt.timedelta(minutes=2),
    )
    exact_replay = store.consume_grant(
        pending.approval_id,
        consumer_ref="attempt-qa-001",
        at=NOW + dt.timedelta(minutes=3),
    )

    assert exact_replay == grant
    assert grant.approval_id == pending.approval_id
    assert grant.purpose is binding.purpose
    assert grant.command == binding.command
    assert grant.target_ref == binding.target_ref
    assert grant.acquisition_opportunity_id == binding.acquisition_opportunity_id
    assert grant.action_fingerprint == binding.action_fingerprint
    assert grant.policy_version == binding.policy_version
    assert grant.policy_snapshot_id == binding.policy_snapshot_id
    assert grant.control_revision == binding.control_revision
    assert grant.scope_fingerprint == binding.scope_fingerprint
    assert grant.issued_at == approved.approved_at
    assert grant.expires_at == binding.expires_at
    assert grant.one_shot is True
    assert grant.consumed_at is None
    assert grant.approved_by_actor_ref == "operator-qa-001"
    with store.engine.connect() as connection:
        row = (
            connection.execute(
                sa.text(
                    "SELECT state, consumed_by_ref, consumed_at FROM acquisition_runtime_approval"
                )
            )
            .mappings()
            .one()
        )
    assert row["state"] == RuntimeApprovalStatus.CONSUMED.value
    assert row["consumed_by_ref"] == "attempt-qa-001"
    assert row["consumed_at"] is not None
    with pytest.raises(ApprovalStateConflict):
        store.consume_grant(
            pending.approval_id,
            consumer_ref="attempt-qa-002",
            at=NOW + dt.timedelta(minutes=3),
        )


def test_two_concurrent_consumers_get_only_one_logical_grant(tmp_path) -> None:
    store, binding = _prepared_store(tmp_path, "consume-concurrency.db")
    pending = store.request_approval(binding)
    store.approve(
        pending.approval_id,
        approved_by_actor_ref="operator-qa-001",
        at=NOW + dt.timedelta(minutes=1),
    )

    def attempt(consumer_ref: str) -> tuple[str, str]:
        try:
            grant = AcquisitionRuntimeApprovalStore(store.engine).consume_grant(
                pending.approval_id,
                consumer_ref=consumer_ref,
                at=NOW + dt.timedelta(minutes=2),
            )
        except ApprovalStateConflict:
            return ("CONFLICT", consumer_ref)
        return ("GRANT", grant.approval_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, ("attempt-qa-a", "attempt-qa-b")))

    assert sorted(result[0] for result in results) == ["CONFLICT", "GRANT"]


def test_expiration_is_fail_closed_for_approval_and_consumption(tmp_path) -> None:
    store, binding = _prepared_store(tmp_path)
    pending = store.request_approval(binding)
    with pytest.raises(ApprovalExpired):
        store.approve(
            pending.approval_id,
            approved_by_actor_ref="operator-qa-001",
            at=binding.expires_at,
        )

    approved = store.approve(
        pending.approval_id,
        approved_by_actor_ref="operator-qa-001",
        at=binding.expires_at - dt.timedelta(seconds=1),
    )
    assert approved.status is RuntimeApprovalStatus.APPROVED
    with pytest.raises(ApprovalExpired):
        store.consume_grant(
            pending.approval_id,
            consumer_ref="attempt-qa-001",
            at=binding.expires_at,
        )


def test_public_inputs_reject_pii_shaped_actor_and_naive_timestamps(tmp_path) -> None:
    store, binding = _prepared_store(tmp_path)
    pending = store.request_approval(binding)

    with pytest.raises(ValueError):
        store.approve(
            pending.approval_id,
            approved_by_actor_ref="person@example.test",
            at=NOW + dt.timedelta(minutes=1),
        )
    with pytest.raises(ValueError):
        store.approve(
            pending.approval_id,
            approved_by_actor_ref="operator-qa-001",
            at=NOW.replace(tzinfo=None),
        )
    with pytest.raises(ValidationError):
        RuntimeApprovalBinding.model_validate(
            {**binding.model_dump(mode="python"), "request_ref": "person@example.test"}
        )


def test_approval_table_has_only_bounded_opaque_audit_fields(tmp_path) -> None:
    store, _binding = _prepared_store(tmp_path)
    columns = {
        column["name"]
        for column in sa.inspect(store.engine).get_columns("acquisition_runtime_approval")
    }
    assert {
        "approval_id",
        "request_ref",
        "cycle_ref",
        "stage",
        "purpose",
        "command",
        "target_ref",
        "acquisition_opportunity_id",
        "action_fingerprint",
        "policy_version",
        "policy_snapshot_id",
        "control_revision",
        "scope_fingerprint",
        "binding_fingerprint",
        "state",
        "requested_at",
        "expires_at",
        "approved_by_actor_ref",
        "approved_at",
        "consumed_by_ref",
        "consumed_at",
        "updated_at",
    } == columns
    forbidden = ("email", "phone", "secret", "payload", "content", "argument")
    assert not any(token in column for column in columns for token in forbidden)
