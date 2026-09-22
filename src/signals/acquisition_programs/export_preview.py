"""Pure Milo Mail France export preview; it has no provider or mutation path."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict

from signals.acquisition_programs.mail_provider import normalize_domain
from signals.compliance.suppression import (
    SuppressionIdentityUnavailable,
    normalize_business_email,
)

ExportStatus = Literal["READY_THEORETICAL", "HOLD", "NO_SEND"]
ExportSector = Literal["Agences", "Conseil", "Recrutement"]
SEGMENTS = ("France Agences", "France Conseil", "France Recrutement")
PREVIEW_VERSION: Literal["milomail-fr-export-preview-v1"] = "milomail-fr-export-preview-v1"
_CAMPAIGN_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_-]{7,127}\Z")


@dataclass(frozen=True)
class ExportLead:
    """Minimal parent-supplied lead; HOLD/NO_SEND may lack contact fields."""

    status: ExportStatus
    email: str | None = field(repr=False)
    company_domain: str | None = field(repr=False)
    sector: ExportSector | None
    country_code: str = "FR"


@dataclass(frozen=True)
class ValidatedReadyPayload:
    """Normalized private candidate for a dry run; never part of the report."""

    email: str = field(repr=False)
    company_domain: str = field(repr=False)
    segment: str


class _AggregateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExportDiff(_AggregateModel):
    added: int
    removed: int
    unchanged: int


class ExportPreviewReceipt(_AggregateModel):
    version: Literal["milomail-fr-export-preview-v1"] = PREVIEW_VERSION
    campaign_ref: str
    mode: Literal["DRY_RUN"] = "DRY_RUN"
    idempotency_hash: str
    previous_hash: str | None
    provider_calls: Literal[0] = 0
    mutations_allowed: Literal[False] = False


class ExportPreview(_AggregateModel):
    segment_counts: dict[str, int]
    input_count: int
    eligible_count: int
    excluded_hold: int
    excluded_no_send: int
    suppressed_count: int
    duplicates_dropped: int
    diff: ExportDiff
    receipt: ExportPreviewReceipt


def validate_ready_payload(record: ExportLead) -> ValidatedReadyPayload:
    """Fail closed unless the record is ready, French and on its company domain."""
    if record.status != "READY_THEORETICAL" or record.country_code != "FR":
        raise ValueError("export payload is not READY_THEORETICAL for France")
    if record.sector not in {"Agences", "Conseil", "Recrutement"}:
        raise ValueError("export payload has an unsupported sector")
    if not record.email or not record.company_domain:
        raise ValueError("export payload lacks a professional address or domain")
    try:
        email = normalize_business_email(record.email)
        company_domain = normalize_domain(record.company_domain)
        local, raw_domain = email.rsplit("@", 1)
        email_domain = normalize_domain(raw_domain)
    except (SuppressionIdentityUnavailable, ValueError, TypeError) as error:
        raise ValueError("export payload address or domain is invalid") from error
    if email_domain != company_domain:
        raise ValueError("export payload address does not match company domain")
    return ValidatedReadyPayload(
        email=f"{local}@{email_domain}", company_domain=company_domain,
        segment=f"France {record.sector}",
    )


def _roster(records: Iterable[ExportLead], *, previous: bool) -> tuple[
    dict[str, ValidatedReadyPayload], int, int, int,
]:
    selected: dict[str, ValidatedReadyPayload] = {}
    hold = no_send = duplicates = 0
    for record in records:
        if record.status == "HOLD" and not previous:
            hold += 1
            continue
        if record.status == "NO_SEND" and not previous:
            no_send += 1
            continue
        payload = validate_ready_payload(record)
        prior = selected.get(payload.email)
        if prior is not None:
            if prior != payload:
                raise ValueError("conflicting duplicate export address")
            duplicates += 1
        else:
            selected[payload.email] = payload
    return selected, hold, no_send, duplicates


def _roster_hash(roster: Iterable[ValidatedReadyPayload], *, campaign_ref: str,
                 hmac_key: bytes) -> str:
    values = sorted((row.email, row.company_domain, row.segment) for row in roster)
    body = json.dumps((PREVIEW_VERSION, campaign_ref, values),
                      ensure_ascii=True, separators=(",", ":")).encode()
    return hmac.new(hmac_key, body, hashlib.sha256).hexdigest()


def build_export_preview(
    records: Iterable[ExportLead], *, is_suppressed: Callable[[str], bool],
    hmac_key: bytes, campaign_ref: str,
    previous: Iterable[ExportLead] | None = None,
) -> ExportPreview:
    """Recheck suppression, then return aggregate dry-run diff and keyed receipt.

    `previous` is the prior private READY_THEORETICAL roster. The callback
    receives each normalized current address once and must return a bool.
    Neither roster nor individual address digests appear in the result.
    """
    if not isinstance(hmac_key, bytes) or len(hmac_key) < 16:
        raise ValueError("export preview requires an HMAC key of at least 16 bytes")
    if not isinstance(campaign_ref, str) or not _CAMPAIGN_REF.fullmatch(campaign_ref):
        raise ValueError("export preview requires a bounded opaque campaign reference")
    input_rows = tuple(records)
    current, hold, no_send, duplicates = _roster(input_rows, previous=False)
    prior = _roster(previous, previous=True)[0] if previous is not None else None

    # This is the last data-dependent step before aggregation and hashing.
    # A failed or indeterminate suppression lookup produces no preview.
    suppressed_count = 0
    for email in sorted(current):
        try:
            suppressed = is_suppressed(email)
        except Exception as error:
            raise ValueError("suppression recheck unavailable") from error
        if type(suppressed) is not bool:
            raise ValueError("suppression recheck returned an indeterminate result")
        if suppressed:
            del current[email]
            suppressed_count += 1

    counts = {segment: 0 for segment in SEGMENTS}
    for row in current.values():
        counts[row.segment] += 1
    current_set = {(row.email, row.company_domain, row.segment) for row in current.values()}
    prior_set = (
        {(row.email, row.company_domain, row.segment) for row in prior.values()}
        if prior is not None else set()
    )
    return ExportPreview(
        segment_counts=counts,
        input_count=len(input_rows), eligible_count=len(current),
        excluded_hold=hold, excluded_no_send=no_send,
        suppressed_count=suppressed_count, duplicates_dropped=duplicates,
        diff=ExportDiff(added=len(current_set - prior_set),
                        removed=len(prior_set - current_set),
                        unchanged=len(current_set & prior_set)),
        receipt=ExportPreviewReceipt(
            campaign_ref=campaign_ref,
            idempotency_hash=_roster_hash(current.values(), campaign_ref=campaign_ref,
                                          hmac_key=hmac_key),
            previous_hash=(
                _roster_hash(prior.values(), campaign_ref=campaign_ref, hmac_key=hmac_key)
                if prior is not None else None
            ),
        ),
    )


__all__ = [
    "ExportDiff", "ExportLead", "ExportPreview", "ExportPreviewReceipt",
    "ValidatedReadyPayload", "build_export_preview", "validate_ready_payload",
]
