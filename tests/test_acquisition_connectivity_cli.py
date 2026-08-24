from __future__ import annotations

import datetime as dt
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from signals.acquisition_connectivity.apollo import ApolloComponents
from signals.acquisition_connectivity.cli import (
    _deployed_sha,
    build_connectivity_composition,
    main,
)
from signals.acquisition_connectivity.contracts import (
    AcquisitionConnectivityConfig,
    AcquisitionMutationDelta,
    AcquisitionShadowSmokePartial,
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
        deployed_sha="c" * 40,
        preflight=ShadowPreflightEvidence(
            policy_control_revision=7,
            policy_version="acquisition-policy-v1",
        ),
        apollo=ApolloIdentityEvidence(acting_profile_fingerprint="a" * 64),
        instantly=InstantlyConnectivityEvidence(),
        hermes=HermesConnectivityEvidence(),
        shadow_plan=ShadowPlanEvidence(
            plan_id="shadow-plan",
            actions=0,
            estimated_cost=Decimal("0"),
            next_review_at=dt.datetime(2026, 8, 24, 13, tzinfo=dt.UTC),
        ),
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
        deployed_sha="c" * 40,
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
        "read_only=true kill_switch=true deployment_sha="
        f"{'c' * 40} policy_control_revision=7\n"
        "apollo auth=READY acting_profile=BOUND\n"
        "instantly workspace=BOUND mailboxes_ready=3 mailboxes_total=3\n"
        "hermes state=AVAILABLE version=0.20.4 executable_tools=0 "
        "model=anthropic/claude-sonnet-4.6 tag=v2026.8.18 commit="
        "e624e9fde561e1add9388384012b295fde669ade\n"
        "shadow_plan status=advisory actions=0 estimated_cost=0.00 "
        "plan_id=shadow-plan next_review_at=2026-08-24T13:00:00Z\n"
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


def test_reached_provider_failure_prints_prior_components_and_zero_postcondition(
    capsys,
) -> None:
    partial = AcquisitionShadowSmokePartial(
        deployed_sha="c" * 40,
        preflight=ShadowPreflightEvidence(
            policy_control_revision=7,
            policy_version="acquisition-policy-v1",
        ),
        failed_component="instantly",
        apollo=ApolloIdentityEvidence(acting_profile_fingerprint="a" * 64),
        mutation_delta=AcquisitionMutationDelta(
            campaigns=0,
            members=0,
            provider_operations=0,
            provider_events=0,
        ),
    )

    def fail() -> AcquisitionShadowSmokeResult:
        raise ConnectivityFailure(
            ConnectivityErrorCode.MAILBOX_NOT_READY,
            partial=partial,
        )

    assert main(["check"], execute_check=fail) == 1
    output = capsys.readouterr().out
    assert "apollo auth=READY acting_profile=BOUND" in output
    assert "instantly workspace=NOT_READY error=MAILBOX_NOT_READY" in output
    assert (
        "mutation_delta campaigns=0 members=0 provider_operations=0 provider_events=0"
        in output
    )
    assert output.endswith("result=FAIL error=MAILBOX_NOT_READY\n")


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


def test_deployed_sha_rejects_a_dirty_or_untracked_deployment(monkeypatch) -> None:
    responses = iter(
        (
            subprocess.CompletedProcess([], 0, stdout="c" * 40 + "\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout=" M src/signals/app.py\n", stderr=""),
        )
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: next(responses))

    with pytest.raises(ConnectivityFailure) as caught:
        _deployed_sha()

    assert caught.value.code is ConnectivityErrorCode.OPERATIONAL_AMBIGUITY
