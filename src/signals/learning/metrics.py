"""Repository aggregation into immutable country-by-wedge learning facts."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import sqlalchemy as sa

from signals.learning.contracts import LearningCellKey, LearningCellMetrics, LearningWindow
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_conversion_event,
    acquisition_conversion_journey,
    acquisition_provider_event,
    acquisition_response_evaluation,
    policy_evaluation,
)


def _utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


@dataclass(frozen=True)
class LearningCostFact:
    amount_minor_units: int
    currency: str | None
    complete: bool
    missing_reason_codes: tuple[str, ...] = ()


class LearningCostSource(Protocol):
    def for_cell(
        self,
        connection: sa.Connection,
        *,
        cell: LearningCellKey,
        member_refs: frozenset[str],
        window: LearningWindow,
    ) -> LearningCostFact: ...


class RepositoryLearningCostSource:
    """The current repository has no complete provider/mailbox cost authority."""

    def for_cell(
        self,
        connection: sa.Connection,
        *,
        cell: LearningCellKey,
        member_refs: frozenset[str],
        window: LearningWindow,
    ) -> LearningCostFact:
        del cell
        if not member_refs:
            return LearningCostFact(
                amount_minor_units=0,
                currency=None,
                complete=False,
                missing_reason_codes=(
                    "MAILBOX_COST_UNAVAILABLE",
                    "PROVIDER_COST_UNAVAILABLE",
                ),
            )
        schedule_costs = connection.execute(
            sa.select(
                policy_evaluation.c.evaluation_id,
                policy_evaluation.c.estimated_cost,
                policy_evaluation.c.currency,
            )
            .select_from(
                acquisition_campaign_member.join(
                    policy_evaluation,
                    acquisition_campaign_member.c.policy_evaluation_id
                    == policy_evaluation.c.evaluation_id,
                )
            )
            .where(acquisition_campaign_member.c.member_ref.in_(tuple(member_refs)))
            .distinct()
        ).mappings()
        response_costs = connection.execute(
            sa.select(
                acquisition_response_evaluation.c.response_evaluation_id,
                acquisition_response_evaluation.c.actual_cost,
                policy_evaluation.c.currency,
            )
            .select_from(
                acquisition_response_evaluation.outerjoin(
                    policy_evaluation,
                    acquisition_response_evaluation.c.policy_evaluation_id
                    == policy_evaluation.c.evaluation_id,
                )
            )
            .where(
                acquisition_response_evaluation.c.member_ref.in_(tuple(member_refs)),
                acquisition_response_evaluation.c.processing_state == "FINALIZED",
                acquisition_response_evaluation.c.finalized_at < window.window_end,
                acquisition_response_evaluation.c.actual_cost.is_not(None),
            )
            .distinct()
        ).mappings()
        total = Decimal(0)
        currencies: set[str] = set()
        missing = {"MAILBOX_COST_UNAVAILABLE", "PROVIDER_COST_UNAVAILABLE"}
        for row in (*schedule_costs, *response_costs):
            amount = row["estimated_cost"] if "estimated_cost" in row else row["actual_cost"]
            if amount is None:
                continue
            currency = str(row["currency"] or "").upper()
            if currency not in {"CHF", "EUR"}:
                missing.add("COST_CURRENCY_UNAVAILABLE")
                continue
            currencies.add(currency)
            total += Decimal(amount)
        scaled = total * 100
        if scaled != scaled.to_integral_value():
            missing.add("SUB_MINOR_COST_UNREPRESENTABLE")
            amount_minor_units = 0
        else:
            amount_minor_units = int(scaled)
        if len(currencies) > 1:
            missing.add("COST_CURRENCY_MIXED")
        return LearningCostFact(
            amount_minor_units=amount_minor_units,
            currency=next(iter(currencies)) if len(currencies) == 1 else None,
            complete=False,
            missing_reason_codes=tuple(sorted(missing)),
        )


class RepositoryLearningMetricsSource:
    def __init__(self, engine: sa.Engine, *, cost_source: LearningCostSource | None = None) -> None:
        self.engine = engine
        self.cost_source = cost_source or RepositoryLearningCostSource()

    def capture(self, *, window: LearningWindow) -> tuple[LearningCellMetrics, ...]:
        with self.engine.connect() as connection:
            return self.capture_in_transaction(connection, window=window)

    def capture_in_transaction(
        self, connection: sa.Connection, *, window: LearningWindow
    ) -> tuple[LearningCellMetrics, ...]:
        cohort_rows = connection.execute(
            sa.select(
                acquisition_campaign_member.c.member_ref,
                acquisition_campaign.c.country,
                acquisition_campaign.c.wedge,
            )
            .select_from(
                acquisition_provider_event.join(
                    acquisition_campaign_member,
                    acquisition_provider_event.c.member_ref
                    == acquisition_campaign_member.c.member_ref,
                ).join(
                    acquisition_campaign,
                    acquisition_campaign_member.c.campaign_ref
                    == acquisition_campaign.c.campaign_ref,
                )
            )
            .where(
                acquisition_provider_event.c.provider_event_type == "email_sent",
                acquisition_provider_event.c.step == 1,
                acquisition_provider_event.c.occurred_at >= window.window_start,
                acquisition_provider_event.c.occurred_at < window.window_end,
            )
            .distinct()
        ).mappings()
        cells: dict[str, LearningCellKey] = {}
        members: dict[str, set[str]] = defaultdict(set)
        member_cell: dict[str, str] = {}
        for row in cohort_rows:
            cell = LearningCellKey(country=row["country"], wedge=row["wedge"])
            cells[cell.key] = cell
            members[cell.key].add(row["member_ref"])
            member_cell[row["member_ref"]] = cell.key
        if not member_cell:
            return ()

        member_refs = tuple(sorted(member_cell))
        bounces = {
            row.member_ref
            for row in connection.execute(
                sa.select(acquisition_provider_event.c.member_ref)
                .where(
                    acquisition_provider_event.c.member_ref.in_(member_refs),
                    acquisition_provider_event.c.provider_event_type == "email_bounced",
                    acquisition_provider_event.c.step == 1,
                    acquisition_provider_event.c.occurred_at < window.window_end,
                )
                .distinct()
            )
        }
        responses = list(
            connection.execute(
                sa.select(acquisition_response_evaluation).where(
                    acquisition_response_evaluation.c.member_ref.in_(member_refs),
                    acquisition_response_evaluation.c.processing_state == "FINALIZED",
                    acquisition_response_evaluation.c.finalized_at < window.window_end,
                )
            ).mappings()
        )
        positive, complaints, unsubscribes, ambiguous = self._response_facts(responses)

        conversion_rows = list(
            connection.execute(
                sa.select(acquisition_conversion_event).where(
                    acquisition_conversion_event.c.member_ref.in_(member_refs),
                    acquisition_conversion_event.c.occurred_at < window.window_end,
                )
            ).mappings()
        )
        journeys = list(
            connection.execute(
                sa.select(acquisition_conversion_journey).where(
                    acquisition_conversion_journey.c.member_ref.in_(member_refs),
                    acquisition_conversion_journey.c.signed_up_at < window.window_end,
                )
            ).mappings()
        )

        result: list[LearningCellMetrics] = []
        for key in sorted(cells):
            cell_members = frozenset(members[key])
            cell_journeys = {
                row["journey_ref"]: row for row in journeys if row["member_ref"] in cell_members
            }
            journey_events: dict[str, list[dict]] = defaultdict(list)
            clicks: set[str] = set()
            for row in conversion_rows:
                if row["member_ref"] not in cell_members:
                    continue
                if row["milestone"] == "CLICK":
                    clicks.add(row["conversion_event_ref"])
                elif row["journey_ref"] in cell_journeys:
                    journey_events[row["journey_ref"]].append(dict(row))
            conversion = self._conversion_facts(
                cell_journeys=cell_journeys,
                journey_events=journey_events,
                window_end=window.window_end,
            )
            cost = self.cost_source.for_cell(
                connection,
                cell=cells[key],
                member_refs=cell_members,
                window=window,
            )
            result.append(
                LearningCellMetrics(
                    cell=cells[key],
                    contacted_count=len(cell_members),
                    bounce_count=len(cell_members & bounces),
                    positive_reply_count=len(cell_members & positive),
                    complaint_count=len(cell_members & complaints),
                    unsubscribe_count=len(cell_members & unsubscribes),
                    click_count=len(clicks),
                    signup_count=len(cell_journeys),
                    activation_count=conversion["activation_count"],
                    paid_count=conversion["paid_count"],
                    known_mrr_minor_units=conversion["known_mrr_minor_units"],
                    retained_mrr_minor_units=conversion["retained_mrr_minor_units"],
                    currency=conversion["currency"],
                    mrr_complete=conversion["mrr_complete"],
                    m1_eligible_count=conversion["m1_eligible_count"],
                    retained_m1_count=conversion["retained_m1_count"],
                    m2_eligible_count=conversion["m2_eligible_count"],
                    retained_m2_count=conversion["retained_m2_count"],
                    churn_count=conversion["churn_count"],
                    known_variable_cost_minor_units=cost.amount_minor_units,
                    cost_currency=cost.currency,
                    cost_complete=cost.complete,
                    missing_cost_reason_codes=cost.missing_reason_codes,
                    conversion_identity_ambiguous=bool(cell_members & ambiguous),
                )
            )
        return tuple(result)

    @staticmethod
    def _response_facts(
        rows: list[sa.RowMapping],
    ) -> tuple[set[str], set[str], set[str], set[str]]:
        positive: set[str] = set()
        complaints: set[str] = set()
        unsubscribes: set[str] = set()
        ambiguous: set[str] = set()
        by_response: dict[str, list[sa.RowMapping]] = defaultdict(list)
        for row in rows:
            by_response[row["response_ref"]].append(row)
            if row["classification"] == "COMPLAINT":
                complaints.add(row["member_ref"])
            if row["classification"] == "UNSUBSCRIBE":
                unsubscribes.add(row["member_ref"])
        for evaluations in by_response.values():
            ids = {row["response_evaluation_id"] for row in evaluations}
            superseded = {
                row["supersedes_response_evaluation_id"]
                for row in evaluations
                if row["supersedes_response_evaluation_id"] is not None
            }
            leaves = [row for row in evaluations if row["response_evaluation_id"] not in superseded]
            invalid_parent = any(
                row["supersedes_response_evaluation_id"] is not None
                and row["supersedes_response_evaluation_id"] not in ids
                for row in evaluations
            )
            if len(leaves) != 1 or invalid_parent:
                ambiguous.update(row["member_ref"] for row in evaluations)
                continue
            if leaves[0]["classification"] == "POSITIVE":
                positive.add(leaves[0]["member_ref"])
        return positive, complaints, unsubscribes, ambiguous

    @staticmethod
    def _conversion_facts(
        *,
        cell_journeys: dict[str, sa.RowMapping],
        journey_events: dict[str, list[dict]],
        window_end: dt.datetime,
    ) -> dict[str, object]:
        activation_count = paid_count = m1_eligible = retained_m1 = 0
        m2_eligible = retained_m2 = churn_count = 0
        current_mrr = retained_mrr = 0
        currencies: set[str] = set()
        mrr_complete = True
        for journey_ref in cell_journeys:
            events = sorted(
                journey_events.get(journey_ref, ()),
                key=lambda row: (_utc(row["occurred_at"]), row["conversion_event_ref"]),
            )
            milestones = {row["milestone"] for row in events}
            activation_count += "ACTIVATED" in milestones
            paid_events = [row for row in events if row["milestone"] == "PAID"]
            if not paid_events:
                continue
            paid_count += 1
            paid_at = min(_utc(row["occurred_at"]) for row in paid_events)
            if paid_at <= window_end - dt.timedelta(days=30):
                m1_eligible += 1
                retained_m1 += "RETAINED_M1" in milestones
            if paid_at <= window_end - dt.timedelta(days=60):
                m2_eligible += 1
                retained_m2 += "RETAINED_M2" in milestones
            churned = "CHURNED" in milestones
            churn_count += churned
            mrr_events = [row for row in events if row["milestone"] == "MRR_CHANGED"]
            if not mrr_events:
                mrr_complete = False
                continue
            latest = mrr_events[-1]
            if not latest["mrr_known"]:
                mrr_complete = False
                continue
            currency = str(latest["currency"]).upper()
            currencies.add(currency)
            amount = int(latest["mrr_minor_units"])
            if churned:
                if amount != 0:
                    mrr_complete = False
                amount = 0
            current_mrr += amount
            if "RETAINED_M1" in milestones and not churned:
                retained_mrr += amount
        if len(currencies) > 1:
            mrr_complete = False
        return {
            "activation_count": activation_count,
            "paid_count": paid_count,
            "known_mrr_minor_units": current_mrr,
            "retained_mrr_minor_units": retained_mrr,
            "currency": next(iter(currencies)) if len(currencies) == 1 else None,
            "mrr_complete": mrr_complete,
            "m1_eligible_count": m1_eligible,
            "retained_m1_count": retained_m1,
            "m2_eligible_count": m2_eligible,
            "retained_m2_count": retained_m2,
            "churn_count": churn_count,
        }


__all__ = [
    "LearningCostFact",
    "LearningCostSource",
    "RepositoryLearningCostSource",
    "RepositoryLearningMetricsSource",
]
