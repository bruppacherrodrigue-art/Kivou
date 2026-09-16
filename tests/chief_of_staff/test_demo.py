from __future__ import annotations

from signals.chief_of_staff.demo import run_demo


def test_offline_demo_builds_validates_persists_and_reads_founder_api(tmp_path) -> None:
    result = run_demo(tmp_path / "chief-demo.sqlite")
    assert result == {
        "fixture_version": "chief-of-staff-demo-v1",
        "context_fingerprint": result["context_fingerprint"],
        "fact_count": 3,
        "context_bytes": result["context_bytes"],
        "capabilities": {
            "BUSINESS_REVIEW": "AVAILABLE",
            "PRODUCT_JOURNEY_REVIEW": "UNAVAILABLE",
            "DATA_HEALTH_REVIEW": "INSUFFICIENT_EVIDENCE",
            "OPERATIONS_REVIEW": "AVAILABLE",
            "ACQUISITION_REVIEW": "INSUFFICIENT_EVIDENCE",
            "ROADMAP_RELEASE_REVIEW": "UNAVAILABLE",
            "STRATEGIC_SYNTHESIS": "INSUFFICIENT_EVIDENCE",
        },
        "report_ref": "report:demo:daily",
        "executive_status": "WATCH",
        "observation_count": 2,
        "priority_count": 2,
        "decision_request_count": 1,
        "unknown_count": 1,
        "inserted": True,
        "idempotent_replay_inserted": False,
        "founder_api_state": "AVAILABLE",
        "attempt_status": "VALIDATED_PERSISTED",
        "attempt_result_code": "REPORT_PERSISTED",
        "attempt_reserved_usd": "0E-8",
        "provider_calls": 0,
        "business_actions": 0,
    }
    assert len(result["context_fingerprint"]) == 64
    assert 0 < result["context_bytes"] <= 65_536


def test_offline_demo_is_idempotent(tmp_path) -> None:
    output = tmp_path / "chief-demo.sqlite"
    assert run_demo(output)["inserted"] is True
    replay = run_demo(output)
    assert replay["inserted"] is False
    assert replay["attempt_status"] == "IDEMPOTENT_EXISTING"
    assert replay["attempt_result_code"] == "REPORT_ALREADY_EXISTS"
