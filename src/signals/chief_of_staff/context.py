"""Build and bound one immutable Chief of Staff context."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from signals.chief_of_staff.capabilities import evaluate_capabilities
from signals.chief_of_staff.contracts import (
    ActiveGate,
    BusinessMemory,
    Cadence,
    ChiefOfStaffContext,
    ChiefOfStaffFact,
    DataQualitySummary,
    KnownIncident,
)
from signals.chief_of_staff.facts import fact_refs_for_metrics
from signals.decision_engine.policy import semantic_fingerprint

_GATE_NAMES = (
    "h_a_runtime",
    "h_b_state",
    "h_c_policy",
    "h_d_shadow",
    "h_e_capped",
    "h_f_closed_loop",
    "h_g_precision",
)


@dataclass(frozen=True)
class ContextLimits:
    max_facts: int = 200
    max_bytes: int = 65_536


def build_context(
    *,
    overview: Any,
    facts: tuple[ChiefOfStaffFact, ...],
    memory: BusinessMemory,
    cadence: Cadence,
    period_start: dt.datetime,
    period_end: dt.datetime,
    generated_at: dt.datetime,
    limits: ContextLimits | None = None,
) -> ChiefOfStaffContext:
    limits = limits or ContextLimits()
    ordered_facts = tuple(sorted(facts, key=lambda item: item.fact_ref))
    if len(ordered_facts) > limits.max_facts:
        raise ValueError("Chief of Staff fact limit exceeded")
    readiness = overview.system.readiness
    active_gates = tuple(
        ActiveGate(
            gate_ref=name,
            status=(
                "OPEN"
                if str(getattr(readiness, name).status) == "READY"
                else "UNKNOWN"
                if str(getattr(readiness, name).status) == "INSUFFICIENT_EVIDENCE"
                else "BLOCKED"
            ),
            reason_codes=tuple(getattr(readiness, name).reason_codes) or ("GATE_STATUS_ONLY",),
            fact_refs=(),
        )
        for name in _GATE_NAMES
        if str(getattr(readiness, name).status) != "READY"
    )
    known_incidents = tuple(
        KnownIncident(
            incident_ref=str(item.item_ref),
            severity=str(item.severity),
            status=str(item.status),
            reason_codes=tuple(item.reason_codes) or ("INCIDENT_OPEN",),
            fact_refs=tuple(
                fact.fact_ref
                for fact in ordered_facts
                if fact.metric_key == "open_attention_item"
                and str(item.severity) == str(fact.value)
            )[:1],
        )
        for item in overview.attention
    )
    quality_metrics = {
        "unresolved_sector_count",
        "unknown_mrr_journey_count",
        "matching_disagreement",
        "retained_m2_mrr_minor_units",
    }
    quality_refs = tuple(
        sorted(
            set(fact_refs_for_metrics(ordered_facts, quality_metrics))
            | {
                fact.fact_ref
                for fact in ordered_facts
                if fact.data_status == "STALE"
            }
        )
    )
    quality_reasons = tuple(
        sorted(
            {
                "DATA_UNKNOWN"
                if fact.data_status == "UNKNOWN"
                else "STALE_DATA"
                if fact.data_status == "STALE"
                else "INSUFFICIENT_EVIDENCE"
                for fact in ordered_facts
                if fact.fact_ref in quality_refs
                and fact.data_status in {"UNKNOWN", "INSUFFICIENT_EVIDENCE", "STALE"}
            }
        )
    )
    context = ChiefOfStaffContext(
        generated_at=generated_at,
        cadence=cadence,
        period_start=period_start,
        period_end=period_end,
        business_memory_version=memory.memory_version,
        business_memory=memory.decisions,
        profile_version="1.1.0",
        facts=ordered_facts,
        active_gates=active_gates,
        known_incidents=known_incidents,
        data_quality=DataQualitySummary(
            reason_codes=quality_reasons,
            fact_refs=quality_refs,
        ),
        capabilities=evaluate_capabilities(ordered_facts),
    )
    size = len(context.model_dump_json().encode("utf-8"))
    if size > limits.max_bytes:
        raise ValueError("Chief of Staff context byte limit exceeded")
    return context


def context_fingerprint(context: ChiefOfStaffContext) -> str:
    return semantic_fingerprint(context.model_dump(mode="json", exclude={"generated_at"}))


__all__ = ["ContextLimits", "build_context", "context_fingerprint"]
