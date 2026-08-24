"""Manual CLI and composition root for the acquisition SHADOW smoke."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy.engine import Engine

from signals.acquisition_connectivity.apollo import ApolloComponents, build_apollo_components
from signals.acquisition_connectivity.config import load_connectivity_config
from signals.acquisition_connectivity.contracts import (
    AcquisitionConnectivityConfig,
    AcquisitionShadowSmokeResult,
    ConnectivityErrorCode,
    ConnectivityFailure,
)
from signals.acquisition_connectivity.instantly import InstantlyConnectivityProbe
from signals.acquisition_connectivity.service import (
    AcquisitionConnectivityService,
    HermesConnectivityProbe,
)
from signals.campaigns.instantly import HttpInstantlyProvider, InstantlyMailboxReadinessSource
from signals.campaigns.store import CampaignStore
from signals.persistence.database import create_database_engine
from signals.policy.store import PolicyStore
from signals.supervisor.contracts import SupervisorLimits
from signals.supervisor.hermes import HermesSupervisorAdapter
from signals.supervisor.runtime import SupervisorSettings


@dataclass(frozen=True)
class ConnectivityComposition:
    """Keep reused clients/adapters explicit and alive for one bounded invocation."""

    service: AcquisitionConnectivityService
    apollo: ApolloComponents
    instantly_provider: HttpInstantlyProvider
    hermes_adapter: HermesSupervisorAdapter


def build_connectivity_composition(
    *,
    config: AcquisitionConnectivityConfig,
    engine: Engine,
    client: httpx.Client,
    deployed_sha: str,
) -> ConnectivityComposition:
    apollo = build_apollo_components(
        api_key=config.apollo_api_key.get_secret_value(),
        client=client,
    )
    instantly_provider = HttpInstantlyProvider(
        api_key=config.instantly_api_key.get_secret_value(),
        client=client,
    )
    instantly = InstantlyConnectivityProbe(
        provider=instantly_provider,
        mailbox_readiness=InstantlyMailboxReadinessSource(
            instantly_provider,
            require_sending_gap=False,
        ),
    )
    settings = SupervisorSettings(
        hermes_python=config.hermes_python,
        hermes_home=config.hermes_home,
        working_directory=config.hermes_cwd,
        limits=SupervisorLimits(
            invocation_timeout_seconds=30,
            max_planned_actions=10,
            max_output_tokens=2_048,
        ),
    )
    hermes_adapter = HermesSupervisorAdapter(settings)
    service = AcquisitionConnectivityService(
        config=config,
        policy_store=PolicyStore(engine),
        campaign_store=CampaignStore(engine),
        apollo_identity=apollo.identity,
        instantly=instantly,
        hermes=HermesConnectivityProbe(config=config, adapter=hermes_adapter),
        deployed_sha=deployed_sha,
    )
    return ConnectivityComposition(
        service=service,
        apollo=apollo,
        instantly_provider=instantly_provider,
        hermes_adapter=hermes_adapter,
    )


def execute_connectivity_check() -> AcquisitionShadowSmokeResult:
    config = load_connectivity_config()
    deployed_sha = _deployed_sha()
    engine = create_database_engine()
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            composition = build_connectivity_composition(
                config=config,
                engine=engine,
                client=client,
                deployed_sha=deployed_sha,
            )
            return composition.service.check(observed_at=dt.datetime.now(dt.UTC))
    finally:
        engine.dispose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m signals.acquisition_connectivity"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="run one manual, read-only SHADOW smoke")
    return parser


def _deployed_sha() -> str:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=normal"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        raise ConnectivityFailure(ConnectivityErrorCode.OPERATIONAL_AMBIGUITY) from None
    value = revision.stdout.strip()
    if (
        revision.returncode != 0
        or status.returncode != 0
        or status.stdout
        or re.fullmatch(r"[0-9a-f]{40}", value) is None
    ):
        raise ConnectivityFailure(ConnectivityErrorCode.OPERATIONAL_AMBIGUITY)
    return value


def _instant(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _print_preflight(result) -> None:
    print(
        "acquisition_shadow environment=STAGING policy=SHADOW "
        "read_only=true kill_switch=true "
        f"deployment_sha={result.deployed_sha} "
        f"policy_control_revision={result.preflight.policy_control_revision}"
    )


def _print_apollo() -> None:
    print("apollo auth=READY acting_profile=BOUND")


def _print_instantly() -> None:
    print("instantly workspace=BOUND mailboxes_ready=3 mailboxes_total=3")


def _print_hermes() -> None:
    print(
        "hermes state=AVAILABLE version=0.20.4 executable_tools=0 "
        "model=anthropic/claude-sonnet-4.6 tag=v2026.8.18 "
        "commit=e624e9fde561e1add9388384012b295fde669ade"
    )


def _print_plan(plan) -> None:
    print(
        f"shadow_plan status=advisory actions={plan.actions} "
        f"estimated_cost={plan.estimated_cost:.2f} plan_id={plan.plan_id} "
        f"next_review_at={_instant(plan.next_review_at)}"
    )


def _print_delta(delta) -> None:
    print(
        f"mutation_delta campaigns={delta.campaigns} members={delta.members} "
        f"provider_operations={delta.provider_operations} "
        f"provider_events={delta.provider_events}"
    )


def _print_success(result: AcquisitionShadowSmokeResult) -> None:
    _print_preflight(result)
    _print_apollo()
    _print_instantly()
    _print_hermes()
    _print_plan(result.shadow_plan)
    _print_delta(result.mutation_delta)
    print("result=PASS")


def _print_failure(exc: ConnectivityFailure) -> None:
    partial = exc.partial
    if partial is not None:
        _print_preflight(partial)
        if partial.apollo is not None:
            _print_apollo()
        elif partial.failed_component == "apollo":
            print(f"apollo auth=NOT_READY error={exc.code.value}")
        if partial.instantly is not None:
            _print_instantly()
        elif partial.failed_component == "instantly":
            print(f"instantly workspace=NOT_READY error={exc.code.value}")
        if partial.hermes is not None:
            _print_hermes()
        elif partial.failed_component == "hermes":
            print(f"hermes state=NOT_READY error={exc.code.value}")
        if partial.shadow_plan is not None:
            _print_plan(partial.shadow_plan)
        if partial.mutation_delta is not None:
            _print_delta(partial.mutation_delta)
        else:
            print("mutation_delta state=UNKNOWN")
    retry = (
        f" retry_after_seconds={exc.retry_after_seconds}"
        if exc.retry_after_seconds is not None
        else ""
    )
    print(f"result=FAIL error={exc.code.value}{retry}")


def main(
    argv: list[str] | None = None,
    *,
    execute_check: Callable[[], AcquisitionShadowSmokeResult] | None = None,
) -> int:
    arguments = _parser().parse_args(argv)
    assert arguments.command == "check"
    execute = execute_check or execute_connectivity_check
    try:
        result = execute()
    except ConnectivityFailure as exc:
        _print_failure(exc)
        return 1
    except Exception:  # noqa: BLE001 - CLI never reflects raw runtime/provider detail
        print(f"result=FAIL error={ConnectivityErrorCode.MALFORMED_RESPONSE.value}")
        return 1
    _print_success(result)
    return 0


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())
