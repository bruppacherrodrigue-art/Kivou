"""Stdlib JSON bridge executed by the separately installed Hermes Python.

This module deliberately has no import from the rest of Kivou. The isolated
Hermes environment can execute this file directly without installing Kivou.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, BinaryIO, TextIO

BRIDGE_PROTOCOL_VERSION = 1
MAX_BRIDGE_REQUEST_BYTES = 2_000_000
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
OPENROUTER_PROVIDER = "openrouter"
OPENROUTER_MODEL = "anthropic/claude-sonnet-4.6"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_PROVIDER_ROUTING = {
    "require_parameters": True,
    "data_collection": "deny",
}


class BridgeRequestError(ValueError):
    pass


def _repository_root(module_file: str) -> Path:
    return Path(module_file).resolve().parent.parent


def _git_directory(root: Path) -> Path | None:
    marker = root / ".git"
    if marker.is_dir():
        return marker
    if not marker.is_file():
        return None
    text = marker.read_text(encoding="utf-8", errors="strict").strip()
    prefix = "gitdir: "
    if not text.startswith(prefix):
        return None
    candidate = Path(text[len(prefix) :])
    return candidate if candidate.is_absolute() else (root / candidate).resolve()


def _source_commit(module_file: str) -> str | None:
    root = _repository_root(module_file)
    git_dir = _git_directory(root)
    if git_dir is None:
        return None
    try:
        head = (git_dir / "HEAD").read_text(encoding="ascii").strip()
        if _COMMIT_PATTERN.fullmatch(head):
            return head
        prefix = "ref: "
        if not head.startswith(prefix):
            return None
        reference = head[len(prefix) :]
        commit = (git_dir / reference).read_text(encoding="ascii").strip()
        return commit if _COMMIT_PATTERN.fullmatch(commit) else None
    except OSError:
        return None


def runtime_metadata() -> dict[str, Any]:
    from agent import oneshot as hermes_oneshot

    return {
        "protocol_version": BRIDGE_PROTOCOL_VERSION,
        "hermes_version": importlib.metadata.version("hermes-agent"),
        "source_commit": _source_commit(hermes_oneshot.__file__),
        # The bridge exposes one stateless model call and never loads a tool registry.
        "executable_tools": [],
    }


def _load_profile_environment() -> None:
    from hermes_cli.env_loader import load_hermes_dotenv

    hermes_home = os.environ.get("HERMES_HOME")
    if not hermes_home:
        raise BridgeRequestError("dedicated HERMES_HOME is required")
    load_hermes_dotenv(
        hermes_home=hermes_home,
        project_env=None,
        load_external_secrets=False,
    )


def _official_oneshot(
    *,
    instructions: str,
    user_input: str,
    max_tokens: int,
    timeout: float,
    provider: str,
    model: str,
    provider_routing: Mapping[str, Any],
    response_schema: Mapping[str, Any],
) -> dict[str, Any]:
    """Make one exact OpenRouter call through Hermes' zero-retry client helper."""
    if (
        provider != OPENROUTER_PROVIDER
        or model != OPENROUTER_MODEL
        or dict(provider_routing) != OPENROUTER_PROVIDER_ROUTING
    ):
        raise BridgeRequestError("the frozen OpenRouter route is required")
    if not response_schema:
        raise BridgeRequestError("response_schema is required")
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise BridgeRequestError("OpenRouter is not configured")

    # This helper is part of the exact pinned Hermes source. Passing max_retries=0
    # prevents the SDK from retrying, while the direct completion call bypasses
    # Hermes' auxiliary retry and provider/model fallback router entirely.
    from agent.auxiliary_client import _create_openai_client

    client = _create_openai_client(
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
        max_retries=0,
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": user_input},
            ],
            max_tokens=max_tokens,
            timeout=timeout,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "kivou_supervisor_plan",
                    "strict": True,
                    "schema": response_schema,
                },
            },
            extra_body={
                "provider": {
                    **OPENROUTER_PROVIDER_ROUTING,
                    "allow_fallbacks": False,
                }
            },
        )
        actual_model = getattr(response, "model", None)
        choices = getattr(response, "choices", None)
        if actual_model != model or not isinstance(choices, list) or len(choices) != 1:
            raise BridgeRequestError("OpenRouter returned an unexpected route")
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise BridgeRequestError("OpenRouter returned no structured response")
        return {
            "response": content.strip(),
            "provider": OPENROUTER_PROVIDER,
            "model": actual_model,
            "automatic_retries": 0,
            "fallbacks": False,
        }
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _validated_metadata(loader: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    metadata = dict(loader())
    if metadata.get("protocol_version") != BRIDGE_PROTOCOL_VERSION:
        raise BridgeRequestError("invalid bridge protocol")
    version = metadata.get("hermes_version")
    if not isinstance(version, str) or not version:
        raise BridgeRequestError("missing Hermes version")
    commit = metadata.get("source_commit")
    if not isinstance(commit, str) or not _COMMIT_PATTERN.fullmatch(commit):
        raise BridgeRequestError("missing Hermes source commit")
    tools = metadata.get("executable_tools")
    if tools != []:
        raise BridgeRequestError("bridge must expose zero executable tools")
    return {
        "protocol_version": BRIDGE_PROTOCOL_VERSION,
        "hermes_version": version,
        "source_commit": commit,
        "executable_tools": [],
    }


def _positive_number(value: Any, *, name: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeRequestError(f"{name} must be numeric")
    number = float(value)
    if not 0 < number <= maximum:
        raise BridgeRequestError(f"{name} outside allowed range")
    return number


def handle_request(
    request: Mapping[str, Any],
    *,
    metadata_loader: Callable[[], Mapping[str, Any]] = runtime_metadata,
    oneshot: Callable[..., Mapping[str, Any]] | None = None,
    load_profile_environment: Callable[[], None] = _load_profile_environment,
) -> dict[str, Any]:
    operation = request.get("operation")
    if operation == "health":
        if set(request) != {"operation"}:
            raise BridgeRequestError("health request contains unknown fields")
        return {"ok": True, **_validated_metadata(metadata_loader)}
    if operation != "plan":
        raise BridgeRequestError("unknown bridge operation")

    required = {
        "operation",
        "instructions",
        "context_json",
        "max_tokens",
        "timeout_seconds",
        "provider",
        "model",
        "provider_routing",
        "response_schema",
    }
    if set(request) != required:
        raise BridgeRequestError("plan request fields are incomplete or unknown")
    instructions = request["instructions"]
    context_json = request["context_json"]
    provider = request["provider"]
    model = request["model"]
    provider_routing = request["provider_routing"]
    response_schema = request["response_schema"]
    if not isinstance(instructions, str) or not instructions.strip():
        raise BridgeRequestError("instructions are required")
    if not isinstance(context_json, str) or not context_json.strip():
        raise BridgeRequestError("context_json is required")
    if provider != OPENROUTER_PROVIDER or model != OPENROUTER_MODEL:
        raise BridgeRequestError("the exact OpenRouter model is required")
    if (
        not isinstance(provider_routing, Mapping)
        or dict(provider_routing) != OPENROUTER_PROVIDER_ROUTING
    ):
        raise BridgeRequestError("the exact OpenRouter routing policy is required")
    if not isinstance(response_schema, Mapping) or not response_schema:
        raise BridgeRequestError("response_schema is required")
    max_tokens = int(_positive_number(request["max_tokens"], name="max_tokens", maximum=16_384))
    timeout = _positive_number(
        request["timeout_seconds"], name="timeout_seconds", maximum=300
    )

    metadata = _validated_metadata(metadata_loader)
    load_profile_environment()
    invoke = oneshot or _official_oneshot
    route = invoke(
        instructions=instructions,
        user_input=context_json,
        max_tokens=max_tokens,
        timeout=timeout,
        provider=provider,
        model=model,
        provider_routing=provider_routing,
        response_schema=response_schema,
    )
    expected_route_fields = {
        "response",
        "provider",
        "model",
        "automatic_retries",
        "fallbacks",
    }
    if not isinstance(route, Mapping) or set(route) != expected_route_fields:
        raise BridgeRequestError("Hermes one-shot route evidence is incomplete")
    response = route["response"]
    if (
        not isinstance(response, str)
        or route["provider"] != OPENROUTER_PROVIDER
        or route["model"] != OPENROUTER_MODEL
        or route["automatic_retries"] != 0
        or route["fallbacks"] is not False
    ):
        raise BridgeRequestError("Hermes one-shot route evidence is invalid")
    return {"ok": True, **metadata, **dict(route)}


def _write_json(stdout: BinaryIO, value: Mapping[str, Any]) -> None:
    stdout.write(json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n")
    stdout.flush()


def run_bridge(
    *,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    input_stream = stdin or sys.stdin.buffer
    output_stream = stdout or sys.stdout.buffer
    _error_stream = stderr or sys.stderr
    try:
        raw = input_stream.read(MAX_BRIDGE_REQUEST_BYTES + 1)
        if len(raw) > MAX_BRIDGE_REQUEST_BYTES:
            raise BridgeRequestError("request too large")
        request = json.loads(raw.decode("utf-8"))
        if not isinstance(request, dict):
            raise BridgeRequestError("request must be a JSON object")
        result = handle_request(request)
    except (BridgeRequestError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        _write_json(output_stream, {"ok": False, "error": "invalid_request"})
        return 2
    except Exception:  # noqa: BLE001 - child boundary must fail closed without leaking details
        _write_json(output_stream, {"ok": False, "error": "runtime_unavailable"})
        return 1
    _write_json(output_stream, result)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run_bridge())
