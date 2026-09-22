"""A B1 retry checks the pool; a completed call is served without new I/O."""

import datetime as dt
import hashlib

import pytest
import sqlalchemy as sa

from signals.acquisition_programs.apollo_account import ApolloAccountState
from signals.acquisition_programs.census import CensusBudgetExceeded, CensusReviewRequired
from signals.acquisition_programs.census_b0 import B0Runner
from signals.acquisition_programs.census_b1 import B1PlanStore
from signals.acquisition_programs.census_b1_runtime import B1Runner
from signals.contact_discovery.contracts import ApolloEnrichedPerson
from signals.persistence.schema import acquisition_census_b1_plan, acquisition_census_call

NOW = dt.datetime(2026, 9, 22, 12, tzinfo=dt.UTC)


class _CachedStore:
    def execute_call(self, *_args, **_kwargs):
        return None, "cached-call-id"


def _runner(prior: str):
    engine = sa.create_engine("sqlite:///:memory:")
    acquisition_census_call.create(engine)
    subject = "opaque-company:person:opaque-person"
    with engine.begin() as connection:
        connection.execute(sa.insert(acquisition_census_call).values(
            call_id="c" * 64, census_id="synthetic-census", kind="PERSON_ENRICH",
            subject_hash=hashlib.sha256(subject.encode()).hexdigest(), attempt=1,
            status=prior, reserved_credits=1, candidate_slots=0,
            started_at=NOW, completed_at=NOW if prior == "COMPLETED" else None,
        ))
    runner = object.__new__(B1Runner)
    runner.engine = engine
    runner.census_id = "synthetic-census"
    runner.store = _CachedStore()
    probes = []

    def credit_state(*, credits):
        probes.append(credits)
        return ApolloAccountState(True, 1500, True, False, {"lead_credit": 1500})

    runner._credit_state = credit_state
    return runner, subject, probes


def test_completed_enrichment_uses_ledger_without_new_probe_or_provider_call() -> None:
    runner, subject, probes = _runner("COMPLETED")
    provider_calls = []
    result, receipt = runner._call(
        candidate_id="a" * 64, partition_id="p", kind="PERSON_ENRICH",
        subject=subject, credits=1, at=NOW,
        invoke=lambda: provider_calls.append("called"), model=ApolloEnrichedPerson,
    )
    assert result is None
    assert receipt["cache_hit"] is True
    assert probes == provider_calls == []


def test_rate_limited_retry_requires_fresh_balance_before_provider_path() -> None:
    runner, subject, probes = _runner("RATE_LIMITED")
    runner._call(
        candidate_id="a" * 64, partition_id="p", kind="PERSON_ENRICH",
        subject=subject, credits=1, at=NOW,
        invoke=lambda: None, model=ApolloEnrichedPerson,
    )
    assert probes == [1, 0]


def test_suppressed_verified_address_does_not_advance_usable_base(monkeypatch) -> None:
    runner = object.__new__(B1Runner)
    runner.census_id = "synthetic-census"
    runner.legal_pages = object()
    runner.official = object()
    monkeypatch.setattr(B0Runner, "_process", lambda *_args, **_kwargs: {
        "classification": "SUPPRESSED", "decision": "NO_SEND",
        "verified_email": True, "email": "founder@cabinet.example",
    })
    result = runner._process({"candidate_id": "a" * 64}, {}, at=NOW)
    assert result["classification"] == "SUPPRESSED"
    assert result["decision"] == "NO_SEND"
    assert result["verified_email"] is False


@pytest.mark.parametrize("balance,credits,allowed", [
    (1001, 1, True), (1000, 1, False), (999, 0, False),
    (1957, 0, False),  # a top-up or pool change needs review
])
def test_b1_live_pool_guard_preserves_reserve_and_rejects_topup(
    balance: int, credits: int, allowed: bool,
) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    acquisition_census_b1_plan.create(engine)
    with engine.begin() as connection:
        connection.execute(sa.insert(acquisition_census_b1_plan).values(
            plan_id="synthetic-b1-plan", census_id="synthetic-census",
            plan_hash="b" * 64, seed="synthetic", caps={}, cumulative_limits={},
            pool_before=1956, status="ACTIVE", created_at=NOW, updated_at=NOW,
        ))
    runner = object.__new__(B1Runner)
    runner.engine = engine
    runner.permit_id = "synthetic-b1-plan"
    runner.account_probe = lambda: ApolloAccountState(
        True, balance, True, False, {"lead_credit": balance},
    )
    if allowed:
        assert runner._credit_state(credits=credits).credit_balance == balance
    else:
        with pytest.raises(CensusBudgetExceeded):
            runner._credit_state(credits=credits)


def test_shared_pool_reconciliation_is_durable_but_not_exclusive_attribution() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    acquisition_census_b1_plan.create(engine)
    acquisition_census_call.create(engine)
    with engine.begin() as connection:
        connection.execute(sa.insert(acquisition_census_b1_plan).values(
            plan_id="synthetic-b1-plan", census_id="synthetic-census",
            plan_hash="b" * 64, seed="synthetic",
            caps={"min_remaining_pool_balance": 1000}, cumulative_limits={},
            pool_before=1956, status="ACTIVE", created_at=NOW, updated_at=NOW,
        ))
        connection.execute(sa.insert(acquisition_census_call).values(
            call_id="c" * 64, permit_id="synthetic-b1-plan",
            census_id="synthetic-census", kind="PERSON_ENRICH",
            subject_hash="d" * 64, attempt=1, status="COMPLETED",
            reserved_credits=1, candidate_slots=0,
            started_at=NOW, completed_at=NOW,
        ))
    store = B1PlanStore(engine)
    report = store.reconcile_usage("synthetic-b1-plan", pool_after=1954, at=NOW)
    assert report["shared_pool_delta"] == 2
    assert report["run_credits_reserved_upper_bound"] == 1
    assert report["shared_pool_attribution"] == "AMBIGUOUS_SHARED_POOL"
    with engine.connect() as connection:
        assert connection.scalar(sa.select(acquisition_census_b1_plan.c.pool_after)) == 1954
    assert store.reconcile_usage("synthetic-b1-plan", pool_after=1954, at=NOW) == report
    for invalid in (999, 1957, 1953):
        with pytest.raises(CensusReviewRequired):
            store.reconcile_usage("synthetic-b1-plan", pool_after=invalid, at=NOW)
