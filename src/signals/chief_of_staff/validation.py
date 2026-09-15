"""Deterministic semantic validation after strict report parsing."""

from __future__ import annotations

import re

from signals.chief_of_staff.context import context_fingerprint
from signals.chief_of_staff.contracts import ChiefOfStaffContext, ChiefOfStaffReport
from signals.supervisor.pin import HermesPin, load_hermes_pin

_DIGIT = re.compile(r"\d")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_SECRET = re.compile(
    r"(?:\b(?:bearer|api[_ -]?key|password|secret|token)\b\s*[:=]|\bsk-[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_FORBIDDEN_COMMAND = re.compile(
    r"(?:\b(?:sudo|systemctl|curl|shell|mcp|apollo|instantly|stripe)\b|"
    r"active\s+la\s+campagne|modifi(?:e|er)\s+le\s+pricing|"
    r"déploi(?:e|er)|reveals?\s+secrets?|révèl(?:e|er)\s+les\s+secrets)",
    re.IGNORECASE,
)
_EXECUTED = re.compile(
    r"(?:j['’]ai\s+(?:exécuté|envoyé|déployé|modifié)|"
    r"(?:a|ont)\s+été\s+(?:exécuté|envoyé|déployé|modifié)|"
    r"(?:action|recommendation)\s+(?:was\s+)?(?:executed|completed))",
    re.IGNORECASE,
)
_SCOPE_EXPANSION = re.compile(
    r"(?:ignore\s+(?:les|the)\s+(?:règles|rules)|"
    r"change\s+(?:ta|your)\s+mission|ajoute\s+des\s+outils|add\s+tools?)",
    re.IGNORECASE,
)


class ReportValidationError(ValueError):
    """A parsed report violates Kivou's semantic publication boundary."""


def _narratives(report: ChiefOfStaffReport) -> tuple[str, ...]:
    return (
        report.executive_summary,
        *(value for item in report.observations for value in (item.summary, item.impact)),
        *(item.recommended_action for item in report.priorities),
        *(item.question for item in report.decision_requests),
        *(item.summary for item in report.unknowns),
    )


def _cited_fact_refs(report: ChiefOfStaffReport) -> tuple[str, ...]:
    return (
        *(ref for item in report.observations for ref in item.fact_refs),
        *(ref for item in report.priorities for ref in item.fact_refs),
        *(ref for item in report.decision_requests for ref in item.fact_refs),
        *(ref for item in report.unknowns for ref in item.fact_refs),
    )


def validate_report(
    report: ChiefOfStaffReport,
    *,
    context: ChiefOfStaffContext,
    pin: HermesPin | None = None,
    max_output_bytes: int = 131_072,
) -> ChiefOfStaffReport:
    expected_pin = pin or load_hermes_pin()
    if report.context_fingerprint != context_fingerprint(context):
        raise ReportValidationError("context fingerprint mismatch")
    if (
        report.cadence != context.cadence
        or report.period_start != context.period_start
        or report.period_end != context.period_end
    ):
        raise ReportValidationError("report period does not match context")
    if report.profile_version != context.profile_version:
        raise ReportValidationError("profile version mismatch")
    if report.supervisor_version != f"hermes-agent-{expected_pin.version}":
        raise ReportValidationError("report Hermes pin mismatch")

    facts = {fact.fact_ref: fact for fact in context.facts}
    cited = _cited_fact_refs(report)
    unknown = sorted(set(cited).difference(facts))
    if unknown:
        raise ReportValidationError(f"unknown fact_ref: {unknown[0]}")
    allowed_sources = set(facts)
    allowed_sources.update(item.source_ref for item in context.business_memory)
    unknown_sources = sorted(set(report.source_refs).difference(allowed_sources))
    if unknown_sources:
        raise ReportValidationError(f"unknown source reference: {unknown_sources[0]}")
    if report.executive_status == "CRITICAL":
        known_evidence = any(
            facts[ref].data_status in {"KNOWN", "STALE"}
            for observation in report.observations
            for ref in observation.fact_refs
        )
        if not report.observations or not known_evidence:
            raise ReportValidationError("critical conclusion lacks known evidence")
    if any(not item.human_decision_required for item in report.decision_requests):
        raise ReportValidationError("decision request must be explicitly human")

    for text in _narratives(report):
        if _DIGIT.search(text):
            raise ReportValidationError("free-form numeric narrative is forbidden")
        if _EMAIL.search(text) or _SECRET.search(text):
            raise ReportValidationError("PII or secret-like content is forbidden")
        if _FORBIDDEN_COMMAND.search(text):
            raise ReportValidationError("forbidden command or provider appears in report")
        if _EXECUTED.search(text):
            raise ReportValidationError("report claims an action was executed")
        if _SCOPE_EXPANSION.search(text):
            raise ReportValidationError("report attempts to expand its scope")
    if len(report.model_dump_json().encode("utf-8")) > max_output_bytes:
        raise ReportValidationError("report output size exceeds limit")
    return report


__all__ = ["ReportValidationError", "validate_report"]
