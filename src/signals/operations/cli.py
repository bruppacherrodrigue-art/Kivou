"""Explicit one-shot internal operations CLI; never autostarts acquisition work."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from collections.abc import Callable

import sqlalchemy as sa

from signals.acquisition_runtime.authorization import (
    AcquisitionRuntimeApprovalStore,
    RuntimeApprovalStatus,
)
from signals.acquisition_runtime.config import load_runtime_config
from signals.api.config import resolve_acquisition_environment
from signals.operations.qa_policy_window import (
    MAXIMUM_QA_WINDOW,
    RuntimeQaPolicyWindowController,
)
from signals.operations.safety_controller import SafetyController
from signals.operations.service import OperationsReadService
from signals.persistence.database import create_database_engine


class _OpaqueMutationArguments(ValueError):
    """A parser failure whose original values must never cross the CLI boundary."""


class _OpaqueMutationParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise _OpaqueMutationArguments("invalid mutation arguments")


def _parser(*, opaque_errors: bool = False) -> argparse.ArgumentParser:
    parser_type = _OpaqueMutationParser if opaque_errors else argparse.ArgumentParser
    parser = parser_type(prog="python -m signals.operations")
    parser.add_argument(
        "--database-url",
        default=None,
        help="explicit database URL; otherwise KIVOU_DATABASE_URL is required",
    )
    parser.add_argument("--now", default=None, help="timezone-aware ISO 8601 instant")
    commands = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=parser_type,
    )
    commands.add_parser("health", help="read bounded local operational health")
    commands.add_parser("readiness", help="read H-A…H-G autonomy readiness")
    commands.add_parser("incidents", help="list bounded operational incident refs")
    commands.add_parser("dead-letters", help="list bounded dead-letter refs")
    commands.add_parser(
        "list-runtime-approvals",
        help="list bounded pending runtime approval metadata",
    )
    approve = commands.add_parser(
        "approve-runtime-approval",
        help="approve one exact durable runtime request",
    )
    approve.add_argument("--approval-id", required=True)
    approve.add_argument("--actor-ref", required=True)
    open_window = commands.add_parser(
        "open-runtime-qa-policy-window",
        help="append one bounded STAGING-only ASSISTED QA authority",
    )
    open_window.add_argument("--duration-seconds", required=True)
    open_window.add_argument("--actor-ref", required=True)
    open_window.add_argument("--reason-code", required=True)
    close_window = commands.add_parser(
        "close-runtime-qa-policy-window",
        help="append safe SHADOW authority after a controlled QA cycle",
    )
    close_window.add_argument("--actor-ref", required=True)
    close_window.add_argument("--reason-code", required=True)
    stop = commands.add_parser(
        "activate-kill-switch",
        help="append SHADOW + kill-switch + READ ONLY Policy authority",
    )
    stop.add_argument("--reason-code", required=True)
    return parser


def _now(raw: str | None) -> dt.datetime:
    value = dt.datetime.fromisoformat(raw) if raw else dt.datetime.now(dt.UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("--now must be timezone-aware")
    return value.astimezone(dt.UTC)


def _system_clock() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


_MUTATING_COMMANDS = frozenset(
    {
        "approve-runtime-approval",
        "open-runtime-qa-policy-window",
        "close-runtime-qa-policy-window",
        "activate-kill-switch",
    }
)


def _mutation_error_label(command: str) -> str:
    if command in {
        "open-runtime-qa-policy-window",
        "close-runtime-qa-policy-window",
    }:
        return "runtime_qa_policy_window_invalid"
    if command == "approve-runtime-approval":
        return "runtime_approval_invalid"
    return "acquisition_kill_switch_invalid"


def _forbidden_mutation_authority(arguments: list[str]) -> str | None:
    command = _mutation_command(arguments)
    if command is None:
        return None
    if any(
        item in {"--database-url", "--now"} or item.startswith(("--database-url=", "--now="))
        for item in arguments
    ):
        return _mutation_error_label(command)
    return None


def _mutation_command(arguments: list[str]) -> str | None:
    return next((item for item in arguments if item in _MUTATING_COMMANDS), None)


def _server_instant(clock: Callable[[], dt.datetime]) -> dt.datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("server clock must be timezone-aware")
    return value.astimezone(dt.UTC)


def _run_mutation(arguments: argparse.Namespace, *, clock: Callable[[], dt.datetime]) -> int:
    error_label = _mutation_error_label(arguments.command)
    try:
        if arguments.database_url is not None or arguments.now is not None:
            raise ValueError("operator database and clock authority are forbidden")
        now = _server_instant(clock)
        engine = create_database_engine()
        if arguments.command == "approve-runtime-approval":
            approval = AcquisitionRuntimeApprovalStore(engine).approve(
                arguments.approval_id,
                approved_by_actor_ref=arguments.actor_ref,
                at=now,
            )
            print(
                f"runtime_approval approval_id={approval.approval_id} "
                f"stage={approval.binding.stage.value} status={approval.status.value}"
            )
            return 0
        if arguments.command == "activate-kill-switch":
            reason = arguments.reason_code.strip().upper()
            if re.fullmatch(r"[A-Z0-9][A-Z0-9_:-]{0,99}", reason) is None:
                raise ValueError("reason code must be a bounded operational code")
            control = SafetyController(engine).critical_stop(
                at=now,
                reason_codes=(reason,),
            )
            print(
                f"acquisition_ops control_revision={control.control_revision} "
                f"autonomy={control.autonomy_mode.value} "
                "kill_switch=true read_only=true"
            )
            return 0

        runtime_config = load_runtime_config()
        controller = RuntimeQaPolicyWindowController(engine)
        if arguments.command == "open-runtime-qa-policy-window":
            duration_seconds = int(arguments.duration_seconds)
            if not 1 <= duration_seconds <= int(MAXIMUM_QA_WINDOW.total_seconds()):
                raise ValueError("runtime QA duration is invalid")
            control = controller.open(
                at=now,
                expires_at=now + dt.timedelta(seconds=duration_seconds),
                actor_ref=arguments.actor_ref,
                reason_code=arguments.reason_code,
                runtime_config=runtime_config,
            )
            print(
                "runtime_qa_policy_window status=OPEN "
                f"control_revision={control.control_revision} "
                "autonomy=ASSISTED read_only=false kill_switch=false"
            )
        else:
            control = controller.close(
                at=now,
                actor_ref=arguments.actor_ref,
                reason_code=arguments.reason_code,
                runtime_config=runtime_config,
            )
            print(
                "runtime_qa_policy_window status=CLOSED "
                f"control_revision={control.control_revision} "
                "autonomy=SHADOW read_only=true kill_switch=false"
            )
        return 0
    except (
        AttributeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        sa.exc.SQLAlchemyError,
    ):
        # This is the mutation security boundary: configuration, clock and DB
        # exceptions may carry private values, so only one fixed code crosses it.
        print(error_label, file=sys.stderr)
        return 2


def main(
    argv: list[str] | None = None,
    *,
    clock: Callable[[], dt.datetime] = _system_clock,
) -> int:
    raw_arguments = list(argv) if argv is not None else sys.argv[1:]
    mutation_command = _mutation_command(raw_arguments)
    authority_error = _forbidden_mutation_authority(raw_arguments)
    if authority_error is not None:
        print(authority_error, file=sys.stderr)
        return 2
    try:
        arguments = _parser(opaque_errors=mutation_command is not None).parse_args(raw_arguments)
    except _OpaqueMutationArguments:
        print(_mutation_error_label(mutation_command or ""), file=sys.stderr)
        return 2
    if arguments.command in _MUTATING_COMMANDS:
        return _run_mutation(arguments, clock=clock)
    now = _now(arguments.now)
    engine = create_database_engine(arguments.database_url)
    environment = resolve_acquisition_environment()
    service = OperationsReadService(engine, environment_identity=environment)
    if arguments.command == "list-runtime-approvals":
        approvals = AcquisitionRuntimeApprovalStore(engine).list_approvals(
            status=RuntimeApprovalStatus.PENDING,
        )
        print(f"runtime_approvals pending={len(approvals)}")
        for approval in approvals:
            print(
                f"approval_id={approval.approval_id} "
                f"stage={approval.binding.stage.value} "
                f"command={approval.binding.command} "
                f"target_ref={approval.binding.target_ref} "
                f"action_fingerprint={approval.binding.action_fingerprint} "
                f"policy_snapshot_id={approval.binding.policy_snapshot_id} "
                f"control_revision={approval.binding.control_revision} "
                f"status={approval.status.value} "
                f"expires_at={approval.binding.expires_at.isoformat()}"
            )
        return 0
    if arguments.command == "health":
        health = service.health(observed_at=now)
        print(
            f"acquisition_ops health status={health.status.value} "
            f"reasons={','.join(health.reason_codes) or 'none'}"
        )
        return 0 if health.status.value == "READY" else 1
    if arguments.command == "readiness":
        readiness = service.readiness(evaluated_at=now)
        print(
            f"acquisition_ops readiness highest_safe_mode={readiness.highest_safe_mode.value} "
            f"blockers={','.join(readiness.blockers) or 'none'}"
        )
        return 0
    if arguments.command == "incidents":
        items = service.incidents(limit=100)
        print(f"acquisition_ops incidents count={len(items)}")
        for item in items:
            print(
                f"incident_ref={item['incident_ref']} state={item['state']} "
                f"severity={item['severity']} scope={item['scope_type']}:{item['scope_ref']}"
            )
        return 0
    if arguments.command == "dead-letters":
        items = service.dead_letters(limit=100)
        print(f"acquisition_ops dead_letters count={len(items)}")
        for item in items:
            print(
                f"dead_letter_ref={item['dead_letter_ref']} status={item['status']} "
                f"work_type={item['work_type']}"
            )
        return 0
    raise AssertionError("unreachable operations command")


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())
