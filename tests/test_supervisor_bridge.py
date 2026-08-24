from __future__ import annotations

import io
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

from signals.supervisor import hermes_bridge as bridge_module
from signals.supervisor.contracts import SupervisorPlan
from signals.supervisor.hermes import transform_provider_schema
from signals.supervisor.hermes_bridge import (
    BRIDGE_PROTOCOL_VERSION,
    BridgeRequestError,
    _official_oneshot,
    handle_request,
    run_bridge,
)

PINNED_METADATA = {
    "protocol_version": 1,
    "hermes_version": "0.20.4",
    "source_commit": "e624e9fde561e1add9388384012b295fde669ade",
    "executable_tools": [],
}
MODEL = "anthropic/claude-sonnet-4.6"
ROUTING = {
    "require_parameters": True,
    "data_collection": "deny",
}
PROVIDER_SCHEMA = transform_provider_schema(SupervisorPlan.model_json_schema())


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
        return {
            "response": '{"plan_id":"plan_001"}',
            "provider": "openrouter",
            "model": MODEL,
            "automatic_retries": 0,
            "fallbacks": False,
        }

    result = handle_request(
        {
            "operation": "plan",
            "instructions": "system authority",
            "context_json": '{"runtime_mode":"SHADOW"}',
            "max_tokens": 512,
            "timeout_seconds": 4.5,
            "provider": "openrouter",
            "model": MODEL,
            "provider_routing": ROUTING,
            "response_schema": PROVIDER_SCHEMA,
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
        "provider": "openrouter",
        "model": MODEL,
        "provider_routing": ROUTING,
        "response_schema": PROVIDER_SCHEMA,
    }
    assert result == {
        "ok": True,
        **PINNED_METADATA,
        "response": '{"plan_id":"plan_001"}',
        "provider": "openrouter",
        "model": MODEL,
        "automatic_retries": 0,
        "fallbacks": False,
    }
    assert "tools" not in captured
    assert "toolsets" not in captured


def test_official_oneshot_makes_one_exact_openrouter_request_without_retry_or_fallback(
    monkeypatch,
):
    captured: dict[str, object] = {}

    class Completions:
        def create(self, **kwargs):
            captured.setdefault("requests", []).append(kwargs)
            return SimpleNamespace(
                model=MODEL,
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"plan_id":"p"}'))],
            )

    class Client:
        def __init__(self):
            self.chat = SimpleNamespace(completions=Completions())

        def close(self):
            captured["closed"] = True

    auxiliary = ModuleType("agent.auxiliary_client")

    def create_client(**kwargs):
        captured["client"] = kwargs
        return Client()

    auxiliary._create_openai_client = create_client
    agent = ModuleType("agent")
    agent.__path__ = []
    monkeypatch.setitem(sys.modules, "agent", agent)
    monkeypatch.setitem(sys.modules, "agent.auxiliary_client", auxiliary)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter")

    result = _official_oneshot(
        instructions="system authority",
        user_input='{"runtime_mode":"SHADOW"}',
        max_tokens=2_048,
        timeout=30,
        provider="openrouter",
        model=MODEL,
        provider_routing=ROUTING,
        response_schema=PROVIDER_SCHEMA,
    )

    assert captured["client"] == {
        "api_key": "synthetic-openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "max_retries": 0,
    }
    requests = captured["requests"]
    assert isinstance(requests, list) and len(requests) == 1
    assert requests[0]["model"] == MODEL
    assert requests[0]["max_tokens"] == 2_048
    assert requests[0]["timeout"] == 30
    assert requests[0]["extra_body"] == {
        "provider": {
            "require_parameters": True,
            "data_collection": "deny",
            "allow_fallbacks": False,
        }
    }
    assert requests[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "kivou_supervisor_plan",
            "strict": True,
            "schema": PROVIDER_SCHEMA,
        },
    }
    assert "tools" not in requests[0]
    assert result == {
        "response": '{"plan_id":"p"}',
        "provider": "openrouter",
        "model": MODEL,
        "automatic_retries": 0,
        "fallbacks": False,
    }
    assert captured["closed"] is True


def _provider_exception(name: str, *, status_code: int | None = None) -> Exception:
    exception = type(name, (RuntimeError,), {})(
        "provider detail and sk-secret must never cross the bridge"
    )
    if status_code is not None:
        exception.status_code = status_code
    return exception


@pytest.mark.parametrize(
    ("failure", "expected_error", "expected_status"),
    [
        (_provider_exception("AuthenticationError", status_code=401), "AUTH", 401),
        (_provider_exception("PermissionDeniedError", status_code=403), "PERMISSION", 403),
        (_provider_exception("RateLimitError", status_code=429), "RATE_LIMITED", 429),
        (_provider_exception("BadRequestError", status_code=400), "HERMES_PLAN_INVALID", 400),
        (
            _provider_exception("UnprocessableEntityError", status_code=422),
            "HERMES_PLAN_INVALID",
            422,
        ),
        (_provider_exception("InternalServerError", status_code=503), "SERVER_ERROR", 503),
        (_provider_exception("APITimeoutError"), "TIMEOUT", None),
        (_provider_exception("APIConnectionError"), "NETWORK", None),
    ],
)
def test_bridge_serializes_only_closed_provider_error_category(
    monkeypatch, failure, expected_error, expected_status
):
    def fail(_request):
        raise failure

    monkeypatch.setattr(bridge_module, "handle_request", fail)
    stdout = io.BytesIO()
    stderr = io.StringIO()

    code = run_bridge(stdin=io.BytesIO(b'{"operation":"plan"}'), stdout=stdout, stderr=stderr)

    expected = {"ok": False, "error": expected_error}
    if expected_status is not None:
        expected["status"] = expected_status
    assert code == 0
    assert json.loads(stdout.getvalue()) == expected
    assert stderr.getvalue() == ""
    assert b"provider detail" not in stdout.getvalue()
    assert b"sk-secret" not in stdout.getvalue()


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
