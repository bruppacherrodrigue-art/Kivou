"""A1 pays at most one credit per ledger entry and pauses on shared-pool drift."""

import datetime as dt

import pytest
import sqlalchemy as sa
from test_milomail_a1_permit import _a1_limits, _a1_permit
from test_milomail_a1_plan import _a0

from signals.acquisition_programs.apollo_account import ApolloAccountState
from signals.acquisition_programs.census import CensusReviewRequired, CensusStore
from signals.acquisition_programs.census_sampling import SamplePlanStore
from signals.acquisition_programs.census_usage_guard import A1UsageGuard
from signals.persistence.schema import acquisition_census_call, acquisition_census_permit
from signals.supplier_discovery.contracts import SupplierSearchPage

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


def _state(balance: int, calls: int) -> ApolloAccountState:
    return ApolloAccountState(
        credential_valid=True, credit_balance=balance,
        usage_stats_available=True, rate_stats_available=True,
        credit_balances={"lead_credit": balance},
        organization_search_day_consumed=calls,
        organization_search_day_limit=50_000,
    )


def test_a1_usage_baseline_is_durable_and_concurrent_pool_change_stops_run() -> None:
    engine, census_id = _a0()
    plan = SamplePlanStore(engine).plan(
        census_id, permit_id="synthetic-a1-permit", max_new_pages=1, at=NOW,
    )
    store = CensusStore(engine, require_permit=False)
    store.start(census_id, _a1_limits(max_pages=10, max_candidates=250,
                                      max_apollo_credits=10), at=NOW,
                phase="COVERAGE_A1_SAMPLE", sample_plan_id=plan["plan_id"])
    current = [_state(2126, 9)]
    guard = A1UsageGuard(engine, permit_id=plan["plan_id"], probe=lambda: current[0])
    assert guard.begin(at=NOW) == {"pool_before": 2126, "org_search_day_before": 9}
    selected = plan["pages"][0]
    page = SupplierSearchPage(page=selected["page"], per_page=25,
                              total_entries=750, total_pages=30,
                              candidates=(), rejections=())
    completed, call_id = store.execute_call(
        census_id, kind="ORG_SEARCH",
        subject=f"{selected['partition_id']}:{selected['page']}",
        partition_id=selected["partition_id"], credits=1, candidate_slots=25,
        at=NOW, invoke=lambda: page,
        encode=lambda value: value.model_dump(mode="json"),
        decode=SupplierSearchPage.model_validate,
    )
    store.record_sample_page(census_id, plan["plan_id"], selected["partition_id"],
                             completed, call_id=call_id, at=NOW)
    # The synthetic store bypasses permits; assign its call to the synthetic
    # permit so the ledger has the same shape as an authorized real run.
    with engine.begin() as connection:
        connection.execute(sa.insert(acquisition_census_permit).values(**_a1_permit(
            census_id=census_id,
            sample_plan_hash=plan["plan_hash"],
        ).model_dump(mode="python")))
        connection.execute(sa.update(acquisition_census_call).where(
            acquisition_census_call.c.call_id == call_id,
        ).values(permit_id=plan["plan_id"]))
    current[0] = _state(2125, 10)
    guard.after_checkpoint()
    assert guard.begin(at=NOW) == {"pool_before": 2126, "org_search_day_before": 9}
    current[0] = _state(2124, 11)
    with pytest.raises(CensusReviewRequired):
        guard.begin(at=NOW)


def test_a1_usage_guard_requires_free_counter_before_first_paid_call() -> None:
    engine, census_id = _a0()
    SamplePlanStore(engine).plan(census_id, permit_id="synthetic-a1-permit", at=NOW)
    guard = A1UsageGuard(engine, permit_id="synthetic-a1-permit",
                         probe=lambda: None)
    with pytest.raises(CensusReviewRequired):
        guard.begin(at=NOW)
