from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

import signals.accounts.schema  # noqa: F401 - registers cross-module FK tables
from signals.acquisition_connectivity.contracts import (
    AcquisitionConnectivityConfig,
    ApolloIdentityEvidence,
    ConnectivityErrorCode,
    ConnectivityFailure,
    HermesConnectivityEvidence,
    InstantlyConnectivityEvidence,
    ShadowConnectivityDocument,
    ShadowPlanEvidence,
)
from signals.acquisition_connectivity.service import AcquisitionConnectivityService
from signals.campaigns.store import CampaignStore
from signals.persistence.database import create_database_engine
from signals.persistence.schema import METADATA
from signals.policy.contracts import AutonomyMode, PolicyControlSnapshot

NOW = dt.datetime(2026, 8, 24, 12, tzinfo=dt.UTC)


def _deployment() -> ShadowConnectivityDocument:
    return ShadowConnectivityDocument.model_validate(
        {
            "schema_version": "acquisition-shadow-connectivity-v1",
            "instantly_workspace_ref": "workspace-staging-ref",
            "mailboxes": [
                {
                    "mailbox_ref": "mailbox-staging-01",
                    "provider_account_id": "one@example.com",
                },
                {
                    "mailbox_ref": "mailbox-staging-02",
                    "provider_account_id": "two@example.com",
                },
                {
                    "mailbox_ref": "mailbox-staging-03",
                    "provider_account_id": "three@example.com",
                },
            ],
        }
    )


def _config(*, environment: str = "STAGING") -> AcquisitionConnectivityConfig:
    return AcquisitionConnectivityConfig(
        environment=environment,
        shadow_config_path=Path("/etc/kivou/acquisition-shadow.json"),
        apollo_api_key=SecretStr("synthetic-apollo-value"),
        instantly_api_key=SecretStr("synthetic-instantly-value"),
        hermes_python=Path("/opt/kivou/hermes/python"),
        hermes_home=Path("/var/lib/kivou/hermes-shadow"),
        hermes_cwd=Path("/var/lib/kivou/hermes-shadow/work"),
        deployment=_deployment(),
    )


def _control(**updates: object) -> PolicyControlSnapshot:
    values: dict[str, object] = {
        "policy_snapshot_id": "shadow-control-1",
        "control_revision": 1,
        "autonomy_mode": AutonomyMode.SHADOW,
        "shadow_target_mode": AutonomyMode.ASSISTED,
        "read_only": True,
        "kill_switch": True,
        "allowed_commands": ("evaluate_opportunity",),
        "allowed_countries": ("CH",),
        "allowed_languages": ("fr",),
        "allowed_wedges": ("construction",),
        "currency": "CHF",
        "daily_cost_cap": Decimal("1"),
        "daily_volume_cap": 0,
        "effective_at": NOW - dt.timedelta(hours=1),
        "expires_at": None,
        "snapshot_fingerprint": "a" * 64,
        "created_at": NOW - dt.timedelta(hours=1),
        "created_by_actor_type": "HUMAN",
        "created_by_actor_ref": "staging-operator",
        "reason_codes": ("SHADOW_CONNECTIVITY",),
    }
    values.update(updates)
    return PolicyControlSnapshot.model_validate(values)


class FakePolicyStore:
    def __init__(self, control: PolicyControlSnapshot | Exception) -> None:
        self.control = control
        self.calls = 0

    def get_effective_control(self, _at: dt.datetime) -> PolicyControlSnapshot:
        self.calls += 1
        if isinstance(self.control, Exception):
            raise self.control
        return self.control


ZERO = {
    "campaigns": 0,
    "members": 0,
    "provider_operations": 0,
    "provider_events": 0,
}


class FakeCampaignStore:
    def __init__(
        self,
        *counts: dict[str, int],
        ambiguous: bool = False,
    ) -> None:
        self.counts = list(counts or (ZERO, ZERO))
        self.ambiguous = ambiguous
        self.count_calls = 0

    def has_ambiguous_positive_provider_operations(self) -> bool:
        return self.ambiguous

    def bounded_connectivity_counts(self) -> dict[str, int]:
        index = min(self.count_calls, len(self.counts) - 1)
        self.count_calls += 1
        return dict(self.counts[index])


class FakeApollo:
    def __init__(self, failure: ConnectivityFailure | None = None) -> None:
        self.failure = failure
        self.calls = 0

    def check(self) -> ApolloIdentityEvidence:
        self.calls += 1
        if self.failure:
            raise self.failure
        return ApolloIdentityEvidence(acting_profile_fingerprint="b" * 64)


class FakeInstantly:
    def __init__(self, failure: ConnectivityFailure | None = None) -> None:
        self.failure = failure
        self.calls = 0

    def check(
        self, _deployment: ShadowConnectivityDocument, *, observed_at: dt.datetime
    ) -> InstantlyConnectivityEvidence:
        assert observed_at == NOW
        self.calls += 1
        if self.failure:
            raise self.failure
        return InstantlyConnectivityEvidence()


class FakeHermes:
    def __init__(self, failure: ConnectivityFailure | None = None) -> None:
        self.failure = failure
        self.calls = 0

    def check(
        self, _control: PolicyControlSnapshot, *, observed_at: dt.datetime
    ) -> tuple[HermesConnectivityEvidence, ShadowPlanEvidence]:
        assert observed_at == NOW
        self.calls += 1
        if self.failure:
            raise self.failure
        return (
            HermesConnectivityEvidence(),
            ShadowPlanEvidence(
                plan_id="shadow-plan",
                actions=0,
                estimated_cost=Decimal("0"),
                next_review_at=NOW + dt.timedelta(hours=1),
            ),
        )


def _service(
    *,
    control: PolicyControlSnapshot | Exception | None = None,
    store: FakeCampaignStore | None = None,
    apollo: FakeApollo | None = None,
    instantly: FakeInstantly | None = None,
    hermes: FakeHermes | None = None,
    environment: str = "STAGING",
) -> tuple[AcquisitionConnectivityService, FakeApollo, FakeInstantly, FakeHermes]:
    apollo = apollo or FakeApollo()
    instantly = instantly or FakeInstantly()
    hermes = hermes or FakeHermes()
    service = AcquisitionConnectivityService(
        config=_config(environment=environment),
        policy_store=FakePolicyStore(control or _control()),
        campaign_store=store or FakeCampaignStore(),
        apollo_identity=apollo,
        instantly=instantly,
        hermes=hermes,
        deployed_sha="c" * 40,
    )
    return service, apollo, instantly, hermes


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"autonomy_mode": AutonomyMode.ASSISTED, "shadow_target_mode": None}, ConnectivityErrorCode.POLICY_NOT_SHADOW),
        ({"read_only": False}, ConnectivityErrorCode.READ_ONLY_REQUIRED),
        ({"kill_switch": False}, ConnectivityErrorCode.KILL_SWITCH_REQUIRED),
        ({"daily_volume_cap": 1}, ConnectivityErrorCode.AUTONOMOUS_VOLUME_REQUIRED),
    ],
)
def test_policy_preflight_fails_before_counts_or_network(
    updates: dict[str, object], code: ConnectivityErrorCode
) -> None:
    store = FakeCampaignStore()
    service, apollo, instantly, hermes = _service(
        control=_control(**updates), store=store
    )

    with pytest.raises(ConnectivityFailure) as caught:
        service.check(observed_at=NOW)

    assert caught.value.code is code
    assert store.count_calls == 0
    assert (apollo.calls, instantly.calls, hermes.calls) == (0, 0, 0)


def test_unavailable_policy_or_ambiguous_provider_operation_fails_before_network() -> None:
    service, apollo, instantly, hermes = _service(control=RuntimeError("database detail"))
    with pytest.raises(ConnectivityFailure) as caught:
        service.check(observed_at=NOW)
    assert caught.value.code is ConnectivityErrorCode.OPERATIONAL_AMBIGUITY
    assert (apollo.calls, instantly.calls, hermes.calls) == (0, 0, 0)

    store = FakeCampaignStore(ambiguous=True)
    service, apollo, instantly, hermes = _service(store=store)
    with pytest.raises(ConnectivityFailure) as caught:
        service.check(observed_at=NOW)
    assert caught.value.code is ConnectivityErrorCode.OPERATIONAL_AMBIGUITY
    assert store.count_calls == 0
    assert (apollo.calls, instantly.calls, hermes.calls) == (0, 0, 0)


def test_success_returns_only_bounded_advisory_evidence_and_zero_delta() -> None:
    store = FakeCampaignStore(ZERO, ZERO)
    service, apollo, instantly, hermes = _service(store=store)

    result = service.check(observed_at=NOW)

    assert result.preflight.environment == "STAGING"
    assert result.preflight.policy == "SHADOW"
    assert result.deployed_sha == "c" * 40
    assert result.preflight.policy_control_revision == 1
    assert result.apollo.auth == "READY"
    assert result.instantly.mailboxes_ready == 3
    assert result.hermes.executable_tools == 0
    assert result.shadow_plan.status == "advisory"
    assert result.mutation_delta.model_dump() == ZERO
    assert store.count_calls == 2
    assert (apollo.calls, instantly.calls, hermes.calls) == (1, 1, 1)


@pytest.mark.parametrize("environment", ["STAGING", "PRODUCTION"])
def test_preflight_evidence_reports_the_environment_it_actually_ran_in(
    environment: str,
) -> None:
    store = FakeCampaignStore(ZERO, ZERO)
    service, _, _, _ = _service(store=store, environment=environment)

    result = service.check(observed_at=NOW)

    assert result.preflight.environment == environment


@pytest.mark.parametrize(
    ("failed_component", "expected_calls"),
    [
        ("apollo", (1, 0, 0)),
        ("instantly", (1, 1, 0)),
        ("hermes", (1, 1, 1)),
    ],
)
def test_every_reached_network_failure_still_rereads_counts(
    failed_component: str, expected_calls: tuple[int, int, int]
) -> None:
    failure = ConnectivityFailure(ConnectivityErrorCode.NETWORK)
    apollo = FakeApollo(failure if failed_component == "apollo" else None)
    instantly = FakeInstantly(failure if failed_component == "instantly" else None)
    hermes = FakeHermes(failure if failed_component == "hermes" else None)
    store = FakeCampaignStore(ZERO, ZERO)
    service, _, _, _ = _service(
        store=store, apollo=apollo, instantly=instantly, hermes=hermes
    )

    with pytest.raises(ConnectivityFailure) as caught:
        service.check(observed_at=NOW)

    assert caught.value.code is ConnectivityErrorCode.NETWORK
    assert caught.value.partial is not None
    assert caught.value.partial.failed_component == failed_component
    assert caught.value.partial.mutation_delta is not None
    assert caught.value.partial.mutation_delta.model_dump() == ZERO
    assert store.count_calls == 2
    assert (apollo.calls, instantly.calls, hermes.calls) == expected_calls


def test_local_mutation_takes_precedence_over_a_provider_failure() -> None:
    after = {**ZERO, "provider_operations": 1}
    store = FakeCampaignStore(ZERO, after)
    apollo = FakeApollo(ConnectivityFailure(ConnectivityErrorCode.AUTH))
    service, _, instantly, hermes = _service(store=store, apollo=apollo)

    with pytest.raises(ConnectivityFailure) as caught:
        service.check(observed_at=NOW)

    assert caught.value.code is ConnectivityErrorCode.LOCAL_MUTATION_DETECTED
    assert caught.value.partial is not None
    assert caught.value.partial.failed_component == "postcondition"
    assert caught.value.partial.mutation_delta is not None
    assert caught.value.partial.mutation_delta.provider_operations == 1
    assert store.count_calls == 2
    assert (instantly.calls, hermes.calls) == (0, 0)


def test_existing_campaign_store_owns_zero_count_snapshot_and_ambiguity_query() -> None:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    METADATA.create_all(engine)
    store = CampaignStore(engine)

    assert store.bounded_connectivity_counts() == ZERO
    assert store.has_ambiguous_positive_provider_operations() is False
