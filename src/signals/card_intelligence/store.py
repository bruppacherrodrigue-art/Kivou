"""Tenant-scoped version and publication storage for pre-generated card copy."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from signals.accounts.schema import target_icp
from signals.card_intelligence.contracts import (
    ArtifactKind,
    CardPresentationPayload,
    PresentationInput,
    QaStatus,
)
from signals.persistence.schema import card_presentation_artifact, materialized_signal


class ForeignOrStalePresentationInput(LookupError):
    """The signal is not owned by this account, or its bound revision is stale."""


class PresentationPublicationConflict(RuntimeError):
    pass


def _artifact_id(source: PresentationInput, kind: ArtifactKind, version: int) -> str:
    material = (
        f"card-presentation-v1\0{source.account_id}\0{source.signal_key}\0"
        f"{source.target_icp_id}\0{kind.value}\0{source.language}\0{version}\0"
        f"{source.fingerprint()}"
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _assert_current_owned_signal(connection: Connection, source: PresentationInput) -> None:
    row = connection.execute(
        sa.select(
            materialized_signal.c.revision,
            materialized_signal.c.target_icp_revision,
            materialized_signal.c.target_icp_id,
        )
        .select_from(
            target_icp.join(
                materialized_signal,
                target_icp.c.target_icp_id == materialized_signal.c.target_icp_id,
            )
        )
        .where(
            target_icp.c.account_id == source.account_id,
            target_icp.c.target_icp_id == source.target_icp_id,
            materialized_signal.c.signal_key == source.signal_key,
            materialized_signal.c.invalidated_at.is_(None),
        )
    ).mappings().one_or_none()
    if row is None or (
        row["revision"] != source.signal_revision
        or row["target_icp_revision"] != source.target_icp_revision
        or row["target_icp_id"] != source.target_icp_id
    ):
        raise ForeignOrStalePresentationInput(source.signal_key)


def _next_version(
    connection: Connection, source: PresentationInput, kind: ArtifactKind
) -> int:
    current = connection.scalar(
        sa.select(sa.func.max(card_presentation_artifact.c.version)).where(
            card_presentation_artifact.c.account_id == source.account_id,
            card_presentation_artifact.c.signal_key == source.signal_key,
            card_presentation_artifact.c.target_icp_id == source.target_icp_id,
            card_presentation_artifact.c.artifact_kind == kind.value,
            card_presentation_artifact.c.language == source.language,
        )
    )
    return int(current or 0) + 1


def append_attempt(
    connection: Connection,
    *,
    source: PresentationInput,
    kind: ArtifactKind,
    payload: CardPresentationPayload | None,
    qa_status: QaStatus,
    qa_reasons: Sequence[str],
    prompt_version: str,
    model_id: str | None,
    provider: str | None,
    qa_model_id: str | None,
    qa_provider: str | None,
    qa_policy_version: str,
    created_at: dt.datetime,
    publish: bool,
) -> Mapping[str, object]:
    """Append one immutable content version and optionally move publication."""
    if publish and qa_status not in (QaStatus.PASS, QaStatus.FALLBACK):
        raise PresentationPublicationConflict(f"{qa_status.value} is not publishable")
    if publish and payload is None:
        raise PresentationPublicationConflict("a published artifact requires content")
    _assert_current_owned_signal(connection, source)
    version = _next_version(connection, source, kind)
    artifact_id = _artifact_id(source, kind, version)
    values = {
        "artifact_id": artifact_id,
        "account_id": source.account_id,
        "signal_key": source.signal_key,
        "target_icp_id": source.target_icp_id,
        "artifact_kind": kind.value,
        "language": source.language,
        "version": version,
        "signal_revision": source.signal_revision,
        "target_icp_revision": source.target_icp_revision,
        "input_fingerprint": source.fingerprint(),
        "schema_version": (
            payload.schema_version if payload is not None else "card-presentation-v1"
        ),
        "prompt_version": prompt_version,
        "model_id": model_id,
        "provider": provider,
        "input_snapshot": source.model_dump(mode="json"),
        "payload": payload.model_dump(mode="json") if payload is not None else None,
        "qa_status": qa_status.value,
        "qa_reasons": list(qa_reasons),
        "qa_model_id": qa_model_id,
        "qa_provider": qa_provider,
        "qa_policy_version": qa_policy_version,
        "created_at": created_at,
        "published_at": created_at if publish else None,
        "superseded_at": None,
    }
    if publish:
        connection.execute(
            sa.update(card_presentation_artifact)
            .where(
                card_presentation_artifact.c.account_id == source.account_id,
                card_presentation_artifact.c.signal_key == source.signal_key,
                card_presentation_artifact.c.target_icp_id == source.target_icp_id,
                card_presentation_artifact.c.artifact_kind == kind.value,
                card_presentation_artifact.c.language == source.language,
                card_presentation_artifact.c.published_at.is_not(None),
                card_presentation_artifact.c.superseded_at.is_(None),
            )
            .values(superseded_at=created_at)
        )
    connection.execute(sa.insert(card_presentation_artifact).values(**values))
    return connection.execute(
        sa.select(card_presentation_artifact).where(
            card_presentation_artifact.c.artifact_id == artifact_id
        )
    ).mappings().one()


def _public_contract(row: Mapping[str, object]) -> dict[str, object]:
    published_at = row["published_at"]
    payload = row["payload"]
    assert isinstance(published_at, dt.datetime)
    assert isinstance(payload, dict)
    return {
        "artifact_id": row["artifact_id"],
        "schema_version": row["schema_version"],
        "version": row["version"],
        "status": row["qa_status"],
        "published_at": published_at.isoformat(),
        "content": payload,
    }


def published_for_signals(
    connection: Connection,
    *,
    account_id: str,
    bindings: Mapping[str, tuple[int, int]],
    language: str,
    kind: ArtifactKind = ArtifactKind.SIGNAL_CARD,
) -> dict[str, dict[str, object]]:
    """One batch read, restricted to current revisions and this exact tenant."""
    if not bindings:
        return {}
    rows = connection.execute(
        sa.select(card_presentation_artifact)
        .where(
            card_presentation_artifact.c.account_id == account_id,
            card_presentation_artifact.c.signal_key.in_(sorted(bindings)),
            card_presentation_artifact.c.artifact_kind == kind.value,
            card_presentation_artifact.c.language == language,
            card_presentation_artifact.c.qa_status.in_((QaStatus.PASS.value, QaStatus.FALLBACK.value)),
            card_presentation_artifact.c.published_at.is_not(None),
            card_presentation_artifact.c.superseded_at.is_(None),
        )
        .order_by(card_presentation_artifact.c.version.desc())
    ).mappings()
    published: dict[str, dict[str, object]] = {}
    for row in rows:
        expected = bindings.get(str(row["signal_key"]))
        if expected != (row["signal_revision"], row["target_icp_revision"]):
            continue
        published.setdefault(str(row["signal_key"]), _public_contract(row))
    return published


def current_publication_row(
    connection: Connection,
    *,
    source: PresentationInput,
    kind: ArtifactKind = ArtifactKind.SIGNAL_CARD,
) -> Mapping[str, object] | None:
    rows = connection.execute(
        sa.select(card_presentation_artifact)
        .where(
            card_presentation_artifact.c.account_id == source.account_id,
            card_presentation_artifact.c.signal_key == source.signal_key,
            card_presentation_artifact.c.target_icp_id == source.target_icp_id,
            card_presentation_artifact.c.artifact_kind == kind.value,
            card_presentation_artifact.c.language == source.language,
            card_presentation_artifact.c.signal_revision == source.signal_revision,
            card_presentation_artifact.c.target_icp_revision == source.target_icp_revision,
            card_presentation_artifact.c.published_at.is_not(None),
            card_presentation_artifact.c.superseded_at.is_(None),
        )
        .order_by(card_presentation_artifact.c.version.desc())
    ).mappings().first()
    return rows
