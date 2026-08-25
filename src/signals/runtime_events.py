"""Safe operational delivery events for the ASGI and alerts runtimes.

This logger owns its handler.  It never configures the root logger: uvicorn and
the alerts CLI can therefore expose transactional delivery outcomes without
changing billing, access or framework logging.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import TextIO

LOGGER_NAME = "signals.runtime_events"
_HANDLER_MARKER = "_kivou_runtime_events"
_SAFE_CODE = re.compile(r"^[a-z0-9_]{1,64}$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9_:-]{1,128}$")


class _CompactJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "runtime_event", None)
        if not isinstance(payload, dict):
            payload = {
                "event": "delivery",
                "channel": "runtime",
                "status": "failed",
                "code": "invalid_runtime_event",
                "retryable": False,
                "attempt": 0,
            }
        return json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


def configure_runtime_event_logging(*, stream: TextIO | None = None) -> logging.Logger:
    """Attach exactly one dedicated handler, without touching other loggers."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(getattr(handler, _HANDLER_MARKER, False) for handler in logger.handlers):
        handler = logging.StreamHandler(stream or sys.stderr)
        setattr(handler, _HANDLER_MARKER, True)
        handler.setLevel(logging.INFO)
        handler.setFormatter(_CompactJsonFormatter())
        logger.addHandler(handler)
    return logger


def emit_delivery_event(
    *,
    channel: str,
    status: str,
    code: str,
    retryable: bool,
    attempt: int,
    account_ref: str | None = None,
    signal_ref: str | None = None,
) -> None:
    """Emit the fixed delivery schema; no arbitrary payload can cross it."""

    payload: dict[str, str | bool | int] = {
        "event": "delivery",
        "channel": _safe_code(channel),
        "status": _safe_code(status),
        "code": _safe_code(code),
        "retryable": bool(retryable),
        "attempt": max(0, int(attempt)),
    }
    if account_ref is not None:
        payload["account_ref"] = _safe_ref(account_ref)
    if signal_ref is not None:
        payload["signal_ref"] = _safe_ref(signal_ref)
    logging.getLogger(LOGGER_NAME).info("delivery", extra={"runtime_event": payload})


def _safe_code(value: str) -> str:
    return value if _SAFE_CODE.fullmatch(value) else "invalid_runtime_value"


def _safe_ref(value: str) -> str:
    return value if _SAFE_REF.fullmatch(value) else "invalid_ref"
