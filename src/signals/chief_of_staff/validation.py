"""Deterministic semantic validation after strict report parsing."""

from __future__ import annotations

import re
import unicodedata

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
_QUALITATIVE_QUANTITY = re.compile(
    r"(?:\b(?:doubl\w*|tripl\w*|multipl\w*|majorit\w*|minor(?:ite|ity)|"
    r"moitie|half|most|twice|\w+fold|augment\w*|hauss\w*|baiss\w*|diminu\w*|croiss\w*|"
    r"chut\w*|progress\w*|recul\w*|increas\w*|decreas\w*|growth|drop\w*|"
    r"improv\w*|declin\w*)\b|"
    r"\b(?:deux|trois|twice|three)\s+fois\s+plus\b|"
    r"\b(?:presque|quasi|almost|nearly)\s+(?:tous|toutes|all)\b|"
    r"\b(?:more|less)\s+than\b)",
    re.IGNORECASE,
)


class ReportValidationError(ValueError):
    """A parsed report violates Kivou's semantic publication boundary."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _reject(message: str, code: str) -> None:
    raise ReportValidationError(message, code=code)


def _normalized(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )


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
        _reject("context fingerprint mismatch", "CONTEXT_FINGERPRINT_MISMATCH")
    if (
        report.cadence != context.cadence
        or report.period_start != context.period_start
        or report.period_end != context.period_end
    ):
        _reject("report period does not match context", "REPORT_PERIOD_MISMATCH")
    if report.profile_version != context.profile_version:
        _reject("profile version mismatch", "PROFILE_VERSION_MISMATCH")
    if report.supervisor_version != f"hermes-agent-{expected_pin.version}":
        _reject("report Hermes pin mismatch", "HERMES_VERSION_MISMATCH")

    facts = {fact.fact_ref: fact for fact in context.facts}
    cited = _cited_fact_refs(report)
    unknown = sorted(set(cited).difference(facts))
    if unknown:
        _reject("unknown fact_ref", "UNKNOWN_FACT_REF")
    allowed_sources = set(facts)
    allowed_sources.update(item.source_ref for item in context.business_memory)
    unknown_sources = sorted(set(report.source_refs).difference(allowed_sources))
    if unknown_sources:
        _reject("unknown source reference", "UNKNOWN_SOURCE_REF")
    if not set(cited).issubset(report.source_refs):
        _reject("cited fact_ref missing from source refs", "SOURCE_REF_INCOMPLETE")

    if report.executive_status == "CRITICAL":
        known_evidence = any(
            facts[ref].data_status in {"KNOWN", "STALE"}
            for observation in report.observations
            for ref in observation.fact_refs
        )
        if not report.observations or not known_evidence:
            _reject("critical conclusion lacks known evidence", "CRITICAL_WITHOUT_EVIDENCE")
    for observation in report.observations:
        statuses = {facts[ref].data_status for ref in observation.fact_refs}
        if observation.kind == "UNKNOWN":
            if "KNOWN" in statuses:
                _reject("unknown observation cites known evidence", "UNKNOWN_PRESENTED_AS_FACT")
        elif not statuses.intersection({"KNOWN", "STALE"}):
            _reject(
                "observation lacks known evidence",
                "OBSERVATION_EVIDENCE_INSUFFICIENT",
            )
    for item in report.unknowns:
        if any(facts[ref].data_status == "KNOWN" for ref in item.fact_refs):
            _reject("unknown cites known evidence", "UNKNOWN_PRESENTED_AS_FACT")
    if any(not item.human_decision_required for item in report.decision_requests):
        _reject("decision request must be explicitly human", "DECISION_NOT_HUMAN")

    for text in _narratives(report):
        if _DIGIT.search(text):
            _reject("free-form numeric narrative is forbidden", "NUMERIC_HALLUCINATION")
        if _QUALITATIVE_QUANTITY.search(_normalized(text)):
            _reject(
                "unverified quantitative narrative is forbidden",
                "UNVERIFIED_QUANTITATIVE_CLAIM",
            )
        if _EMAIL.search(text) or _SECRET.search(text):
            _reject("PII or secret-like content is forbidden", "SENSITIVE_CONTENT")
        if _FORBIDDEN_COMMAND.search(text):
            _reject(
                "forbidden command or provider appears in report",
                "FORBIDDEN_COMMAND",
            )
        if _EXECUTED.search(text):
            _reject("report claims an action was executed", "ACTION_EXECUTION_CLAIM")
        if _SCOPE_EXPANSION.search(text):
            _reject("report attempts to expand its scope", "SCOPE_EXPANSION")
    if len(report.model_dump_json().encode("utf-8")) > max_output_bytes:
        _reject("report output size exceeds limit", "REPORT_TOO_LARGE")
    return report


__all__ = ["ReportValidationError", "validate_report"]
