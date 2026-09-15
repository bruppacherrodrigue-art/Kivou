from __future__ import annotations

from signals.chief_of_staff.demo import run_demo


def test_offline_demo_builds_validates_persists_and_reads_founder_api(tmp_path) -> None:
    result = run_demo(tmp_path / "chief-demo.sqlite")
    assert result == {
        "fixture_version": "chief-of-staff-demo-v1",
        "context_fingerprint": result["context_fingerprint"],
        "fact_count": 3,
        "report_ref": "report:demo:daily",
        "executive_status": "WATCH",
        "observation_count": 2,
        "priority_count": 2,
        "decision_request_count": 1,
        "unknown_count": 1,
        "inserted": True,
        "founder_api_state": "AVAILABLE",
        "provider_calls": 0,
    }
    assert len(result["context_fingerprint"]) == 64


def test_offline_demo_is_idempotent(tmp_path) -> None:
    output = tmp_path / "chief-demo.sqlite"
    assert run_demo(output)["inserted"] is True
    assert run_demo(output)["inserted"] is False
