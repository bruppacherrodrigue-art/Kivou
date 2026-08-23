"""Reproducible, read-only aggregation over SPEC-026 through SPEC-029 truth."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa

from signals.cockpit.contracts import (
    AnalyticalRow,
    CockpitDataQuality,
    CockpitWeek,
    FunnelMetrics,
    MoneyTotal,
    WedgeM2Efficiency,
)
from signals.conversion.source import AttributionSourceResolver
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_conversion_event,
    acquisition_conversion_journey,
    acquisition_opportunity,
    acquisition_provider_event,
    acquisition_response_evaluation,
)

UNRESOLVED_SECTOR = "UNRESOLVED"
_UNKNOWN_SECTOR = "sector-unknown-v1"
_RATE_QUANTUM = Decimal("0.000001")
_MRR_CURRENCIES = ("CHF", "EUR")


def _utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=dt.UTC)
    return value.astimezone(dt.UTC)


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        _RATE_QUANTUM, rounding=ROUND_HALF_UP
    )


def _money(values: dict[str, int]) -> tuple[MoneyTotal, ...]:
    return tuple(
        MoneyTotal(currency=currency, minor_units=values[currency])
        for currency in sorted(values)
        if currency in {"CHF", "EUR"}
    )


@dataclass(frozen=True)
class _Member:
    member_ref: str
    campaign_ref: str
    country: str
    wedge: str
    need_ref: str
    signal_ref: str
    sent_at: dt.datetime


@dataclass(frozen=True)
class CockpitMetrics:
    funnel: FunnelMetrics
    analytical_rows: tuple[AnalyticalRow, ...]
    wedge_m2_efficiency: tuple[WedgeM2Efficiency, ...]
    data_quality: CockpitDataQuality


class RepositoryCockpitMetrics:
    """One bounded read model; it performs no writes and owns no business truth."""

    def __init__(
        self,
        engine: sa.Engine,
        *,
        source_resolver: AttributionSourceResolver | None = None,
    ) -> None:
        self.engine = engine
        self.source_resolver = source_resolver or AttributionSourceResolver(engine)

    def capture(self, *, week: CockpitWeek) -> CockpitMetrics:
        with self.engine.connect() as connection:
            members = self._weekly_members(connection, week)
            member_refs = tuple(sorted(members))
            bounces = self._bounces(connection, member_refs, cutoff=week.week_end)
            positive = self._positive_members(connection, member_refs, cutoff=week.week_end)
            journeys = self._journeys(connection, member_refs, cutoff=week.week_end)
            events = self._conversion_events(connection, member_refs, cutoff=week.week_end)
            sectors = self._sectors(members, journeys)
            funnel, rows, unknown_mrr = self._weekly_aggregates(
                members=members,
                bounces=bounces,
                positive=positive,
                journeys=journeys,
                conversion_events=events,
                sectors=sectors,
            )
            m2 = self._m2_efficiency(connection, cutoff=week.week_end)
        unresolved = sum(
            1
            for member_ref in member_refs
            if sectors[member_ref] == UNRESOLVED_SECTOR
        )
        insufficient = tuple(
            sorted({row.wedge for row in m2 if row.data_status == "INSUFFICIENT_M2_EVIDENCE"})
        )
        return CockpitMetrics(
            funnel=funnel,
            analytical_rows=rows,
            wedge_m2_efficiency=m2,
            data_quality=CockpitDataQuality(
                unresolved_sector_count=unresolved,
                unknown_mrr_journey_count=unknown_mrr,
                m2_insufficient_wedges=insufficient,
                captured_at=week.week_end,
            ),
        )

    @staticmethod
    def _weekly_members(
        connection: sa.Connection, week: CockpitWeek
    ) -> dict[str, _Member]:
        rows = connection.execute(
            sa.select(
                acquisition_campaign_member.c.member_ref,
                acquisition_campaign.c.campaign_ref,
                acquisition_campaign.c.country,
                acquisition_campaign.c.wedge,
                acquisition_campaign.c.selected_need_category,
                acquisition_opportunity.c.signal_ref,
                acquisition_provider_event.c.occurred_at,
            )
            .select_from(
                acquisition_provider_event.join(
                    acquisition_campaign_member,
                    acquisition_provider_event.c.member_ref
                    == acquisition_campaign_member.c.member_ref,
                )
                .join(
                    acquisition_campaign,
                    acquisition_campaign_member.c.campaign_ref
                    == acquisition_campaign.c.campaign_ref,
                )
                .join(
                    acquisition_opportunity,
                    acquisition_campaign_member.c.acquisition_opportunity_id
                    == acquisition_opportunity.c.acquisition_opportunity_id,
                )
            )
            .where(
                acquisition_provider_event.c.provider_event_type == "email_sent",
                acquisition_provider_event.c.step == 1,
                acquisition_provider_event.c.occurred_at >= week.week_start,
                acquisition_provider_event.c.occurred_at < week.week_end,
            )
            .order_by(
                acquisition_campaign_member.c.member_ref,
                acquisition_provider_event.c.occurred_at,
            )
        ).mappings()
        result: dict[str, _Member] = {}
        for row in rows:
            ref = row["member_ref"]
            if ref in result:
                continue
            result[ref] = _Member(
                member_ref=ref,
                campaign_ref=row["campaign_ref"],
                country=row["country"],
                wedge=row["wedge"],
                need_ref=row["selected_need_category"],
                signal_ref=row["signal_ref"],
                sent_at=_utc(row["occurred_at"]),
            )
        return result

    @staticmethod
    def _bounces(
        connection: sa.Connection, member_refs: tuple[str, ...], *, cutoff: dt.datetime
    ) -> set[str]:
        if not member_refs:
            return set()
        return set(
            connection.scalars(
                sa.select(acquisition_provider_event.c.member_ref)
                .where(
                    acquisition_provider_event.c.member_ref.in_(member_refs),
                    acquisition_provider_event.c.provider_event_type == "email_bounced",
                    acquisition_provider_event.c.step == 1,
                    acquisition_provider_event.c.occurred_at < cutoff,
                )
                .distinct()
            )
        )

    @staticmethod
    def _positive_members(
        connection: sa.Connection, member_refs: tuple[str, ...], *, cutoff: dt.datetime
    ) -> set[str]:
        if not member_refs:
            return set()
        rows = list(
            connection.execute(
                sa.select(acquisition_response_evaluation).where(
                    acquisition_response_evaluation.c.member_ref.in_(member_refs),
                    acquisition_response_evaluation.c.processing_state == "FINALIZED",
                    acquisition_response_evaluation.c.finalized_at < cutoff,
                )
            ).mappings()
        )
        by_response: dict[str, list[sa.RowMapping]] = defaultdict(list)
        for row in rows:
            by_response[row["response_ref"]].append(row)
        positive: set[str] = set()
        for evaluations in by_response.values():
            ids = {row["response_evaluation_id"] for row in evaluations}
            superseded = {
                row["supersedes_response_evaluation_id"]
                for row in evaluations
                if row["supersedes_response_evaluation_id"] is not None
            }
            if any(
                row["supersedes_response_evaluation_id"] is not None
                and row["supersedes_response_evaluation_id"] not in ids
                for row in evaluations
            ):
                continue
            leaves = [row for row in evaluations if row["response_evaluation_id"] not in superseded]
            if len(leaves) == 1 and leaves[0]["classification"] == "POSITIVE":
                positive.add(leaves[0]["member_ref"])
        return positive

    @staticmethod
    def _journeys(
        connection: sa.Connection, member_refs: tuple[str, ...], *, cutoff: dt.datetime
    ) -> tuple[sa.RowMapping, ...]:
        if not member_refs:
            return ()
        return tuple(
            connection.execute(
                sa.select(acquisition_conversion_journey).where(
                    acquisition_conversion_journey.c.member_ref.in_(member_refs),
                    acquisition_conversion_journey.c.signed_up_at < cutoff,
                )
            ).mappings()
        )

    @staticmethod
    def _conversion_events(
        connection: sa.Connection, member_refs: tuple[str, ...], *, cutoff: dt.datetime
    ) -> tuple[sa.RowMapping, ...]:
        if not member_refs:
            return ()
        return tuple(
            connection.execute(
                sa.select(acquisition_conversion_event).where(
                    acquisition_conversion_event.c.member_ref.in_(member_refs),
                    acquisition_conversion_event.c.occurred_at < cutoff,
                )
            ).mappings()
        )

    def _sectors(
        self, members: dict[str, _Member], journeys: tuple[sa.RowMapping, ...]
    ) -> dict[str, str]:
        journey_sectors: dict[str, set[str]] = defaultdict(set)
        for row in journeys:
            journey_sectors[row["member_ref"]].add(row["sector_ref"])
        result: dict[str, str] = {}
        for ref, member in members.items():
            frozen = journey_sectors.get(ref, set())
            if len(frozen) == 1:
                value = next(iter(frozen))
            elif len(frozen) > 1:
                value = UNRESOLVED_SECTOR
            else:
                value = self.source_resolver.sector_ref_for_signal(member.signal_ref)
            result[ref] = UNRESOLVED_SECTOR if value == _UNKNOWN_SECTOR else value
        return result

    @staticmethod
    def _weekly_aggregates(
        *,
        members: dict[str, _Member],
        bounces: set[str],
        positive: set[str],
        journeys: tuple[sa.RowMapping, ...],
        conversion_events: tuple[sa.RowMapping, ...],
        sectors: dict[str, str],
    ) -> tuple[FunnelMetrics, tuple[AnalyticalRow, ...], int]:
        keys = {
            ref: (member.country, sectors[ref], member.need_ref, member.campaign_ref)
            for ref, member in members.items()
        }
        row_members: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
        for ref, key in keys.items():
            row_members[key].add(ref)
        journeys_by_ref = {row["journey_ref"]: row for row in journeys}
        events_by_journey: dict[str, list[sa.RowMapping]] = defaultdict(list)
        clicks: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
        for row in conversion_events:
            member_ref = row["member_ref"]
            if member_ref not in keys:
                continue
            if row["milestone"] == "CLICK":
                clicks[keys[member_ref]].add(row["conversion_event_ref"])
            elif row["journey_ref"] in journeys_by_ref:
                events_by_journey[row["journey_ref"]].append(row)

        row_journeys: dict[tuple[str, str, str, str], list[sa.RowMapping]] = defaultdict(list)
        for journey in journeys:
            if journey["member_ref"] in keys:
                row_journeys[keys[journey["member_ref"]]].append(journey)

        total_money: dict[str, int] = defaultdict(int)
        total_activation = total_paid = total_churn = total_unknown = 0
        rows: list[AnalyticalRow] = []
        for key in sorted(row_members):
            member_set = row_members[key]
            delivered = len(member_set - bounces)
            activated = paid = churned = unknown = 0
            money: dict[str, int] = defaultdict(int)
            for journey in row_journeys.get(key, ()):
                facts = sorted(
                    events_by_journey.get(journey["journey_ref"], ()),
                    key=lambda event: (_utc(event["occurred_at"]), event["conversion_event_ref"]),
                )
                milestones = {event["milestone"] for event in facts}
                activated += "ACTIVATED" in milestones
                is_paid = "PAID" in milestones
                paid += is_paid
                is_churned = "CHURNED" in milestones
                churned += is_churned
                if not is_paid:
                    continue
                mrr = [event for event in facts if event["milestone"] == "MRR_CHANGED"]
                if not mrr or not mrr[-1]["mrr_known"]:
                    unknown += 1
                    continue
                currency = str(mrr[-1]["currency"] or "").upper()
                if currency not in {"CHF", "EUR"}:
                    unknown += 1
                    continue
                amount = 0 if is_churned else int(mrr[-1]["mrr_minor_units"])
                money[currency] += amount
            total_activation += activated
            total_paid += paid
            total_churn += churned
            total_unknown += unknown
            for currency, amount in money.items():
                total_money[currency] += amount
            positives = len(member_set & positive)
            rows.append(
                AnalyticalRow(
                    country=key[0],
                    sector_ref=key[1],
                    need_ref=key[2],
                    campaign_ref=key[3],
                    delivered_proxy_count=delivered,
                    positive_reply_count=positives,
                    click_count=len(clicks.get(key, set())),
                    activated_account_count=activated,
                    paid_account_count=paid,
                    mrr_by_currency=_money(money),
                    churn_count=churned,
                    positive_reply_rate=_rate(positives, delivered),
                    click_rate=_rate(len(clicks.get(key, set())), delivered),
                    activation_rate=_rate(activated, delivered),
                    paid_rate=_rate(paid, delivered),
                )
            )
        funnel = FunnelMetrics(
            delivered_proxy_count=len(set(members) - bounces),
            positive_reply_count=len(set(members) & positive),
            click_count=sum(len(value) for value in clicks.values()),
            activated_account_count=total_activation,
            paid_account_count=total_paid,
            mrr_by_currency=_money(total_money),
            churn_count=total_churn,
        )
        return funnel, tuple(rows), total_unknown

    def _m2_efficiency(
        self, connection: sa.Connection, *, cutoff: dt.datetime
    ) -> tuple[WedgeM2Efficiency, ...]:
        sent_rows = connection.execute(
            sa.select(
                acquisition_campaign_member.c.member_ref,
                acquisition_campaign.c.wedge,
                acquisition_provider_event.c.occurred_at,
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
                acquisition_provider_event.c.occurred_at < cutoff,
            )
            .order_by(
                acquisition_campaign_member.c.member_ref,
                acquisition_provider_event.c.occurred_at,
            )
        ).mappings()
        member_wedge: dict[str, str] = {}
        member_sent_at: dict[str, dt.datetime] = {}
        for row in sent_rows:
            member_wedge.setdefault(row["member_ref"], row["wedge"])
            member_sent_at.setdefault(row["member_ref"], _utc(row["occurred_at"]))
        if not member_wedge:
            return ()
        refs = tuple(sorted(member_wedge))
        bounces = self._bounces(connection, refs, cutoff=cutoff)
        maturity = _utc(cutoff) - dt.timedelta(days=60)
        mature_refs = tuple(
            ref
            for ref in refs
            if member_sent_at[ref] <= maturity and ref not in bounces
        )
        journeys = self._journeys(connection, mature_refs, cutoff=cutoff)
        events = self._conversion_events(connection, mature_refs, cutoff=cutoff)
        by_journey: dict[str, list[sa.RowMapping]] = defaultdict(list)
        for row in events:
            if row["journey_ref"] is not None:
                by_journey[row["journey_ref"]].append(row)
        eligible_members: dict[str, set[str]] = defaultdict(set)
        for member_ref in mature_refs:
            eligible_members[member_wedge[member_ref]].add(member_ref)
        retained_accounts: dict[tuple[str, str], int] = defaultdict(int)
        retained_money: dict[tuple[str, str], int] = defaultdict(int)
        incomplete: set[str] = set()
        for journey in journeys:
            member_ref = journey["member_ref"]
            wedge = member_wedge[member_ref]
            facts = sorted(
                by_journey.get(journey["journey_ref"], ()),
                key=lambda event: (_utc(event["occurred_at"]), event["conversion_event_ref"]),
            )
            milestones = {event["milestone"] for event in facts}
            if "RETAINED_M2" not in milestones or "CHURNED" in milestones:
                continue
            mrr = [event for event in facts if event["milestone"] == "MRR_CHANGED"]
            if not mrr or not mrr[-1]["mrr_known"]:
                incomplete.add(wedge)
                continue
            currency = str(mrr[-1]["currency"] or "").upper()
            if currency not in {"CHF", "EUR"}:
                incomplete.add(wedge)
                continue
            retained_accounts[(wedge, currency)] += 1
            retained_money[(wedge, currency)] += int(mrr[-1]["mrr_minor_units"])
        wedges = sorted(set(member_wedge.values()))
        result: list[WedgeM2Efficiency] = []
        for wedge in wedges:
            denominator = len(eligible_members.get(wedge, set()))
            if denominator == 0 or wedge in incomplete:
                result.append(
                    WedgeM2Efficiency(
                        wedge=wedge,
                        currency=None,
                        m2_eligible_delivered_proxy_count=denominator,
                        retained_m2_accounts=0,
                        retained_m2_mrr_minor_units=None,
                        retained_m2_mrr_per_1000_delivered=None,
                        data_status="INSUFFICIENT_M2_EVIDENCE",
                    )
                )
                continue
            for currency in _MRR_CURRENCIES:
                amount = retained_money[(wedge, currency)]
                result.append(
                    WedgeM2Efficiency(
                        wedge=wedge,
                        currency=currency,
                        m2_eligible_delivered_proxy_count=denominator,
                        retained_m2_accounts=retained_accounts[(wedge, currency)],
                        retained_m2_mrr_minor_units=amount,
                        retained_m2_mrr_per_1000_delivered=(
                            Decimal(amount) * Decimal(1000) / Decimal(denominator)
                        ).quantize(_RATE_QUANTUM, rounding=ROUND_HALF_UP),
                        data_status="READY",
                    )
                )
        return tuple(result)


__all__ = ["UNRESOLVED_SECTOR", "CockpitMetrics", "RepositoryCockpitMetrics"]
