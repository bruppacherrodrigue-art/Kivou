"""Strict, versioned contracts shared by Card Intelligence and QA Signals."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SCHEMA_VERSION = "card-presentation-v1"
QA_POLICY_VERSION = "qa-signals-policy-v1"

StableText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
StableRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ArtifactKind(StrEnum):
    AWARD_SUMMARY = "AWARD_SUMMARY"
    SIGNAL_CARD = "SIGNAL_CARD"


class QaStatus(StrEnum):
    PASS = "PASS"
    REGENERATE = "REGENERATE"
    FALLBACK = "FALLBACK"
    REVIEW = "REVIEW"


class PresentationVariant(StrEnum):
    FULL = "FULL"
    FACTUAL_FALLBACK = "FACTUAL_FALLBACK"


class ClaimKind(StrEnum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    RECOMMENDATION = "RECOMMENDATION"


class PresentationClaim(Contract):
    claim_id: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]
    kind: ClaimKind
    text: Annotated[str, StringConstraints(min_length=1, max_length=420)]
    evidence_refs: tuple[StableRef, ...] = Field(default=(), max_length=16)
    confidence: Literal["high", "medium", "low"] | None = None

    @model_validator(mode="after")
    def evidence_semantics(self):
        if self.kind in (ClaimKind.FACT, ClaimKind.INFERENCE) and not self.evidence_refs:
            raise ValueError(f"{self.kind.value} claim requires evidence_refs")
        if self.kind is ClaimKind.INFERENCE and self.confidence is None:
            raise ValueError("INFERENCE claim requires confidence")
        return self


class CardPresentationPayload(Contract):
    schema_version: Literal["card-presentation-v1"] = SCHEMA_VERSION
    variant: PresentationVariant
    headline: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    award_summary: Annotated[str, StringConstraints(min_length=1, max_length=420)]
    commercial_importance: Annotated[str, StringConstraints(min_length=1, max_length=420)] | None = None
    fit_reason: Annotated[str, StringConstraints(min_length=1, max_length=420)] | None = None
    timing: Annotated[str, StringConstraints(min_length=1, max_length=320)] | None = None
    recommended_action: Annotated[str, StringConstraints(min_length=1, max_length=320)] | None = None
    target_roles: tuple[
        Literal[
            "PROCUREMENT_MANAGER",
            "SITE_PROCUREMENT_MANAGER",
            "PROJECT_MANAGER",
            "WORKS_MANAGER",
            "SUPPLY_MANAGER",
        ],
        ...,
    ] = Field(default=(), max_length=6)
    fit_need_categories: tuple[StableRef, ...] = Field(default=(), max_length=8)
    unknowns: tuple[Annotated[str, StringConstraints(min_length=1, max_length=240)], ...] = Field(
        default=(), max_length=8
    )
    claims: tuple[PresentationClaim, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def variant_shape(self):
        commercial = (
            self.commercial_importance,
            self.fit_reason,
            self.timing,
            self.recommended_action,
        )
        if self.variant is PresentationVariant.FULL:
            if any(value is None for value in commercial):
                raise ValueError("FULL presentation requires all commercial fields")
            if not self.target_roles:
                raise ValueError("FULL presentation requires at least one target role")
            if not self.fit_need_categories:
                raise ValueError("FULL presentation requires a structured matched need")
        else:
            if (
                any(value is not None for value in commercial)
                or self.target_roles
                or self.fit_need_categories
            ):
                raise ValueError("FACTUAL_FALLBACK cannot carry commercial conclusions")
            if any(claim.kind is not ClaimKind.FACT for claim in self.claims):
                raise ValueError("FACTUAL_FALLBACK can contain FACT claims only")
        return self


class SourceFacts(Contract):
    winner_name: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    buyer_name: Annotated[str, StringConstraints(min_length=1, max_length=512)] | None = None
    award_title: Annotated[str, StringConstraints(min_length=1, max_length=4000)] | None = None
    amount: Decimal | None = None
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] | None = None
    location: Annotated[str, StringConstraints(min_length=1, max_length=512)] | None = None
    award_date: dt.date | None = None
    contract_notification_date: dt.date | None = None
    publication_date: dt.date | None = None
    source_system: StableRef
    source_notice_id: StableRef
    evidence_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def complete_amount(self):
        if (self.amount is None) != (self.currency is None):
            raise ValueError("amount and currency must be present together")
        return self


class PresentationInput(Contract):
    account_id: StableRef
    signal_key: StableRef
    signal_revision: int = Field(ge=1)
    target_icp_id: StableRef
    target_icp_revision: int = Field(ge=1)
    language: Literal["fr", "en"]
    target_icp_label: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    target_icp_customer_input: dict[str, object]
    icp_matched_needs: tuple[StableRef, ...] = Field(default=(), max_length=32)
    facts: SourceFacts

    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json")
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GenerationResponse(Contract):
    payload: CardPresentationPayload | None = None
    failure_kind: Annotated[str, StringConstraints(min_length=1, max_length=80)] | None = None

    @model_validator(mode="after")
    def exactly_one_result(self):
        if (self.payload is None) == (self.failure_kind is None):
            raise ValueError("generation returns payload or failure_kind, exactly one")
        return self
