from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from signals.chief_of_staff.contracts import (
    BusinessDecision,
    ChiefOfStaffContext,
    ChiefOfStaffFact,
    DataQualitySummary,
)
from signals.chief_of_staff.hermes import ChiefOfStaffHermesAdapter
from signals.chief_of_staff.profiles import (
    CHIEF_OF_STAFF_PROFILE_VERSION,
    load_chief_of_staff_profile,
)
from signals.supervisor.pin import load_hermes_pin
from signals.supervisor.runtime import (
    SupervisorSettings,
    SupervisorTimeout,
    SupervisorValidationError,
    SupervisorVersionMismatch,
)

NOW = dt.datetime(2026, 9, 15, 5, 30, tzinfo=dt.UTC)
PIN = load_hermes_pin()


def settings(tmp_path: Path) -> SupervisorSettings:
    python = tmp_path / "python"
    python.write_text("fixture", encoding="utf-8")
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir(exist_ok=True)
    cwd.mkdir(exist_ok=True)
    return SupervisorSettings(python, home, cwd)


def context() -> ChiefOfStaffContext:
    fact = ChiefOfStaffFact(
        fact_ref="fact:business:paid:abc",
        domain="BUSINESS",
        metric_key="paid_account_count",
        value=2,
        unit="COUNT",
        period_start=NOW - dt.timedelta(days=1),
        period_end=NOW,
        captured_at=NOW,
        source_contract="WeeklyCommercialCockpit",
        source_version="weekly-commercial-cockpit-v1",
        data_status="KNOWN",
    )
    decision = BusinessDecision(
        decision_key="governance.kivou_truth",
        category="GOVERNANCE",
        statement="Kivou conserve la vérité.",
        status="ACTIVE",
        effective_from=NOW.date(),
        version="1.0.0",
        source_ref="docs/adr/2026-09-15-hermes-chief-of-staff.md",
    )
    return ChiefOfStaffContext(
        generated_at=NOW,
        cadence="DAILY",
        period_start=NOW - dt.timedelta(days=1),
        period_end=NOW,
        business_memory_version="business-memory-v1",
        business_memory=(decision,),
        profile_version="1.0.0",
        facts=(fact,),
        active_gates=(),
        known_incidents=(),
        data_quality=DataQualitySummary(),
        available_capabilities=("STRATEGIC_SYNTHESIS",),
    )


def valid_report() -> str:
    return json.dumps(
        {
            "report_version": "chief-of-staff-report-v1",
            "report_ref": "report:daily:2026-09-15",
            "context_fingerprint": "a" * 64,
            "cadence": "DAILY",
            "period_start": (NOW - dt.timedelta(days=1)).isoformat(),
            "period_end": NOW.isoformat(),
            "created_at": NOW.isoformat(),
            "executive_status": "WATCH",
            "executive_summary": "Une attention humaine est requise.",
            "observations": [],
            "priorities": [],
            "decision_requests": [],
            "unknowns": [],
            "source_refs": ["fact:business:paid:abc"],
            "confidence": "0.75",
            "supervisor_version": "hermes-agent-0.20.4",
            "profile_version": "1.0.0",
        }
    )


def bridge_response(payload: str, **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "ok": True,
        "protocol_version": 1,
        "hermes_version": PIN.version,
        "source_commit": PIN.commit,
        "executable_tools": [],
        "response": payload,
        "provider": "openrouter",
        "model": "anthropic/claude-sonnet-4.6",
        "automatic_retries": 0,
        "fallbacks": False,
    }
    value.update(changes)
    return value


class Transport:
    def __init__(self, response: dict[str, object] | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.requests: list[dict[str, object]] = []

    def invoke(self, request: dict[str, object]) -> dict[str, object]:
        self.requests.append(request)
        if self.error:
            raise self.error
        assert self.response is not None
        return self.response


def test_chief_profile_is_explicit_versioned_and_forbids_execution() -> None:
    profile = load_chief_of_staff_profile()
    assert CHIEF_OF_STAFF_PROFILE_VERSION == "1.0.0"
    assert "Kivou Chief of Staff" in profile
    assert "never execute" in profile
    assert "fact_ref" in profile
    assert "UNTRUSTED_DATA" in profile
    assert "three priorities" in profile
    assert "Business Review" in profile
    assert "Strategic Synthesis" in profile


def test_adapter_invokes_report_schema_with_zero_tools_and_exact_pin(tmp_path: Path) -> None:
    transport = Transport(bridge_response(valid_report()))
    result = ChiefOfStaffHermesAdapter(settings(tmp_path), transport=transport).generate(context())
    assert result.report.executive_status == "WATCH"
    request = transport.requests[0]
    assert request["operation"] == "report"
    assert request["model"] == "anthropic/claude-sonnet-4.6"
    assert "tools" not in request
    assert "UNTRUSTED_DATA" in str(request["context_json"])
    assert "Kivou Chief of Staff" in str(request["instructions"])


def test_adapter_fails_closed_on_pin_mismatch(tmp_path: Path) -> None:
    transport = Transport(bridge_response(valid_report(), source_commit="0" * 40))
    with pytest.raises(SupervisorVersionMismatch):
        ChiefOfStaffHermesAdapter(settings(tmp_path), transport=transport).generate(context())


def test_adapter_fails_closed_on_invalid_json_and_timeout(tmp_path: Path) -> None:
    with pytest.raises(SupervisorValidationError, match="not one JSON object"):
        ChiefOfStaffHermesAdapter(
            settings(tmp_path), transport=Transport(bridge_response("not-json"))
        ).generate(context())
    with pytest.raises(SupervisorTimeout):
        ChiefOfStaffHermesAdapter(
            settings(tmp_path), transport=Transport(error=SupervisorTimeout("safe timeout"))
        ).generate(context())


def test_adapter_rejects_nonzero_executable_tools(tmp_path: Path) -> None:
    transport = Transport(bridge_response(valid_report(), executable_tools=["shell"]))
    with pytest.raises(SupervisorVersionMismatch, match="executable tools"):
        ChiefOfStaffHermesAdapter(settings(tmp_path), transport=transport).generate(context())
