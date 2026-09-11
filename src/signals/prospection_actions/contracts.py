"""Versioned contracts shared by the Founder queue and action service."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

CONTRACT_VERSION = "founder-prospection-actions-v1"

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ProspectStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"


class RejectionReason(StrEnum):
    WRONG_COMPANY = "wrong_company"
    WRONG_ADDRESS = "wrong_address"
    OFF_TOPIC = "off_topic"
    OTHER = "other"


class EmailVerificationStatus(StrEnum):
    MX_VERIFIED = "mx_verified"
    MX_FAILED = "mx_failed"


class EmailSource(StrEnum):
    APOLLO = "apollo"
    SITE = "site"
    MANUAL = "manual"


class DeliveryStatus(StrEnum):
    NOT_SENT = "not_sent"
    SENT = "sent"
    OPENED = "opened"
    CLICKED = "clicked"
    REPLIED = "replied"
    BOUNCED = "bounced"
    UNSUBSCRIBED = "unsubscribed"


class CompanySnapshot(_Contract):
    siren: Annotated[str, StringConstraints(pattern=r"^\d{9}$")]
    name: ShortText
    city: ShortText
    employees: int = Field(ge=10, le=250)
    family: ShortText


class DirectorSnapshot(_Contract):
    name: ShortText
    title: ShortText
    source: Literal["registry", "manual"]


class EmailSnapshot(_Contract):
    address: EmailStr
    source: EmailSource
    verification_status: EmailVerificationStatus


class SignalSnapshot(_Contract):
    opportunity_key: ShortText
    holder: ShortText
    subject: ShortText
    amount_minor_units: int = Field(ge=5_000_000)
    currency: Literal["eur", "chf"]
    location: ShortText
    decision_date: dt.date


class MailSnapshot(_Contract):
    subject: str = Field(min_length=1, max_length=998)
    text: str = Field(min_length=1, max_length=20_000)
    html: str = Field(min_length=1, max_length=50_000)
    attribution_url: str = Field(pattern=r"^https://[^/]+/a/", max_length=2048)
    unsubscribe_url: str = Field(pattern=r"^https://", max_length=2048)
    word_count: int = Field(ge=1, le=90)
    contract_status: Literal["passed", "failed"]
    contract_failure: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def contract_state_is_consistent(self) -> MailSnapshot:
        if (self.contract_status == "passed") != (self.contract_failure is None):
            raise ValueError("mail contract state is inconsistent")
        return self


class DeliverySnapshot(_Contract):
    status: DeliveryStatus = DeliveryStatus.NOT_SENT
    instantly_id: str | None = Field(default=None, max_length=128)
    sent_at: dt.datetime | None = None
    opened_at: dt.datetime | None = None
    clicked_at: dt.datetime | None = None
    replied_at: dt.datetime | None = None
    bounced_at: dt.datetime | None = None
    unsubscribed_at: dt.datetime | None = None
    reply_classification: Literal["human_reply", "auto_reply"] | None = None
    instantly_credit_units: int = Field(default=0, ge=0)
    instantly_request_count: int = Field(default=0, ge=0)


class ProspectTarget(_Contract):
    target_id: UUID
    version: int = Field(ge=1)
    status: ProspectStatus
    company: CompanySnapshot
    director: DirectorSnapshot | None
    email: EmailSnapshot
    signal: SignalSnapshot
    mail: MailSnapshot
    delivery: DeliverySnapshot
    created_at: dt.datetime
    updated_at: dt.datetime
    approved_at: dt.datetime | None = None
    approved_by: str | None = Field(default=None, max_length=320)

    @model_validator(mode="after")
    def message_is_final(self) -> ProspectTarget:
        if self.director is None and not self.mail.text.lstrip().startswith("Bonjour,"):
            raise ValueError("mail.text must contain the final Bonjour greeting")
        return self


class ApproveCommand(_Contract):
    target_id: UUID
    expected_version: int = Field(ge=1)


class CorrectionChanges(_Contract):
    email_address: EmailStr | None = None
    director_name: str | None = Field(default=None, min_length=1, max_length=256)
    company_name: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def at_least_one_change(self) -> CorrectionChanges:
        if all(
            value is None for value in (self.email_address, self.director_name, self.company_name)
        ):
            raise ValueError("at least one correction is required")
        return self


class CorrectCommand(_Contract):
    target_id: UUID
    expected_version: int = Field(ge=1)
    changes: CorrectionChanges


class RejectCommand(_Contract):
    target_id: UUID
    expected_version: int = Field(ge=1)
    reason: RejectionReason
    comment: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def other_requires_comment(self) -> RejectCommand:
        if self.reason is RejectionReason.OTHER and not self.comment:
            raise ValueError("other rejection requires a comment")
        return self


class SendTarget(_Contract):
    target_id: UUID
    expected_version: int = Field(ge=1)


class SendCommand(_Contract):
    request_id: UUID
    targets: tuple[SendTarget, ...] = Field(min_length=1, max_length=25)

    @field_validator("targets")
    @classmethod
    def unique_targets(cls, value: tuple[SendTarget, ...]) -> tuple[SendTarget, ...]:
        if len({item.target_id for item in value}) != len(value):
            raise ValueError("send target ids must be unique")
        return value


class DailyCounts(_Contract):
    prepared: int = Field(ge=0)
    approved: int = Field(ge=0)
    rejected: int = Field(ge=0)
    sent: int = Field(ge=0)


class Pagination(_Contract):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=25)
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=0)


class ListResponse(_Contract):
    version: Literal["founder-prospection-actions-v1"] = CONTRACT_VERSION
    generated_at: dt.datetime
    daily_counts: DailyCounts
    daily_cap: Literal[25] = 25
    kill_switch_active: bool
    items: tuple[ProspectTarget, ...]
    pagination: Pagination


__all__ = [
    "CONTRACT_VERSION",
    "ApproveCommand",
    "CorrectCommand",
    "CorrectionChanges",
    "DeliverySnapshot",
    "DeliveryStatus",
    "EmailSnapshot",
    "EmailSource",
    "EmailVerificationStatus",
    "ListResponse",
    "ProspectStatus",
    "ProspectTarget",
    "RejectCommand",
    "RejectionReason",
    "SendCommand",
]
