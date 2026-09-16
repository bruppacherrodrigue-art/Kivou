"""Deterministic, sanitized projections of existing Kivou read contracts."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from signals.chief_of_staff.contracts import ChiefOfStaffFact, DataStatus, Domain, FactValue
from signals.decision_engine.policy import semantic_fingerprint


def _ref(
    *, domain: str, metric_key: str, period_start: dt.datetime, period_end: dt.datetime, key: str
) -> str:
    digest = semantic_fingerprint(
        {
            "domain": domain,
            "metric_key": metric_key,
            "period_start": period_start,
            "period_end": period_end,
            "key": key,
        }
    )
    return f"fact:{domain.lower()}:{metric_key}:{digest[:16]}"


def _fact(
    *,
    domain: Domain,
    metric_key: str,
    value: FactValue,
    unit: str,
    period_start: dt.datetime,
    period_end: dt.datetime,
    captured_at: dt.datetime,
    source_contract: str,
    source_version: str,
    data_status: DataStatus = "KNOWN",
    currency: str | None = None,
    dimension: str = "all",
) -> ChiefOfStaffFact:
    return ChiefOfStaffFact(
        fact_ref=_ref(
            domain=domain,
            metric_key=metric_key,
            period_start=period_start,
            period_end=period_end,
            key=f"{dimension}:{currency or '-'}",
        ),
        domain=domain,
        metric_key=metric_key,
        value=value,
        unit=unit,
        currency=currency,
        period_start=period_start,
        period_end=period_end,
        captured_at=captured_at,
        source_contract=source_contract,
        source_version=source_version,
        data_status=data_status,
    )


def _operational_period(at: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    return at - dt.timedelta(microseconds=1), at


def collect_founder_facts(overview: Any) -> tuple[ChiefOfStaffFact, ...]:
    """Project bounded aggregates only; customer and prospect text is never read."""

    facts: list[ChiefOfStaffFact] = []
    business = overview.business
    business_source = str(business.report_version)
    business_version = f"{business_source}:{business.delivery_semantics}"
    business_counts = {
        "delivered_proxy_count": business.funnel.delivered_proxy_count,
        "positive_reply_count": business.funnel.positive_reply_count,
        "click_count": business.funnel.click_count,
        "activated_account_count": business.funnel.activated_account_count,
        "paid_account_count": business.funnel.paid_account_count,
        "churn_count": business.funnel.churn_count,
    }
    for metric_key, value in business_counts.items():
        facts.append(
            _fact(
                domain="BUSINESS",
                metric_key=metric_key,
                value=int(value),
                unit="COUNT",
                period_start=business.week_start,
                period_end=business.week_end,
                captured_at=business.captured_at,
                source_contract="WeeklyCommercialCockpit",
                source_version=business_version,
            )
        )
    for money in business.funnel.mrr_by_currency:
        facts.append(
            _fact(
                domain="BUSINESS",
                metric_key="weekly_mrr_minor_units",
                value=int(money.minor_units),
                unit="MINOR_UNITS",
                currency=str(money.currency),
                period_start=business.week_start,
                period_end=business.week_end,
                captured_at=business.captured_at,
                source_contract="WeeklyCommercialCockpit",
                source_version=business_source,
                dimension=str(money.currency),
            )
        )
    for row in business.wedge_m2_efficiency:
        status: DataStatus = (
            "KNOWN" if str(row.data_status) == "READY" else "INSUFFICIENT_EVIDENCE"
        )
        facts.extend(
            (
                _fact(
                    domain="BUSINESS",
                    metric_key="m2_eligible_delivered_proxy_count",
                    value=(int(row.m2_eligible_delivered_proxy_count) if status == "KNOWN" else None),
                    unit="COUNT",
                    period_start=business.week_start,
                    period_end=business.week_end,
                    captured_at=business.captured_at,
                    source_contract="WedgeM2Efficiency",
                    source_version=business_version,
                    data_status=status,
                    dimension=str(row.wedge),
                ),
                _fact(
                    domain="BUSINESS",
                    metric_key="retained_m2_mrr_minor_units",
                    value=(
                        int(row.retained_m2_mrr_minor_units)
                        if status == "KNOWN" and row.retained_m2_mrr_minor_units is not None
                        else None
                    ),
                    unit="MINOR_UNITS",
                    currency=(str(row.currency) if row.currency is not None else None),
                    period_start=business.week_start,
                    period_end=business.week_end,
                    captured_at=business.captured_at,
                    source_contract="WedgeM2Efficiency",
                    source_version=business_source,
                    data_status=status,
                    dimension=str(row.wedge),
                ),
            )
        )
    quality = business.data_quality
    for metric_key in (
        "unresolved_sector_count",
        "unknown_mrr_journey_count",
        "matching_disagreement",
    ):
        facts.append(
            _fact(
                domain="DATA",
                metric_key=metric_key,
                value=int(getattr(quality, metric_key)),
                unit="COUNT",
                period_start=business.week_start,
                period_end=business.week_end,
                captured_at=quality.captured_at,
                source_contract="CockpitDataQuality",
                source_version=business_source,
            )
        )

    observed_at = overview.generated_at
    operational_start, operational_end = _operational_period(observed_at)
    acquisition = overview.acquisition_status
    for metric_key in ("mode", "activity", "last_cycle_status"):
        value = getattr(acquisition, metric_key, None)
        facts.append(
            _fact(
                domain="ACQUISITION",
                metric_key=metric_key,
                value=(str(value) if value is not None else None),
                unit="STATUS",
                period_start=operational_start,
                period_end=operational_end,
                captured_at=observed_at,
                source_contract="FounderAcquisitionStatus",
                source_version="founder-acquisition-status-v1",
                data_status=("KNOWN" if value is not None else "UNKNOWN"),
            )
        )
    health = overview.system.health
    for metric_key in (
        "status",
        "api",
        "database",
        "hermes_runtime",
        "supervisor_loop",
        "policy_control",
        "campaign_execution",
        "dlq",
        "circuit_breakers",
    ):
        facts.append(
            _fact(
                domain="OPERATIONS",
                metric_key=metric_key,
                value=str(getattr(health, metric_key)),
                unit="STATUS",
                period_start=operational_start,
                period_end=operational_end,
                captured_at=health.observed_at,
                source_contract="AcquisitionOperationalHealth",
                source_version=str(health.version),
            )
        )
    for attention in overview.attention:
        facts.append(
            _fact(
                domain="OPERATIONS",
                metric_key="open_attention_item",
                value=str(attention.severity),
                unit="STATUS",
                period_start=operational_start,
                period_end=operational_end,
                captured_at=observed_at,
                source_contract="FounderAttentionItem",
                source_version="founder-console-overview-v1",
                dimension=str(attention.item_ref),
            )
        )
    return tuple(sorted(facts, key=lambda item: item.fact_ref))


def fact_refs_for_metrics(
    facts: Iterable[ChiefOfStaffFact], metric_keys: set[str]
) -> tuple[str, ...]:
    return tuple(sorted(item.fact_ref for item in facts if item.metric_key in metric_keys))


__all__ = ["collect_founder_facts", "fact_refs_for_metrics"]
