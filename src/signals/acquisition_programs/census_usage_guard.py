"""Stop A1 when free Apollo account counters diverge from our paid-call ledger."""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition_programs.apollo_account import ApolloAccountState
from signals.acquisition_programs.census import CensusReviewRequired
from signals.persistence.schema import acquisition_census_call, acquisition_census_sample_plan


class A1UsageGuard:
    """Persist the pre-run counters and verify them after each checkpoint."""

    def __init__(self, engine: Engine, *, permit_id: str,
                 probe: Callable[[], ApolloAccountState | None]) -> None:
        self.engine = engine
        self.permit_id = permit_id
        self.probe = probe

    @staticmethod
    def _counts(state: ApolloAccountState | None) -> tuple[int, int]:
        if (state is None or not state.credential_valid or
                state.credit_balance is None or
                state.organization_search_day_consumed is None):
            raise CensusReviewRequired("Apollo account usage counters are unavailable")
        return state.credit_balance, state.organization_search_day_consumed

    def begin(self, *, at: dt.datetime) -> dict[str, int]:
        balance, counter = self._counts(self.probe())
        with self.engine.begin() as connection:
            plan = connection.execute(sa.select(acquisition_census_sample_plan).where(
                acquisition_census_sample_plan.c.plan_id == self.permit_id,
            ).with_for_update()).mappings().one()
            used = connection.execute(sa.select(
                sa.func.coalesce(sa.func.sum(acquisition_census_call.c.reserved_credits), 0),
                sa.func.count(),
            ).where(acquisition_census_call.c.permit_id == self.permit_id)).one()
            if used[0] != used[1]:
                raise CensusReviewRequired("A1 ledger is not one credit per organization call")
            if plan["apollo_pool_before"] is None:
                if used[1] != 0 or plan["apollo_org_search_day_before"] is not None:
                    raise CensusReviewRequired("A1 usage baseline was not captured before paid use")
                connection.execute(sa.update(acquisition_census_sample_plan).where(
                    acquisition_census_sample_plan.c.plan_id == self.permit_id,
                ).values(apollo_pool_before=balance,
                         apollo_org_search_day_before=counter,
                         usage_baseline_at=at))
                return {"pool_before": balance, "org_search_day_before": counter}
            before_balance = plan["apollo_pool_before"]
            before_counter = plan["apollo_org_search_day_before"]
            if (before_counter is None or balance != before_balance - used[0] or
                    counter != before_counter + used[1]):
                raise CensusReviewRequired("shared Apollo pool or search counter diverged")
            return {"pool_before": before_balance, "org_search_day_before": before_counter}

    def after_checkpoint(self) -> None:
        with self.engine.connect() as connection:
            plan = connection.execute(sa.select(acquisition_census_sample_plan).where(
                acquisition_census_sample_plan.c.plan_id == self.permit_id,
            )).mappings().one()
            used = connection.execute(sa.select(
                sa.func.coalesce(sa.func.sum(acquisition_census_call.c.reserved_credits), 0),
                sa.func.count(),
            ).where(acquisition_census_call.c.permit_id == self.permit_id)).one()
        if (plan["apollo_pool_before"] is None or
                plan["apollo_org_search_day_before"] is None or used[0] != used[1]):
            raise CensusReviewRequired("A1 usage baseline or ledger is inconsistent")
        # Apollo usage stats may lag a successful search by a few seconds.
        # Every probe is a documented free account endpoint, never a search.
        for attempt in range(3):
            try:
                balance, counter = self._counts(self.probe())
            except CensusReviewRequired:
                balance = counter = -1
            if (balance == plan["apollo_pool_before"] - used[0] and
                    counter == plan["apollo_org_search_day_before"] + used[1]):
                return
            if attempt < 2:
                time.sleep(1)
        raise CensusReviewRequired("shared Apollo pool or search counter diverged")

    def status(self) -> dict[str, int | None]:
        with self.engine.connect() as connection:
            plan = connection.execute(sa.select(acquisition_census_sample_plan).where(
                acquisition_census_sample_plan.c.plan_id == self.permit_id,
            )).mappings().one()
        balance: int | None
        counter: int | None
        try:
            balance, counter = self._counts(self.probe())
        except CensusReviewRequired:
            balance = counter = None
        return {"pool_before": plan["apollo_pool_before"],
                "pool_after": balance,
                "org_search_day_before": plan["apollo_org_search_day_before"],
                "org_search_day_after": counter}
