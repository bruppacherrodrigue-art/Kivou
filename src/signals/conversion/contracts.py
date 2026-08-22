"""Immutable v1 conversion contracts with no prospect or account PII."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator, model_validator

ATTRIBUTION_TOKEN_VERSION = "conversion-attribution-token-v1"
ATTRIBUTION_POLICY_VERSION = "click-to-signup-attribution-v1"
CONVERSION_EVENT_VERSION = "conversion-event-v1"
CONVERSION_MRR_VERSION = "conversion-mrr-v1"
ATTRIBUTION_WINDOW = dt.timedelta(days=30)

StableRef = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
ShortCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ConversionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def _aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(dt.UTC)


class ConversionMilestone(StrEnum):
    CLICK = "CLICK"
    SIGNUP = "SIGNUP"
    ACTIVATED = "ACTIVATED"
    PAID = "PAID"
    MRR_CHANGED = "MRR_CHANGED"
    RETAINED_M1 = "RETAINED_M1"
    RETAINED_M2 = "RETAINED_M2"
    CHURNED = "CHURNED"


class AttributionTokenPayload(ConversionContract):
    token_version: Literal["conversion-attribution-token-v1"] = ATTRIBUTION_TOKEN_VERSION
    key_version: ShortCode | None = None
    campaign_ref: StableRef
    member_ref: StableRef
    acquisition_opportunity_id: StableRef
    wedge: ShortCode
    wedge_version: ShortCode
    country: Literal["CH", "FR"]
    sector_ref: StableRef
    need_ref: StableRef
    need_version: ShortCode
    issued_at: dt.datetime
    expires_at: dt.datetime

    _times = field_validator("issued_at", "expires_at")(_aware)

    @model_validator(mode="after")
    def valid_interval(self) -> AttributionTokenPayload:
        if self.expires_at <= self.issued_at:
            raise ValueError("attribution token expiry must follow issuance")
        if self.expires_at - self.issued_at > dt.timedelta(days=62):
            raise ValueError("attribution token lifetime is unbounded")
        return self


class Money(ConversionContract):
    amount_minor_units: int
    currency: Literal["chf", "eur"]

    @field_validator("amount_minor_units")
    @classmethod
    def non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("money cannot be negative")
        return value


__all__ = [
    "ATTRIBUTION_POLICY_VERSION",
    "ATTRIBUTION_TOKEN_VERSION",
    "ATTRIBUTION_WINDOW",
    "CONVERSION_EVENT_VERSION",
    "CONVERSION_MRR_VERSION",
    "AttributionTokenPayload",
    "ConversionMilestone",
    "Money",
]
