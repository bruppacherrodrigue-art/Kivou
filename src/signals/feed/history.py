"""Opaque, closed cursor and factual clock for the award history."""

from __future__ import annotations

import base64
import binascii
import dataclasses
import datetime as dt
import json
import re
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from signals.persistence.repository import StoredSignal

HistoryDateKind = Literal["award", "notification", "publication", "unknown"]

_CURSOR_KEYS = frozenset({"v", "d", "k"})
_CURSOR_VERSION = 1
_MAX_ENCODED_CURSOR_LENGTH = 512
_SIGNAL_KEY = re.compile(r"^[0-9a-f]{40,64}$")


class InvalidHistoryCursor(ValueError):
    """The cursor is malformed or belongs to another contract version."""


@dataclasses.dataclass(frozen=True)
class HistoryCursor:
    date: dt.date | None
    signal_key: str
    version: Literal[1] = _CURSOR_VERSION

    def __post_init__(self) -> None:
        if self.version != _CURSOR_VERSION or not _SIGNAL_KEY.fullmatch(self.signal_key):
            raise InvalidHistoryCursor("invalid history cursor")


def encode_history_cursor(cursor: HistoryCursor) -> str:
    payload = json.dumps(
        {
            "v": cursor.version,
            "d": cursor.date.isoformat() if cursor.date is not None else None,
            "k": cursor.signal_key,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_history_cursor(value: str) -> HistoryCursor:
    if not value or len(value) > _MAX_ENCODED_CURSOR_LENGTH:
        raise InvalidHistoryCursor("invalid history cursor")
    padding = "=" * (-len(value) % 4)
    try:
        raw = base64.b64decode(
            (value + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw)
    except (UnicodeEncodeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as error:
        raise InvalidHistoryCursor("invalid history cursor") from error
    if not isinstance(payload, dict) or frozenset(payload) != _CURSOR_KEYS:
        raise InvalidHistoryCursor("invalid history cursor")
    if payload["v"] != _CURSOR_VERSION or not isinstance(payload["k"], str):
        raise InvalidHistoryCursor("invalid history cursor")
    raw_date = payload["d"]
    if raw_date is not None and not isinstance(raw_date, str):
        raise InvalidHistoryCursor("invalid history cursor")
    try:
        parsed_date = None if raw_date is None else dt.date.fromisoformat(raw_date)
        return HistoryCursor(date=parsed_date, signal_key=payload["k"])
    except (TypeError, ValueError) as error:
        raise InvalidHistoryCursor("invalid history cursor") from error


def effective_history_date(signal: StoredSignal) -> tuple[dt.date | None, HistoryDateKind]:
    """Select the published clock used to order history, without inference."""
    if signal.award.award_date is not None:
        return signal.award.award_date, "award"
    if signal.award.contract_notification_date is not None:
        return signal.award.contract_notification_date, "notification"
    if signal.event.published_on is not None:
        return signal.event.published_on, "publication"
    return None, "unknown"


def cursor_for_signal(signal: StoredSignal) -> HistoryCursor:
    date, _kind = effective_history_date(signal)
    return HistoryCursor(date=date, signal_key=signal.signal_key)


__all__ = [
    "HistoryCursor",
    "HistoryDateKind",
    "InvalidHistoryCursor",
    "cursor_for_signal",
    "decode_history_cursor",
    "effective_history_date",
    "encode_history_cursor",
]
