"""Safe SHADOW command for Chief of Staff report generation."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa

from signals.chief_of_staff.config import (
    ChiefOfStaffConfigurationState,
    chief_of_staff_config_from_environment,
)
from signals.chief_of_staff.hermes import ChiefOfStaffHermesAdapter
from signals.chief_of_staff.service import ChiefOfStaffService
from signals.chief_of_staff.store import ChiefOfStaffReportStore
from signals.company_research.instance_lock import InstanceAlreadyRunning, exclusive_instance_lock
from signals.founder_api.read_models import FounderReadService
from signals.model_runtime.budget import ModelBudgetStore
from signals.persistence.database import create_database_engine
from signals.supervisor.runtime import SupervisorError, SupervisorSettings

DEFAULT_LOCK_FILE = "/srv/kivou/run/chief-of-staff.lock"


def _instant(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--at must be an ISO 8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--at must include a timezone")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m signals.chief_of_staff")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate", help="generate one SHADOW briefing")
    generate.add_argument(
        "--cadence", choices=("daily", "weekly", "on-demand"), required=True
    )
    generate.add_argument("--at", type=_instant)
    generate.add_argument(
        "--persist",
        action="store_true",
        help="append the validated report; the default is a dry run",
    )
    generate.add_argument(
        "--lock-file",
        default=os.environ.get("KIVOU_CHIEF_OF_STAFF_LOCK_FILE", DEFAULT_LOCK_FILE),
    )
    return parser


def build_service_for_tests(
    *,
    engine: sa.Engine,
    overview_reader: object,
    generator: object,
    clock,
) -> ChiefOfStaffService:
    return ChiefOfStaffService(
        overview_reader=overview_reader,  # type: ignore[arg-type]
        generator=generator,  # type: ignore[arg-type]
        store=ChiefOfStaffReportStore(engine),
        clock=clock,
    )


def _runtime_service(*, at: dt.datetime | None = None) -> ChiefOfStaffService:
    engine = create_database_engine()
    model = chief_of_staff_config_from_environment()
    if model.state is not ChiefOfStaffConfigurationState.CONFIGURED or model.route is None:
        raise RuntimeError("Chief of Staff model is NOT_CONFIGURED")
    settings = SupervisorSettings.from_environ()
    budget_store = (
        ModelBudgetStore(engine, clock=lambda: at)
        if at is not None
        else ModelBudgetStore(engine)
    )
    generator = ChiefOfStaffHermesAdapter(
        settings,
        model_route=model.route,
        budget_store=budget_store,
        batch_id=f"chief-{(at or dt.datetime.now(dt.UTC)).date().isoformat()}",
    )
    return ChiefOfStaffService(
        overview_reader=FounderReadService(engine),
        generator=generator,
        store=ChiefOfStaffReportStore(engine),
    )


def main(arguments: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(arguments)
    cadence = args.cadence.replace("-", "_").upper()
    try:
        lock_path = Path(args.lock_file)
        with exclusive_instance_lock(lock_path):
            service = _runtime_service(at=args.at)
            outcome = service.generate(
                cadence=cadence,
                at=args.at,
                persist=bool(args.persist),
            )
    except InstanceAlreadyRunning:
        print(json.dumps({"status": "ALREADY_RUNNING"}, sort_keys=True))
        return 3
    except (RuntimeError, ValueError, SupervisorError) as error:
        print(json.dumps({"status": "FAILED_CLOSED", "category": type(error).__name__}))
        return 2
    print(
        json.dumps(
            {
                "status": "VALIDATED_SHADOW",
                "report_ref": outcome.report.report_ref,
                "executive_status": outcome.report.executive_status,
                "cadence": outcome.report.cadence,
                "persisted": outcome.persisted,
                "inserted": outcome.inserted,
                "fact_ref_count": len(outcome.context.facts),
                "model": outcome.model,
            },
            sort_keys=True,
        )
    )
    return 0


__all__ = ["DEFAULT_LOCK_FILE", "build_service_for_tests", "main"]
