"""Explicit, local-only recovery for an interrupted prospect send request.

The recovery command never constructs an Instantly client.  It only rebuilds
the durable local queue from remote identities that were already persisted on
the incident targets; the normal worker performs later verification.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.persistence.schema import prospect_send_item, prospect_send_request, prospect_target

_MAX_RECOVERY_TARGETS = 25
_RECOVERY_ACCOUNTED_ACCEPTANCE = "recovery_already_accepted"


class RecoveryError(RuntimeError):
    """A deliberately bounded operational failure for the recovery command."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RecoveryPreview:
    request_id: str
    approved_count: int
    already_sent_count: int
    existing_lead_count: int
    create_lead_count: int


@dataclass(frozen=True)
class _RecoveryPlan:
    preview: RecoveryPreview
    target_ids: tuple[str, ...]
    campaign_id: str
    sent_target_ids: frozenset[str]
    targets: dict[str, dict[str, object]]
    request: dict[str, object]


def _rows_for_recovery(connection: sa.Connection, request_id: str, *, lock: bool) -> _RecoveryPlan:
    request_query = sa.select(prospect_send_request).where(
        prospect_send_request.c.request_id == request_id
    )
    if lock and connection.dialect.name == "postgresql":
        request_query = request_query.with_for_update()
    request = connection.execute(request_query).mappings().one_or_none()
    if request is None:
        raise RecoveryError("RECOVERY_REQUEST_NOT_FOUND")

    raw_target_ids = request["target_ids"]
    if (
        not isinstance(raw_target_ids, list)
        or not 1 <= len(raw_target_ids) <= _MAX_RECOVERY_TARGETS
        or any(not isinstance(target_id, str) for target_id in raw_target_ids)
        or len(set(raw_target_ids)) != len(raw_target_ids)
    ):
        raise RecoveryError("RECOVERY_TARGET_SET_INVALID")
    target_ids = tuple(raw_target_ids)
    target_query = sa.select(prospect_target).where(prospect_target.c.target_id.in_(target_ids))
    if lock and connection.dialect.name == "postgresql":
        target_query = target_query.with_for_update()
    targets = {
        str(row["target_id"]): dict(row) for row in connection.execute(target_query).mappings()
    }
    if len(targets) != len(target_ids):
        raise RecoveryError("RECOVERY_TARGET_NOT_FOUND")

    approved = []
    sent = []
    for target_id in target_ids:
        target = targets[target_id]
        if target["status"] == "approved":
            approved.append(target)
        elif target["status"] == "sent":
            sent.append(target)
        else:
            raise RecoveryError("RECOVERY_TARGET_NOT_RECOVERABLE")
        if not target["provider_campaign_id"] or not target["instantly_id"]:
            raise RecoveryError("RECOVERY_REMOTE_ID_MISSING")
    if not sent:
        raise RecoveryError("RECOVERY_ORIGINAL_ACCEPTANCE_MISSING")

    campaign_ids = {str(target["provider_campaign_id"]) for target in [*approved, *sent]}
    request_campaign_id = request["provider_campaign_id"]
    if len(campaign_ids) != 1 or (
        request_campaign_id is not None and str(request_campaign_id) not in campaign_ids
    ):
        raise RecoveryError("RECOVERY_CAMPAIGN_BINDING_CONFLICT")
    campaign_id = next(iter(campaign_ids))

    return _RecoveryPlan(
        preview=RecoveryPreview(
            request_id=request_id,
            approved_count=len(approved),
            already_sent_count=len(sent),
            existing_lead_count=len(approved),
            create_lead_count=0,
        ),
        target_ids=target_ids,
        campaign_id=campaign_id,
        sent_target_ids=frozenset(str(target["target_id"]) for target in sent),
        targets=targets,
        request=dict(request),
    )


def _validate_existing_items(connection: sa.Connection, plan: _RecoveryPlan) -> int:
    """Accept only a complete, internally coherent durable replay state."""

    request_id = plan.preview.request_id
    items = tuple(
        connection.execute(
            sa.select(prospect_send_item)
            .where(prospect_send_item.c.request_id == request_id)
            .order_by(prospect_send_item.c.position)
        ).mappings()
    )
    if not items:
        return 0
    if (
        len(items) != len(plan.target_ids)
        or tuple(item["target_id"] for item in items) != plan.target_ids
    ):
        raise RecoveryError("RECOVERY_ALREADY_STARTED")
    if tuple(item["position"] for item in items) != tuple(range(len(plan.target_ids))):
        raise RecoveryError("RECOVERY_ITEM_INCONSISTENT")
    if plan.request["provider_campaign_id"] != plan.campaign_id:
        raise RecoveryError("RECOVERY_ITEM_INCONSISTENT")

    processed = sent = failed = 0
    for item in items:
        target_id = str(item["target_id"])
        target = plan.targets[target_id]
        if item["instantly_id"] != target["instantly_id"]:
            raise RecoveryError("RECOVERY_ITEM_INCONSISTENT")
        if target["provider_campaign_id"] != plan.campaign_id:
            raise RecoveryError("RECOVERY_ITEM_INCONSISTENT")
        status = str(item["status"])
        sentinel = item["error_code"] == _RECOVERY_ACCOUNTED_ACCEPTANCE
        if sentinel:
            if not (
                status == "sent"
                and item["completed_at"] is not None
                and target["status"] == "sent"
                and target["instantly_accepted_at"] is not None
                and target["send_request_id"] in (None, request_id)
            ):
                raise RecoveryError("RECOVERY_ITEM_INCONSISTENT")
        elif status in ("queued", "running", "verification_pending"):
            if not (
                target["status"] == "approved"
                and target["send_request_id"] == request_id
                and int(item["expected_version"]) == int(target["version"])
                and item["instantly_id"]
                and target["provider_campaign_id"]
            ):
                raise RecoveryError("RECOVERY_ITEM_INCONSISTENT")
        elif status == "sent":
            if target["status"] != "sent" or item["completed_at"] is None:
                raise RecoveryError("RECOVERY_ITEM_INCONSISTENT")
        elif status == "failed":
            if (
                target["status"] == "sent"
                or target["send_request_id"] == request_id
                or not item["error_code"]
            ):
                raise RecoveryError("RECOVERY_ITEM_INCONSISTENT")
        else:
            raise RecoveryError("RECOVERY_ITEM_INCONSISTENT")
        if status in ("sent", "failed"):
            processed += 1
        if status == "sent":
            sent += 1
        if status == "failed":
            failed += 1

    request = plan.request
    snapshot_processed = int(request["processed_count"])
    snapshot_sent = int(request["sent_count"])
    snapshot_failed = int(request["failed_count"])
    snapshot_consistent = snapshot_processed == snapshot_sent + snapshot_failed
    snapshot_is_current = (
        snapshot_processed == processed and snapshot_sent == sent and snapshot_failed == failed
    )
    snapshot_is_prior = (
        request["status"] in ("running", "waiting")
        and snapshot_consistent
        and snapshot_processed <= processed
        and snapshot_sent <= sent
        and snapshot_failed <= failed
    )
    if not snapshot_is_current and not snapshot_is_prior:
        raise RecoveryError("RECOVERY_ITEM_INCONSISTENT")
    if processed == len(items):
        expected_status = "completed" if failed == 0 else ("partial" if sent else "failed")
        activation_waiting = (
            request["status"] == "waiting"
            and request["next_attempt_at"] is not None
            and bool(request["error"])
        )
        terminal_crash_replay = request["status"] == "running" and snapshot_is_prior
        if (
            request["status"] != expected_status
            and not activation_waiting
            and not terminal_crash_replay
        ):
            raise RecoveryError("RECOVERY_ITEM_INCONSISTENT")
    elif request["status"] not in ("queued", "running", "waiting"):
        raise RecoveryError("RECOVERY_ITEM_INCONSISTENT")
    return len(items)


def recover_request(
    engine: Engine,
    *,
    request_id: UUID | str,
    dry_run: bool,
    now: dt.datetime | None = None,
) -> RecoveryPreview:
    """Preview or atomically reconstruct an interrupted legacy request.

    Every recoverable target must already be bound to one campaign and one
    provider lead.  This routine contains no provider dependency and performs
    no write transaction for a dry run.
    """

    normalized_request_id = str(UUID(str(request_id)))
    if dry_run:
        with engine.connect() as connection:
            plan = _rows_for_recovery(connection, normalized_request_id, lock=False)
            _validate_existing_items(connection, plan)
            return plan.preview

    now = now or dt.datetime.now(dt.UTC)
    if now.tzinfo is None:
        raise ValueError("recovery clock must be timezone-aware")
    with engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        plan = _rows_for_recovery(connection, normalized_request_id, lock=True)
        item_count = _validate_existing_items(connection, plan)
        if item_count:
            return plan.preview

        sent_count = plan.preview.already_sent_count
        connection.execute(
            sa.update(prospect_send_request)
            .where(prospect_send_request.c.request_id == normalized_request_id)
            .values(
                reserved_count=len(plan.target_ids),
                processed_count=sent_count,
                sent_count=sent_count,
                failed_count=0,
                status="queued",
                provider_campaign_id=plan.campaign_id,
                next_attempt_at=now,
                attempt_count=0,
                claimed_by=None,
                lease_id=None,
                lease_expires_at=None,
                result={
                    **(plan.request["result"] if isinstance(plan.request["result"], dict) else {}),
                    "recovery": {"state": "reconstructed"},
                },
                error=None,
                started_at=None,
                updated_at=now,
                completed_at=None,
            )
        )
        connection.execute(
            sa.insert(prospect_send_item),
            [
                {
                    "request_id": normalized_request_id,
                    "target_id": target_id,
                    "position": position,
                    "expected_version": int(plan.targets[target_id]["version"]),
                    "status": "sent" if target_id in plan.sent_target_ids else "queued",
                    "instantly_id": plan.targets[target_id]["instantly_id"],
                    "verification_status": 1 if target_id in plan.sent_target_ids else None,
                    "error_code": (
                        _RECOVERY_ACCOUNTED_ACCEPTANCE
                        if target_id in plan.sent_target_ids
                        else None
                    ),
                    "next_attempt_at": now,
                    "attempt_count": 0,
                    "created_at": now,
                    "updated_at": now,
                    "completed_at": (
                        plan.targets[target_id]["instantly_accepted_at"] or now
                        if target_id in plan.sent_target_ids
                        else None
                    ),
                }
                for position, target_id in enumerate(plan.target_ids)
            ],
        )
        if plan.preview.approved_count:
            reserved = connection.execute(
                sa.update(prospect_target)
                .where(
                    prospect_target.c.target_id.in_(
                        tuple(
                            target_id
                            for target_id in plan.target_ids
                            if target_id not in plan.sent_target_ids
                        )
                    ),
                    prospect_target.c.status == "approved",
                    prospect_target.c.send_request_id.is_(None),
                )
                .values(send_request_id=normalized_request_id, updated_at=now)
            )
            if reserved.rowcount != plan.preview.approved_count:
                raise RecoveryError("RECOVERY_TARGET_CHANGED")
    return plan.preview


def _target_ids(engine: Engine, request_id: str) -> list[str]:
    with engine.connect() as connection:
        return list(_rows_for_recovery(connection, request_id, lock=False).target_ids)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ValueError("invalid prospect recovery arguments")


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as error:
        raise argparse.ArgumentTypeError("request id must be a UUID") from error


def _parser() -> _SafeArgumentParser:
    parser = _SafeArgumentParser(
        prog="python -m signals.prospection_actions.recovery", add_help=False
    )
    parser.add_argument("request_id", type=_uuid)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser


def _summary(
    *, status: str, preview: RecoveryPreview | None = None, target_ids: list[str] | None = None
) -> str:
    payload: dict[str, object] = {"status": status}
    if preview is not None:
        payload.update(
            {
                "request_id": preview.request_id,
                "approved_count": preview.approved_count,
                "already_sent_count": preview.already_sent_count,
                "existing_lead_count": preview.existing_lead_count,
                "create_lead_count": preview.create_lead_count,
                "target_ids": target_ids or [],
            }
        )
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def main(
    argv: list[str] | None = None,
    *,
    read_engine_factory: Callable[[], Engine] | None = None,
    write_engine_factory: Callable[[], Engine] | None = None,
) -> int:
    """Run exactly one local recovery preview or apply action."""

    try:
        arguments = _parser().parse_args(argv)
    except (SystemExit, ValueError):
        print(_summary(status="configuration_invalid"))
        return 2

    engine: Engine | None = None
    try:
        if arguments.dry_run:
            if read_engine_factory is None:
                from signals.founder_api.database import create_founder_database_engine

                read_engine_factory = create_founder_database_engine
            engine = read_engine_factory()
        else:
            if write_engine_factory is None:
                from signals.founder_api.database import create_founder_write_database_engine

                write_engine_factory = create_founder_write_database_engine
            engine = write_engine_factory()
        preview = recover_request(
            engine, request_id=arguments.request_id, dry_run=arguments.dry_run
        )
        print(
            _summary(
                status="dry_run" if arguments.dry_run else "applied",
                preview=preview,
                target_ids=_target_ids(engine, arguments.request_id),
            )
        )
        return 0
    except (RecoveryError, RuntimeError, sa.exc.SQLAlchemyError, ValueError):
        print(_summary(status="recovery_failed"))
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":  # pragma: no cover - process boundary
    raise SystemExit(main())
