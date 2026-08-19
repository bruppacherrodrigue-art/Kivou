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


def _official_oneshot(**kwargs: Any) -> str:
    from agent.oneshot import run_oneshot

    return run_oneshot(**kwargs)


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
    oneshot: Callable[..., str] | None = None,
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
    }
    if set(request) != required:
        raise BridgeRequestError("plan request fields are incomplete or unknown")
    instructions = request["instructions"]
    context_json = request["context_json"]
    if not isinstance(instructions, str) or not instructions.strip():
        raise BridgeRequestError("instructions are required")
    if not isinstance(context_json, str) or not context_json.strip():
        raise BridgeRequestError("context_json is required")
    max_tokens = int(_positive_number(request["max_tokens"], name="max_tokens", maximum=16_384))
    timeout = _positive_number(
        request["timeout_seconds"], name="timeout_seconds", maximum=300
    )

    metadata = _validated_metadata(metadata_loader)
    load_profile_environment()
    invoke = oneshot or _official_oneshot
    response = invoke(
        instructions=instructions,
        user_input=context_json,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    if not isinstance(response, str):
        raise BridgeRequestError("Hermes one-shot response must be text")
    return {"ok": True, **metadata, "response": response}


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
