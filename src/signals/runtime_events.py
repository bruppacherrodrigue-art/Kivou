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
_SAFE_REF = re.compile(r"^[A-Za-z0-9_:-]{1,128}$")
_SMTP_STATUS_CODE = re.compile(r"^smtp_[1-5][0-9]{2}$")
_SAFE_CHANNELS = frozenset({"alert", "password_reset", "invalid_runtime_value"})
_SAFE_STATUSES = frozenset(
    {
        "blocked",
        "failed",
        "persistence_failed",
        "submitted",
        "suppressed",
        "unknown_delivery_state",
        "invalid_runtime_value",
    }
)
_SAFE_CODES = frozenset(
    {
        "attempt_budget_exhausted",
        "delivery_state_persistence_failed",
        "entitlement_lost",
        "invalid_runtime_value",
        "notifications_disabled",
        "public_app_url_missing",
        "recipient_context_changed",
        "recipient_context_unverifiable",
        "signal_inaccessible",
        "smtp_authentication_failed",
        "smtp_recipient_refusal_unclassified",
        "smtp_recipient_refused",
        "smtp_submission_accepted",
        "smtp_tls_failed",
        "smtp_unavailable",
        "unexpected_error",
        "unknown_delivery_state",
    }
)
_REQUIRED_KEYS = frozenset(
    {"event", "channel", "status", "code", "retryable", "attempt"}
)
_ALLOWED_KEYS = _REQUIRED_KEYS | {"account_ref", "signal_ref"}


class _CompactJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = _validated_payload(getattr(record, "runtime_event", None))
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
    logger.disabled = False
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
        "channel": _safe_member(channel, _SAFE_CHANNELS),
        "status": _safe_member(status, _SAFE_STATUSES),
        "code": _safe_delivery_code(code),
        "retryable": bool(retryable),
        "attempt": max(0, int(attempt)),
    }
    if account_ref is not None:
        payload["account_ref"] = _safe_ref(account_ref)
    if signal_ref is not None:
        payload["signal_ref"] = _safe_ref(signal_ref)
    logging.getLogger(LOGGER_NAME).info("delivery", extra={"runtime_event": payload})


def _safe_member(value: str, allowed: frozenset[str]) -> str:
    return (
        value
        if isinstance(value, str) and value in allowed
        else "invalid_runtime_value"
    )


def _safe_delivery_code(value: str) -> str:
    if isinstance(value, str) and (
        value in _SAFE_CODES or _SMTP_STATUS_CODE.fullmatch(value)
    ):
        return value
    return "invalid_runtime_value"


def _safe_ref(value: str) -> str:
    return (
        value
        if isinstance(value, str) and _SAFE_REF.fullmatch(value)
        else "invalid_ref"
    )


def _validated_payload(value: object) -> dict[str, str | bool | int]:
    """Copy only a complete, typed event; direct logger calls cannot leak data."""

    if isinstance(value, dict) and _REQUIRED_KEYS <= value.keys() <= _ALLOWED_KEYS:
        attempt = value["attempt"]
        retryable = value["retryable"]
        codes_are_safe = (
            isinstance(value["channel"], str)
            and value["channel"] in _SAFE_CHANNELS
            and isinstance(value["status"], str)
            and value["status"] in _SAFE_STATUSES
            and _safe_delivery_code(value["code"]) == value["code"]
        )
        refs_are_safe = all(
            key not in value
            or (isinstance(value[key], str) and _SAFE_REF.fullmatch(value[key]))
            for key in ("account_ref", "signal_ref")
        )
        if (
            value["event"] == "delivery"
            and codes_are_safe
            and refs_are_safe
            and isinstance(retryable, bool)
            and isinstance(attempt, int)
            and not isinstance(attempt, bool)
            and attempt >= 0
        ):
            return {key: value[key] for key in value}
    return {
        "event": "delivery",
        "channel": "runtime",
        "status": "failed",
        "code": "invalid_runtime_event",
        "retryable": False,
        "attempt": 0,
    }
