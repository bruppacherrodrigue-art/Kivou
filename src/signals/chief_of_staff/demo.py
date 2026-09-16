"""Reproducible offline demonstration of the complete publication path."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from signals.chief_of_staff.attempt_store import ChiefOfStaffAttemptStore
from signals.chief_of_staff.business_memory import load_business_memory
from signals.chief_of_staff.context import build_context, context_fingerprint
from signals.chief_of_staff.contracts import (
    REPORT_VERSION,
    ChiefOfStaffDecisionRequest,
    ChiefOfStaffFact,
    ChiefOfStaffObservation,
    ChiefOfStaffPriority,
    ChiefOfStaffReport,
    ChiefOfStaffUnknown,
)
from signals.chief_of_staff.store import ChiefOfStaffReportStore
from signals.chief_of_staff.validation import validate_report
from signals.founder_api.app import create_founder_app
from signals.founder_api.config import FounderApiConfig
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.supervisor.pin import load_hermes_pin

DEMO_FIXTURE = Path(__file__).with_name("demo_fixture.v1.json")


def _aware(value: str) -> dt.datetime:
    result = dt.datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("demo fixture timestamps must be timezone-aware")
    return result


def _overview(readiness: dict[str, str]) -> SimpleNamespace:
    def gate(name: str) -> SimpleNamespace:
        status = readiness[name]
        reasons = () if status == "READY" else ("DEMO_GATE_NOT_READY",)
        return SimpleNamespace(status=status, reason_codes=reasons)

    return SimpleNamespace(
        system=SimpleNamespace(
            readiness=SimpleNamespace(
                **{name: gate(name) for name in readiness}
            )
        ),
        attention=(),
    )


def _simulated_report(context) -> ChiefOfStaffReport:
    pin = load_hermes_pin()
    operations_ref = next(
        fact.fact_ref for fact in context.facts if fact.domain == "OPERATIONS"
    )
    business_ref = next(
        fact.fact_ref for fact in context.facts if fact.domain == "BUSINESS"
    )
    unknown_ref = next(
        fact.fact_ref
        for fact in context.facts
        if fact.data_status == "INSUFFICIENT_EVIDENCE"
    )
    return ChiefOfStaffReport(
        report_ref="report:demo:daily",
        context_fingerprint=context_fingerprint(context),
        cadence=context.cadence,
        period_start=context.period_start,
        period_end=context.period_end,
        created_at=context.generated_at,
        executive_status="WATCH",
        executive_summary="La situation opérationnelle demande une revue humaine.",
        reason_codes=("OPERATIONS_DEGRADED", "INSUFFICIENT_M2_EVIDENCE"),
        observations=(
            ChiefOfStaffObservation(
                observation_id="observation:operations",
                domain="OPERATIONS",
                kind="RISK",
                summary="La santé opérationnelle est dégradée.",
                impact="La fiabilité doit être vérifiée avant toute évolution.",
                reason_codes=("OPERATIONS_DEGRADED",),
                fact_refs=(operations_ref,),
                confidence=Decimal("0.9"),
            ),
            ChiefOfStaffObservation(
                observation_id="observation:business",
                domain="BUSINESS",
                kind="STATUS",
                summary="Un revenu vérifié est disponible dans sa devise source.",
                impact="La lecture business peut rester séparée par devise.",
                reason_codes=("CURRENCY_PRESERVED",),
                fact_refs=(business_ref,),
                confidence=Decimal("0.9"),
            ),
        ),
        priorities=(
            ChiefOfStaffPriority(
                priority=1,
                owner="ENGINEERING",
                recommended_action="Examiner la santé opérationnelle et préparer un diagnostic.",
                reason_codes=("OPERATIONS_DEGRADED",),
                fact_refs=(operations_ref,),
                approval_required=True,
            ),
            ChiefOfStaffPriority(
                priority=2,
                owner="DATA",
                recommended_action="Vérifier la disponibilité des preuves de rétention.",
                reason_codes=("INSUFFICIENT_M2_EVIDENCE",),
                fact_refs=(unknown_ref,),
                approval_required=True,
            ),
        ),
        decision_requests=(
            ChiefOfStaffDecisionRequest(
                decision_id="decision:operational-focus",
                question="Le fondateur souhaite-t-il prioriser le diagnostic opérationnel ?",
                reason_codes=("FOUNDER_DECISION_REQUIRED",),
                fact_refs=(operations_ref,),
            ),
        ),
        unknowns=(
            ChiefOfStaffUnknown(
                unknown_id="unknown:m2",
                domain="DATA",
                summary="Les preuves de rétention sont insuffisantes.",
                reason_codes=("INSUFFICIENT_M2_EVIDENCE",),
                fact_refs=(unknown_ref,),
            ),
        ),
        source_refs=tuple(sorted((business_ref, operations_ref, unknown_ref))),
        confidence=Decimal("0.8"),
        supervisor_version=f"hermes-agent-{pin.version}",
        profile_version="1.1.0",
    )


def _read_founder_api(app) -> dict[str, Any]:
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/founder/chief-of-staff/latest"
    )
    projection = route.endpoint(identity=None, cadence=None)
    return projection.model_dump(mode="json")


def run_demo(output: Path) -> dict[str, Any]:
    fixture = json.loads(DEMO_FIXTURE.read_text(encoding="utf-8"))
    facts = tuple(
        ChiefOfStaffFact.model_validate_json(json.dumps(item))
        for item in fixture["facts"]
    )
    context = build_context(
        overview=_overview(fixture["readiness"]),
        facts=facts,
        memory=load_business_memory(),
        cadence="DAILY",
        period_start=_aware(fixture["period_start"]),
        period_end=_aware(fixture["period_end"]),
        generated_at=_aware(fixture["generated_at"]),
    )
    report = validate_report(_simulated_report(context), context=context)
    engine = create_database_engine(f"sqlite+pysqlite:///{output}")
    migrate_to_latest(engine)
    store = ChiefOfStaffReportStore(engine)
    stored, inserted = store.append(
        report=report,
        context=context,
        captured_at=context.generated_at,
        model_route="fixture/offline-no-provider",
        usage_metadata={"fixture": fixture["fixture_version"]},
        estimated_cost=Decimal("0"),
        actual_cost=Decimal("0"),
        model_call_id=None,
    )
    replayed, replay_inserted = store.append(
        report=report,
        context=context,
        captured_at=context.generated_at,
        model_route="fixture/offline-no-provider",
        usage_metadata={"fixture": fixture["fixture_version"]},
        estimated_cost=Decimal("0"),
        actual_cost=Decimal("0"),
        model_call_id=None,
    )
    if replayed.report.report_ref != stored.report.report_ref or replay_inserted:
        raise RuntimeError("offline demo report idempotence failed")
    attempts = ChiefOfStaffAttemptStore(engine)
    attempt = attempts.append(
        attempt_id=str(uuid.uuid4()),
        context_fingerprint=context_fingerprint(context),
        cadence=context.cadence,
        period_start=context.period_start,
        period_end=context.period_end,
        started_at=context.generated_at,
        completed_at=context.generated_at,
        model_route="fixture/offline-no-provider",
        model_call_id=None,
        status="VALIDATED_PERSISTED" if inserted else "IDEMPOTENT_EXISTING",
        stage="COMPLETE",
        result_code="REPORT_PERSISTED" if inserted else "REPORT_ALREADY_EXISTS",
        profile_version=context.profile_version,
        context_version=context.context_version,
        expected_report_version=REPORT_VERSION,
        hermes_version=load_hermes_pin().version,
    )
    secret = "offline-demo-origin-secret-value-000000000"
    app = create_founder_app(
        FounderApiConfig(
            allowed_email="rodrigue.bruppacher@gmail.com",
            allowed_user="rodrigue",
            origin_secret=secret,
        ),
        now_override=lambda: context.generated_at,
        chief_of_staff_store=store,
    )
    payload = _read_founder_api(app)
    engine.dispose()
    return {
        "fixture_version": fixture["fixture_version"],
        "context_fingerprint": context_fingerprint(context),
        "fact_count": len(context.facts),
        "context_bytes": len(context.model_dump_json().encode("utf-8")),
        "capabilities": {
            item.capability: item.status for item in context.capabilities
        },
        "report_ref": stored.report.report_ref,
        "executive_status": stored.report.executive_status,
        "observation_count": len(stored.report.observations),
        "priority_count": len(stored.report.priorities),
        "decision_request_count": len(stored.report.decision_requests),
        "unknown_count": len(stored.report.unknowns),
        "inserted": inserted,
        "idempotent_replay_inserted": replay_inserted,
        "founder_api_state": payload["state"],
        "attempt_status": attempt.status,
        "attempt_result_code": attempt.result_code,
        "attempt_reserved_usd": str(attempt.reserved_usd),
        "provider_calls": 0,
        "business_actions": 0,
    }


__all__ = ["DEMO_FIXTURE", "run_demo"]
