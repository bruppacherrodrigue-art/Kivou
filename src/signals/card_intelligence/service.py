"""Offline Card Intelligence -> deterministic gates -> QA -> publication."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping

from sqlalchemy.engine import Connection

from signals.card_intelligence.contracts import (
    ArtifactKind,
    CardPresentationPayload,
    PresentationInput,
    QaStatus,
)
from signals.card_intelligence.fallback import factual_fallback
from signals.card_intelligence.protocol import CardIntelligenceModel
from signals.card_intelligence.store import append_attempt
from signals.card_intelligence.validation import validate_payload
from signals.qa_signals.protocol import QaSignalsModel

MAX_GENERATION_ATTEMPTS = 2
FALLBACK_VERSION = "card-factual-fallback-v1"


def _append(
    connection: Connection,
    *,
    source: PresentationInput,
    payload: CardPresentationPayload | None,
    status: QaStatus,
    reasons: tuple[str, ...],
    generator: CardIntelligenceModel | None,
    qa: QaSignalsModel | None,
    now: dt.datetime,
    publish: bool,
) -> Mapping[str, object]:
    return append_attempt(
        connection,
        source=source,
        kind=ArtifactKind.SIGNAL_CARD,
        payload=payload,
        qa_status=status,
        qa_reasons=reasons,
        prompt_version=generator.prompt_version if generator else FALLBACK_VERSION,
        model_id=generator.model_id if generator else None,
        provider=generator.provider if generator else None,
        qa_model_id=qa.model_id if qa else None,
        qa_provider=qa.provider if qa else None,
        qa_policy_version=qa.policy_version if qa else "qa-signals-policy-v1",
        created_at=now,
        publish=publish,
    )


def publish_factual_fallback(
    connection: Connection,
    *,
    source: PresentationInput,
    now: dt.datetime,
    reasons: tuple[str, ...] = ("intelligence_unavailable",),
    generator: CardIntelligenceModel | None = None,
    qa: QaSignalsModel | None = None,
) -> Mapping[str, object]:
    payload = factual_fallback(source)
    validation = validate_payload(payload, source)
    if not validation.valid:
        # An actor/source inconsistency is not repaired by a generic sentence.
        return _append(
            connection,
            source=source,
            payload=payload,
            status=QaStatus.REVIEW,
            reasons=("fallback_not_safe", *validation.errors),
            generator=generator,
            qa=qa,
            now=now,
            publish=False,
        )
    return _append(
        connection,
        source=source,
        payload=payload,
        status=QaStatus.FALLBACK,
        reasons=reasons,
        generator=generator,
        qa=qa,
        now=now,
        publish=True,
    )


def generate_and_publish(
    connection: Connection,
    *,
    source: PresentationInput,
    generator: CardIntelligenceModel,
    qa: QaSignalsModel,
    now: dt.datetime,
    max_attempts: int = MAX_GENERATION_ATTEMPTS,
) -> Mapping[str, object]:
    """Run outside HTTP. One regeneration at most, then fallback or review."""
    if not 1 <= max_attempts <= MAX_GENERATION_ATTEMPTS:
        raise ValueError(f"max_attempts must be between 1 and {MAX_GENERATION_ATTEMPTS}")

    for attempt in range(1, max_attempts + 1):
        try:
            generated = generator.generate(source, attempt=attempt)
        except Exception:  # noqa: BLE001 - provider boundary fails closed
            generated = None
        if generated is None or generated.failure_kind is not None:
            reason = generated.failure_kind if generated is not None else "generation_exception"
            _append(
                connection,
                source=source,
                payload=None,
                status=QaStatus.REGENERATE,
                reasons=(reason,),
                generator=generator,
                qa=qa,
                now=now,
                publish=False,
            )
            if attempt < max_attempts:
                continue
            return publish_factual_fallback(
                connection,
                source=source,
                now=now,
                reasons=("generation_failed_after_retry", reason),
                generator=generator,
                qa=qa,
            )

        payload = generated.payload
        assert payload is not None
        validation = validate_payload(payload, source)
        if not validation.valid:
            _append(
                connection,
                source=source,
                payload=payload,
                status=QaStatus.REGENERATE,
                reasons=validation.errors,
                generator=generator,
                qa=qa,
                now=now,
                publish=False,
            )
            if attempt < max_attempts:
                continue
            return publish_factual_fallback(
                connection,
                source=source,
                now=now,
                reasons=("deterministic_validation_failed_after_retry", *validation.errors),
                generator=generator,
                qa=qa,
            )

        try:
            reviewed = qa.review(source, payload)
        except Exception:  # noqa: BLE001 - provider boundary fails closed
            reviewed = None
        if reviewed is None or reviewed.failure_kind is not None:
            reason = reviewed.failure_kind if reviewed is not None else "qa_exception"
            _append(
                connection,
                source=source,
                payload=payload,
                status=QaStatus.REGENERATE,
                reasons=(reason,),
                generator=generator,
                qa=qa,
                now=now,
                publish=False,
            )
            if attempt < max_attempts:
                continue
            return publish_factual_fallback(
                connection,
                source=source,
                now=now,
                reasons=("qa_unavailable_after_retry", reason),
                generator=generator,
                qa=qa,
            )

        decision = reviewed.decision
        assert decision is not None
        if decision.status is QaStatus.PASS:
            return _append(
                connection,
                source=source,
                payload=payload,
                status=QaStatus.PASS,
                reasons=decision.reasons,
                generator=generator,
                qa=qa,
                now=now,
                publish=True,
            )
        if decision.status is QaStatus.REVIEW:
            return _append(
                connection,
                source=source,
                payload=payload,
                status=QaStatus.REVIEW,
                reasons=decision.reasons,
                generator=generator,
                qa=qa,
                now=now,
                publish=False,
            )
        if decision.status is QaStatus.FALLBACK:
            return publish_factual_fallback(
                connection,
                source=source,
                now=now,
                reasons=decision.reasons or ("qa_requested_fallback",),
                generator=generator,
                qa=qa,
            )

        _append(
            connection,
            source=source,
            payload=payload,
            status=QaStatus.REGENERATE,
            reasons=decision.reasons or ("qa_requested_regeneration",),
            generator=generator,
            qa=qa,
            now=now,
            publish=False,
        )
        if attempt == max_attempts:
            return publish_factual_fallback(
                connection,
                source=source,
                now=now,
                reasons=("qa_regeneration_exhausted", *decision.reasons),
                generator=generator,
                qa=qa,
            )

    raise AssertionError("bounded generation loop did not return")
