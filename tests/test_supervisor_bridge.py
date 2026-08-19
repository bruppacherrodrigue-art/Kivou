from __future__ import annotations

import io
import json

import pytest

from signals.supervisor.hermes_bridge import (
    BRIDGE_PROTOCOL_VERSION,
    BridgeRequestError,
    handle_request,
    run_bridge,
)

PINNED_METADATA = {
    "protocol_version": 1,
    "hermes_version": "0.20.4",
    "source_commit": "e624e9fde561e1add9388384012b295fde669ade",
    "executable_tools": [],
}


def test_health_reports_actual_runtime_identity_and_zero_tools():
    result = handle_request(
        {"operation": "health"}, metadata_loader=lambda: PINNED_METADATA.copy()
    )
    assert BRIDGE_PROTOCOL_VERSION == 1
    assert result == {"ok": True, **PINNED_METADATA}
    assert result["executable_tools"] == []


def test_plan_calls_only_injected_stateless_oneshot_with_bounded_arguments():
    captured = {}

    def oneshot(**kwargs):
        captured.update(kwargs)
        return '{"plan_id":"plan_001"}'

    result = handle_request(
        {
            "operation": "plan",
            "instructions": "system authority",
            "context_json": '{"runtime_mode":"SHADOW"}',
            "max_tokens": 512,
            "timeout_seconds": 4.5,
        },
        metadata_loader=lambda: PINNED_METADATA.copy(),
        oneshot=oneshot,
        load_profile_environment=lambda: None,
    )
    assert captured == {
        "instructions": "system authority",
        "user_input": '{"runtime_mode":"SHADOW"}',
        "max_tokens": 512,
        "timeout": 4.5,
    }
    assert result == {"ok": True, **PINNED_METADATA, "response": '{"plan_id":"plan_001"}'}
    assert "tools" not in captured
    assert "toolsets" not in captured


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"operation": "execute"},
        {"operation": "plan", "instructions": "x"},
        {
            "operation": "plan",
            "instructions": "x",
            "context_json": "{}",
            "max_tokens": 0,
            "timeout_seconds": 1,
        },
        {
            "operation": "plan",
            "instructions": "x",
            "context_json": "{}",
            "max_tokens": 10,
            "timeout_seconds": -1,
        },
    ],
)
def test_malformed_requests_are_rejected_without_best_effort(payload):
    with pytest.raises(BridgeRequestError):
        handle_request(payload, metadata_loader=lambda: PINNED_METADATA.copy())


def test_bridge_writes_one_sanitized_error_object_and_no_secret_to_stderr():
    stdin = io.BytesIO(b'{"operation":"execute","secret":"sk_live_never_print"}')
    stdout = io.BytesIO()
    stderr = io.StringIO()
    code = run_bridge(stdin=stdin, stdout=stdout, stderr=stderr)
    assert code == 2
    response = json.loads(stdout.getvalue())
    assert response == {"ok": False, "error": "invalid_request"}
    assert stderr.getvalue() == ""
    assert b"sk_live_never_print" not in stdout.getvalue()


def test_bridge_rejects_oversized_stdin_before_json_parsing():
    stdin = io.BytesIO(b"x" * 2_000_001)
    stdout = io.BytesIO()
    code = run_bridge(stdin=stdin, stdout=stdout, stderr=io.StringIO())
    assert code == 2
    assert json.loads(stdout.getvalue()) == {"ok": False, "error": "invalid_request"}


def test_metadata_contract_rejects_any_executable_tool_declaration():
    metadata = {**PINNED_METADATA, "executable_tools": ["terminal"]}
    with pytest.raises(BridgeRequestError, match="executable tools"):
        handle_request({"operation": "health"}, metadata_loader=lambda: metadata)
