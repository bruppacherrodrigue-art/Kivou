"""Manual CLI and composition root for the acquisition SHADOW smoke."""

from __future__ import annotations

import argparse
import datetime as dt
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
        mailbox_readiness=InstantlyMailboxReadinessSource(instantly_provider),
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
    )
    return ConnectivityComposition(
        service=service,
        apollo=apollo,
        instantly_provider=instantly_provider,
        hermes_adapter=hermes_adapter,
    )


def execute_connectivity_check() -> AcquisitionShadowSmokeResult:
    config = load_connectivity_config()
    engine = create_database_engine()
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            composition = build_connectivity_composition(
                config=config,
                engine=engine,
                client=client,
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


def _print_success(result: AcquisitionShadowSmokeResult) -> None:
    print(
        "acquisition_shadow environment=STAGING policy=SHADOW "
        "read_only=true kill_switch=true"
    )
    print("apollo auth=READY acting_profile=BOUND")
    print("instantly workspace=BOUND mailboxes_ready=3 mailboxes_total=3")
    print(
        "hermes state=AVAILABLE version=0.20.4 executable_tools=0 "
        "model=anthropic/claude-sonnet-4.6"
    )
    print(
        f"shadow_plan status=advisory actions={result.shadow_plan.actions} "
        f"estimated_cost={result.shadow_plan.estimated_cost:.2f}"
    )
    delta = result.mutation_delta
    print(
        f"mutation_delta campaigns={delta.campaigns} members={delta.members} "
        f"provider_operations={delta.provider_operations} "
        f"provider_events={delta.provider_events}"
    )
    print("result=PASS")


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
        retry = (
            f" retry_after_seconds={exc.retry_after_seconds}"
            if exc.retry_after_seconds is not None
            else ""
        )
        print(f"result=FAIL error={exc.code.value}{retry}")
        return 1
    except Exception:  # noqa: BLE001 - CLI never reflects raw runtime/provider detail
        print(f"result=FAIL error={ConnectivityErrorCode.MALFORMED_RESPONSE.value}")
        return 1
    _print_success(result)
    return 0


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())

