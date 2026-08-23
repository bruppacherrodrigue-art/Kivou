"""Explicit one-shot internal operations CLI; never autostarts acquisition work."""

from __future__ import annotations

import argparse
import datetime as dt
import re

from signals.api.config import resolve_acquisition_environment
from signals.operations.safety_controller import SafetyController
from signals.operations.service import OperationsReadService
from signals.persistence.database import create_database_engine


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m signals.operations")
    parser.add_argument(
        "--database-url",
        default=None,
        help="explicit database URL; otherwise KIVOU_DATABASE_URL is required",
    )
    parser.add_argument("--now", default=None, help="timezone-aware ISO 8601 instant")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health", help="read bounded local operational health")
    commands.add_parser("readiness", help="read H-A…H-G autonomy readiness")
    commands.add_parser("incidents", help="list bounded operational incident refs")
    commands.add_parser("dead-letters", help="list bounded dead-letter refs")
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


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    now = _now(arguments.now)
    engine = create_database_engine(arguments.database_url)
    service = OperationsReadService(
        engine, environment_identity=resolve_acquisition_environment()
    )
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
    reason = arguments.reason_code.strip().upper()
    if re.fullmatch(r"[A-Z0-9][A-Z0-9_:-]{0,99}", reason) is None:
        raise ValueError("reason code must be a bounded operational code")
    control = SafetyController(engine).critical_stop(at=now, reason_codes=(reason,))
    print(
        f"acquisition_ops control_revision={control.control_revision} "
        f"autonomy={control.autonomy_mode.value} kill_switch=true read_only=true"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())
