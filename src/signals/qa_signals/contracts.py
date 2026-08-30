"""Closed QA Signals decisions; QA can decide but cannot rewrite content."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class QaContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )


class QaStatus(StrEnum):
    PASS = "PASS"
    REGENERATE = "REGENERATE"
    FALLBACK = "FALLBACK"
    REVIEW = "REVIEW"


class QaDecision(QaContract):
    status: QaStatus
    reasons: tuple[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)],
        ...,
    ] = Field(default=(), max_length=12)
