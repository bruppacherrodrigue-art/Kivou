"""Strict, versioned contracts for pre-published card presentations.

These models describe an offline publication boundary.  They do not select or
configure a generator, a provider, a prompt, or a worker.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from signals.accounts.icp_input import BuyerTrade, OfferKind
from signals.needs import NeedCategory

SCHEMA_VERSION = "card-presentation-v1"

StableRef = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
BoundedCommercialText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=420),
]
BoundedActionText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=320),
]
BoundedUnknown = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
]


class Contract(BaseModel):
    """Closed immutable base shared by every Card Intelligence contract."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )

    @classmethod
    def from_json_value(cls, value: object) -> Self:
        """Decode a SQL/JSON value through Pydantic's strict JSON path."""

        try:
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as error:
            raise ValueError("contract value must be JSON-compatible") from error
        return cls.model_validate_json(encoded)


class ArtifactKind(StrEnum):
    """One artifact is shared by feed and detail; surfaces are not artifact kinds."""

    CARD_PRESENTATION = "CARD_PRESENTATION"


class PresentationVariant(StrEnum):
    FULL = "FULL"
    FACTUAL_FALLBACK = "FACTUAL_FALLBACK"


class ClaimKind(StrEnum):
    FACT = "FACT"
    INFERENCE = "INFERENCE"
    RECOMMENDATION = "RECOMMENDATION"


class TargetRoleKind(StrEnum):
    """Functional role categories, never inferred people or named contacts."""

    PROCUREMENT_MANAGER = "PROCUREMENT_MANAGER"
    SITE_PROCUREMENT_MANAGER = "SITE_PROCUREMENT_MANAGER"
    PROJECT_MANAGER = "PROJECT_MANAGER"
    WORKS_MANAGER = "WORKS_MANAGER"
    SUPPLY_MANAGER = "SUPPLY_MANAGER"


class PresentationClaim(Contract):
    claim_id: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]
    kind: ClaimKind
    text: Annotated[str, StringConstraints(min_length=1, max_length=420)]
    evidence_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=16)
    confidence: Literal["high", "medium", "low"] | None = None

    @model_validator(mode="after")
    def inference_requires_confidence(self) -> PresentationClaim:
        if self.kind is ClaimKind.INFERENCE and self.confidence is None:
            raise ValueError("INFERENCE claim requires confidence")
        if self.kind is not ClaimKind.INFERENCE and self.confidence is not None:
            raise ValueError("only INFERENCE claims carry confidence")
        return self


class TargetRole(Contract):
    role: TargetRoleKind
    rationale: BoundedCommercialText
    evidence_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=16)


class PresentationUnknown(Contract):
    text: BoundedUnknown
    evidence_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=16)


class TargetIcpThresholdSnapshot(Contract):
    """Strict immutable copy of the monetary part of a customer ICP."""

    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    minimum_amount: float = Field(ge=0)
    maximum_amount: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def ordered_bounds(self) -> TargetIcpThresholdSnapshot:
        if self.maximum_amount is not None and self.minimum_amount > self.maximum_amount:
            raise ValueError("minimum_amount cannot exceed maximum_amount")
        return self


class TargetIcpSnapshot(Contract):
    """Deeply immutable customer-declared ICP captured for one presentation input."""

    offer_summary: Annotated[str, StringConstraints(max_length=4000)] = ""
    offers: tuple[OfferKind, ...] = Field(default=(), max_length=7)
    secondary_offers: tuple[OfferKind, ...] = Field(default=(), max_length=7)
    buyer_trades: tuple[BuyerTrade, ...] = Field(default=(), max_length=8)
    secondary_buyer_trades: tuple[BuyerTrade, ...] = Field(default=(), max_length=8)
    territories: tuple[
        Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")],
        ...,
    ] = Field(default=(), max_length=249)
    minimum_contract_value: TargetIcpThresholdSnapshot | None = None

    @model_validator(mode="after")
    def declared_values_are_unique(self) -> TargetIcpSnapshot:
        sequences = {
            "offers": self.offers,
            "secondary_offers": self.secondary_offers,
            "buyer_trades": self.buyer_trades,
            "secondary_buyer_trades": self.secondary_buyer_trades,
            "territories": self.territories,
        }
        for field, values in sequences.items():
            if len(set(values)) != len(values):
                raise ValueError(f"{field} values must be unique")
        return self

class CardPresentationPayload(Contract):
    schema_version: Literal["card-presentation-v1"] = SCHEMA_VERSION
    variant: PresentationVariant
    headline: Annotated[str, StringConstraints(min_length=1, max_length=160)]
    award_summary: Annotated[str, StringConstraints(min_length=1, max_length=420)]
    commercial_importance: BoundedCommercialText | None = None
    fit_reason: BoundedCommercialText | None = None
    timing: BoundedActionText | None = None
    recommended_action: BoundedActionText | None = None
    target_roles: tuple[TargetRole, ...] = Field(default=(), max_length=6)
    fit_need_categories: tuple[NeedCategory, ...] = Field(default=(), max_length=8)
    unknowns: tuple[PresentationUnknown, ...] = Field(default=(), max_length=8)
    claims: tuple[PresentationClaim, ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def closed_variant_and_unique_claims(self) -> CardPresentationPayload:
        commercial = (
            self.commercial_importance,
            self.fit_reason,
            self.timing,
            self.recommended_action,
        )
        if len({claim.claim_id for claim in self.claims}) != len(self.claims):
            raise ValueError("claim_id values must be unique")
        if len({role.role for role in self.target_roles}) != len(self.target_roles):
            raise ValueError("target role categories must be unique")
        if len(set(self.fit_need_categories)) != len(self.fit_need_categories):
            raise ValueError("fit_need_categories values must be unique")
        if self.variant is PresentationVariant.FULL:
            if any(value is None for value in commercial):
                raise ValueError("FULL requires every commercial field")
            if not self.target_roles or not self.fit_need_categories:
                raise ValueError("FULL requires roles and matched needs")
        elif (
            any(value is not None for value in commercial)
            or self.target_roles
            or self.fit_need_categories
        ):
            raise ValueError("FACTUAL_FALLBACK cannot carry commercial conclusions")
        elif any(claim.kind is not ClaimKind.FACT for claim in self.claims):
            raise ValueError("FACTUAL_FALLBACK contains FACT claims only")

        expected_kinds = {
            "headline": ClaimKind.FACT,
            "award_summary": ClaimKind.FACT,
            "commercial_importance": ClaimKind.INFERENCE,
            "fit_reason": ClaimKind.INFERENCE,
            "timing": ClaimKind.INFERENCE,
            "recommended_action": ClaimKind.RECOMMENDATION,
        }
        for field, expected_kind in expected_kinds.items():
            text = getattr(self, field)
            if text is None:
                continue
            if not any(
                claim.text == text and claim.kind is expected_kind for claim in self.claims
            ):
                raise ValueError(
                    f"{field} requires an exact evidenced claim of kind {expected_kind.value}"
                )
        return self


class SourceFacts(Contract):
    winner_name: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    buyer_name: Annotated[str, StringConstraints(min_length=1, max_length=512)] | None = None
    award_title: Annotated[str, StringConstraints(min_length=1, max_length=4000)] | None = None
    amount: Annotated[Decimal, Field(ge=0)] | None = None
    currency: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")] | None = None
    location: Annotated[str, StringConstraints(min_length=1, max_length=512)] | None = None
    award_date: dt.date | None = None
    contract_notification_date: dt.date | None = None
    publication_date: dt.date | None = None
    source_system: StableRef
    source_notice_id: StableRef
    evidence_refs: tuple[StableRef, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def closed_evidence_catalog_and_complete_amount(self) -> SourceFacts:
        if (self.amount is None) != (self.currency is None):
            raise ValueError("amount and currency must be present together")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence_refs in the source catalog must be unique")
        return self

    @property
    def evidence_catalog(self) -> frozenset[str]:
        """The complete set of references candidates are allowed to cite."""

        return frozenset(self.evidence_refs)

    def unresolved_evidence_refs(self, payload: CardPresentationPayload) -> tuple[str, ...]:
        """Return every public evidence reference outside the closed catalog."""

        referenced = {
            ref
            for evidence_refs in (
                *(claim.evidence_refs for claim in payload.claims),
                *(role.evidence_refs for role in payload.target_roles),
                *(unknown.evidence_refs for unknown in payload.unknowns),
            )
            for ref in evidence_refs
        }
        return tuple(sorted(referenced - self.evidence_catalog))

    def ensure_evidence_refs(self, payload: CardPresentationPayload) -> CardPresentationPayload:
        """Fail closed unless every claim, role, and unknown cites known evidence."""

        unresolved = self.unresolved_evidence_refs(payload)
        if unresolved:
            raise ValueError(f"unknown evidence_refs: {', '.join(unresolved)}")
        return payload


class PresentationInput(Contract):
    account_id: StableRef
    signal_key: StableRef
    signal_revision: int = Field(ge=1)
    target_icp_id: StableRef
    target_icp_revision: int = Field(ge=1)
    language: Literal["fr", "en"]
    target_icp_label: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    target_icp_customer_input: TargetIcpSnapshot
    icp_matched_needs: tuple[NeedCategory, ...] = Field(default=(), max_length=32)
    facts: SourceFacts

    @model_validator(mode="after")
    def matched_needs_are_unique(self) -> PresentationInput:
        if len(set(self.icp_matched_needs)) != len(self.icp_matched_needs):
            raise ValueError("icp_matched_needs must be unique")
        return self

    def fingerprint(self) -> str:
        """Canonical SHA-256 over all tenant, revision, language, ICP, and fact input."""

        payload = self.model_dump(mode="json")
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def ensure_evidence_refs(self, payload: CardPresentationPayload) -> CardPresentationPayload:
        return self.facts.ensure_evidence_refs(payload)


class GenerationResponse(Contract):
    payload: CardPresentationPayload | None = None
    failure_kind: Annotated[str, StringConstraints(min_length=1, max_length=80)] | None = None

    @model_validator(mode="after")
    def exactly_one_result(self) -> GenerationResponse:
        if (self.payload is None) == (self.failure_kind is None):
            raise ValueError("generation returns payload or failure_kind, exactly one")
        return self


class PublishedCardPresentation(Contract):
    artifact_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    version: int = Field(gt=0)
    status: Literal["PASS", "FALLBACK"]
    schema_version: Literal["card-presentation-v1"]
    published_at: dt.datetime
    content: CardPresentationPayload

    @model_validator(mode="after")
    def exact_public_pair(self) -> PublishedCardPresentation:
        expected = {
            "PASS": PresentationVariant.FULL,
            "FALLBACK": PresentationVariant.FACTUAL_FALLBACK,
        }[self.status]
        if self.content.variant is not expected:
            raise ValueError("invalid published status/variant pair")
        if self.schema_version != self.content.schema_version:
            raise ValueError("envelope/content schema mismatch")
        if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        return self
