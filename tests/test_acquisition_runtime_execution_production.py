from __future__ import annotations

import datetime as dt
import hashlib
import hmac
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
from signals.acquisition_runtime.contracts import (
    ACQUISITION_PRODUCTION_SCHEMA_VERSION,
    AcquisitionRuntimeConfig,
    AcquisitionRuntimeDeployment,
    AcquisitionRuntimeLimits,
    AcquisitionRuntimeStage,
    RuntimeActionResult,
    RuntimeDependencyState,
    RuntimeQaScope,
    RuntimeStageDependency,
    RuntimeStageStatus,
)
from signals.acquisition_runtime.execution import (
    RuntimeExecutionConfigurationError,
    RuntimeLinkConfiguration,
    build_runtime_execution_composition,
)
from signals.campaigns.runtime_webhook import InstantlyWebhookRuntimeConfiguration
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
    contract_award,
    opportunity_representation,
    policy_evaluation,
    source_event,
)
from signals.policy.store import PolicyStore
from signals.responses.contracts import ContentFingerprintKeyring
from signals.supervisor.contracts import ProposedAction, SupervisorPlan
from signals.supervisor.pin import load_hermes_pin
from signals.supervisor.profile import PROFILE_VERSION
from signals.supervisor.runtime import HealthState, SupervisorHealth

# Montage lifted from tests/test_acquisition_runtime_execution.py, per the task
# brief: an approximate montage produces failures unrelated to production
# selection, since build_runtime_execution_composition has many preconditions
# (clock, webhook ingress, policy control, provider clients, Hermes).

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


class ClosedFakeHermes:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.required_action_counts: list[int | None] = []

    def health(self) -> SupervisorHealth:
        pin = load_hermes_pin()
        return SupervisorHealth(
            state=HealthState.AVAILABLE,
            hermes_version=pin.version,
            source_commit=pin.commit,
            executable_tools=(),
        )

    def plan(self, context, *, required_action_count=None) -> SupervisorPlan:
        command = context.available_commands[0]
        target = context.opportunities[0].object_ref
        cost = context.budget.maximum_cycle_cost
        self.commands.append(command)
        self.required_action_counts.append(required_action_count)
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
            source_event,
            contract_award,
            opportunity_representation,
        ],
    )
    PolicyStore(engine).append_control(
        control(
            1,
            allowed_countries=("FR",),
            allowed_languages=("fr",),
            allowed_wedges=("construction",),
            allowed_commands=tuple(stage.command for stage in AcquisitionRuntimeStage),
            effective_at=NOW - dt.timedelta(hours=1),
        )
    )
    return engine


def _seed(engine: sa.Engine, *, key: str, country: str, published_on: dt.date) -> None:
    """Insère une opportunité minimale : un événement, un award, une représentation."""

    with engine.begin() as connection:
        connection.execute(
            sa.insert(source_event).values(
                event_key=f"event-{key}",
                source_system="BOAMP",
                source_notice_id=f"notice-{key}",
                source_country=country,
                event_type="AWARD",
                published_on=published_on,
                procedure_buyers=[],
                created_at=NOW,
            )
        )
        connection.execute(
            sa.insert(contract_award).values(
                award_key=f"award-{key}",
                event_key=f"event-{key}",
                cpv_additional=[],
                winner_status="undisclosed",
                awardee_parties=[],
                contract_signatories=[],
                created_at=NOW,
            )
        )
        connection.execute(
            sa.insert(opportunity_representation).values(
                award_key=f"award-{key}", opportunity_key=key, created_at=NOW
            )
        )


def _production_runtime_config() -> AcquisitionRuntimeConfig:
    return AcquisitionRuntimeConfig(
        environment="PRODUCTION",
        deployment_path=Path("/etc/kivou/acquisition-production.json"),
        deployment=AcquisitionRuntimeDeployment(
            schema_version=ACQUISITION_PRODUCTION_SCHEMA_VERSION,
            qa_scope=RuntimeQaScope(
                country="FR", language="fr", wedge="construction"
            ),
            limits=AcquisitionRuntimeLimits(
                maximum_cycle_cost=Decimal("10"),
                maximum_provider_operations=3,
                maximum_wall_seconds=600,
                lease_seconds=900,
            ),
        ),
    )


def _staging_runtime_config() -> AcquisitionRuntimeConfig:
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
                country="FR", language="fr", wedge="construction"
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


def _connectivity_config(
    tmp_path,
    *,
    managed_gap: int | None = 10,
) -> AcquisitionConnectivityConfig:
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
                    managed_airmail_sending_gap_minutes=managed_gap,
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


def _apollo(provider: NoNetworkProvider) -> ApolloComponents:
    return ApolloComponents(
        organization_search=provider,
        contact_discovery=provider,
        company_research=provider,
        identity=provider,
    )


def _closed_domain_builder(**_kwargs):
    """A domain builder that never touches production transport.

    Updated in Task 6 fix round 1. The *original* reason this stub existed
    is now fixed: `build_acquisition_domain_composition` (composition.py) no
    longer unconditionally builds a `StagingQaRecipientOverride`
    (transport.py) — it only does so for `environment == "STAGING"`, and
    passes `None` for production, matching `CampaignWorker`'s existing
    `recipient_override: CampaignRecipientOverride | None = None` support.

    But composing the real domain for a production config is *still*
    blocked, by a second, deeper precondition discovered while verifying
    that fix: `AcquisitionDomainActions.__init__` (domain.py) requires
    `qa_transport_recipient_identity` / `qa_transport_recipient_key_version`
    as non-optional, SHA-256-validated strings, read unconditionally from
    `recipient_override.transport_recipient_identity` /
    `.transport_key_version` — which crashes with `AttributeError` when
    `recipient_override is None`. That is domain.py business logic (the
    campaign handoff truth-binding), not composition wiring, and is out of
    scope for both this task and the fix round that touched composition.py.
    See `tests/test_acquisition_runtime_composition.py::
    test_production_domain_composition_still_blocked_by_qa_transport_binding`
    (an `xfail(strict=True)` regression pin) for the durable, executable
    proof, and the fix-round report for the full writeup.

    Standing in for the domain with closed fakes isolates the composition-
    and-run-once mechanics this task actually tests (opportunity selection
    routed through the real store/registry/runner, and so the real
    `resume_or_create_cycle`) from that still-open domain.py gap, exactly as
    `test_fake_full_cycle_uses_real_store_registry_runner_and_closed_supervisor`
    already does in tests/test_acquisition_runtime_execution.py.
    """

    def handler(context):
        return RuntimeActionResult(
            status=RuntimeStageStatus.SUCCEEDED,
            result_refs=(f"result:{context.stage.value.lower()}",),
            reason_codes=("STAGE_COMPLETE",),
        )

    return SimpleNamespace(
        handlers={stage: handler for stage in AcquisitionRuntimeStage}
    )


@pytest.fixture
def engine():
    value = _engine()
    yield value
    value.dispose()


@pytest.fixture
def production_arguments(engine: sa.Engine, tmp_path):
    provider = NoNetworkProvider()
    return {
        "engine": engine,
        "runtime_config": _production_runtime_config(),
        "connectivity_config": _connectivity_config(tmp_path),
        "links": _links(),
        "webhook_configuration": _webhook_configuration(),
        "apollo": _apollo(provider),
        "instantly_provider": provider,
        "hermes_runtime": ClosedFakeHermes(),
        "dependency_probe": ReadyDependencyProbe(),
        "domain_builder": _closed_domain_builder,
        "clock": lambda: NOW,
    }


@pytest.fixture
def staging_arguments(engine: sa.Engine, tmp_path):
    provider = NoNetworkProvider()
    return {
        "engine": engine,
        "runtime_config": _staging_runtime_config(),
        "connectivity_config": _connectivity_config(tmp_path),
        "links": _links(),
        "webhook_configuration": _webhook_configuration(),
        "apollo": _apollo(provider),
        "instantly_provider": provider,
        "hermes_runtime": ClosedFakeHermes(),
        "dependency_probe": ReadyDependencyProbe(),
        "clock": lambda: NOW,
    }


@pytest.fixture
def seeded_french_opportunity(engine: sa.Engine) -> str:
    key = "opportunity-production-fr-001"
    _seed(engine, key=key, country="FR", published_on=dt.date(2026, 8, 20))
    return key


def test_production_without_eligible_opportunity_fails_closed(
    production_arguments,
) -> None:
    with pytest.raises(RuntimeExecutionConfigurationError) as error:
        build_runtime_execution_composition(**production_arguments)
    assert "NO_ELIGIBLE_OPPORTUNITY" in str(error.value)


def test_production_composition_uses_the_selected_opportunity(
    production_arguments, seeded_french_opportunity
) -> None:
    composition = build_runtime_execution_composition(**production_arguments)
    assert composition.capability.environment == "PRODUCTION"
    assert composition.capability.qa_only is False
    assert composition.runner.allowed_opportunity_keys == (
        seeded_french_opportunity,
    )


def test_staging_composition_is_unchanged(staging_arguments) -> None:
    composition = build_runtime_execution_composition(**staging_arguments)
    assert composition.capability.environment == "STAGING"
    assert composition.capability.qa_only is True
