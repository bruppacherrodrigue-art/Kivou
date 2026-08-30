"""Immutable Card Intelligence attempts and fail-closed publication reads.

This module is a persistence boundary only.  It wires no generator, QA model,
provider, prompt, worker, or network client.  Frontend/API GETs can therefore
read only already-published, recursively validated artifacts.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, NoReturn, cast

import sqlalchemy as sa
from pydantic import StringConstraints, ValidationError, field_validator
from sqlalchemy.engine import Connection, RowMapping

from signals.accounts.schema import target_icp
from signals.card_intelligence.contracts import (
    ArtifactKind,
    CardPresentationPayload,
    Contract,
    PresentationInput,
    PresentationVariant,
    PublishedCardPresentation,
    SourceFacts,
    TargetIcpSnapshot,
)
from signals.card_intelligence.input import (
    PresentationInputUnavailable,
    _awardees,
    _buyers,
    _clean_text,
    _ensure_complete_icp,
    _location_label,
    _source_binding,
    _source_field_ref,
    build_presentation_input,
)
from signals.card_intelligence.validation import validate_payload
from signals.persistence.schema import (
    card_presentation_artifact,
    contract_award,
    evidence,
    materialized_signal,
    source_event,
)
from signals.qa_signals.contracts import QaDecision, QaStatus

_CONFLICT = "card presentation publication conflict"
_VERSION_IDENTIFIER = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[0-9A-Za-z][0-9A-Za-z._-]*$",
    ),
]
_PROVIDER_IDENTIFIER = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[0-9A-Za-z][0-9A-Za-z._-]*$",
    ),
]
_MODEL_IDENTIFIER = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=256,
        pattern=r"^[0-9A-Za-z][0-9A-Za-z._:/-]*$",
    ),
]


class PresentationPublicationConflict(RuntimeError):
    """A write cannot prove that publication is current and valid."""


class AttemptMetadata(Contract):
    """Non-secret identifiers that describe one offline generation attempt."""

    generator_version: _VERSION_IDENTIFIER
    qa_policy_version: _VERSION_IDENTIFIER
    prompt_version: _VERSION_IDENTIFIER | None = None
    model_id: _MODEL_IDENTIFIER | None = None
    provider: _PROVIDER_IDENTIFIER | None = None
    qa_model_id: _MODEL_IDENTIFIER | None = None
    qa_provider: _PROVIDER_IDENTIFIER | None = None

    @field_validator("model_id", "qa_model_id")
    @classmethod
    def model_identifiers_are_not_urls(cls, value: str | None) -> str | None:
        if value is not None and "://" in value:
            raise ValueError("model metadata must be an identifier, not a URL")
        return value


def _conflict() -> NoReturn:
    raise PresentationPublicationConflict(_CONFLICT)


def _aware(value: object) -> dt.datetime:
    if not isinstance(value, dt.datetime):
        _conflict()
    if value.tzinfo is None or value.utcoffset() is None:
        _conflict()
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _locked_signal_statement(source: PresentationInput) -> sa.Select:
    """Build the current-row ownership lock used by every append.

    ``of=materialized_signal`` is intentionally explicit: PostgreSQL must lock
    the stream authority row, while SQLite remains usable for local tests.
    """

    return (
        sa.select(materialized_signal.c.signal_key)
        .select_from(
            materialized_signal.join(
                target_icp,
                materialized_signal.c.target_icp_id == target_icp.c.target_icp_id,
            )
        )
        .where(
            materialized_signal.c.signal_key == source.signal_key,
            materialized_signal.c.target_icp_id == source.target_icp_id,
            materialized_signal.c.revision == source.signal_revision,
            materialized_signal.c.target_icp_revision == source.target_icp_revision,
            materialized_signal.c.invalidated_at.is_(None),
            target_icp.c.account_id == source.account_id,
            target_icp.c.status == "active",
            target_icp.c.plan_limit_code.is_(None),
            target_icp.c.matching_revision == source.target_icp_revision,
            materialized_signal.c.target_icp_revision == target_icp.c.matching_revision,
        )
        .with_for_update(of=materialized_signal)
    )


def _validated_write_contracts(
    *,
    source: PresentationInput,
    payload: CardPresentationPayload | None,
    qa_status: QaStatus,
    qa_reasons: Sequence[str],
    metadata: AttemptMetadata,
    created_at: dt.datetime,
    publish: bool,
) -> tuple[PresentationInput, CardPresentationPayload | None, QaDecision, AttemptMetadata]:
    try:
        if type(publish) is not bool:
            _conflict()
        checked_source = PresentationInput.model_validate(source)
        checked_payload = (
            None if payload is None else CardPresentationPayload.model_validate(payload)
        )
        if isinstance(qa_reasons, (str, bytes)):
            _conflict()
        checked_decision = QaDecision(
            status=qa_status,
            reasons=tuple(qa_reasons),
        )
        checked_metadata = AttemptMetadata.model_validate(metadata)
        _aware(created_at)
    except PresentationPublicationConflict:
        raise
    except (ValidationError, TypeError, ValueError, AttributeError):
        _conflict()

    if checked_decision.status in {QaStatus.PASS, QaStatus.FALLBACK}:
        if checked_payload is None:
            _conflict()
        expected = {
            QaStatus.PASS: PresentationVariant.FULL,
            QaStatus.FALLBACK: PresentationVariant.FACTUAL_FALLBACK,
        }[checked_decision.status]
        if checked_payload.variant is not expected:
            _conflict()

    if checked_decision.status is QaStatus.FALLBACK and any(
        value is not None
        for value in (
            checked_metadata.prompt_version,
            checked_metadata.model_id,
            checked_metadata.provider,
            checked_metadata.qa_model_id,
            checked_metadata.qa_provider,
        )
    ):
        _conflict()

    if publish:
        if checked_decision.status not in {QaStatus.PASS, QaStatus.FALLBACK}:
            _conflict()
        assert checked_payload is not None
        if not validate_payload(checked_payload, checked_source).valid:
            _conflict()

    return checked_source, checked_payload, checked_decision, checked_metadata


def _fresh_source_under_lock(
    connection: Connection,
    source: PresentationInput,
) -> PresentationInput:
    locked = connection.execute(_locked_signal_statement(source)).one_or_none()
    if locked is None:
        _conflict()
    try:
        current = build_presentation_input(
            connection,
            account_id=source.account_id,
            signal_key=source.signal_key,
            language=source.language,
        )
    except PresentationInputUnavailable:
        _conflict()
    if (
        current != source
        or current.fingerprint() != source.fingerprint()
        or current.facts.source_award_binding != source.facts.source_award_binding
        or current.facts.source_event_binding != source.facts.source_event_binding
    ):
        _conflict()
    return current


def _stream_predicate(source: PresentationInput) -> tuple[sa.ColumnElement[bool], ...]:
    return (
        card_presentation_artifact.c.account_id == source.account_id,
        card_presentation_artifact.c.signal_key == source.signal_key,
        card_presentation_artifact.c.target_icp_id == source.target_icp_id,
        card_presentation_artifact.c.artifact_kind
        == ArtifactKind.CARD_PRESENTATION.value,
        card_presentation_artifact.c.language == source.language,
    )


def _artifact_values(
    *,
    source: PresentationInput,
    payload: CardPresentationPayload | None,
    decision: QaDecision,
    metadata: AttemptMetadata,
    created_at: dt.datetime,
    publish: bool,
    version: int,
) -> dict[str, object]:
    payload_value = None if payload is None else payload.model_dump(mode="json")

    identity = _artifact_identity(
        source=source,
        payload_value=payload_value,
        decision=decision,
        metadata=metadata,
        version=version,
    )
    return {
        "artifact_id": _sha256_json(identity),
        "account_id": source.account_id,
        "signal_key": source.signal_key,
        "signal_revision": source.signal_revision,
        "target_icp_id": source.target_icp_id,
        "target_icp_revision": source.target_icp_revision,
        "artifact_kind": ArtifactKind.CARD_PRESENTATION.value,
        "language": source.language,
        "version": version,
        "input_fingerprint": source.fingerprint(),
        "payload": payload_value,
        "payload_variant": None if payload is None else payload.variant.value,
        "qa_status": decision.status.value,
        "qa_reasons": list(decision.reasons),
        "qa_policy_version": metadata.qa_policy_version,
        "generator_version": metadata.generator_version,
        "prompt_version": metadata.prompt_version,
        "model_id": metadata.model_id,
        "provider": metadata.provider,
        "qa_model_id": metadata.qa_model_id,
        "qa_provider": metadata.qa_provider,
        "created_at": created_at,
        "published_at": created_at if publish else None,
        "superseded_at": None,
    }


def _artifact_identity(
    *,
    source: PresentationInput,
    payload_value: object,
    decision: QaDecision,
    metadata: AttemptMetadata,
    version: int,
) -> dict[str, object]:
    return {
        "account_id": source.account_id,
        "signal_key": source.signal_key,
        "signal_revision": source.signal_revision,
        "target_icp_id": source.target_icp_id,
        "target_icp_revision": source.target_icp_revision,
        "artifact_kind": ArtifactKind.CARD_PRESENTATION.value,
        "language": source.language,
        "version": version,
        "input_fingerprint": source.fingerprint(),
        "payload_hash": _sha256_json(payload_value),
        "qa_decision": decision.model_dump(mode="json"),
        "metadata": metadata.model_dump(mode="json"),
    }


def append_attempt(
    connection: Connection,
    *,
    source: PresentationInput,
    payload: CardPresentationPayload | None,
    qa_status: QaStatus,
    qa_reasons: Sequence[str],
    metadata: AttemptMetadata,
    created_at: dt.datetime,
    publish: bool,
) -> Mapping[str, object]:
    """Append one immutable attempt and optionally publish it atomically."""

    checked_source, checked_payload, decision, checked_metadata = _validated_write_contracts(
        source=source,
        payload=payload,
        qa_status=qa_status,
        qa_reasons=qa_reasons,
        metadata=metadata,
        created_at=created_at,
        publish=publish,
    )
    _fresh_source_under_lock(connection, checked_source)

    predicate = _stream_predicate(checked_source)
    maximum = connection.scalar(
        sa.select(sa.func.max(card_presentation_artifact.c.version)).where(*predicate)
    )
    version = 1 if maximum is None else int(maximum) + 1
    values = _artifact_values(
        source=checked_source,
        payload=checked_payload,
        decision=decision,
        metadata=checked_metadata,
        created_at=created_at,
        publish=publish,
        version=version,
    )

    active_rows: list[RowMapping] = []
    if publish:
        active_rows = list(
            connection.execute(
                sa.select(
                    card_presentation_artifact.c.artifact_id,
                    card_presentation_artifact.c.published_at,
                ).where(
                    *predicate,
                    card_presentation_artifact.c.published_at.is_not(None),
                    card_presentation_artifact.c.superseded_at.is_(None),
                )
            ).mappings()
        )
        if len(active_rows) > 1:
            _conflict()
        if active_rows:
            prior_published = active_rows[0]["published_at"]
            if isinstance(prior_published, dt.datetime):
                if prior_published.tzinfo is None:
                    prior_published = prior_published.replace(tzinfo=dt.UTC)
                if prior_published > created_at:
                    _conflict()

    try:
        with connection.begin_nested():
            if active_rows:
                updated = connection.execute(
                    sa.update(card_presentation_artifact)
                    .where(
                        card_presentation_artifact.c.artifact_id
                        == active_rows[0]["artifact_id"],
                        card_presentation_artifact.c.superseded_at.is_(None),
                    )
                    .values(superseded_at=created_at)
                )
                if updated.rowcount != 1:
                    _conflict()
            connection.execute(sa.insert(card_presentation_artifact).values(**values))
    except PresentationPublicationConflict:
        raise
    except sa.exc.IntegrityError as error:
        raise PresentationPublicationConflict(_CONFLICT) from error
    return values


def _json_value(value: object) -> object:
    if not isinstance(value, str):
        return value
    return json.loads(value)


def _stored_date(value: object) -> dt.date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("stored date is not text")
    parsed = dt.date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("stored date is not canonical")
    return parsed


def _stored_datetime(value: object) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = dt.datetime.fromisoformat(value)
    else:
        raise TypeError("stored timestamp is invalid")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    if parsed.utcoffset() is None:
        raise ValueError("stored timestamp is not timezone-aware")
    return parsed


def _source_from_read_row(
    row: RowMapping,
    *,
    account_id: str,
    language: Literal["fr", "en"],
) -> PresentationInput:
    customer_input = TargetIcpSnapshot.from_json_value(
        _json_value(row["current_icp_customer_input"])
    )
    _ensure_complete_icp(customer_input)
    matched_needs = _json_value(row["current_icp_matched_needs"])
    if not isinstance(matched_needs, list):
        raise TypeError("stored matched needs are invalid")
    award_key = row["current_award_key"]
    event_key = row["current_event_key"]
    award_binding = _source_binding(award_key)
    event_binding = _source_binding(event_key)
    source_refs = (
        _source_field_ref(
            table="contract_award",
            row_key=award_key,
            column="awardee_parties",
        ),
        _source_field_ref(
            table="source_event",
            row_key=event_key,
            column="procedure_buyers",
        ),
        _source_field_ref(table="contract_award", row_key=award_key, column="amount"),
        _source_field_ref(table="contract_award", row_key=award_key, column="currency"),
        _source_field_ref(
            table="contract_award",
            row_key=award_key,
            column="place_of_performance",
        ),
        _source_field_ref(
            table="contract_award",
            row_key=award_key,
            column="award_date",
        ),
        _source_field_ref(
            table="contract_award",
            row_key=award_key,
            column="contract_notification_date",
        ),
        _source_field_ref(
            table="source_event",
            row_key=event_key,
            column="published_on",
        ),
    )
    amount_raw = row["current_amount"]
    try:
        amount = None if amount_raw is None else Decimal(str(amount_raw))
    except InvalidOperation as error:
        raise ValueError("stored amount is invalid") from error
    facts = SourceFacts(
        source_award_binding=award_binding,
        source_event_binding=event_binding,
        awardees=_awardees(_json_value(row["current_awardees"])),
        buyers=_buyers(_json_value(row["current_buyers"])),
        award_title=_clean_text(row["current_award_title"]),
        amount=amount,
        currency=_clean_text(row["current_currency"]),
        location=_location_label(_json_value(row["current_location"])),
        award_date=_stored_date(row["current_award_date"]),
        contract_notification_date=_stored_date(row["current_notification_date"]),
        publication_date=_stored_date(row["current_publication_date"]),
        source_system=_clean_text(row["current_source_system"], required=True),
        source_notice_id=_clean_text(row["current_source_notice_id"], required=True),
        evidence_refs=source_refs,
    )
    return PresentationInput(
        account_id=account_id,
        signal_key=row["artifact_signal_key"],
        signal_revision=row["current_signal_revision"],
        target_icp_id=row["current_target_icp_id"],
        target_icp_revision=row["current_target_icp_revision"],
        language=language,
        target_icp_label=row["current_icp_label"],
        target_icp_customer_input=customer_input,
        icp_matched_needs=tuple(matched_needs),
        facts=facts,
    )


def _read_columns() -> tuple[sa.ColumnElement[object], ...]:
    return (
        card_presentation_artifact.c.artifact_id.label("artifact_id"),
        card_presentation_artifact.c.account_id.label("artifact_account_id"),
        card_presentation_artifact.c.signal_key.label("artifact_signal_key"),
        card_presentation_artifact.c.signal_revision.label("artifact_signal_revision"),
        card_presentation_artifact.c.target_icp_id.label("artifact_target_icp_id"),
        card_presentation_artifact.c.target_icp_revision.label(
            "artifact_target_icp_revision"
        ),
        card_presentation_artifact.c.language.label("artifact_language"),
        card_presentation_artifact.c.version.label("artifact_version"),
        card_presentation_artifact.c.input_fingerprint.label("artifact_input_fingerprint"),
        sa.cast(card_presentation_artifact.c.payload, sa.Text).label(
            "artifact_payload"
        ),
        card_presentation_artifact.c.payload_variant.label("artifact_payload_variant"),
        card_presentation_artifact.c.qa_status.label("artifact_qa_status"),
        sa.cast(card_presentation_artifact.c.qa_reasons, sa.Text).label(
            "artifact_qa_reasons"
        ),
        card_presentation_artifact.c.qa_policy_version.label(
            "artifact_qa_policy_version"
        ),
        card_presentation_artifact.c.generator_version.label(
            "artifact_generator_version"
        ),
        card_presentation_artifact.c.prompt_version.label("artifact_prompt_version"),
        card_presentation_artifact.c.model_id.label("artifact_model_id"),
        card_presentation_artifact.c.provider.label("artifact_provider"),
        card_presentation_artifact.c.qa_model_id.label("artifact_qa_model_id"),
        card_presentation_artifact.c.qa_provider.label("artifact_qa_provider"),
        sa.cast(card_presentation_artifact.c.created_at, sa.Text).label(
            "artifact_created_at"
        ),
        sa.cast(card_presentation_artifact.c.published_at, sa.Text).label(
            "artifact_published_at"
        ),
        sa.cast(card_presentation_artifact.c.superseded_at, sa.Text).label(
            "artifact_superseded_at"
        ),
        materialized_signal.c.revision.label("current_signal_revision"),
        materialized_signal.c.target_icp_id.label("current_target_icp_id"),
        materialized_signal.c.target_icp_revision.label("current_target_icp_revision"),
        sa.cast(materialized_signal.c.icp_matched_needs, sa.Text).label(
            "current_icp_matched_needs"
        ),
        target_icp.c.label.label("current_icp_label"),
        sa.cast(target_icp.c.customer_input, sa.Text).label(
            "current_icp_customer_input"
        ),
        contract_award.c.award_key.label("current_award_key"),
        sa.cast(contract_award.c.awardee_parties, sa.Text).label("current_awardees"),
        contract_award.c.title.label("current_award_title"),
        sa.cast(contract_award.c.amount, sa.Text).label("current_amount"),
        contract_award.c.currency.label("current_currency"),
        sa.cast(contract_award.c.place_of_performance, sa.Text).label(
            "current_location"
        ),
        sa.cast(contract_award.c.award_date, sa.Text).label("current_award_date"),
        sa.cast(contract_award.c.contract_notification_date, sa.Text).label(
            "current_notification_date"
        ),
        source_event.c.event_key.label("current_event_key"),
        source_event.c.source_system.label("current_source_system"),
        source_event.c.source_notice_id.label("current_source_notice_id"),
        sa.cast(source_event.c.published_on, sa.Text).label("current_publication_date"),
        sa.cast(source_event.c.procedure_buyers, sa.Text).label("current_buyers"),
    )


def _read_statement(
    *,
    account_id: str,
    bindings: Mapping[str, tuple[int, int]],
    language: Literal["fr", "en"],
    artifact_id: str | None,
    active_only: bool,
) -> sa.Select:
    binding_predicates = tuple(
        sa.and_(
            card_presentation_artifact.c.signal_key == signal_key,
            card_presentation_artifact.c.signal_revision == signal_revision,
            card_presentation_artifact.c.target_icp_revision == icp_revision,
        )
        for signal_key, (signal_revision, icp_revision) in bindings.items()
    )
    statement = (
        sa.select(*_read_columns())
        .select_from(
            card_presentation_artifact.join(
                materialized_signal,
                card_presentation_artifact.c.signal_key
                == materialized_signal.c.signal_key,
            )
            .join(
                target_icp,
                materialized_signal.c.target_icp_id == target_icp.c.target_icp_id,
            )
            .join(
                contract_award,
                materialized_signal.c.materialization_award_key
                == contract_award.c.award_key,
            )
            .join(source_event, contract_award.c.event_key == source_event.c.event_key)
        )
        .where(
            card_presentation_artifact.c.account_id == account_id,
            target_icp.c.account_id == account_id,
            card_presentation_artifact.c.artifact_kind
            == ArtifactKind.CARD_PRESENTATION.value,
            card_presentation_artifact.c.language == language,
            card_presentation_artifact.c.published_at.is_not(None),
            card_presentation_artifact.c.qa_status.in_(("PASS", "FALLBACK")),
            card_presentation_artifact.c.signal_revision
            == materialized_signal.c.revision,
            card_presentation_artifact.c.target_icp_id
            == materialized_signal.c.target_icp_id,
            card_presentation_artifact.c.target_icp_revision
            == materialized_signal.c.target_icp_revision,
            materialized_signal.c.target_icp_revision == target_icp.c.matching_revision,
            materialized_signal.c.invalidated_at.is_(None),
            target_icp.c.status == "active",
            target_icp.c.plan_limit_code.is_(None),
            contract_award.c.winner_status == "identified",
            sa.exists(
                sa.select(sa.literal(1)).where(
                    evidence.c.award_key == contract_award.c.award_key,
                    evidence.c.anchors_kind == "award_fact",
                )
            ),
            sa.or_(*binding_predicates),
        )
    )
    if active_only:
        statement = statement.where(card_presentation_artifact.c.superseded_at.is_(None))
    if artifact_id is not None:
        statement = statement.where(card_presentation_artifact.c.artifact_id == artifact_id)
    return statement


def _valid_read_arguments(
    *,
    account_id: object,
    bindings: object,
    language: object,
) -> bool:
    if not isinstance(account_id, str) or not account_id.strip():
        return False
    if language not in ("fr", "en") or not isinstance(bindings, Mapping):
        return False
    for signal_key, binding in bindings.items():
        if not isinstance(signal_key, str) or not signal_key.strip():
            return False
        if not isinstance(binding, tuple) or len(binding) != 2:
            return False
        if any(type(revision) is not int or revision < 1 for revision in binding):
            return False
    return True


def _presentation_from_row(
    row: RowMapping,
    *,
    account_id: str,
    language: Literal["fr", "en"],
) -> PublishedCardPresentation | None:
    try:
        payload_value = _json_value(row["artifact_payload"])
        if payload_value is None:
            return None
        payload = CardPresentationPayload.from_json_value(payload_value)
        reasons = _json_value(row["artifact_qa_reasons"])
        decision = QaDecision.from_json_value(
            {"status": row["artifact_qa_status"], "reasons": reasons}
        )
        metadata = AttemptMetadata(
            generator_version=row["artifact_generator_version"],
            qa_policy_version=row["artifact_qa_policy_version"],
            prompt_version=row["artifact_prompt_version"],
            model_id=row["artifact_model_id"],
            provider=row["artifact_provider"],
            qa_model_id=row["artifact_qa_model_id"],
            qa_provider=row["artifact_qa_provider"],
        )
        if decision.status not in {QaStatus.PASS, QaStatus.FALLBACK}:
            return None
        expected_variant = {
            QaStatus.PASS: PresentationVariant.FULL,
            QaStatus.FALLBACK: PresentationVariant.FACTUAL_FALLBACK,
        }[decision.status]
        if payload.variant is not expected_variant:
            return None
        if row["artifact_payload_variant"] != payload.variant.value:
            return None
        if decision.status is QaStatus.FALLBACK and any(
            value is not None
            for value in (
                metadata.prompt_version,
                metadata.model_id,
                metadata.provider,
                metadata.qa_model_id,
                metadata.qa_provider,
            )
        ):
            return None

        current_source = _source_from_read_row(
            row,
            account_id=account_id,
            language=language,
        )
        if row["artifact_input_fingerprint"] != current_source.fingerprint():
            return None
        if not validate_payload(payload, current_source).valid:
            return None
        identity = _artifact_identity(
            source=current_source,
            payload_value=payload.model_dump(mode="json"),
            decision=decision,
            metadata=metadata,
            version=row["artifact_version"],
        )
        if row["artifact_id"] != _sha256_json(identity):
            return None

        created_at = _stored_datetime(row["artifact_created_at"])
        published_at = _stored_datetime(row["artifact_published_at"])
        superseded_at = _stored_datetime(row["artifact_superseded_at"])
        if created_at is None or published_at is None or created_at > published_at:
            return None
        if superseded_at is not None and published_at > superseded_at:
            return None
        return PublishedCardPresentation(
            artifact_id=row["artifact_id"],
            version=row["artifact_version"],
            status=cast(Literal["PASS", "FALLBACK"], decision.status.value),
            schema_version=payload.schema_version,
            published_at=published_at,
            content=payload,
        )
    except (
        PresentationInputUnavailable,
        ValidationError,
        json.JSONDecodeError,
        InvalidOperation,
        KeyError,
        TypeError,
        ValueError,
    ):
        return None


def published_for_signals(
    connection: Connection,
    *,
    account_id: str,
    bindings: Mapping[str, tuple[int, int]],
    language: Literal["fr", "en"],
) -> dict[str, PublishedCardPresentation]:
    """Load current presentations for one feed page in exactly one SELECT."""

    if not _valid_read_arguments(
        account_id=account_id,
        bindings=bindings,
        language=language,
    ) or not bindings:
        return {}
    rows = connection.execute(
        _read_statement(
            account_id=account_id,
            bindings=bindings,
            language=language,
            artifact_id=None,
            active_only=True,
        )
    ).mappings()
    grouped: dict[str, list[RowMapping]] = defaultdict(list)
    for row in rows:
        grouped[row["artifact_signal_key"]].append(row)

    presentations: dict[str, PublishedCardPresentation] = {}
    for signal_key, candidates in grouped.items():
        if len(candidates) != 1:
            continue
        presentation = _presentation_from_row(
            candidates[0],
            account_id=account_id,
            language=language,
        )
        if presentation is not None:
            presentations[signal_key] = presentation
    return presentations


def published_artifact_for_signal(
    connection: Connection,
    *,
    account_id: str,
    signal_key: str,
    binding: tuple[int, int],
    language: Literal["fr", "en"],
    artifact_id: str,
) -> PublishedCardPresentation | None:
    """Resolve one immutable current-or-superseded artifact for a pinned detail."""

    bindings = {signal_key: binding}
    if not _valid_read_arguments(
        account_id=account_id,
        bindings=bindings,
        language=language,
    ) or not isinstance(artifact_id, str) or re.fullmatch(
        r"[0-9a-f]{64}", artifact_id
    ) is None:
        return None
    rows = list(
        connection.execute(
            _read_statement(
                account_id=account_id,
                bindings=bindings,
                language=language,
                artifact_id=artifact_id,
                active_only=False,
            )
        ).mappings()
    )
    if len(rows) != 1:
        return None
    return _presentation_from_row(rows[0], account_id=account_id, language=language)


__all__ = [
    "AttemptMetadata",
    "PresentationPublicationConflict",
    "append_attempt",
    "published_artifact_for_signal",
    "published_for_signals",
]
