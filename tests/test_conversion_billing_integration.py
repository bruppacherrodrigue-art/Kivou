from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from billing_helpers import FakeStripe, subscription_state
from test_conversion_attribution import NOW, create_account, prepared

from signals.billing.gateway import StripeEvent
from signals.billing.webhooks import RESULT_APPLIED, RESULT_DUPLICATE, handle_event
from signals.conversion.milestones import ConversionMilestoneService
from signals.persistence.schema import acquisition_conversion_event


def test_existing_stripe_webhook_transaction_records_paid_once_without_new_endpoint(
    tmp_path,
) -> None:
    engine, attribution, token, _ = prepared(tmp_path)
    attribution.record_click(token.raw_token, at=NOW + dt.timedelta(hours=1))
    with engine.begin() as connection:
        account_id = create_account(connection, suffix="stripe-hook", now=NOW + dt.timedelta(days=1))
        assert attribution.bind_signup_in_transaction(
            connection,
            account_id=account_id,
            raw_token=token.raw_token,
            at=NOW + dt.timedelta(days=1),
        )

    state = subscription_state(
        subscription_id="sub_synthetic_conversion_hook",
        customer_id="cus_synthetic_conversion_hook",
        account_id=account_id,
        lookup_key="kivou_pro_monthly_chf",
        currency="chf",
        status="active",
    )
    gateway = FakeStripe()
    gateway.put_subscription(state)
    event = StripeEvent(
        event_id="evt_synthetic_conversion_hook",
        event_type="customer.subscription.updated",
        created=NOW + dt.timedelta(days=3),
        livemode=False,
        object_id=state.subscription_id,
        data_object={"id": state.subscription_id},
    )
    payload = b'{"synthetic":"conversion-hook"}'
    observer = ConversionMilestoneService(engine)

    with engine.begin() as connection:
        first = handle_event(
            connection,
            gateway,
            event,
            payload=payload,
            expect_livemode=False,
            now=event.created,
            conversion_milestone_service=observer,
        )
    with engine.begin() as connection:
        second = handle_event(
            connection,
            gateway,
            event,
            payload=payload,
            expect_livemode=False,
            now=event.created,
            conversion_milestone_service=observer,
        )

    assert first.result == RESULT_APPLIED
    assert second.result == RESULT_DUPLICATE
    with engine.connect() as connection:
        values = tuple(
            connection.scalars(
                sa.select(acquisition_conversion_event.c.milestone).where(
                    acquisition_conversion_event.c.milestone.in_(("PAID", "MRR_CHANGED"))
                )
            )
        )
    assert sorted(values) == ["MRR_CHANGED", "PAID"]

