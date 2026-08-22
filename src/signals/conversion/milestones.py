"""Derive conversion milestones from current Kivou account and billing truth."""

from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa

from signals.accounts.schema import account, target_icp
from signals.acquisition.contracts import AcquisitionState, EventType
from signals.acquisition.store import AcquisitionStore
from signals.billing import catalogue
from signals.billing.service import StoredSubscription
from signals.conversion.contracts import (
    CONVERSION_EVENT_VERSION,
    ConversionMilestone,
)
from signals.decision_engine.policy import semantic_fingerprint
from signals.persistence.schema import (
    acquisition_conversion_event,
    acquisition_conversion_journey,
)


@dataclasses.dataclass(frozen=True)
class MilestoneResult:
    conversion_event_ref: str
    milestone: ConversionMilestone
    outcome_event_ref: str | None


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


class ConversionMilestoneService:
    def __init__(self, engine: sa.Engine) -> None:
        self.engine = engine

    def observe_activation_in_transaction(
        self,
        connection: sa.Connection,
        *,
        account_id: str,
        observed_at: dt.datetime,
    ) -> MilestoneResult | None:
        journey = self._journey(connection, account_id)
        if journey is None:
            return None
        row = connection.execute(
            sa.select(account.c.onboarding_status).where(account.c.account_id == account_id)
        ).scalar_one_or_none()
        active = tuple(
            connection.scalars(
                sa.select(target_icp.c.target_icp_id)
                .where(
                    target_icp.c.account_id == account_id,
                    target_icp.c.status == "active",
                )
                .order_by(target_icp.c.target_icp_id)
            )
        )
        if row != "ready_for_signals" or not active:
            return None
        activation_fingerprint = semantic_fingerprint(
            {
                "kind": "conversion-activation-v1",
                "account_id": account_id,
                "onboarding_status": row,
                "active_target_icps": active,
            }
        )
        return self._ensure_event(
            connection,
            journey=journey,
            milestone=ConversionMilestone.ACTIVATED,
            observed_at=observed_at,
            identity={"journey_ref": journey["journey_ref"]},
            activation_fingerprint=activation_fingerprint,
            outcome_state=AcquisitionState.ACTIVATED,
            reason_code="ACCOUNT_READY_FOR_SIGNALS",
        )

    def observe_billing_in_transaction(
        self,
        connection: sa.Connection,
        *,
        account_id: str,
        subscription: StoredSubscription,
        observed_at: dt.datetime,
    ) -> tuple[MilestoneResult, ...]:
        journey = self._journey(connection, account_id)
        if journey is None:
            return ()
        results: list[MilestoneResult] = []
        subscription_ref = semantic_fingerprint(
            {
                "kind": "conversion-billing-subscription-ref-v1",
                "subscription_id": subscription.stripe_subscription_id,
            }
        )
        if subscription.grants_paid_access:
            paid = self._ensure_event(
                connection,
                journey=journey,
                milestone=ConversionMilestone.PAID,
                observed_at=observed_at,
                identity={"journey_ref": journey["journey_ref"]},
                billing_subscription_ref=subscription_ref,
                outcome_state=AcquisitionState.PAID,
                reason_code="BILLING_SUBSCRIPTION_PAYING",
            )
            results.append(paid)
            money = self._mrr(subscription)
            results.append(
                self._ensure_mrr_event(
                    connection,
                    journey=journey,
                    subscription_ref=subscription_ref,
                    observed_at=observed_at,
                    **money,
                )
            )
            return tuple(results)

        if subscription.status == "active" and (
            subscription.plan_code not in catalogue.PURCHASABLE_PLANS
            or subscription.currency not in catalogue.CURRENCIES
        ):
            results.append(
                self._ensure_mrr_event(
                    connection,
                    journey=journey,
                    subscription_ref=subscription_ref,
                    observed_at=observed_at,
                    known=False,
                    amount=None,
                    currency=None,
                    reason="MRR_UNKNOWN_PLAN",
                )
            )
            return tuple(results)

        if subscription.status == "canceled" and self._has_milestone(
            connection, journey["journey_ref"], ConversionMilestone.PAID
        ):
            churn_at = subscription.canceled_at or observed_at
            results.append(
                self._ensure_event(
                    connection,
                    journey=journey,
                    milestone=ConversionMilestone.CHURNED,
                    observed_at=observed_at,
                    occurred_at=churn_at,
                    identity={"journey_ref": journey["journey_ref"]},
                    billing_subscription_ref=subscription_ref,
                    outcome_state=AcquisitionState.CHURNED,
                    reason_code="BILLING_SUBSCRIPTION_CANCELED",
                )
            )
            if subscription.currency in catalogue.CURRENCIES:
                results.append(
                    self._ensure_mrr_event(
                        connection,
                        journey=journey,
                        subscription_ref=subscription_ref,
                        observed_at=observed_at,
                        known=True,
                        amount=0,
                        currency=subscription.currency,
                        reason=None,
                    )
                )
        return tuple(results)

    def record_retention_in_transaction(
        self,
        connection: sa.Connection,
        *,
        account_id: str,
        at: dt.datetime,
    ) -> tuple[MilestoneResult, ...]:
        from signals.billing.service import current_subscription

        journey = self._journey(connection, account_id)
        if journey is None or self._has_milestone(
            connection, journey["journey_ref"], ConversionMilestone.CHURNED
        ):
            return ()
        paid = self._event_for_milestone(
            connection, journey["journey_ref"], ConversionMilestone.PAID
        )
        subscription = current_subscription(connection, account_id=account_id)
        if paid is None or subscription is None or not subscription.grants_paid_access:
            return ()
        status = connection.execute(
            sa.select(account.c.onboarding_status).where(account.c.account_id == account_id)
        ).scalar_one_or_none()
        active_count = connection.scalar(
            sa.select(sa.func.count())
            .select_from(target_icp)
            .where(target_icp.c.account_id == account_id, target_icp.c.status == "active")
        )
        if status != "ready_for_signals" or not active_count:
            return ()
        first_paid_at = _aware(paid["occurred_at"])
        observed = _aware(at)
        results: list[MilestoneResult] = []
        for days, milestone in (
            (30, ConversionMilestone.RETAINED_M1),
            (60, ConversionMilestone.RETAINED_M2),
        ):
            if observed < first_paid_at + dt.timedelta(days=days):
                continue
            if self._has_milestone(connection, journey["journey_ref"], milestone):
                continue
            results.append(
                self._ensure_event(
                    connection,
                    journey=journey,
                    milestone=milestone,
                    observed_at=at,
                    identity={
                        "journey_ref": journey["journey_ref"],
                        "first_paid_event_ref": paid["conversion_event_ref"],
                        "retention_days": days,
                    },
                    outcome_state=(
                        AcquisitionState.RETAINED
                        if milestone is ConversionMilestone.RETAINED_M1
                        else None
                    ),
                    reason_code=f"PAYING_AND_ACTIVATED_DAY_{days}",
                )
            )
        return tuple(results)

    @staticmethod
    def _mrr(subscription: StoredSubscription) -> dict[str, object]:
        if (
            subscription.plan_code not in catalogue.PURCHASABLE_PLANS
            or subscription.currency not in catalogue.CURRENCIES
        ):
            return {
                "known": False,
                "amount": None,
                "currency": None,
                "reason": "MRR_UNKNOWN_PLAN",
            }
        amount = (
            catalogue.FOUNDING_EFFECTIVE_MINOR_UNITS
            if subscription.offer_code == "founding"
            else catalogue.amount_for(subscription.plan_code, subscription.currency)
        )
        return {
            "known": True,
            "amount": amount,
            "currency": subscription.currency,
            "reason": None,
        }

    def _ensure_mrr_event(
        self,
        connection: sa.Connection,
        *,
        journey: sa.RowMapping,
        subscription_ref: str,
        observed_at: dt.datetime,
        known: bool,
        amount: int | None,
        currency: str | None,
        reason: str | None,
    ) -> MilestoneResult:
        latest = connection.execute(
            sa.select(acquisition_conversion_event)
            .where(
                acquisition_conversion_event.c.journey_ref == journey["journey_ref"],
                acquisition_conversion_event.c.milestone
                == ConversionMilestone.MRR_CHANGED.value,
            )
            .order_by(
                acquisition_conversion_event.c.occurred_at.desc(),
                acquisition_conversion_event.c.conversion_event_ref.desc(),
            )
        ).mappings().first()
        if latest is not None and (
            latest["catalogue_version"] == catalogue.CATALOGUE_VERSION
            and latest["mrr_known"] is known
            and latest["mrr_minor_units"] == amount
            and latest["currency"] == currency
            and latest["reason_code"] == reason
        ):
            return MilestoneResult(
                latest["conversion_event_ref"],
                ConversionMilestone.MRR_CHANGED,
                latest["outcome_event_ref"],
            )
        return self._ensure_event(
            connection,
            journey=journey,
            milestone=ConversionMilestone.MRR_CHANGED,
            observed_at=observed_at,
            identity={
                "journey_ref": journey["journey_ref"],
                "subscription_ref": subscription_ref,
                "catalogue_version": catalogue.CATALOGUE_VERSION,
                "known": known,
                "amount": amount,
                "currency": currency,
                "reason": reason,
                "previous_mrr_event_ref": (
                    latest["conversion_event_ref"] if latest is not None else None
                ),
            },
            billing_subscription_ref=subscription_ref,
            catalogue_version=catalogue.CATALOGUE_VERSION,
            mrr_known=known,
            mrr_minor_units=amount,
            currency=currency,
            reason_code=reason,
        )

    def _ensure_event(
        self,
        connection: sa.Connection,
        *,
        journey: sa.RowMapping,
        milestone: ConversionMilestone,
        observed_at: dt.datetime,
        identity: dict[str, object],
        occurred_at: dt.datetime | None = None,
        activation_fingerprint: str | None = None,
        billing_subscription_ref: str | None = None,
        catalogue_version: str | None = None,
        mrr_known: bool | None = None,
        mrr_minor_units: int | None = None,
        currency: str | None = None,
        reason_code: str | None = None,
        outcome_state: AcquisitionState | None = None,
    ) -> MilestoneResult:
        event_ref = semantic_fingerprint(
            {
                "kind": CONVERSION_EVENT_VERSION,
                "milestone": milestone.value,
                **identity,
            }
        )
        existing = connection.execute(
            sa.select(acquisition_conversion_event).where(
                acquisition_conversion_event.c.conversion_event_ref == event_ref
            )
        ).mappings().one_or_none()
        if existing is not None:
            return MilestoneResult(event_ref, milestone, existing["outcome_event_ref"])

        outcome_event_ref = None
        if outcome_state is not None:
            acquisition = AcquisitionStore(self.engine, clock=lambda: observed_at)
            current = acquisition.get_opportunity_in_transaction(
                connection, journey["acquisition_opportunity_id"]
            )
            outcome = acquisition.append_in_transaction(
                connection,
                journey["acquisition_opportunity_id"],
                event_type=EventType.OUTCOME_RECORDED,
                expected_version=current.stream_version,
                idempotency_key=f"conversion-outcome:{event_ref}",
                payload={"outcome_state": outcome_state.value},
                reason_codes=(reason_code or f"CONVERSION_{milestone.value}",),
                evidence_refs=(f"conversion-event:{event_ref}",),
                occurred_at=occurred_at or observed_at,
            )
            outcome_event_ref = outcome.event.event_id
        values = {
            "conversion_event_ref": event_ref,
            "journey_ref": journey["journey_ref"],
            "milestone": milestone.value,
            "event_version": CONVERSION_EVENT_VERSION,
            "event_fingerprint": event_ref,
            "token_fingerprint": None,
            "trigger_ref_type": (
                "BILLING_STATE"
                if billing_subscription_ref
                else "ACCOUNT_PRODUCT_STATE"
            ),
            "trigger_ref": billing_subscription_ref or activation_fingerprint,
            "account_id": journey["account_id"],
            "campaign_ref": journey["campaign_ref"],
            "member_ref": journey["member_ref"],
            "acquisition_opportunity_id": journey["acquisition_opportunity_id"],
            "activation_fingerprint": activation_fingerprint,
            "billing_subscription_ref": billing_subscription_ref,
            "catalogue_version": catalogue_version,
            "mrr_known": mrr_known,
            "mrr_minor_units": mrr_minor_units,
            "currency": currency,
            "reason_code": reason_code,
            "outcome_event_ref": outcome_event_ref,
            "occurred_at": occurred_at or observed_at,
            "observed_at": observed_at,
            "recorded_at": observed_at,
        }
        connection.execute(sa.insert(acquisition_conversion_event).values(**values))
        return MilestoneResult(event_ref, milestone, outcome_event_ref)

    @staticmethod
    def _journey(connection: sa.Connection, account_id: str):
        return connection.execute(
            sa.select(acquisition_conversion_journey)
            .where(acquisition_conversion_journey.c.account_id == account_id)
            .with_for_update()
        ).mappings().one_or_none()

    @staticmethod
    def _event_for_milestone(
        connection: sa.Connection, journey_ref: str, milestone: ConversionMilestone
    ):
        return connection.execute(
            sa.select(acquisition_conversion_event)
            .where(
                acquisition_conversion_event.c.journey_ref == journey_ref,
                acquisition_conversion_event.c.milestone == milestone.value,
            )
            .order_by(acquisition_conversion_event.c.occurred_at)
        ).mappings().first()

    def _has_milestone(
        self, connection: sa.Connection, journey_ref: str, milestone: ConversionMilestone
    ) -> bool:
        return self._event_for_milestone(connection, journey_ref, milestone) is not None


__all__ = ["ConversionMilestoneService", "MilestoneResult"]
