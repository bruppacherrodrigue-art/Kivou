"""One-shot Kivou-owned CLI for Hermes SHADOW supervision."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from signals.supervisor.contracts import BudgetEnvelope, SupervisorContext
from signals.supervisor.hermes import HermesSupervisorAdapter
from signals.supervisor.registry import ALLOWED_COMMANDS
from signals.supervisor.runtime import HealthState, SupervisorError, SupervisorSettings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m signals.supervisor")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health", help="check the isolated Hermes boundary")
    shadow = commands.add_parser("shadow", help="produce one advisory SHADOW plan")
    shadow.add_argument("--context", type=Path, help="strict bounded SupervisorContext JSON")
    return parser


def _built_in_context() -> SupervisorContext:
    return SupervisorContext(
        current_time=dt.datetime.now(dt.UTC),
        runtime_mode="SHADOW",
        policy_version="policy-placeholder-v1",
        budget=BudgetEnvelope(currency="CHF", maximum_cycle_cost=Decimal("1")),
        available_commands=tuple(sorted(ALLOWED_COMMANDS)),
    )


def _load_context(path: Path | None) -> SupervisorContext:
    if path is None:
        return _built_in_context()
    parsed = json.loads(path.read_text(encoding="utf-8"))
    return SupervisorContext.model_validate(parsed)


def _instant(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _health(adapter: HermesSupervisorAdapter) -> int:
    health = adapter.health()
    version = health.hermes_version or "none"
    print(
        f"supervisor=hermes state={health.state.value} version={version} "
        f"executable_tools={len(health.executable_tools)}"
    )
    return 0 if health.state is HealthState.AVAILABLE else 1


def _shadow(adapter: HermesSupervisorAdapter, context_path: Path | None) -> int:
    try:
        context = _load_context(context_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError):
        print("supervisor=hermes mode=SHADOW status=error category=invalid_context")
        return 2
    try:
        plan = adapter.plan(context)
    except SupervisorError as exc:
        print(f"supervisor=hermes mode=SHADOW status=error category={exc.category}")
        return 1
    except Exception:  # noqa: BLE001 - CLI boundary never reflects runtime details
        print("supervisor=hermes mode=SHADOW status=error category=unavailable")
        return 1
    print(
        f"supervisor=hermes mode=SHADOW plan_id={plan.plan_id} "
        f"actions={len(plan.proposed_actions)} estimated_cost={plan.estimated_cost} "
        f"next_review_at={_instant(plan.next_review_at)} status=advisory"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    adapter = HermesSupervisorAdapter(SupervisorSettings.from_environ())
    if arguments.command == "health":
        return _health(adapter)
    return _shadow(adapter, arguments.context)
