from __future__ import annotations

import datetime as dt

from signals.acquisition_runtime.authorization import (
    AcquisitionRuntimeApprovalStore,
    RuntimeApprovalBinding,
    RuntimeApprovalStatus,
)
from signals.acquisition_runtime.contracts import AcquisitionRuntimeStage
from signals.acquisition_runtime.store import AcquisitionRuntimeStore
from signals.operations.cli import main
from signals.persistence.database import create_database_engine
from signals.persistence.schema import METADATA
from signals.policy.contracts import POLICY_VERSION, ApprovalPurpose

NOW = dt.datetime(2026, 8, 25, 12, tzinfo=dt.UTC)


def _pending(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path / 'runtime-approval-cli.db'}"
    engine = create_database_engine(url)
    METADATA.create_all(engine)
    cycle = AcquisitionRuntimeStore(engine).resume_or_create_cycle(
        opportunity_keys=("signal-qa-001",),
        config_fingerprint="c" * 64,
        at=NOW,
    )
    store = AcquisitionRuntimeApprovalStore(engine)
    snapshot = store.request_approval(
        RuntimeApprovalBinding(
            request_ref="request-qa-001",
            cycle_ref=cycle.cycle_ref,
            stage=AcquisitionRuntimeStage.CAMPAIGN,
            purpose=ApprovalPurpose.ACTION,
            command=AcquisitionRuntimeStage.CAMPAIGN.command,
            target_ref="private-target-marker",
            acquisition_opportunity_id="private-opportunity-marker",
            action_fingerprint="a" * 64,
            policy_version=POLICY_VERSION,
            policy_snapshot_id="policy-snapshot-qa-001",
            control_revision=1,
            scope_fingerprint="b" * 64,
            requested_at=NOW,
            expires_at=NOW + dt.timedelta(minutes=30),
        )
    )
    return url, store, snapshot


def test_operator_lists_only_bounded_pending_approval_metadata(
    tmp_path, capsys
) -> None:
    url, _store, pending = _pending(tmp_path)

    result = main(
        [
            "--database-url",
            url,
            "--now",
            (NOW + dt.timedelta(minutes=1)).isoformat(),
            "list-runtime-approvals",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "runtime_approvals pending=1" in output
    assert f"approval_id={pending.approval_id}" in output
    assert "stage=CAMPAIGN" in output
    assert "status=PENDING" in output
    assert "expires_at=2026-08-25T12:30:00+00:00" in output
    assert "private-target-marker" not in output
    assert "private-opportunity-marker" not in output


def test_operator_approves_one_exact_request_with_an_explicit_actor(
    tmp_path, capsys
) -> None:
    url, store, pending = _pending(tmp_path)

    result = main(
        [
            "--database-url",
            url,
            "--now",
            (NOW + dt.timedelta(minutes=1)).isoformat(),
            "approve-runtime-approval",
            "--approval-id",
            pending.approval_id,
            "--actor-ref",
            "operator-qa-001",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert output == (
        f"runtime_approval approval_id={pending.approval_id} "
        "stage=CAMPAIGN status=APPROVED\n"
    )
    rows = store.list_approvals(status=RuntimeApprovalStatus.APPROVED)
    assert len(rows) == 1
    assert rows[0].approved_by_actor_ref == "operator-qa-001"


def test_invalid_operator_values_fail_closed_without_reflection(tmp_path, capsys) -> None:
    url, _store, _pending_snapshot = _pending(tmp_path)
    marker = "private@example.test"

    result = main(
        [
            "--database-url",
            url,
            "--now",
            (NOW + dt.timedelta(minutes=1)).isoformat(),
            "approve-runtime-approval",
            "--approval-id",
            marker,
            "--actor-ref",
            marker,
        ]
    )

    assert result == 2
    streams = capsys.readouterr()
    assert streams.out == ""
    assert streams.err == "runtime_approval_invalid\n"
    assert marker not in streams.err
