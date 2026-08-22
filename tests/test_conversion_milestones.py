from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa
from test_conversion_attribution import NOW, create_account, prepared

from signals.accounts import service as account_service
from signals.accounts.icp_input import MonetaryThreshold, TargetIcpInput
from signals.acquisition.contracts import AcquisitionState, EventType
from signals.billing.gateway import StripeSubscriptionState
from signals.billing.service import synchronize_subscription
from signals.conversion.milestones import ConversionMilestoneService
from signals.conversion.worker import ConversionRetentionWorker
from signals.persistence.schema import (
    acquisition_conversion_event,
    acquisition_opportunity,
)


def attributed_account(tmp_path):
    engine, attribution, token, opportunity_id = prepared(tmp_path)
    attribution.record_click(token.raw_token, at=NOW + dt.timedelta(hours=1))
    with engine.begin() as connection:
        account_id = create_account(connection, suffix="milestones", now=NOW + dt.timedelta(days=1))
        journey = attribution.bind_signup_in_transaction(
            connection,
            account_id=account_id,
            raw_token=token.raw_token,
            at=NOW + dt.timedelta(days=1),
        )
    assert journey is not None
    return engine, account_id, opportunity_id, journey


def activate(connection, *, account_id: str, now: dt.datetime) -> None:
    account_service.create_target_icp(
        connection,
        account_id=account_id,
        label="Synthetic Active ICP",
        customer_input=TargetIcpInput(
            offers=("materials_and_components",),
            territories=("CH",),
            minimum_contract_value=MonetaryThreshold(
                currency="CHF", minimum_amount=1000
            ),
        ),
        now=now,
    )


def subscription(
    account_id: str,
    *,
    status: str = "active",
    lookup_key: str | None = "kivou_pro_monthly_chf",
    currency: str = "chf",
    canceled_at: dt.datetime | None = None,
    scheduled_cancellation_at: dt.datetime | None = None,
    discount_coupon_id: str | None = None,
) -> StripeSubscriptionState:
    return StripeSubscriptionState(
        subscription_id="sub_synthetic_conversion",
        customer_id="cus_synthetic_conversion",
        status=status,
        price_id="price_synthetic_conversion",
        product_id="prod_synthetic_conversion",
        lookup_key=lookup_key,
        currency=currency,
        current_period_start=NOW,
        current_period_end=NOW + dt.timedelta(days=30),
        cancel_at_period_end=scheduled_cancellation_at is not None,
        canceled_at=canceled_at,
        livemode=False,
        account_id=account_id,
        discount_coupon_id=discount_coupon_id,
        scheduled_cancellation_at=scheduled_cancellation_at,
    )


def sync(connection, state: StripeSubscriptionState, *, now: dt.datetime):
    stored, _ = synchronize_subscription(
        connection,
        state,
        account_id=state.account_id or "missing",
        event_created_at=now,
        expect_livemode=False,
        now=now,
    )
    return stored


def milestones(engine) -> list[dict]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                sa.select(acquisition_conversion_event).order_by(
                    acquisition_conversion_event.c.recorded_at,
                    acquisition_conversion_event.c.milestone,
                )
            ).mappings()
        )


def test_activation_requires_real_ready_for_signals_and_is_idempotent(tmp_path) -> None:
    engine, account_id, opportunity_id, _ = attributed_account(tmp_path)
    service = ConversionMilestoneService(engine)
    at = NOW + dt.timedelta(days=2)
    with engine.begin() as connection:
        assert service.observe_activation_in_transaction(
            connection, account_id=account_id, observed_at=at
        ) is None
        activate(connection, account_id=account_id, now=at)
        first = service.observe_activation_in_transaction(
            connection, account_id=account_id, observed_at=at
        )
        second = service.observe_activation_in_transaction(
            connection, account_id=account_id, observed_at=at
        )

    assert first == second
    assert [row["milestone"] for row in milestones(engine)].count("ACTIVATED") == 1
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(acquisition_opportunity.c.state).where(
                acquisition_opportunity.c.acquisition_opportunity_id == opportunity_id
            )
        ) == AcquisitionState.ACTIVATED.value


def test_active_known_subscription_records_paid_and_reproducible_monthly_mrr(tmp_path) -> None:
    engine, account_id, opportunity_id, _ = attributed_account(tmp_path)
    service = ConversionMilestoneService(engine)
    at = NOW + dt.timedelta(days=3)
    with engine.begin() as connection:
        stored = sync(connection, subscription(account_id), now=at)
        first = service.observe_billing_in_transaction(
            connection, account_id=account_id, subscription=stored, observed_at=at
        )
        second = service.observe_billing_in_transaction(
            connection, account_id=account_id, subscription=stored, observed_at=at
        )

    assert first == second
    events = milestones(engine)
    assert [row["milestone"] for row in events].count("PAID") == 1
    mrr = next(row for row in events if row["milestone"] == "MRR_CHANGED")
    assert mrr["mrr_known"] is True
    assert mrr["mrr_minor_units"] == 9900
    assert mrr["currency"] == "chf"
    assert "sub_synthetic_conversion" not in repr(events)
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(acquisition_opportunity.c.state).where(
                acquisition_opportunity.c.acquisition_opportunity_id == opportunity_id
            )
        ) == AcquisitionState.PAID.value


def test_founding_mrr_and_unknown_plan_never_invent_revenue(tmp_path) -> None:
    engine, account_id, _, _ = attributed_account(tmp_path)
    service = ConversionMilestoneService(engine)
    at = NOW + dt.timedelta(days=3)
    with engine.begin() as connection:
        stored = sync(
            connection,
            subscription(account_id, discount_coupon_id="coupon_synthetic"),
            now=at,
        )
        service.observe_billing_in_transaction(
            connection, account_id=account_id, subscription=stored, observed_at=at
        )
    assert next(
        row["mrr_minor_units"]
        for row in milestones(engine)
        if row["milestone"] == "MRR_CHANGED"
    ) == 2900

    unknown = dataclasses.replace(stored, plan_code=None)
    with engine.begin() as connection:
        service.observe_billing_in_transaction(
            connection,
            account_id=account_id,
            subscription=unknown,
            observed_at=at + dt.timedelta(hours=1),
        )
    latest = [row for row in milestones(engine) if row["milestone"] == "MRR_CHANGED"][-1]
    assert latest["mrr_known"] is False
    assert latest["mrr_minor_units"] is None
    assert latest["reason_code"] == "MRR_UNKNOWN_PLAN"


def test_mrr_change_chain_records_a_reversion_without_duplicate_same_value(tmp_path) -> None:
    engine, account_id, _, _ = attributed_account(tmp_path)
    service = ConversionMilestoneService(engine)
    at = NOW + dt.timedelta(days=3)
    with engine.begin() as connection:
        pro = sync(connection, subscription(account_id), now=at)
        service.observe_billing_in_transaction(
            connection, account_id=account_id, subscription=pro, observed_at=at
        )
        essential = dataclasses.replace(pro, plan_code="essential")
        service.observe_billing_in_transaction(
            connection,
            account_id=account_id,
            subscription=essential,
            observed_at=at + dt.timedelta(hours=1),
        )
        service.observe_billing_in_transaction(
            connection,
            account_id=account_id,
            subscription=essential,
            observed_at=at + dt.timedelta(hours=2),
        )
        service.observe_billing_in_transaction(
            connection,
            account_id=account_id,
            subscription=pro,
            observed_at=at + dt.timedelta(hours=3),
        )

    amounts = [
        row["mrr_minor_units"]
        for row in milestones(engine)
        if row["milestone"] == "MRR_CHANGED"
    ]
    assert amounts == [9900, 4900, 9900]


def test_scheduled_cancel_and_past_due_are_not_churn_but_canceled_after_paid_is(tmp_path) -> None:
    engine, account_id, opportunity_id, _ = attributed_account(tmp_path)
    service = ConversionMilestoneService(engine)
    paid_at = NOW + dt.timedelta(days=3)
    with engine.begin() as connection:
        paid = sync(connection, subscription(account_id), now=paid_at)
        service.observe_billing_in_transaction(
            connection, account_id=account_id, subscription=paid, observed_at=paid_at
        )
        scheduled = dataclasses.replace(
            paid,
            cancel_at_period_end=True,
            scheduled_cancellation_at=paid_at + dt.timedelta(days=20),
        )
        service.observe_billing_in_transaction(
            connection,
            account_id=account_id,
            subscription=scheduled,
            observed_at=paid_at + dt.timedelta(days=1),
        )
        past_due = dataclasses.replace(paid, status="past_due")
        service.observe_billing_in_transaction(
            connection,
            account_id=account_id,
            subscription=past_due,
            observed_at=paid_at + dt.timedelta(days=2),
        )
    assert not any(row["milestone"] == "CHURNED" for row in milestones(engine))

    churn_at = paid_at + dt.timedelta(days=25)
    with engine.begin() as connection:
        canceled = dataclasses.replace(paid, status="canceled", canceled_at=churn_at)
        first = service.observe_billing_in_transaction(
            connection,
            account_id=account_id,
            subscription=canceled,
            observed_at=churn_at,
        )
        second = service.observe_billing_in_transaction(
            connection,
            account_id=account_id,
            subscription=canceled,
            observed_at=churn_at,
        )
    assert first == second
    assert [row["milestone"] for row in milestones(engine)].count("CHURNED") == 1
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(acquisition_opportunity.c.state).where(
                acquisition_opportunity.c.acquisition_opportunity_id == opportunity_id
            )
        ) == AcquisitionState.CHURNED.value


def test_explicit_worker_records_m1_m2_only_when_paying_and_activated(tmp_path) -> None:
    engine, account_id, _, _ = attributed_account(tmp_path)
    service = ConversionMilestoneService(engine)
    paid_at = NOW + dt.timedelta(days=3)
    with engine.begin() as connection:
        activate(connection, account_id=account_id, now=paid_at)
        service.observe_activation_in_transaction(
            connection, account_id=account_id, observed_at=paid_at
        )
        stored = sync(connection, subscription(account_id), now=paid_at)
        service.observe_billing_in_transaction(
            connection, account_id=account_id, subscription=stored, observed_at=paid_at
        )

    worker = ConversionRetentionWorker(engine, service)
    assert worker.run(at=paid_at + dt.timedelta(days=29)) == ()
    assert len(worker.run(at=paid_at + dt.timedelta(days=30))) == 1
    assert len(worker.run(at=paid_at + dt.timedelta(days=60))) == 1
    assert worker.run(at=paid_at + dt.timedelta(days=61)) == ()
    assert [row["milestone"] for row in milestones(engine)].count("RETAINED_M1") == 1
    assert [row["milestone"] for row in milestones(engine)].count("RETAINED_M2") == 1
    assert EventType.OUTCOME_RECORDED.value in {
        row[0]
        for row in engine.connect().execute(
            sa.text("SELECT event_type FROM acquisition_event")
        )
    }
