from __future__ import annotations

import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import httpx
from pydantic import SecretStr

from signals.acquisition_connectivity.apollo import ApolloComponents
from signals.acquisition_connectivity.cli import (
    build_connectivity_composition,
    main,
)
from signals.acquisition_connectivity.contracts import (
    AcquisitionConnectivityConfig,
    AcquisitionMutationDelta,
    AcquisitionShadowSmokeResult,
    ApolloIdentityEvidence,
    ConnectivityErrorCode,
    ConnectivityFailure,
    HermesConnectivityEvidence,
    InstantlyConnectivityEvidence,
    ShadowConnectivityDocument,
    ShadowPlanEvidence,
    ShadowPreflightEvidence,
)
from signals.campaigns.instantly import HttpInstantlyProvider
from signals.persistence.database import create_database_engine
from signals.supervisor.hermes import HermesSupervisorAdapter


def _config() -> AcquisitionConnectivityConfig:
    deployment = ShadowConnectivityDocument.model_validate(
        {
            "schema_version": "acquisition-shadow-connectivity-v1",
            "instantly_workspace_ref": "workspace-staging-ref",
            "mailboxes": [
                {"mailbox_ref": "mailbox-01", "provider_account_id": "one@example.com"},
                {"mailbox_ref": "mailbox-02", "provider_account_id": "two@example.com"},
                {"mailbox_ref": "mailbox-03", "provider_account_id": "three@example.com"},
            ],
        }
    )
    return AcquisitionConnectivityConfig(
        environment="STAGING",
        shadow_config_path=Path("/etc/kivou/acquisition-shadow.json"),
        apollo_api_key=SecretStr("synthetic-apollo-value"),
        instantly_api_key=SecretStr("synthetic-instantly-value"),
        hermes_python=Path("/opt/kivou/hermes/python"),
        hermes_home=Path("/var/lib/kivou/hermes-shadow"),
        hermes_cwd=Path("/var/lib/kivou/hermes-shadow/work"),
        deployment=deployment,
    )


def _result() -> AcquisitionShadowSmokeResult:
    return AcquisitionShadowSmokeResult(
        preflight=ShadowPreflightEvidence(),
        apollo=ApolloIdentityEvidence(acting_profile_fingerprint="a" * 64),
        instantly=InstantlyConnectivityEvidence(),
        hermes=HermesConnectivityEvidence(),
        shadow_plan=ShadowPlanEvidence(actions=0, estimated_cost=Decimal("0")),
        mutation_delta=AcquisitionMutationDelta(
            campaigns=0,
            members=0,
            provider_operations=0,
            provider_events=0,
        ),
    )


def test_composition_root_reuses_existing_provider_policy_store_and_adapter() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
        timeout=10,
    )
    composition = build_connectivity_composition(
        config=_config(),
        engine=create_database_engine("sqlite+pysqlite:///:memory:"),
        client=client,
    )

    assert isinstance(composition.apollo, ApolloComponents)
    assert isinstance(composition.instantly_provider, HttpInstantlyProvider)
    assert isinstance(composition.hermes_adapter, HermesSupervisorAdapter)
    assert composition.hermes_adapter.settings.limits.invocation_timeout_seconds == 30
    assert composition.hermes_adapter.settings.limits.max_output_tokens == 2_048
    assert composition.hermes_adapter.settings.limits.max_planned_actions == 10


def test_check_command_prints_the_exact_bounded_pass_shape(capsys) -> None:
    exit_code = main(["check"], execute_check=_result)

    assert exit_code == 0
    assert capsys.readouterr().out == (
        "acquisition_shadow environment=STAGING policy=SHADOW "
        "read_only=true kill_switch=true\n"
        "apollo auth=READY acting_profile=BOUND\n"
        "instantly workspace=BOUND mailboxes_ready=3 mailboxes_total=3\n"
        "hermes state=AVAILABLE version=0.20.4 executable_tools=0 "
        "model=anthropic/claude-sonnet-4.6\n"
        "shadow_plan status=advisory actions=0 estimated_cost=0.00\n"
        "mutation_delta campaigns=0 members=0 provider_operations=0 provider_events=0\n"
        "result=PASS\n"
    )


def test_closed_failures_have_stable_exit_and_never_print_exception_details(capsys) -> None:
    def fail() -> AcquisitionShadowSmokeResult:
        raise ConnectivityFailure(
            ConnectivityErrorCode.AUTH,
            retry_after_seconds=7,
        )

    exit_code = main(["check"], execute_check=fail)

    assert exit_code == 1
    assert capsys.readouterr().out == "result=FAIL error=AUTH retry_after_seconds=7\n"


def test_unexpected_failure_is_bounded_and_redacted(capsys) -> None:
    def fail() -> AcquisitionShadowSmokeResult:
        raise RuntimeError(
            "synthetic-apollo-value one@example.com raw-provider-response"
        )

    exit_code = main(["check"], execute_check=fail)

    assert exit_code == 1
    output = capsys.readouterr().out
    assert output == "result=FAIL error=MALFORMED_RESPONSE\n"
    assert "@" not in output
    assert "synthetic" not in output


def test_module_entrypoint_requires_explicit_check_and_does_not_touch_network() -> None:
    process = subprocess.run(
        [sys.executable, "-m", "signals.acquisition_connectivity"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert process.returncode == 2
    assert "check" in process.stderr
    assert process.stdout == ""
