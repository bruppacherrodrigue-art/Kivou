"""Provider-neutral orchestration for offline card candidates.

The web application never constructs the protocols accepted here.  Candidate
generation and QA stay private and offline; the only publishable output is the
exact deterministic factual fallback rendered by this repository.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.engine import Connection

from signals.card_intelligence.contracts import (
    CardPresentationPayload,
    GenerationResponse,
    PresentationInput,
    PresentationVariant,
)
from signals.card_intelligence.fallback import factual_fallback
from signals.card_intelligence.protocol import CardGenerator
from signals.card_intelligence.store import AttemptMetadata, append_attempt
from signals.card_intelligence.validation import validate_payload
from signals.qa_signals.contracts import QaDecision, QaStatus
from signals.qa_signals.protocol import QaSignals

FACTUAL_GENERATOR_VERSION = "factual-fallback-v1"
FACTUAL_QA_POLICY_VERSION = "deterministic-factual-qa-v1"
MAX_CANDIDATE_ATTEMPTS = 2

_PRIVATE_FAILURE_GENERATOR_VERSION = "offline-candidate-service-v1"
_AUTHORIZED_QA_INPUT_ERRORS = ("full_variant_not_authorized",)
_DEFAULT_FACTUAL_REASONS = ("deterministic_factual_fallback",)


class _NextState(StrEnum):
    RETRY = "RETRY"
    FACTUAL = "FACTUAL"


@dataclass(frozen=True)
class _PrivateAttempt:
    payload: CardPresentationPayload | None
    status: QaStatus
    reasons: tuple[str, ...]
    next_state: _NextState
    factual_cause: tuple[str, ...] | None = None

    @property
    def fallback_reasons(self) -> tuple[str, ...]:
        return self.factual_cause or self.reasons


def _checked_source(source: PresentationInput) -> PresentationInput:
    return PresentationInput.model_validate(source)


def _checked_now(now: dt.datetime) -> dt.datetime:
    if not isinstance(now, dt.datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now


def _checked_reasons(reasons: Sequence[str]) -> tuple[str, ...]:
    if isinstance(reasons, (str, bytes)):
        raise TypeError("reasons must be a bounded sequence")
    try:
        return QaDecision(status=QaStatus.REVIEW, reasons=tuple(reasons)).reasons
    except (ValidationError, TypeError, ValueError, AttributeError) as error:
        raise ValueError("reasons must satisfy the QA contract") from error


def _merge_reasons(*groups: Sequence[str]) -> tuple[str, ...]:
    """Preserve deterministic order, remove duplicates, and retain the bound."""

    merged: list[str] = []
    for group in groups:
        for reason in group:
            if reason not in merged:
                merged.append(reason)
            if len(merged) == 12:
                return tuple(merged)
    return tuple(merged)


def _factual_metadata() -> AttemptMetadata:
    return AttemptMetadata(
        generator_version=FACTUAL_GENERATOR_VERSION,
        qa_policy_version=FACTUAL_QA_POLICY_VERSION,
    )


def _private_failure_metadata() -> AttemptMetadata:
    """Use service-owned identifiers when protocol identifiers are untrusted."""

    return AttemptMetadata(
        generator_version=_PRIVATE_FAILURE_GENERATOR_VERSION,
        qa_policy_version=FACTUAL_QA_POLICY_VERSION,
    )


def _protocol_metadata(
    generator: CardGenerator,
    qa: QaSignals,
) -> AttemptMetadata | None:
    """Read and validate only non-secret identifiers before any provider call."""

    try:
        return AttemptMetadata(
            generator_version=generator.generator_version,
            qa_policy_version=qa.policy_version,
            prompt_version=generator.prompt_version,
            model_id=generator.model_id,
            provider=generator.provider,
            qa_model_id=qa.model_id,
            qa_provider=qa.provider,
        )
    except sa.exc.SQLAlchemyError:
        raise
    except Exception:  # noqa: BLE001 - untrusted protocol metadata boundary
        return None


def _append_private(
    connection: Connection,
    *,
    source: PresentationInput,
    payload: CardPresentationPayload | None,
    status: QaStatus,
    reasons: Sequence[str],
    metadata: AttemptMetadata,
    now: dt.datetime,
) -> Mapping[str, object]:
    return append_attempt(
        connection,
        source=source,
        payload=payload,
        qa_status=status,
        qa_reasons=_merge_reasons(reasons),
        metadata=metadata,
        created_at=now,
        publish=False,
    )


def publish_factual_fallback(
    connection: Connection,
    *,
    source: PresentationInput,
    now: dt.datetime,
    reasons: Sequence[str] = _DEFAULT_FACTUAL_REASONS,
) -> Mapping[str, object]:
    """Publish only the exact server-rendered fallback, or retain private review.

    A structurally ambiguous source (for example the same actor bound as buyer
    and awardee) makes even the canonical renderer unpublishable.  That attempt
    is retained for review but never crosses the publication boundary.
    """

    checked_source = _checked_source(source)
    checked_time = _checked_now(now)
    checked_reasons = _checked_reasons(reasons)
    payload = factual_fallback(checked_source)
    validation = validate_payload(payload, checked_source)
    publish = validation.valid
    status = QaStatus.FALLBACK if publish else QaStatus.REVIEW
    attempt_reasons = (
        checked_reasons
        if publish
        else _merge_reasons(validation.errors, checked_reasons)
    )
    return append_attempt(
        connection,
        source=checked_source,
        payload=payload,
        qa_status=status,
        qa_reasons=attempt_reasons,
        metadata=_factual_metadata(),
        created_at=checked_time,
        publish=publish,
    )


def _checked_generation_response(value: object) -> GenerationResponse | None:
    if not isinstance(value, GenerationResponse):
        return None
    try:
        return GenerationResponse.model_validate(value)
    except (ValidationError, TypeError, ValueError, AttributeError):
        return None


def _checked_qa_decision(value: object) -> QaDecision | None:
    if not isinstance(value, QaDecision):
        return None
    try:
        return QaDecision.model_validate(value)
    except (ValidationError, TypeError, ValueError, AttributeError):
        return None


def _retry(
    *,
    payload: CardPresentationPayload | None,
    reasons: Sequence[str],
) -> _PrivateAttempt:
    return _PrivateAttempt(
        payload=payload,
        status=QaStatus.REGENERATE,
        reasons=_merge_reasons(reasons),
        next_state=_NextState.RETRY,
    )


def _finish(
    *,
    payload: CardPresentationPayload | None,
    status: QaStatus,
    reasons: Sequence[str],
    factual_cause: Sequence[str] | None = None,
) -> _PrivateAttempt:
    return _PrivateAttempt(
        payload=payload,
        status=status,
        reasons=_merge_reasons(reasons),
        next_state=_NextState.FACTUAL,
        factual_cause=(
            None if factual_cause is None else _merge_reasons(factual_cause)
        ),
    )


def _review_candidate(
    *,
    source: PresentationInput,
    candidate: CardPresentationPayload,
    qa: QaSignals,
) -> _PrivateAttempt:
    """Return one private QA transition without ever accepting rewritten copy."""

    source_snapshot = source.model_dump_json()
    candidate_snapshot = candidate.model_dump_json()
    qa_source = PresentationInput.model_validate_json(source_snapshot)
    qa_candidate = CardPresentationPayload.model_validate_json(candidate_snapshot)
    try:
        raw_decision = qa.review(qa_source, qa_candidate)
    except sa.exc.SQLAlchemyError:
        raise
    except Exception:  # noqa: BLE001 - offline QA boundary
        return _finish(
            payload=CardPresentationPayload.model_validate_json(candidate_snapshot),
            status=QaStatus.REVIEW,
            reasons=("qa_exception",),
        )

    original = CardPresentationPayload.model_validate_json(candidate_snapshot)
    try:
        checked_after_qa = CardPresentationPayload.model_validate(qa_candidate)
        qa_mutated_payload = checked_after_qa.model_dump_json() != candidate_snapshot
    except (ValidationError, TypeError, ValueError, AttributeError):
        qa_mutated_payload = True
    if qa_mutated_payload:
        return _finish(
            payload=original,
            status=QaStatus.REVIEW,
            reasons=("qa_payload_mutation",),
        )

    decision = _checked_qa_decision(raw_decision)
    if decision is None:
        return _finish(
            payload=original,
            status=QaStatus.REVIEW,
            reasons=("qa_decision_invalid",),
        )
    if decision.status is QaStatus.PASS:
        return _finish(
            payload=original,
            status=QaStatus.PASS,
            reasons=decision.reasons,
            factual_cause=("full_publication_not_authorized",),
        )
    if decision.status is QaStatus.REGENERATE:
        return _retry(
            payload=original,
            reasons=decision.reasons or ("qa_regeneration_requested",),
        )
    if decision.status is QaStatus.FALLBACK:
        return _finish(
            payload=original,
            status=QaStatus.REVIEW,
            reasons=_merge_reasons(("qa_requested_fallback",), decision.reasons),
        )
    return _finish(
        payload=original,
        status=QaStatus.REVIEW,
        reasons=decision.reasons or ("qa_review_requested",),
    )


def _candidate_attempt(
    *,
    source: PresentationInput,
    generator: CardGenerator,
    qa: QaSignals,
    attempt_number: int,
) -> _PrivateAttempt:
    """Run one bounded generation transition and, only when safe, QA."""

    generator_source = PresentationInput.model_validate_json(source.model_dump_json())
    try:
        raw_response = generator.generate(generator_source, attempt=attempt_number)
    except sa.exc.SQLAlchemyError:
        raise
    except Exception:  # noqa: BLE001 - offline generator boundary
        return _retry(payload=None, reasons=("generation_exception",))

    response = _checked_generation_response(raw_response)
    if response is None:
        return _retry(payload=None, reasons=("generation_response_invalid",))
    if response.failure_kind is not None:
        return _retry(payload=None, reasons=("generation_failed",))

    candidate = response.payload
    if candidate is None:
        return _retry(payload=None, reasons=("generation_response_invalid",))
    if candidate.variant is PresentationVariant.FACTUAL_FALLBACK:
        return _finish(
            payload=candidate,
            status=QaStatus.REVIEW,
            reasons=("generator_fallback_not_authorized",),
        )

    validation = validate_payload(candidate, source)
    if validation.errors != _AUTHORIZED_QA_INPUT_ERRORS:
        return _retry(
            payload=candidate,
            reasons=validation.errors or ("candidate_validation_failed",),
        )
    return _review_candidate(source=source, candidate=candidate, qa=qa)


def _factual_after_candidate(
    connection: Connection,
    *,
    source: PresentationInput,
    now: dt.datetime,
    cause: Sequence[str],
) -> Mapping[str, object]:
    return publish_factual_fallback(
        connection,
        source=source,
        now=now,
        reasons=_merge_reasons(_DEFAULT_FACTUAL_REASONS, cause),
    )


def run_offline_candidate_pipeline(
    connection: Connection,
    *,
    source: PresentationInput,
    generator: CardGenerator,
    qa: QaSignals,
    now: dt.datetime,
    max_attempts: int = MAX_CANDIDATE_ATTEMPTS,
) -> Mapping[str, object]:
    """Exercise private generator/QA protocols and finish on factual output.

    At most one regeneration is possible.  No candidate, including a QA PASS,
    is publishable while intelligent generation remains unapproved.
    """

    if type(max_attempts) is not int or not 1 <= max_attempts <= MAX_CANDIDATE_ATTEMPTS:
        raise ValueError(f"max_attempts must be between 1 and {MAX_CANDIDATE_ATTEMPTS}")

    checked_source = _checked_source(source)
    checked_time = _checked_now(now)
    metadata = _protocol_metadata(generator, qa)
    if metadata is None:
        reason = ("candidate_metadata_invalid",)
        _append_private(
            connection,
            source=checked_source,
            payload=None,
            status=QaStatus.REVIEW,
            reasons=reason,
            metadata=_private_failure_metadata(),
            now=checked_time,
        )
        return _factual_after_candidate(
            connection,
            source=checked_source,
            now=checked_time,
            cause=reason,
        )

    for attempt_number in range(1, max_attempts + 1):
        private_attempt = _candidate_attempt(
            source=checked_source,
            generator=generator,
            qa=qa,
            attempt_number=attempt_number,
        )
        _append_private(
            connection,
            source=checked_source,
            payload=private_attempt.payload,
            status=private_attempt.status,
            reasons=private_attempt.reasons,
            metadata=metadata,
            now=checked_time,
        )
        if (
            private_attempt.next_state is _NextState.RETRY
            and attempt_number < max_attempts
        ):
            continue
        return _factual_after_candidate(
            connection,
            source=checked_source,
            now=checked_time,
            cause=private_attempt.fallback_reasons,
        )

    raise AssertionError("bounded candidate loop must produce an attempt")


__all__ = [
    "FACTUAL_GENERATOR_VERSION",
    "FACTUAL_QA_POLICY_VERSION",
    "MAX_CANDIDATE_ATTEMPTS",
    "publish_factual_fallback",
    "run_offline_candidate_pipeline",
]
