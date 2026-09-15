from __future__ import annotations

import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[2] / "src/signals/chief_of_staff/evaluation_cases.v1.json"


def test_evaluation_fixture_covers_all_required_scenarios() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["version"] == "chief-of-staff-evaluation-v1"
    cases = payload["cases"]
    assert len(cases) == 15
    assert {case["case_id"] for case in cases} == {
        "healthy_system",
        "ted_ingestion_blocked",
        "stale_source",
        "payment_webhook_degraded",
        "conversion_drop",
        "unknown_mrr",
        "insufficient_m2",
        "chf_eur_coexist",
        "acquisition_runtime_stopped",
        "critical_incident",
        "contradictory_data",
        "empty_context",
        "prompt_injection",
        "invented_reference",
        "unsupported_recommendation",
    }
    for case in cases:
        assert isinstance(case["input_facts"], list)
        assert isinstance(case["minimal_memory"], list)
        assert case["expected_status"] in {"HEALTHY", "WATCH", "CRITICAL", "UNKNOWN"}
        assert case["expected_domains"]
        assert case["expected_reason_codes"]
        assert isinstance(case["allowed_priorities"], list)
        assert case["forbidden_conclusions"]
