"""Explicit local smoke against the separately installed pinned Hermes runtime.

This file is intentionally outside pytest's configured ``tests/`` path. Run it
explicitly after installing the official immutable Hermes source commit; normal
CI remains deterministic and uses the fake transport boundary.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

from signals.supervisor.contracts import BudgetEnvelope, SupervisorContext
from signals.supervisor.hermes import HermesSupervisorAdapter
from signals.supervisor.pin import load_hermes_pin
from signals.supervisor.profile import PROFILE_VERSION
from signals.supervisor.registry import ALLOWED_COMMANDS
from signals.supervisor.runtime import HealthState, SupervisorLimits, SupervisorSettings


def _required_path(name: str) -> Path:
    value = os.environ.get(name)
    assert value, f"{name} must point at the explicit pinned Hermes smoke runtime"
    path = Path(value)
    assert path.is_absolute() and path.exists()
    return path


def _plan() -> dict[str, Any]:
    return {
        "plan_id": "spec017-runtime-smoke",
        "created_at": "2026-08-19T16:00:00Z",
        "objective": "Return an advisory no-action shadow plan",
        "priority": 3,
        "proposed_actions": [],
        "reason_codes": ["NO_ACTION_PREFERRED"],
        "confidence": "1",
        "estimated_cost": "0",
        "next_review_at": "2026-08-19T17:00:00Z",
        "supervisor_version": f"hermes-agent-{load_hermes_pin().version}",
        "skill_version": PROFILE_VERSION,
    }


class _OpenAICompatibleHandler(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict[str, Any]]] = []
    response_plan: ClassVar[dict[str, Any]] = {}

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        type(self).requests.append(request)
        payload = {
            "id": "spec017-local-smoke",
            "object": "chat.completion",
            "created": 1_776_614_400,
            "model": "kivou-hermes-smoke",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(type(self).response_plan),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def test_actual_pinned_hermes_oneshot_exposes_zero_executable_tools(tmp_path: Path) -> None:
    hermes_python = _required_path("KIVOU_SPEC017_HERMES_PYTHON")
    hermes_source = _required_path("KIVOU_SPEC017_HERMES_SOURCE")
    assert (hermes_source / ".git").exists()
    source_commit = subprocess.run(
        ["git", "-C", str(hermes_source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert source_commit == load_hermes_pin().commit

    _OpenAICompatibleHandler.requests = []
    _OpenAICompatibleHandler.response_plan = _plan()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OpenAICompatibleHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        hermes_home = tmp_path / "controlled-hermes-home"
        hermes_cwd = tmp_path / "controlled-hermes-cwd"
        hermes_home.mkdir()
        hermes_cwd.mkdir()
        port = server.server_address[1]
        (hermes_home / "config.yaml").write_text(
            "\n".join(
                [
                    "model:",
                    "  default: kivou-hermes-smoke",
                    "  provider: custom",
                    f"  base_url: http://127.0.0.1:{port}/v1",
                    "auxiliary:",
                    "  title_generation:",
                    "    provider: custom",
                    "    model: kivou-hermes-smoke",
                    f"    base_url: http://127.0.0.1:{port}/v1",
                    "    key_env: OPENAI_API_KEY",
                    "    fallback_chain: []",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (hermes_home / ".env").write_text(
            "OPENAI_API_KEY=local-smoke-placeholder\n", encoding="utf-8"
        )

        settings = SupervisorSettings(
            hermes_python=hermes_python,
            hermes_home=hermes_home,
            working_directory=hermes_cwd,
            limits=SupervisorLimits(invocation_timeout_seconds=15),
        )
        adapter = HermesSupervisorAdapter(settings)

        health = adapter.health()
        assert health.state is HealthState.AVAILABLE
        assert health.executable_tools == ()

        context = SupervisorContext(
            current_time=dt.datetime(2026, 8, 19, 16, 0, tzinfo=dt.UTC),
            runtime_mode="SHADOW",
            policy_version="policy-placeholder-v1",
            budget=BudgetEnvelope(currency="CHF", maximum_cycle_cost=Decimal("1")),
            available_commands=tuple(sorted(ALLOWED_COMMANDS)),
        )
        result = adapter.plan(context)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

    assert result.plan_id == "spec017-runtime-smoke"
    assert result.proposed_actions == ()
    assert len(_OpenAICompatibleHandler.requests) == 1
    wire_request = _OpenAICompatibleHandler.requests[0]
    assert "tools" not in wire_request
    assert "tool_choice" not in wire_request
    assert wire_request["model"] == "kivou-hermes-smoke"
    assert [message["role"] for message in wire_request["messages"]] == ["system", "user"]
    context_on_wire = json.loads(wire_request["messages"][1]["content"])
    assert context_on_wire["content_boundary"] == "UNTRUSTED_DATA"
