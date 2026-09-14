"""Opaque, closed cursor and factual clock for the award history."""

from __future__ import annotations

import base64
import binascii
import dataclasses
import datetime as dt
import json
import re
from decimal import Decimal, InvalidOperation
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
    context_tag: str | None = None
    sort: str = "recent"
    amount: Decimal | None = None
    currency: str | None = None

    def __post_init__(self) -> None:
        if self.version != _CURSOR_VERSION or not _SIGNAL_KEY.fullmatch(self.signal_key):
            raise InvalidHistoryCursor("invalid history cursor")
        if self.sort not in ("recent", "amount") or (
            self.context_tag is not None and not re.fullmatch(r"[a-f0-9]{24}", self.context_tag)
        ):
            raise InvalidHistoryCursor("invalid history cursor")


def encode_history_cursor(cursor: HistoryCursor) -> str:
    extra = (
        {
            "x": {
                "f": cursor.context_tag,
                "s": cursor.sort,
                "a": str(cursor.amount) if cursor.amount is not None else None,
                "u": cursor.currency,
            }
        }
        if cursor.context_tag is not None or cursor.sort != "recent"
        else {}
    )
    payload = json.dumps(
        {
            "v": cursor.version,
            "d": cursor.date.isoformat() if cursor.date is not None else None,
            "k": cursor.signal_key,
            **extra,
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
    if not isinstance(payload, dict) or frozenset(payload) not in (
        _CURSOR_KEYS,
        _CURSOR_KEYS | {"x"},
    ):
        raise InvalidHistoryCursor("invalid history cursor")
    if payload["v"] != _CURSOR_VERSION or not isinstance(payload["k"], str):
        raise InvalidHistoryCursor("invalid history cursor")
    raw_date = payload["d"]
    if raw_date is not None and not isinstance(raw_date, str):
        raise InvalidHistoryCursor("invalid history cursor")
    try:
        parsed_date = None if raw_date is None else dt.date.fromisoformat(raw_date)
        extra = payload.get("x")
        if extra is None:
            return HistoryCursor(date=parsed_date, signal_key=payload["k"])
        if not isinstance(extra, dict) or set(extra) != {"f", "s", "a", "u"}:
            raise ValueError("invalid cursor context")
        amount = None if extra["a"] is None else Decimal(extra["a"])
        if amount is not None and (not amount.is_finite() or amount < 0):
            raise ValueError("invalid amount")
        if extra["u"] is not None and not re.fullmatch(r"[A-Z]{3}", extra["u"]):
            raise ValueError("invalid currency")
        return HistoryCursor(
            date=parsed_date,
            signal_key=payload["k"],
            context_tag=extra["f"],
            sort=extra["s"],
            amount=amount,
            currency=extra["u"],
        )
    except (TypeError, ValueError, InvalidOperation) as error:
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


def cursor_for_signal(signal: StoredSignal, *, context_tag=None, sort="recent") -> HistoryCursor:
    date, _kind = effective_history_date(signal)
    return HistoryCursor(
        date=date,
        signal_key=signal.signal_key,
        context_tag=context_tag,
        sort=sort,
        amount=signal.award.amount,
        currency=signal.award.currency,
    )


def history_sort_key(signal: StoredSignal) -> tuple[int, int]:
    """The most recent effective date first; undated signals last.

    Fix round 1 — moved here from `api/routes_companies.py`'s private copy so
    the dashboard's "most recent signal of a company" can share it instead of
    drifting from what the company page already means by "most recent".
    """
    date, _kind = effective_history_date(signal)
    if date is None:
        return (1, 0)
    return (0, -date.toordinal())


__all__ = [
    "HistoryCursor",
    "HistoryDateKind",
    "InvalidHistoryCursor",
    "cursor_for_signal",
    "decode_history_cursor",
    "effective_history_date",
    "encode_history_cursor",
    "history_sort_key",
]
