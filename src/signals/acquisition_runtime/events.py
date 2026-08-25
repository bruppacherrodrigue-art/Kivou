"""Closed, PII-free operational events for the Acquisition runtime."""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import TextIO

from signals.acquisition_runtime.contracts import AcquisitionRuntimeStage

LOGGER_NAME = "signals.acquisition_runtime.events"
_HANDLER_MARKER = "_kivou_acquisition_runtime_events"
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_MACHINE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")
_ACTIONS = frozenset({"lease", "cycle", "stage", "health", "runtime"})
_STATUSES = frozenset(
    {
        "started",
        "already_running",
        "succeeded",
        "waiting",
        "blocked",
        "failed",
        "suppressed",
        "cancelled",
        "released",
        "ready",
        "not_ready",
    }
)
_STAGES = frozenset(stage.value for stage in AcquisitionRuntimeStage)
_REQUIRED_KEYS = frozenset({"event", "action", "status", "code", "attempt"})
_ALLOWED_KEYS = _REQUIRED_KEYS | {"cycle_ref", "stage"}


class _ClosedJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = _validated_payload(getattr(record, "runtime_event", None))
        return json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


def configure_acquisition_runtime_logging(
    *, stream: TextIO | None = None
) -> logging.Logger:
    """Attach one dedicated handler without altering uvicorn/root logging."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.disabled = False
    logger.propagate = False
    if not any(
        getattr(handler, _HANDLER_MARKER, False) for handler in logger.handlers
    ):
        handler = logging.StreamHandler(stream or sys.stderr)
        setattr(handler, _HANDLER_MARKER, True)
        handler.setLevel(logging.INFO)
        handler.setFormatter(_ClosedJsonFormatter())
        logger.addHandler(handler)
    return logger


def emit_acquisition_runtime_event(
    *,
    action: str,
    status: str,
    code: str,
    attempt: int = 0,
    cycle_ref: str | None = None,
    stage: str | None = None,
) -> None:
    """Emit only allowlisted state and opaque internal identifiers."""

    payload: dict[str, str | int] = {
        "event": "acquisition_runtime",
        "action": action if action in _ACTIONS else "runtime",
        "status": status if status in _STATUSES else "failed",
        "code": code if _MACHINE_CODE.fullmatch(code) else "INVALID_RUNTIME_VALUE",
        "attempt": max(0, int(attempt)),
    }
    if cycle_ref is not None:
        payload["cycle_ref"] = (
            cycle_ref if _FINGERPRINT.fullmatch(cycle_ref) else "invalid_ref"
        )
    if stage is not None:
        payload["stage"] = stage if stage in _STAGES else "INVALID_STAGE"
    logging.getLogger(LOGGER_NAME).info(
        "acquisition_runtime", extra={"runtime_event": payload}
    )


def _validated_payload(value: object) -> dict[str, str | int]:
    if isinstance(value, dict) and _REQUIRED_KEYS <= value.keys() <= _ALLOWED_KEYS:
        action = value["action"]
        status = value["status"]
        code = value["code"]
        attempt = value["attempt"]
        cycle_ref = value.get("cycle_ref")
        stage = value.get("stage")
        if (
            value["event"] == "acquisition_runtime"
            and isinstance(action, str)
            and action in _ACTIONS
            and isinstance(status, str)
            and status in _STATUSES
            and isinstance(code, str)
            and _MACHINE_CODE.fullmatch(code)
            and isinstance(attempt, int)
            and not isinstance(attempt, bool)
            and attempt >= 0
            and (
                cycle_ref is None
                or (
                    isinstance(cycle_ref, str)
                    and (
                        cycle_ref == "invalid_ref"
                        or _FINGERPRINT.fullmatch(cycle_ref)
                    )
                )
            )
            and (
                stage is None
                or (
                    isinstance(stage, str)
                    and (stage == "INVALID_STAGE" or stage in _STAGES)
                )
            )
        ):
            return {key: value[key] for key in value}
    return {
        "event": "acquisition_runtime",
        "action": "runtime",
        "status": "failed",
        "code": "INVALID_RUNTIME_EVENT",
        "attempt": 0,
    }


__all__ = [
    "LOGGER_NAME",
    "configure_acquisition_runtime_logging",
    "emit_acquisition_runtime_event",
]
