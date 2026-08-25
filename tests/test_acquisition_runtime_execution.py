from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import inspect
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from test_policy_persistence import control

from signals.acquisition_connectivity.apollo import ApolloComponents
from signals.acquisition_connectivity.contracts import (
    AcquisitionConnectivityConfig,
    ShadowConnectivityDocument,
    ShadowMailboxBinding,
)
from signals.acquisition_runtime.composition import execute_runtime_run_once
from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeConfig,
    AcquisitionRuntimeDeployment,
    AcquisitionRuntimeLimits,
    AcquisitionRuntimeStage,
    RuntimeActionResult,
    RuntimeDependencyState,
    RuntimeQaScope,
    RuntimeRunRequest,
    RuntimeRunStatus,
    RuntimeStageDependency,
    RuntimeStageStatus,
)
from signals.acquisition_runtime.execution import (
    ProductionRuntimeDependencyProbe,
    RuntimeExecutionConfigurationError,
    RuntimeLinkConfiguration,
    build_runtime_execution_composition,
    load_runtime_link_config,
)
from signals.campaigns.runtime_webhook import (
    InstantlyWebhookRuntimeConfiguration,
    build_instantly_webhook_service,
)
from signals.campaigns.webhooks import WebhookFingerprintKeyring
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.persistence.database import create_database_engine
from signals.persistence.schema import (
    METADATA,
    acquisition_policy_snapshot,
    acquisition_runtime_approval,
    acquisition_runtime_cycle,
    acquisition_runtime_lease,
    acquisition_runtime_observation,
    acquisition_runtime_stage,
    acquisition_runtime_stage_attempt,
    policy_evaluation,
)
from signals.policy.store import PolicyStore
from signals.responses.contracts import ContentFingerprintKeyring
from signals.supervisor.contracts import ProposedAction, SupervisorPlan
from signals.supervisor.pin import load_hermes_pin
from signals.supervisor.profile import PROFILE_VERSION
from signals.supervisor.runtime import HealthState, SupervisorHealth

NOW = dt.datetime(2026, 8, 25, 14, tzinfo=dt.UTC)
QA_RECIPIENT = "qa-runtime@example.com"
QA_KEY = "synthetic-runtime-recipient-key"


class NoNetworkProvider:
    def __getattr__(self, name: str):
        raise AssertionError(f"provider I/O was attempted: {name}")


class ReadyDependencyProbe:
    def check(self, *, observed_at):
        assert observed_at == NOW
        return tuple(
            RuntimeStageDependency(
                stage=stage,
                status=RuntimeDependencyState.READY,
            )
            for stage in AcquisitionRuntimeStage
        )


class ProbeApolloIdentity:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    def check(self):
        if not self.available:
            raise RuntimeError("private-apollo-detail")
        return SimpleNamespace(acting_profile_fingerprint="a" * 64)


class ProbeInstantlyProvider:
    def __init__(self, *, mailbox_ready: bool = True) -> None:
        self.mailbox_ready = mailbox_ready

    def get_current_workspace_ref(self):
        return "workspace-qa"

    def get_mailbox_readiness(self, _provider_account_email):
        return {
            "status": 1 if self.mailbox_ready else -1,
            "warmup_status": 1,
            "setup_pending": False,
            "daily_limit": 3,
            "sending_gap": 10,
            "tracking_domain_status": "active",
        }


class ClosedFakeHermes:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def health(self) -> SupervisorHealth:
        pin = load_hermes_pin()
        return SupervisorHealth(
            state=HealthState.AVAILABLE,
            hermes_version=pin.version,
            source_commit=pin.commit,
            executable_tools=(),
        )

    def plan(self, context) -> SupervisorPlan:
        command = context.available_commands[0]
        target = context.opportunities[0].object_ref
        cost = context.budget.maximum_cycle_cost
        self.commands.append(command)
        pin = load_hermes_pin()
        return SupervisorPlan(
            plan_id=f"plan-{len(self.commands):02d}",
            created_at=NOW,
            objective="Execute one closed Kivou stage",
            priority=1,
            proposed_actions=(
                ProposedAction(
                    command=command,
                    target_ref=target,
                    arguments={},
                    reason_codes=("CLOSED_RUNTIME",),
                    evidence_refs=(),
                    estimated_cost=cost,
                ),
            ),
            reason_codes=("CLOSED_RUNTIME",),
            confidence=Decimal("1"),
            estimated_cost=cost,
            next_review_at=NOW + dt.timedelta(minutes=5),
            supervisor_version=f"hermes-agent-{pin.version}",
            skill_version=PROFILE_VERSION,
        )


def _engine() -> sa.Engine:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    METADATA.create_all(
        engine,
        tables=[
            acquisition_policy_snapshot,
            policy_evaluation,
            acquisition_runtime_lease,
            acquisition_runtime_cycle,
            acquisition_runtime_observation,
            acquisition_runtime_stage,
            acquisition_runtime_stage_attempt,
            acquisition_runtime_approval,
        ],
    )
    PolicyStore(engine).append_control(
        control(
            1,
            allowed_commands=tuple(stage.command for stage in AcquisitionRuntimeStage),
            effective_at=NOW - dt.timedelta(hours=1),
        )
    )
    return engine


def _runtime_config() -> AcquisitionRuntimeConfig:
    recipient_hmac = hmac.new(
        QA_KEY.encode(), QA_RECIPIENT.encode(), hashlib.sha256
    ).hexdigest()
    return AcquisitionRuntimeConfig(
        environment="STAGING",
        deployment_path=Path("/etc/kivou/acquisition-runtime.json"),
        deployment=AcquisitionRuntimeDeployment(
            qa_only=True,
            allowed_opportunity_keys=("signal-qa-001",),
            qa_scope=RuntimeQaScope(
                country="CH", language="fr", wedge="construction"
            ),
            qa_recipient_identity_hmac=recipient_hmac,
            qa_recipient_key_version="qa-runtime-v1",
            qa_provider_mutations_capable=True,
            limits=AcquisitionRuntimeLimits(
                maximum_cycle_cost=Decimal("10"),
                maximum_provider_operations=3,
                maximum_wall_seconds=600,
                lease_seconds=900,
            ),
        ),
        qa_recipient=SecretStr(QA_RECIPIENT),
        qa_recipient_hmac_key=SecretStr(QA_KEY),
    )


def _connectivity_config(tmp_path) -> AcquisitionConnectivityConfig:
    return AcquisitionConnectivityConfig(
        environment="STAGING",
        shadow_config_path=tmp_path / "shadow.json",
        apollo_api_key=SecretStr("synthetic-apollo-key"),
        instantly_api_key=SecretStr("synthetic-instantly-key"),
        hermes_python=tmp_path / "hermes-python",
        hermes_home=tmp_path / "hermes-home",
        hermes_cwd=tmp_path / "hermes-cwd",
        deployment=ShadowConnectivityDocument(
            instantly_workspace_ref="workspace-qa",
            mailboxes=tuple(
                ShadowMailboxBinding(
                    mailbox_ref=f"mailbox-qa-{index}",
                    provider_account_id=f"sender-{index}@example.com",
                )
                for index in range(1, 4)
            ),
        ),
    )


def _links() -> RuntimeLinkConfiguration:
    return RuntimeLinkConfiguration(
        public_app_url="https://staging.kivou.eu",
        attribution_hmac_key=b"synthetic-attribution-key",
        attribution_key_version="attribution-v1",
    )


def _webhook_configuration(
    *, workspace: str = "workspace-qa"
) -> InstantlyWebhookRuntimeConfiguration:
    return InstantlyWebhookRuntimeConfiguration(
        provider_webhook_secret="synthetic-webhook-route-secret",
        provider_workspace_ref=workspace,
        fingerprint_keyring=WebhookFingerprintKeyring(
            current_key_version="event-v1",
            keys={"event-v1": b"synthetic-event-secret"},
        ),
        suppression_keyring=SuppressionIdentityKeyring(
            current_key_version="suppression-v1",
            keys={"suppression-v1": b"synthetic-suppression-secret"},
        ),
        response_source_keyring=ContentFingerprintKeyring(
            current_key_version="source-v1",
            keys={"source-v1": b"synthetic-source-secret"},
        ),
        response_content_keyring=ContentFingerprintKeyring(
            current_key_version="content-v1",
            keys={"content-v1": b"synthetic-content-secret"},
        ),
    )


def test_execute_runtime_run_once_has_the_closed_cli_signature() -> None:
    assert tuple(inspect.signature(execute_runtime_run_once).parameters) == (
        "allow_qa_provider_mutations",
    )
    parameter = inspect.signature(execute_runtime_run_once).parameters[
        "allow_qa_provider_mutations"
    ]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_link_configuration_is_required_and_never_exposes_key_material() -> None:
    secret = "synthetic-private-attribution-key"
    with pytest.raises(RuntimeExecutionConfigurationError) as missing:
        load_runtime_link_config({})
    assert missing.value.code == "LINKS_NOT_CONFIGURED"

    loaded = load_runtime_link_config(
        {
            "KIVOU_PUBLIC_APP_URL": "https://staging.kivou.eu",
            "KIVOU_ATTRIBUTION_HMAC_KEY": secret,
            "KIVOU_ATTRIBUTION_HMAC_KEY_VERSION": "attribution-v1",
        }
    )
    assert loaded.attribution_hmac_key == secret.encode()
    assert secret not in repr(loaded)


@pytest.mark.parametrize(
    "unsafe_origin",
    (
        "https://kivou.eu",
        "https://other.example.com",
        "http://staging.kivou.eu",
        "https://staging.kivou.eu:444",
    ),
)
def test_staging_runtime_rejects_production_or_noncanonical_origins(
    unsafe_origin: str,
) -> None:
    with pytest.raises(RuntimeExecutionConfigurationError) as error:
        load_runtime_link_config(
            {
                "KIVOU_PUBLIC_APP_URL": unsafe_origin,
                "KIVOU_ATTRIBUTION_HMAC_KEY": "synthetic-private-attribution-key",
                "KIVOU_ATTRIBUTION_HMAC_KEY_VERSION": "attribution-v1",
            }
        )

    assert error.value.code == "LINKS_NOT_CONFIGURED"


def test_production_dependency_probe_reports_real_bounded_component_readiness(
    tmp_path,
) -> None:
    instantly = ProbeInstantlyProvider()
    probe = ProductionRuntimeDependencyProbe(
        apollo=SimpleNamespace(identity=ProbeApolloIdentity()),
        instantly_provider=instantly,
        connectivity=_connectivity_config(tmp_path),
        hermes_runtime=ClosedFakeHermes(),
        webhook_configuration=_webhook_configuration(),
    )

    dependencies = probe.check(observed_at=NOW)

    assert tuple(item.stage for item in dependencies) == tuple(
        AcquisitionRuntimeStage
    )
    assert all(
        item.status is RuntimeDependencyState.READY for item in dependencies
    )


def test_production_dependency_probe_keeps_provider_failures_component_scoped(
    tmp_path,
) -> None:
    probe = ProductionRuntimeDependencyProbe(
        apollo=SimpleNamespace(identity=ProbeApolloIdentity(available=False)),
        instantly_provider=ProbeInstantlyProvider(mailbox_ready=False),
        connectivity=_connectivity_config(tmp_path),
        hermes_runtime=ClosedFakeHermes(),
        webhook_configuration=None,
    )

    dependencies = {
        item.stage: item for item in probe.check(observed_at=NOW)
    }

    assert dependencies[
        AcquisitionRuntimeStage.SIGNAL_SEED
    ].status is RuntimeDependencyState.READY
    assert dependencies[
        AcquisitionRuntimeStage.COMPANY_RESEARCH
    ].reason_codes == ("APOLLO_DEPENDENCY_NOT_READY",)
    assert dependencies[AcquisitionRuntimeStage.CAMPAIGN].reason_codes == (
        "MAILBOX_DEPENDENCY_NOT_READY",
    )
    assert dependencies[AcquisitionRuntimeStage.RESPONSE].reason_codes == (
        "WEBHOOK_INGRESS_NOT_READY",
    )


def test_default_root_composition_constructs_real_domains_without_network(
    tmp_path,
) -> None:
    engine = _engine()
    provider = NoNetworkProvider()
    apollo = ApolloComponents(
        organization_search=provider,
        contact_discovery=provider,
        company_research=provider,
        identity=provider,
    )
    webhook_configuration = _webhook_configuration()

    composition = build_runtime_execution_composition(
        engine=engine,
        runtime_config=_runtime_config(),
        connectivity_config=_connectivity_config(tmp_path),
        links=_links(),
        webhook_configuration=webhook_configuration,
        apollo=apollo,
        instantly_provider=provider,
        hermes_runtime=ClosedFakeHermes(),
        clock=lambda: NOW,
    )

    assert set(composition.domain.handlers) == set(AcquisitionRuntimeStage)
    assert composition.registry.identity == composition.capability.registry_identity
    assert all(
        item.status is RuntimeDependencyState.NOT_READY
        for item in composition.capability.dependencies
    )
    assert len(composition.config_fingerprint) == 64
    assert QA_RECIPIENT not in repr(composition)
    assert QA_KEY not in repr(composition)
    expected_identity = webhook_configuration.suppression_keyring.identities_for_email(
        QA_RECIPIENT
    )[webhook_configuration.suppression_keyring.current_key_version]
    assert composition.domain.actions._qa_transport_binding == (
        expected_identity,
        webhook_configuration.suppression_keyring.current_key_version,
    )
    api_ingress = build_instantly_webhook_service(engine, webhook_configuration)
    assert api_ingress._suppression_keyring.identities_for_email(QA_RECIPIENT)[
        webhook_configuration.suppression_keyring.current_key_version
    ] == expected_identity
    engine.dispose()


def test_policy_window_changes_do_not_change_durable_cycle_identity(tmp_path) -> None:
    engine = _engine()
    provider = NoNetworkProvider()
    apollo = ApolloComponents(
        organization_search=provider,
        contact_discovery=provider,
        company_research=provider,
        identity=provider,
    )
    arguments = {
        "engine": engine,
        "runtime_config": _runtime_config(),
        "connectivity_config": _connectivity_config(tmp_path),
        "links": _links(),
        "webhook_configuration": _webhook_configuration(),
        "apollo": apollo,
        "instantly_provider": provider,
        "hermes_runtime": ClosedFakeHermes(),
        "clock": lambda: NOW,
    }
    before = build_runtime_execution_composition(**arguments)
    PolicyStore(engine).append_control(
        control(
            2,
            kill_switch=True,
            allowed_commands=tuple(
                stage.command for stage in AcquisitionRuntimeStage
            ),
            effective_at=NOW - dt.timedelta(minutes=30),
        )
    )

    after = build_runtime_execution_composition(**arguments)

    assert after.config_fingerprint == before.config_fingerprint
    engine.dispose()


def test_runtime_scope_must_equal_the_live_operator_policy_scope(tmp_path) -> None:
    engine = _engine()
    provider = NoNetworkProvider()
    apollo = ApolloComponents(
        organization_search=provider,
        contact_discovery=provider,
        company_research=provider,
        identity=provider,
    )
    configured = _runtime_config()
    mismatched = configured.model_copy(
        update={
            "deployment": configured.deployment.model_copy(
                update={
                    "qa_scope": RuntimeQaScope(
                        country="FR",
                        language="fr",
                        wedge="construction",
                    )
                }
            )
        }
    )

    with pytest.raises(RuntimeError, match="POLICY_SCOPE_NOT_EXACT"):
        build_runtime_execution_composition(
            engine=engine,
            runtime_config=mismatched,
            connectivity_config=_connectivity_config(tmp_path),
            links=_links(),
            webhook_configuration=_webhook_configuration(),
            apollo=apollo,
            instantly_provider=provider,
            hermes_runtime=ClosedFakeHermes(),
            clock=lambda: NOW,
        )
    engine.dispose()


def test_runtime_rejects_budget_below_the_bounded_apollo_recovery_envelope(
    tmp_path,
) -> None:
    engine = _engine()
    provider = NoNetworkProvider()
    apollo = ApolloComponents(
        organization_search=provider,
        contact_discovery=provider,
        company_research=provider,
        identity=provider,
    )
    configured = _runtime_config()
    undersized = configured.model_copy(
        update={
            "deployment": configured.deployment.model_copy(
                update={
                    "limits": configured.deployment.limits.model_copy(
                        update={"maximum_cycle_cost": Decimal("5")}
                    )
                }
            )
        }
    )

    with pytest.raises(RuntimeExecutionConfigurationError) as error:
        build_runtime_execution_composition(
            engine=engine,
            runtime_config=undersized,
            connectivity_config=_connectivity_config(tmp_path),
            links=_links(),
            webhook_configuration=_webhook_configuration(),
            apollo=apollo,
            instantly_provider=provider,
            hermes_runtime=ClosedFakeHermes(),
            clock=lambda: NOW,
        )

    assert error.value.code == "RUNTIME_RECOVERY_COST_ENVELOPE_TOO_SMALL"
    engine.dispose()


def test_fake_full_cycle_uses_real_store_registry_runner_and_closed_supervisor(
    tmp_path,
) -> None:
    engine = _engine()
    provider = NoNetworkProvider()
    apollo = ApolloComponents(
        organization_search=provider,
        contact_discovery=provider,
        company_research=provider,
        identity=provider,
    )
    executed: list[AcquisitionRuntimeStage] = []

    def domain_builder(**_kwargs):
        def handler(context):
            executed.append(context.stage)
            return RuntimeActionResult(
                status=RuntimeStageStatus.SUCCEEDED,
                result_refs=(f"result:{context.stage.value.lower()}",),
                reason_codes=("STAGE_COMPLETE",),
            )

        return SimpleNamespace(
            handlers={stage: handler for stage in AcquisitionRuntimeStage}
        )

    hermes = ClosedFakeHermes()
    composition = build_runtime_execution_composition(
        engine=engine,
        runtime_config=_runtime_config(),
        connectivity_config=_connectivity_config(tmp_path),
        links=_links(),
        webhook_configuration=_webhook_configuration(),
        apollo=apollo,
        instantly_provider=provider,
        hermes_runtime=hermes,
        domain_builder=domain_builder,
        dependency_probe=ReadyDependencyProbe(),
        clock=lambda: NOW,
    )

    result = composition.runner.run_once(
        RuntimeRunRequest(
            owner_ref="runtime-owner:qa-001",
            allow_qa_provider_mutations=True,
        )
    )

    assert result.status is RuntimeRunStatus.COMPLETED
    assert executed == list(AcquisitionRuntimeStage)
    assert hermes.commands == [stage.command for stage in AcquisitionRuntimeStage]
    assert composition.store.read_runtime_observation() is not None
    engine.dispose()


def test_runtime_rejects_webhook_workspace_different_from_provider_workspace(
    tmp_path,
) -> None:
    engine = _engine()
    provider = NoNetworkProvider()
    apollo = ApolloComponents(
        organization_search=provider,
        contact_discovery=provider,
        company_research=provider,
        identity=provider,
    )

    with pytest.raises(RuntimeExecutionConfigurationError) as error:
        build_runtime_execution_composition(
            engine=engine,
            runtime_config=_runtime_config(),
            connectivity_config=_connectivity_config(tmp_path),
            links=_links(),
            webhook_configuration=_webhook_configuration(
                workspace="workspace-other"
            ),
            apollo=apollo,
            instantly_provider=provider,
            hermes_runtime=ClosedFakeHermes(),
            clock=lambda: NOW,
        )
    assert error.value.code == "WEBHOOK_INGRESS_NOT_CONFIGURED"
    engine.dispose()
