"""QA Signals can decide, but its response has no field that can rewrite copy."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from signals.card_intelligence.contracts import QaStatus


class QaContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class QaDecision(QaContract):
    status: QaStatus
    reasons: tuple[Annotated[str, StringConstraints(min_length=1, max_length=160)], ...] = Field(
        default=(), max_length=12
    )


class QaResponse(QaContract):
    decision: QaDecision | None = None
    failure_kind: Annotated[str, StringConstraints(min_length=1, max_length=80)] | None = None

    @model_validator(mode="after")
    def exactly_one_result(self):
        if (self.decision is None) == (self.failure_kind is None):
            raise ValueError("QA returns decision or failure_kind, exactly one")
        return self
