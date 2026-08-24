"""Fail-closed orchestration of the manual acquisition SHADOW smoke."""

from __future__ import annotations

import datetime as dt
from typing import Protocol

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
