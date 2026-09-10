"""Sanitized process boundary for the bounded acquisition runtime."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import signal
import sys
from collections.abc import Callable

import sqlalchemy as sa

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeDependencyState,
    RuntimeRunResult,
    RuntimeStageDependency,
)
from signals.acquisition_runtime.events import configure_acquisition_runtime_logging
from signals.acquisition_runtime.shadow_store import latest_shadow_mails
from signals.acquisition_runtime.store import AcquisitionRuntimeStore
from signals.persistence.database import create_database_engine

RuntimeExecutor = Callable[[bool], RuntimeRunResult]
RuntimeDependencyExecutor = Callable[[], tuple[RuntimeStageDependency, ...]]
_EXPECTED_DEPENDENCY_COUNT = 11


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        self.exit(2, "status=INVALID_ARGUMENTS\n")


def _parser() -> _SafeArgumentParser:
    parser = _SafeArgumentParser(prog="python -m signals.acquisition_runtime")
    commands = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=_SafeArgumentParser,
    )
    run_once = commands.add_parser(
        "run-once",
        help="execute one bounded durable acquisition cycle",
    )
    run_once.add_argument(
        "--allow-qa-provider-mutations",
        action="store_true",
        help="manual staging-only gate; rejected in production",
    )
    commands.add_parser(
        "check-dependencies",
        help="run fresh read-only production dependency probes",
    )
    review = commands.add_parser("review", help="render recent shadow mails as Markdown")
    review.add_argument("--last", type=int, default=20)
    stats = commands.add_parser("stats", help="show bounded shadow runtime counters")
    stats.add_argument("--since", default="24h")
    abandon = commands.add_parser("abandon", help="suppress one blocked cycle")
    abandon.add_argument("cycle_id")
    abandon.add_argument("--reason", required=True)
    return parser


def _default_execute(allow_qa_provider_mutations: bool) -> RuntimeRunResult:
    from signals.acquisition_runtime.composition import execute_runtime_run_once

    return execute_runtime_run_once(allow_qa_provider_mutations=allow_qa_provider_mutations)


def _default_check_dependencies() -> tuple[RuntimeStageDependency, ...]:
    from signals.acquisition_runtime.execution import (
        execute_runtime_dependency_check,
    )

    return execute_runtime_dependency_check()


def _all_dependencies_ready(
    dependencies: tuple[RuntimeStageDependency, ...],
) -> bool:
    expected_stages = tuple(AcquisitionRuntimeStage)
    return (
        len(expected_stages) == _EXPECTED_DEPENDENCY_COUNT
        and tuple(item.stage for item in dependencies) == expected_stages
        and all(item.status is RuntimeDependencyState.READY for item in dependencies)
    )


def _summary(result: RuntimeRunResult) -> str:
    parts = [f"status={result.status.value}"]
    if result.cycle_ref is not None:
        parts.append(f"cycle_ref={result.cycle_ref}")
    if result.stage is not None:
        parts.append(f"stage={result.stage.value}")
    if result.reason_code is not None:
        parts.append(f"reason={result.reason_code}")
    return " ".join(parts)


def main(
    argv: list[str] | None = None,
    *,
    execute: RuntimeExecutor | None = None,
    check_dependencies: RuntimeDependencyExecutor | None = None,
) -> int:
    configure_acquisition_runtime_logging()
    arguments = _parser().parse_args(argv)
    if arguments.command == "review":
        try:
            records = latest_shadow_mails(
                create_database_engine(), limit=max(1, min(arguments.last, 20))
            )
        except (OSError, sa.exc.SQLAlchemyError, ValueError):
            print("status=REVIEW_UNAVAILABLE")
            return 1
        print("# PR7 shadow — relecture\n")
        for index, record in enumerate(records, 1):
            print(f"## {index}. {record.company_name} — {record.contact_role}")
            print(f"E-mail : {record.masked_email}\n")
            print(f"Signal : {record.opportunity_key}\n")
            print(f"Requêtes SIRENE/Apollo : `{record.apollo_query}`\n")
            print("### Texte\n")
            print(record.body)
            print("\n---\n")
        return 0
    if arguments.command == "stats":
        try:
            engine = create_database_engine()
            with engine.connect() as connection:
                from signals.persistence.schema import acquisition_runtime_cycle

                count = connection.execute(
                    sa.select(sa.func.count()).select_from(acquisition_runtime_cycle)
                ).scalar_one()
            print(f"cycles={count} mails_generated={len(latest_shadow_mails(engine, limit=20))}")
        except (OSError, sa.exc.SQLAlchemyError, ValueError):
            print("status=STATS_UNAVAILABLE")
            return 1
        return 0
    if arguments.command == "abandon":
        try:
            changed = AcquisitionRuntimeStore(create_database_engine()).abandon_cycle(
                arguments.cycle_id,
                reason=arguments.reason,
                at=dt.datetime.now(dt.UTC),
            )
        except (KeyError, OSError, sa.exc.SQLAlchemyError, ValueError):
            print("status=ABANDON_UNAVAILABLE")
            return 1
        print(
            f"status=ABANDONED cycle_ref={arguments.cycle_id} changed={'yes' if changed else 'no'}"
        )
        return 0
    if arguments.command == "check-dependencies":
        check = check_dependencies or _default_check_dependencies
        try:
            dependencies = check()
            ready = _all_dependencies_ready(dependencies)
        except Exception:  # noqa: BLE001 - no provider/config detail crosses the CLI
            ready = False
        if not ready:
            print("status=NOT_READY")
            return 1
        print(f"status=READY dependency_count={_EXPECTED_DEPENDENCY_COUNT}")
        return 0

    assert arguments.command == "run-once"
    if bool(arguments.allow_qa_provider_mutations) and (
        (os.environ.get("KIVOU_ACQUISITION_ENVIRONMENT") or "").strip().upper() == "PRODUCTION"
    ):
        print("status=INVALID_ARGUMENTS", file=sys.stderr)
        return 2
    run = execute or _default_execute

    def interrupt_runtime(_signum: int, _frame: object) -> None:
        raise InterruptedError("acquisition runtime termination requested")

    previous_sigterm = signal.signal(signal.SIGTERM, interrupt_runtime)
    try:
        try:
            result = run(bool(arguments.allow_qa_provider_mutations))
        except (RuntimeError, ValueError):
            print("status=CONFIGURATION_INVALID", file=sys.stderr)
            return 2
        except Exception:  # noqa: BLE001 - no provider/config detail crosses the CLI
            print("status=RUNTIME_FAILED", file=sys.stderr)
            return 1
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
    print(_summary(result))
    return result.exit_code


__all__ = ["main"]
