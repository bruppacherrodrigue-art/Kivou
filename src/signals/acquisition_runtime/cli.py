"""Sanitized process boundary for one bounded acquisition runtime cycle."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from signals.acquisition_runtime.contracts import RuntimeRunResult
from signals.acquisition_runtime.events import configure_acquisition_runtime_logging

RuntimeExecutor = Callable[[bool], RuntimeRunResult]


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
        help="manual staging-only gate; durable Policy and approval still apply",
    )
    return parser


def _default_execute(allow_qa_provider_mutations: bool) -> RuntimeRunResult:
    from signals.acquisition_runtime.composition import execute_runtime_run_once

    return execute_runtime_run_once(
        allow_qa_provider_mutations=allow_qa_provider_mutations
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
) -> int:
    configure_acquisition_runtime_logging()
    arguments = _parser().parse_args(argv)
    assert arguments.command == "run-once"
    run = execute or _default_execute
    try:
        result = run(bool(arguments.allow_qa_provider_mutations))
    except (RuntimeError, ValueError):
        print("status=CONFIGURATION_INVALID", file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 - no provider/config detail crosses the CLI
        print("status=RUNTIME_FAILED", file=sys.stderr)
        return 1
    print(_summary(result))
    return result.exit_code


__all__ = ["main"]
