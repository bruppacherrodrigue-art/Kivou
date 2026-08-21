"""Bounded persistence contracts for deterministic personalization artifacts."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

StableRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

INPUT_VERSION = "personalization-input-v1"


class PersonalizationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PersonalizationDisposition(StrEnum):
    READY = "READY"
    POLICY_BLOCKED = "POLICY_BLOCKED"


class ClaimMapEntry(PersonalizationContract):
    claim_id: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,99}$")]
    kind: Literal["PUBLIC_FACT", "KIVOU_INFERENCE", "KIVOU_PRODUCT_COPY"]
    evidence_refs: tuple[StableRef, ...] = Field(default=(), max_length=16)


class PersonalizationArtifactWrite(PersonalizationContract):
    personalization_artifact_id: StableRef
    acquisition_opportunity_id: StableRef
    supplier_ref: StableRef
    contact_ref: StableRef
    policy_evaluation_id: StableRef
    decision_evaluation_id: StableRef
    language: Literal["fr", "en"]
    input_version: Literal["personalization-input-v1"] = INPUT_VERSION
    input_fingerprint: Fingerprint
    eligibility_fingerprint: Fingerprint
    need_engine_version: StableRef
    selected_need_fingerprint: Fingerprint
    template_version: StableRef
    catalog_version: StableRef
    language_policy_version: StableRef
    policy_action_fingerprint: Fingerprint
    artifact_fingerprint: Fingerprint
    input_snapshot: dict[str, object]
    claim_map: tuple[ClaimMapEntry, ...] = Field(min_length=1, max_length=8)
    disposition: PersonalizationDisposition
    policy_status: StableRef
    policy_counterfactual_status: StableRef | None = None
    subject: Annotated[str, StringConstraints(min_length=1, max_length=90)] | None = None
    greeting: Annotated[str, StringConstraints(min_length=1, max_length=80)] | None = None
    body: Annotated[str, StringConstraints(min_length=1, max_length=700)] | None = None
    cta: Annotated[str, StringConstraints(min_length=1, max_length=256)] | None = None
    recorded_event_id: StableRef | None = None
    created_at: dt.datetime

    @field_validator("created_at")
    @classmethod
    def aware_created_at(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value
