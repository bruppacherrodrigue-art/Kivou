"""Small immutable contracts for the Founder Console foundation."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

FOUNDER_SESSION_VERSION = "founder-session-v1"


class FounderContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(dt.UTC)


class FounderSession(FounderContract):
    version: Literal["founder-session-v1"] = FOUNDER_SESSION_VERSION
    service: Literal["kivou-founder-control"] = "kivou-founder-control"
    environment: Literal["PRODUCTION"] = "PRODUCTION"
    operator_email: str
    read_only: Literal[True] = True
    generated_at: dt.datetime

    _generated_at = field_validator("generated_at")(_aware)


__all__ = ["FOUNDER_SESSION_VERSION", "FounderContract", "FounderSession"]
