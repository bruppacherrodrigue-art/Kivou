"""Provider-independent contracts and policy constants for queue preparation."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, field_validator

DAILY_PENDING_CAP = 25
DAILY_SIGNAL_CAP = 5
CONTACT_COOLDOWN = dt.timedelta(days=30)
SMALL_SIGNAL_LIMIT = 5
LARGE_SIGNAL_LIMIT = 8
SMALL_SIGNAL_MAX_MINOR_UNITS = 10_000_000


class AssistedSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    opportunity_key: str = Field(min_length=1, max_length=256)
    acquisition_opportunity_id: str = Field(min_length=1, max_length=64)
    procedure_key: str = Field(min_length=1, max_length=256)
    holder: str = Field(min_length=1, max_length=512)
    holder_siren: str | None = Field(default=None, pattern=r"^\d{9}$")
    holder_family_required: bool = False
    target_holder_family: bool = False
    subject: str = Field(min_length=1, max_length=998)
    amount_minor_units: int = Field(ge=5_000_000)
    currency: str = Field(pattern=r"^(eur|chf)$")
    location: str = Field(min_length=1, max_length=512)
    city: str | None = Field(default=None, min_length=1, max_length=512)
    department: str = Field(pattern=r"^(?:\d{2,3}|2[AB])$")
    decision_date: dt.date
    source_url: str = Field(min_length=8, max_length=2048)
    vertical: str = Field(min_length=1, max_length=100)
    families: tuple[tuple[str, str], ...] = Field(min_length=1, max_length=5)

    @field_validator("holder")
    @classmethod
    def holder_is_a_named_company(cls, value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if len(digits) in {9, 14} and not re.sub(r"[\d\s.-]", "", value):
            raise ValueError("holder must be a named company")
        return value


@dataclass(frozen=True)
class PreparationResult:
    prepared: int
    status: str
    target_ids: tuple[str, ...] = ()
    reason: str | None = None
    directory_candidates: int = 0
    enrichment_required: bool = False


def director(row: dict[str, object]) -> tuple[str | None, str | None]:
    selected = str(row.get("director_display_name") or "").strip()
    if selected:
        return selected, str(row.get("email_contact_title") or "Dirigeant")
    return None, None


__all__ = [
    "CONTACT_COOLDOWN",
    "DAILY_PENDING_CAP",
    "DAILY_SIGNAL_CAP",
    "LARGE_SIGNAL_LIMIT",
    "SMALL_SIGNAL_LIMIT",
    "SMALL_SIGNAL_MAX_MINOR_UNITS",
    "AssistedSignal",
    "PreparationResult",
    "director",
]
