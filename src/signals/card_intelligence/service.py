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


class _NextState(StrEnum):
    RETRY = "RETRY"
    FACTUAL = "FACTUAL"


class _FactualCause(StrEnum):
    DETERMINISTIC_FACTUAL_FALLBACK = "deterministic_factual_fallback"
    CANDIDATE_METADATA_INVALID = "candidate_metadata_invalid"
    GENERATION_EXCEPTION = "generation_exception"
    GENERATION_FAILED = "generation_failed"
    GENERATION_RESPONSE_INVALID = "generation_response_invalid"
    GENERATOR_FALLBACK_NOT_AUTHORIZED = "generator_fallback_not_authorized"
    CANDIDATE_VALIDATION_EXHAUSTED = "candidate_validation_exhausted"
    QA_EXCEPTION = "qa_exception"
    QA_INPUT_MUTATION = "qa_input_mutation"
    QA_DECISION_INVALID = "qa_decision_invalid"
    QA_PASSED_PRIVATE = "qa_passed_private"
    QA_REVIEW_REQUESTED = "qa_review_requested"
    QA_REQUESTED_FALLBACK = "qa_requested_fallback"
    QA_REGENERATION_REQUESTED = "qa_regeneration_requested"
    QA_REGENERATION_EXHAUSTED = "qa_regeneration_exhausted"


@dataclass(frozen=True)
class _PrivateAttempt:
    payload: CardPresentationPayload | None
    status: QaStatus
    reasons: tuple[str, ...]
    next_state: _NextState
    factual_cause: _FactualCause


def _checked_source(source: PresentationInput) -> PresentationInput:
    return PresentationInput.model_validate(source)


def _checked_now(now: dt.datetime) -> dt.datetime:
    if not isinstance(now, dt.datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now


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


def _publish_factual_fallback(
    connection: Connection,
    *,
    source: PresentationInput,
    now: dt.datetime,
    cause: _FactualCause,
) -> Mapping[str, object]:
    if not isinstance(cause, _FactualCause):
        raise TypeError("factual cause must be a closed internal code")

    checked_source = _checked_source(source)
    checked_time = _checked_now(now)
    payload = factual_fallback(checked_source)
    validation = validate_payload(payload, checked_source)
    publish = validation.valid
    status = QaStatus.FALLBACK if publish else QaStatus.REVIEW
    factual_reasons = (_FactualCause.DETERMINISTIC_FACTUAL_FALLBACK.value,)
    if cause is not _FactualCause.DETERMINISTIC_FACTUAL_FALLBACK:
        factual_reasons = (*factual_reasons, cause.value)
    attempt_reasons = (
        factual_reasons
        if publish
        else _merge_reasons(validation.errors, factual_reasons)
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


def publish_factual_fallback(
    connection: Connection,
    *,
    source: PresentationInput,
    now: dt.datetime,
) -> Mapping[str, object]:
    """Publish only exact server facts with no caller-controlled reason surface.

    A structurally ambiguous source makes even the canonical renderer private
    REVIEW; it can never cross the publication boundary.
    """

    return _publish_factual_fallback(
        connection,
        source=source,
        now=now,
        cause=_FactualCause.DETERMINISTIC_FACTUAL_FALLBACK,
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
    factual_cause: _FactualCause,
) -> _PrivateAttempt:
    return _PrivateAttempt(
        payload=payload,
        status=QaStatus.REGENERATE,
        reasons=_merge_reasons(reasons),
        next_state=_NextState.RETRY,
        factual_cause=factual_cause,
    )


def _finish(
    *,
    payload: CardPresentationPayload | None,
    status: QaStatus,
    reasons: Sequence[str],
    factual_cause: _FactualCause,
) -> _PrivateAttempt:
    return _PrivateAttempt(
        payload=payload,
        status=status,
        reasons=_merge_reasons(reasons),
        next_state=_NextState.FACTUAL,
        factual_cause=factual_cause,
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
            reasons=(_FactualCause.QA_EXCEPTION.value,),
            factual_cause=_FactualCause.QA_EXCEPTION,
        )

    original = CardPresentationPayload.model_validate_json(candidate_snapshot)
    try:
        checked_source_after_qa = PresentationInput.model_validate(qa_source)
        checked_after_qa = CardPresentationPayload.model_validate(qa_candidate)
        qa_mutated_input = (
            checked_source_after_qa.model_dump_json() != source_snapshot
            or checked_after_qa.model_dump_json() != candidate_snapshot
        )
    except (ValidationError, TypeError, ValueError, AttributeError):
        qa_mutated_input = True
    if qa_mutated_input:
        return _finish(
            payload=original,
            status=QaStatus.REVIEW,
            reasons=(_FactualCause.QA_INPUT_MUTATION.value,),
            factual_cause=_FactualCause.QA_INPUT_MUTATION,
        )

    decision = _checked_qa_decision(raw_decision)
    if decision is None:
        return _finish(
            payload=original,
            status=QaStatus.REVIEW,
            reasons=(_FactualCause.QA_DECISION_INVALID.value,),
            factual_cause=_FactualCause.QA_DECISION_INVALID,
        )
    if decision.status is QaStatus.PASS:
        return _finish(
            payload=original,
            status=QaStatus.PASS,
            reasons=(_FactualCause.QA_PASSED_PRIVATE.value,),
            factual_cause=_FactualCause.QA_PASSED_PRIVATE,
        )
    if decision.status is QaStatus.REGENERATE:
        return _retry(
            payload=original,
            reasons=(_FactualCause.QA_REGENERATION_REQUESTED.value,),
            factual_cause=_FactualCause.QA_REGENERATION_EXHAUSTED,
        )
    if decision.status is QaStatus.FALLBACK:
        return _finish(
            payload=original,
            status=QaStatus.REVIEW,
            reasons=(_FactualCause.QA_REQUESTED_FALLBACK.value,),
            factual_cause=_FactualCause.QA_REQUESTED_FALLBACK,
        )
    return _finish(
        payload=original,
        status=QaStatus.REVIEW,
        reasons=(_FactualCause.QA_REVIEW_REQUESTED.value,),
        factual_cause=_FactualCause.QA_REVIEW_REQUESTED,
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
        return _retry(
            payload=None,
            reasons=(_FactualCause.GENERATION_EXCEPTION.value,),
            factual_cause=_FactualCause.GENERATION_EXCEPTION,
        )

    response = _checked_generation_response(raw_response)
    if response is None:
        return _retry(
            payload=None,
            reasons=(_FactualCause.GENERATION_RESPONSE_INVALID.value,),
            factual_cause=_FactualCause.GENERATION_RESPONSE_INVALID,
        )
    if response.failure_kind is not None:
        return _retry(
            payload=None,
            reasons=(_FactualCause.GENERATION_FAILED.value,),
            factual_cause=_FactualCause.GENERATION_FAILED,
        )

    candidate = response.payload
    if candidate is None:
        return _retry(
            payload=None,
            reasons=(_FactualCause.GENERATION_RESPONSE_INVALID.value,),
            factual_cause=_FactualCause.GENERATION_RESPONSE_INVALID,
        )
    if candidate.variant is PresentationVariant.FACTUAL_FALLBACK:
        return _finish(
            payload=candidate,
            status=QaStatus.REVIEW,
            reasons=(_FactualCause.GENERATOR_FALLBACK_NOT_AUTHORIZED.value,),
            factual_cause=_FactualCause.GENERATOR_FALLBACK_NOT_AUTHORIZED,
        )

    validation = validate_payload(candidate, source)
    if validation.errors != _AUTHORIZED_QA_INPUT_ERRORS:
        return _retry(
            payload=candidate,
            reasons=(
                validation.errors
                or (_FactualCause.CANDIDATE_VALIDATION_EXHAUSTED.value,)
            ),
            factual_cause=_FactualCause.CANDIDATE_VALIDATION_EXHAUSTED,
        )
    return _review_candidate(source=source, candidate=candidate, qa=qa)


def _factual_after_candidate(
    connection: Connection,
    *,
    source: PresentationInput,
    now: dt.datetime,
    cause: _FactualCause,
) -> Mapping[str, object]:
    if not isinstance(cause, _FactualCause):
        raise TypeError("factual cause must be a closed internal code")
    return _publish_factual_fallback(
        connection,
        source=source,
        now=now,
        cause=cause,
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
        cause = _FactualCause.CANDIDATE_METADATA_INVALID
        _append_private(
            connection,
            source=checked_source,
            payload=None,
            status=QaStatus.REVIEW,
            reasons=(cause.value,),
            metadata=_private_failure_metadata(),
            now=checked_time,
        )
        return _factual_after_candidate(
            connection,
            source=checked_source,
            now=checked_time,
            cause=cause,
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
            cause=private_attempt.factual_cause,
        )

    raise AssertionError("bounded candidate loop must produce an attempt")


__all__ = [
    "FACTUAL_GENERATOR_VERSION",
    "FACTUAL_QA_POLICY_VERSION",
    "MAX_CANDIDATE_ATTEMPTS",
    "publish_factual_fallback",
    "run_offline_candidate_pipeline",
]
