"""Fail-closed orchestration of the manual acquisition SHADOW smoke."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Protocol

from signals.acquisition_connectivity.config import validate_hermes_shadow_config
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
from signals.policy.contracts import AutonomyMode, PolicyControlSnapshot
from signals.supervisor.contracts import BudgetEnvelope, SupervisorContext, validate_plan
from signals.supervisor.hermes import HermesSupervisorAdapter
from signals.supervisor.pin import load_hermes_pin
from signals.supervisor.profile import PROFILE_VERSION
from signals.supervisor.registry import ALLOWED_COMMANDS
from signals.supervisor.runtime import (
    HealthState,
    SupervisorNotConfigured,
    SupervisorProtocolError,
    SupervisorTimeout,
    SupervisorUnavailable,
    SupervisorValidationError,
    SupervisorVersionMismatch,
)

HERMES_REPOSITORY = "https://github.com/NousResearch/hermes-agent.git"
HERMES_TAG = "v2026.8.18"
HERMES_COMMIT = "e624e9fde561e1add9388384012b295fde669ade"
HERMES_VERSION = "0.20.4"
HERMES_PYTHON_CONTRACT = ">=3.11,<3.14"
OPENROUTER_MODEL = "anthropic/claude-sonnet-4.6"


class _PolicyReader(Protocol):
    def get_effective_control(self, at: dt.datetime) -> PolicyControlSnapshot: ...


class _CampaignStateReader(Protocol):
    def bounded_connectivity_counts(self) -> dict[str, int]: ...
    def has_ambiguous_positive_provider_operations(self) -> bool: ...


class _ApolloIdentity(Protocol):
    def check(self) -> ApolloIdentityEvidence: ...


class _InstantlyConnectivity(Protocol):
    def check(
        self,
        deployment: ShadowConnectivityDocument,
        *,
        observed_at: dt.datetime,
    ) -> InstantlyConnectivityEvidence: ...


class _HermesConnectivity(Protocol):
    def check(
        self,
        control: PolicyControlSnapshot,
        *,
        observed_at: dt.datetime,
    ) -> tuple[HermesConnectivityEvidence, ShadowPlanEvidence]: ...


class HermesConnectivityProbe:
    """Validate deployment wiring, then use the existing adapter unchanged."""

    def __init__(
        self,
        *,
        config: AcquisitionConnectivityConfig,
        adapter: HermesSupervisorAdapter,
    ) -> None:
        self._config = config
        self._adapter = adapter

    def check(
        self,
        control: PolicyControlSnapshot,
        *,
        observed_at: dt.datetime,
    ) -> tuple[HermesConnectivityEvidence, ShadowPlanEvidence]:
        validate_hermes_shadow_config(self._config)
        pin = load_hermes_pin()
        if (
            pin.repository != HERMES_REPOSITORY
            or pin.tag != HERMES_TAG
            or pin.commit != HERMES_COMMIT
            or pin.version != HERMES_VERSION
            or pin.python != HERMES_PYTHON_CONTRACT
        ):
            raise ConnectivityFailure(ConnectivityErrorCode.HERMES_VERSION_MISMATCH)
        limits = self._adapter.settings.limits
        if (
            limits.invocation_timeout_seconds > 30
            or limits.max_output_tokens > 2_048
            or limits.max_planned_actions > 10
        ):
            raise ConnectivityFailure(ConnectivityErrorCode.HERMES_PLAN_INVALID)
        try:
            health = self._adapter.health()
        except Exception:  # noqa: BLE001 - adapter detail cannot cross the smoke boundary
            raise ConnectivityFailure(ConnectivityErrorCode.NETWORK) from None
        if health.executable_tools:
            raise ConnectivityFailure(ConnectivityErrorCode.HERMES_TOOLS_EXPOSED)
        if health.state is HealthState.NOT_CONFIGURED:
            raise ConnectivityFailure(ConnectivityErrorCode.NOT_CONFIGURED)
        if health.state is HealthState.VERSION_MISMATCH:
            raise ConnectivityFailure(ConnectivityErrorCode.HERMES_VERSION_MISMATCH)
        if health.state is not HealthState.AVAILABLE:
            raise ConnectivityFailure(ConnectivityErrorCode.NETWORK)
        if health.hermes_version != pin.version or health.source_commit != pin.commit:
            raise ConnectivityFailure(ConnectivityErrorCode.HERMES_VERSION_MISMATCH)

        context = SupervisorContext(
            current_time=observed_at,
            runtime_mode="SHADOW",
            policy_version=control.policy_version,
            budget=BudgetEnvelope(currency="CHF", maximum_cycle_cost=Decimal("1")),
            available_commands=tuple(sorted(ALLOWED_COMMANDS)),
        )
        try:
            plan = self._adapter.plan(context)
            validate_plan(plan, limits)
            if any(action.command not in context.available_commands for action in plan.proposed_actions):
                raise ValueError("plan command is unavailable")
            if plan.supervisor_version != f"hermes-agent-{pin.version}":
                raise ValueError("supervisor version mismatch")
            if plan.skill_version != PROFILE_VERSION:
                raise ValueError("profile version mismatch")
            if plan.estimated_cost > context.budget.maximum_cycle_cost:
                raise ValueError("plan exceeds budget")
            if sum(
                (action.estimated_cost for action in plan.proposed_actions),
                start=Decimal("0"),
            ) > context.budget.maximum_cycle_cost:
                raise ValueError("actions exceed budget")
        except SupervisorTimeout:
            raise ConnectivityFailure(ConnectivityErrorCode.TIMEOUT) from None
        except SupervisorVersionMismatch:
            raise ConnectivityFailure(ConnectivityErrorCode.HERMES_VERSION_MISMATCH) from None
        except SupervisorNotConfigured:
            raise ConnectivityFailure(ConnectivityErrorCode.NOT_CONFIGURED) from None
        except (SupervisorProtocolError, SupervisorUnavailable):
            raise ConnectivityFailure(ConnectivityErrorCode.NETWORK) from None
        except (SupervisorValidationError, TypeError, ValueError):
            raise ConnectivityFailure(ConnectivityErrorCode.HERMES_PLAN_INVALID) from None
        return (
            HermesConnectivityEvidence(),
            ShadowPlanEvidence(
                actions=len(plan.proposed_actions),
                estimated_cost=plan.estimated_cost,
            ),
        )


class AcquisitionConnectivityService:
    def __init__(
        self,
        *,
        config: AcquisitionConnectivityConfig,
        policy_store: _PolicyReader,
        campaign_store: _CampaignStateReader,
        apollo_identity: _ApolloIdentity,
        instantly: _InstantlyConnectivity,
        hermes: _HermesConnectivity,
    ) -> None:
        self._config = config
        self._policy = policy_store
        self._campaigns = campaign_store
        self._apollo = apollo_identity
        self._instantly = instantly
        self._hermes = hermes

    def check(self, *, observed_at: dt.datetime) -> AcquisitionShadowSmokeResult:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ConnectivityFailure(ConnectivityErrorCode.OPERATIONAL_AMBIGUITY)
        observed_at = observed_at.astimezone(dt.UTC)
        control, preflight = self._preflight(observed_at)
        before = self._counts()
        failure: ConnectivityFailure | None = None
        apollo: ApolloIdentityEvidence | None = None
        instantly: InstantlyConnectivityEvidence | None = None
        hermes: HermesConnectivityEvidence | None = None
        shadow_plan: ShadowPlanEvidence | None = None
        network_reached = False

        try:
            network_reached = True
            apollo = self._apollo.check()
            instantly = self._instantly.check(
                self._config.deployment, observed_at=observed_at
            )
            hermes, shadow_plan = self._hermes.check(control, observed_at=observed_at)
        except ConnectivityFailure as exc:
            failure = exc
        except Exception:  # noqa: BLE001 - boundary maps details to a closed safe code
            failure = ConnectivityFailure(ConnectivityErrorCode.MALFORMED_RESPONSE)

        delta = AcquisitionMutationDelta(**{name: 0 for name in before})
        if network_reached:
            try:
                after = self._counts()
                delta = AcquisitionMutationDelta(
                    **{name: after[name] - before[name] for name in before}
                )
            except ConnectivityFailure as exc:
                failure = exc
            if delta.detected:
                raise ConnectivityFailure(ConnectivityErrorCode.LOCAL_MUTATION_DETECTED)
        if failure is not None:
            raise failure
        assert apollo is not None
        assert instantly is not None
        assert hermes is not None
        assert shadow_plan is not None
        return AcquisitionShadowSmokeResult(
            preflight=preflight,
            apollo=apollo,
            instantly=instantly,
            hermes=hermes,
            shadow_plan=shadow_plan,
            mutation_delta=delta,
        )

    def _preflight(
        self, observed_at: dt.datetime
    ) -> tuple[PolicyControlSnapshot, ShadowPreflightEvidence]:
        if self._config.environment != "STAGING":
            raise ConnectivityFailure(ConnectivityErrorCode.WRONG_ENVIRONMENT)
        try:
            control = self._policy.get_effective_control(observed_at)
        except Exception:  # noqa: BLE001 - no database/control detail crosses boundary
            raise ConnectivityFailure(ConnectivityErrorCode.OPERATIONAL_AMBIGUITY) from None
        if control.autonomy_mode is not AutonomyMode.SHADOW:
            raise ConnectivityFailure(ConnectivityErrorCode.POLICY_NOT_SHADOW)
        if not control.read_only:
            raise ConnectivityFailure(ConnectivityErrorCode.READ_ONLY_REQUIRED)
        if not control.kill_switch:
            raise ConnectivityFailure(ConnectivityErrorCode.KILL_SWITCH_REQUIRED)
        if control.daily_volume_cap != 0:
            raise ConnectivityFailure(ConnectivityErrorCode.AUTONOMOUS_VOLUME_REQUIRED)
        try:
            ambiguous = self._campaigns.has_ambiguous_positive_provider_operations()
        except Exception:  # noqa: BLE001 - fail closed without persistence detail
            raise ConnectivityFailure(ConnectivityErrorCode.OPERATIONAL_AMBIGUITY) from None
        if ambiguous:
            raise ConnectivityFailure(ConnectivityErrorCode.OPERATIONAL_AMBIGUITY)
        return control, ShadowPreflightEvidence()

    def _counts(self) -> dict[str, int]:
        expected = {
            "campaigns",
            "members",
            "provider_operations",
            "provider_events",
        }
        try:
            counts = self._campaigns.bounded_connectivity_counts()
            if set(counts) != expected or any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in counts.values()
            ):
                raise ValueError("invalid connectivity counts")
            return counts
        except Exception:  # noqa: BLE001 - fail closed without persistence detail
            raise ConnectivityFailure(ConnectivityErrorCode.OPERATIONAL_AMBIGUITY) from None
