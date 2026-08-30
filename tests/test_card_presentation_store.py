from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from feed_helpers import (
    BOAMP_AGING,
    BOAMP_PUBLICATION_ONLY,
    make_account,
    make_icp,
    materialize_boamp,
)
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from signals.accounts.schema import target_icp
from signals.card_intelligence.contracts import (
    CardPresentationPayload,
    ClaimKind,
    PresentationClaim,
    PresentationInput,
    PresentationVariant,
    PublishedCardPresentation,
    TargetRole,
    TargetRoleKind,
)
from signals.card_intelligence.fallback import factual_fallback
from signals.card_intelligence.input import build_presentation_input
from signals.card_intelligence.store import (
    AttemptMetadata,
    PresentationPublicationConflict,
    _locked_signal_statement,
    append_attempt,
    published_artifact_for_signal,
    published_for_signals,
)
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import (
    card_presentation_artifact,
    contract_award,
    materialized_signal,
)
from signals.qa_signals.contracts import QaStatus

NOW = dt.datetime(2026, 8, 30, 10, 0, tzinfo=dt.UTC)
REASONS = ("deterministic_factual_fallback",)


@dataclass(frozen=True)
class PersistedCase:
    account_id: str
    other_account_id: str
    target_icp_id: str
    signal_key: str
    award_key: str


@pytest.fixture
def engine(tmp_path) -> sa.Engine:
    database = create_database_engine(
        f"sqlite+pysqlite:///{tmp_path / 'card-presentation-store.db'}"
    )
    migrate_to_latest(database)
    return database


@pytest.fixture
def persisted_case(engine: sa.Engine) -> PersistedCase:
    with engine.begin() as connection:
        account_id = make_account(connection, "alice-store@test.invalid", "Alice Matériaux")
        other_account_id = make_account(connection, "bob-store@test.invalid", "Bob Matériaux")
        target_icp_id = make_icp(connection, account_id, label="Intrants France")
        signal = materialize_boamp(
            connection,
            BOAMP_AGING,
            target_icp_id=target_icp_id,
        )
    return PersistedCase(
        account_id=account_id,
        other_account_id=other_account_id,
        target_icp_id=target_icp_id,
        signal_key=signal.signal_key,
        award_key=signal.materialization_award_key,
    )


@pytest.fixture
def source(engine: sa.Engine, persisted_case: PersistedCase) -> PresentationInput:
    with engine.connect() as connection:
        return build_presentation_input(
            connection,
            account_id=persisted_case.account_id,
            signal_key=persisted_case.signal_key,
            language="fr",
        )


@pytest.fixture
def fallback(source: PresentationInput) -> CardPresentationPayload:
    return factual_fallback(source)


@pytest.fixture
def metadata() -> AttemptMetadata:
    return AttemptMetadata(
        generator_version="factual-fallback-v1",
        qa_policy_version="factual-qa-v1",
    )


def _publish(
    connection: sa.Connection,
    *,
    source: PresentationInput,
    payload: CardPresentationPayload,
    metadata: AttemptMetadata,
    created_at: dt.datetime = NOW,
) -> dict[str, object]:
    return dict(
        append_attempt(
            connection,
            source=source,
            payload=payload,
            qa_status=QaStatus.FALLBACK,
            qa_reasons=REASONS,
            metadata=metadata,
            created_at=created_at,
            publish=True,
        )
    )


def _binding(source: PresentationInput) -> tuple[int, int]:
    return source.signal_revision, source.target_icp_revision


def _current(
    connection: sa.Connection,
    source: PresentationInput,
) -> PublishedCardPresentation | None:
    return published_for_signals(
        connection,
        account_id=source.account_id,
        bindings={source.signal_key: _binding(source)},
        language=source.language,
    ).get(source.signal_key)


def _full_payload(source: PresentationInput) -> CardPresentationPayload:
    awardee_ref = next(
        ref for ref in source.facts.evidence_refs if ref.endswith(":awardee_parties")
    )
    buyer_ref = next(
        ref for ref in source.facts.evidence_refs if ref.endswith(":procedure_buyers")
    )
    publication_ref = next(
        ref for ref in source.facts.evidence_refs if ref.endswith(":published_on")
    )
    headline = f"Attribution publiée pour {source.facts.winner_name}"
    summary = (
        f"Acheteur publié : {source.facts.buyer_name}. "
        f"Attributaire publié : {source.facts.winner_name}."
    )
    importance = "Les matériaux correspondent au profil déclaré."
    fit = "Le besoin en matériaux correspond au ciblage courant."
    timing = "Suivre la date de publication du marché."
    action = "Contacter le responsable achats au sujet des matériaux."
    return CardPresentationPayload(
        variant=PresentationVariant.FULL,
        headline=headline,
        award_summary=summary,
        commercial_importance=importance,
        fit_reason=fit,
        timing=timing,
        recommended_action=action,
        target_roles=(
            TargetRole(
                role=TargetRoleKind.PROCUREMENT_MANAGER,
                rationale="Le responsable achats traite les matériaux.",
                evidence_refs=(awardee_ref,),
            ),
        ),
        fit_need_categories=("materials_or_components",),
        claims=(
            PresentationClaim(
                claim_id="FACT_HEADLINE",
                kind=ClaimKind.FACT,
                text=headline,
                evidence_refs=(awardee_ref,),
            ),
            PresentationClaim(
                claim_id="FACT_SUMMARY",
                kind=ClaimKind.FACT,
                text=summary,
                evidence_refs=(awardee_ref, buyer_ref),
            ),
            PresentationClaim(
                claim_id="INFERENCE_IMPORTANCE",
                kind=ClaimKind.INFERENCE,
                text=importance,
                evidence_refs=(awardee_ref,),
                confidence="medium",
            ),
            PresentationClaim(
                claim_id="INFERENCE_FIT",
                kind=ClaimKind.INFERENCE,
                text=fit,
                evidence_refs=(awardee_ref,),
                confidence="medium",
            ),
            PresentationClaim(
                claim_id="INFERENCE_TIMING",
                kind=ClaimKind.INFERENCE,
                text=timing,
                evidence_refs=(publication_ref,),
                confidence="low",
            ),
            PresentationClaim(
                claim_id="RECOMMENDED_ACTION",
                kind=ClaimKind.RECOMMENDATION,
                text=action,
                evidence_refs=(awardee_ref,),
            ),
        ),
    )


@contextmanager
def _ignore_sqlite_checks(connection: sa.Connection) -> Iterator[None]:
    connection.exec_driver_sql("PRAGMA ignore_check_constraints = ON")
    try:
        yield
    finally:
        connection.exec_driver_sql("PRAGMA ignore_check_constraints = OFF")


def test_valid_factual_attempt_is_published_and_read_as_one_immutable_contract(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
) -> None:
    with engine.begin() as connection:
        stored = _publish(
            connection,
            source=source,
            payload=fallback,
            metadata=metadata,
        )
        current = _current(connection, source)

    assert stored["version"] == 1
    assert stored["qa_status"] == "FALLBACK"
    assert stored["qa_policy_version"] == "factual-qa-v1"
    assert current == PublishedCardPresentation(
        artifact_id=stored["artifact_id"],
        version=1,
        status="FALLBACK",
        schema_version="card-presentation-v1",
        published_at=NOW,
        content=fallback,
    )
    with pytest.raises(ValidationError):
        current.content.headline = "rewrite"  # type: ignore[misc,union-attr]


def test_replacement_is_monotonic_supersedes_only_the_old_active_row_and_remains_pinnable(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
) -> None:
    with engine.begin() as connection:
        first = _publish(connection, source=source, payload=fallback, metadata=metadata)
        before = dict(
            connection.execute(
                sa.select(card_presentation_artifact).where(
                    card_presentation_artifact.c.artifact_id == first["artifact_id"]
                )
            ).mappings().one()
        )
        second = _publish(
            connection,
            source=source,
            payload=fallback,
            metadata=metadata,
            created_at=NOW + dt.timedelta(seconds=1),
        )
        after = dict(
            connection.execute(
                sa.select(card_presentation_artifact).where(
                    card_presentation_artifact.c.artifact_id == first["artifact_id"]
                )
            ).mappings().one()
        )
        current = _current(connection, source)
        pinned = published_artifact_for_signal(
            connection,
            account_id=source.account_id,
            signal_key=source.signal_key,
            binding=_binding(source),
            language=source.language,
            artifact_id=str(first["artifact_id"]),
        )

    assert first["version"] == 1
    assert second["version"] == 2
    assert current is not None and current.artifact_id == second["artifact_id"]
    assert pinned is not None and pinned.artifact_id == first["artifact_id"]
    assert pinned.content == fallback
    mutable = {"superseded_at"}
    assert {key: value for key, value in before.items() if key not in mutable} == {
        key: value for key, value in after.items() if key not in mutable
    }
    assert after["superseded_at"] is not None


def test_private_attempts_consume_versions_without_crossing_the_read_boundary(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
) -> None:
    full = _full_payload(source)
    with engine.begin() as connection:
        first = _publish(connection, source=source, payload=fallback, metadata=metadata)
        review = append_attempt(
            connection,
            source=source,
            payload=full,
            qa_status=QaStatus.REVIEW,
            qa_reasons=("full_variant_not_authorized",),
            metadata=AttemptMetadata(
                generator_version="candidate-v1",
                qa_policy_version="qa-v1",
                provider="provider-id",
                model_id="org/model-v1",
                prompt_version="prompt-v1",
            ),
            created_at=NOW + dt.timedelta(seconds=1),
            publish=False,
        )
        third = _publish(
            connection,
            source=source,
            payload=fallback,
            metadata=metadata,
            created_at=NOW + dt.timedelta(seconds=2),
        )
        current = _current(connection, source)

    assert first["version"] == 1
    assert review["version"] == 2
    assert review["published_at"] is None
    assert third["version"] == 3
    assert current is not None and current.artifact_id == third["artifact_id"]


@pytest.mark.parametrize("status", (QaStatus.REVIEW, QaStatus.REGENERATE))
def test_review_and_regenerate_can_never_be_published(
    engine: sa.Engine,
    source: PresentationInput,
    metadata: AttemptMetadata,
    status: QaStatus,
) -> None:
    with engine.begin() as connection, pytest.raises(
        PresentationPublicationConflict,
        match="card presentation publication conflict",
    ):
        append_attempt(
            connection,
            source=source,
            payload=_full_payload(source),
            qa_status=status,
            qa_reasons=("private_only",),
            metadata=metadata,
            created_at=NOW,
            publish=True,
        )


def test_full_pass_remains_private_until_the_generation_stack_is_authorized(
    engine: sa.Engine,
    source: PresentationInput,
) -> None:
    with engine.begin() as connection, pytest.raises(
        PresentationPublicationConflict,
        match="card presentation publication conflict",
    ):
        append_attempt(
            connection,
            source=source,
            payload=_full_payload(source),
            qa_status=QaStatus.PASS,
            qa_reasons=("qa_pass",),
            metadata=AttemptMetadata(
                generator_version="candidate-v1",
                qa_policy_version="qa-v1",
                provider="provider-id",
                model_id="org/model-v1",
                prompt_version="prompt-v1",
                qa_provider="qa-provider-id",
                qa_model_id="org/qa-model-v1",
            ),
            created_at=NOW,
            publish=True,
        )


@pytest.mark.parametrize(
    ("status", "payload_factory"),
    (
        (QaStatus.PASS, lambda source, fallback: fallback),
        (QaStatus.FALLBACK, lambda source, fallback: _full_payload(source)),
    ),
    ids=("pass-fallback", "fallback-full"),
)
def test_status_and_variant_pairs_are_exact_even_for_private_attempts(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
    status: QaStatus,
    payload_factory,
) -> None:
    with engine.begin() as connection, pytest.raises(PresentationPublicationConflict):
        append_attempt(
            connection,
            source=source,
            payload=payload_factory(source, fallback),
            qa_status=status,
            qa_reasons=("wrong_pair",),
            metadata=metadata,
            created_at=NOW,
            publish=False,
        )


def test_invalid_attempt_cannot_supersede_current(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
) -> None:
    forged = fallback.model_copy(update={"variant": PresentationVariant.FULL})
    with engine.begin() as connection:
        first = _publish(connection, source=source, payload=fallback, metadata=metadata)
        with pytest.raises(PresentationPublicationConflict):
            append_attempt(
                connection,
                source=source,
                payload=forged,
                qa_status=QaStatus.PASS,
                qa_reasons=("forged",),
                metadata=metadata,
                created_at=NOW + dt.timedelta(seconds=1),
                publish=True,
            )
        current = _current(connection, source)
        count = connection.scalar(sa.select(sa.func.count()).select_from(card_presentation_artifact))

    assert current is not None and current.artifact_id == first["artifact_id"]
    assert count == 1


def test_integrity_failure_rolls_back_supersession_and_becomes_a_stable_conflict(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
) -> None:
    with engine.begin() as connection:
        first = _publish(connection, source=source, payload=fallback, metadata=metadata)
        connection.exec_driver_sql(
            "CREATE TRIGGER fail_second_card_artifact "
            "BEFORE INSERT ON card_presentation_artifact "
            "WHEN NEW.version = 2 BEGIN SELECT RAISE(ABORT, 'forced conflict'); END"
        )
        with pytest.raises(
            PresentationPublicationConflict,
            match="card presentation publication conflict",
        ):
            _publish(
                connection,
                source=source,
                payload=fallback,
                metadata=metadata,
                created_at=NOW + dt.timedelta(seconds=1),
            )
        old = connection.execute(
            sa.select(card_presentation_artifact).where(
                card_presentation_artifact.c.artifact_id == first["artifact_id"]
            )
        ).mappings().one()

    assert old["superseded_at"] is None


def test_database_rejects_two_active_publications_in_the_same_stream(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
) -> None:
    with engine.begin() as connection:
        _publish(connection, source=source, payload=fallback, metadata=metadata)
        duplicate = dict(
            connection.execute(sa.select(card_presentation_artifact)).mappings().one()
        )
        duplicate.update(
            artifact_id="f" * 64,
            version=2,
            input_fingerprint="e" * 64,
        )
        with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
            connection.execute(sa.insert(card_presentation_artifact).values(**duplicate))


@pytest.mark.parametrize(
    "mutation",
    (
        {"revision": 2},
        {"invalidated_at": NOW, "invalidation_reason": "icp_updated"},
    ),
    ids=("stale-signal", "invalidated-signal"),
)
def test_publication_and_reads_fail_closed_for_a_noncurrent_signal(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
    mutation: dict[str, object],
) -> None:
    with engine.begin() as connection:
        first = _publish(connection, source=source, payload=fallback, metadata=metadata)
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == source.signal_key)
            .values(**mutation)
        )
        with pytest.raises(PresentationPublicationConflict):
            _publish(
                connection,
                source=source,
                payload=fallback,
                metadata=metadata,
                created_at=NOW + dt.timedelta(seconds=1),
            )
        assert _current(connection, source) is None
        assert (
            published_artifact_for_signal(
                connection,
                account_id=source.account_id,
                signal_key=source.signal_key,
                binding=_binding(source),
                language=source.language,
                artifact_id=str(first["artifact_id"]),
            )
            is None
        )


@pytest.mark.parametrize(
    "mutation",
    (
        {"matching_revision": 2},
        {"status": "draft"},
        {"plan_limit_code": "territory_limit_exceeded", "plan_limited_at": NOW},
    ),
    ids=("stale-icp", "inactive-icp", "limited-icp"),
)
def test_publication_and_reads_fail_closed_for_a_noncurrent_icp(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
    mutation: dict[str, object],
) -> None:
    with engine.begin() as connection:
        first = _publish(connection, source=source, payload=fallback, metadata=metadata)
        connection.execute(
            sa.update(target_icp)
            .where(target_icp.c.target_icp_id == source.target_icp_id)
            .values(**mutation)
        )
        with pytest.raises(PresentationPublicationConflict):
            _publish(
                connection,
                source=source,
                payload=fallback,
                metadata=metadata,
                created_at=NOW + dt.timedelta(seconds=1),
            )
        assert _current(connection, source) is None
        assert (
            published_artifact_for_signal(
                connection,
                account_id=source.account_id,
                signal_key=source.signal_key,
                binding=_binding(source),
                language=source.language,
                artifact_id=str(first["artifact_id"]),
            )
            is None
        )


def test_changed_source_award_binding_after_capture_fails_before_supersession(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
) -> None:
    with engine.begin() as connection:
        first = _publish(connection, source=source, payload=fallback, metadata=metadata)
        other = materialize_boamp(
            connection,
            BOAMP_PUBLICATION_ONLY,
            target_icp_id=source.target_icp_id,
        )
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == source.signal_key)
            .values(materialization_award_key=other.materialization_award_key)
        )
        with pytest.raises(PresentationPublicationConflict):
            _publish(
                connection,
                source=source,
                payload=fallback,
                metadata=metadata,
                created_at=NOW + dt.timedelta(seconds=1),
            )
        old = connection.execute(
            sa.select(card_presentation_artifact.c.superseded_at).where(
                card_presentation_artifact.c.artifact_id == first["artifact_id"]
            )
        ).scalar_one()

    assert old is None


def test_changed_source_event_binding_after_capture_fails_before_supersession(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
) -> None:
    with engine.begin() as connection:
        first = _publish(connection, source=source, payload=fallback, metadata=metadata)
        other = materialize_boamp(
            connection,
            BOAMP_PUBLICATION_ONLY,
            target_icp_id=source.target_icp_id,
        )
        other_event_key = connection.scalar(
            sa.select(contract_award.c.event_key).where(
                contract_award.c.award_key == other.materialization_award_key
            )
        )
        award_key = connection.scalar(
            sa.select(materialized_signal.c.materialization_award_key).where(
                materialized_signal.c.signal_key == source.signal_key
            )
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == award_key)
            .values(event_key=other_event_key)
        )
        with pytest.raises(PresentationPublicationConflict):
            _publish(
                connection,
                source=source,
                payload=fallback,
                metadata=metadata,
                created_at=NOW + dt.timedelta(seconds=1),
            )
        old = connection.scalar(
            sa.select(card_presentation_artifact.c.superseded_at).where(
                card_presentation_artifact.c.artifact_id == first["artifact_id"]
            )
        )

    assert old is None


def test_tenant_language_binding_and_missing_pin_never_leak_an_artifact(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
    persisted_case: PersistedCase,
) -> None:
    with engine.begin() as connection:
        stored = _publish(connection, source=source, payload=fallback, metadata=metadata)
        assert published_for_signals(
            connection,
            account_id=persisted_case.other_account_id,
            bindings={source.signal_key: _binding(source)},
            language="fr",
        ) == {}
        for account_id, language, artifact_id in (
            (persisted_case.other_account_id, "fr", str(stored["artifact_id"])),
            (source.account_id, "en", str(stored["artifact_id"])),
            (source.account_id, "fr", "0" * 64),
        ):
            assert (
                published_artifact_for_signal(
                    connection,
                    account_id=account_id,
                    signal_key=source.signal_key,
                    binding=_binding(source),
                    language=language,
                    artifact_id=artifact_id,
                )
                is None
            )


@pytest.mark.parametrize(
    "corruption",
    (
        "malformed-payload",
        "null-payload",
        "extra-payload-key",
        "status-variant-mismatch",
        "malformed-reasons",
        "input-fingerprint-mismatch",
        "artifact-id-mismatch",
    ),
)
def test_batch_and_pinned_reads_omit_corrupt_persisted_artifacts(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
    corruption: str,
) -> None:
    with engine.begin() as connection:
        stored = _publish(connection, source=source, payload=fallback, metadata=metadata)
        artifact_id = str(stored["artifact_id"])
        if corruption == "malformed-payload":
            connection.exec_driver_sql(
                "UPDATE card_presentation_artifact SET payload = ? WHERE artifact_id = ?",
                ("{", artifact_id),
            )
        elif corruption == "null-payload":
            with _ignore_sqlite_checks(connection):
                connection.exec_driver_sql(
                    "UPDATE card_presentation_artifact SET payload = NULL WHERE artifact_id = ?",
                    (artifact_id,),
                )
        elif corruption == "extra-payload-key":
            payload = fallback.model_dump(mode="json")
            payload["unexpected"] = True
            connection.exec_driver_sql(
                "UPDATE card_presentation_artifact SET payload = ? WHERE artifact_id = ?",
                (json.dumps(payload), artifact_id),
            )
        elif corruption == "status-variant-mismatch":
            with _ignore_sqlite_checks(connection):
                connection.execute(
                    sa.update(card_presentation_artifact)
                    .where(card_presentation_artifact.c.artifact_id == artifact_id)
                    .values(qa_status="PASS", payload_variant="FULL")
                )
        elif corruption == "malformed-reasons":
            connection.exec_driver_sql(
                "UPDATE card_presentation_artifact SET qa_reasons = ? WHERE artifact_id = ?",
                ("{", artifact_id),
            )
        elif corruption == "input-fingerprint-mismatch":
            connection.execute(
                sa.update(card_presentation_artifact)
                .where(card_presentation_artifact.c.artifact_id == artifact_id)
                .values(input_fingerprint="0" * 64)
            )
        else:
            connection.execute(
                sa.update(card_presentation_artifact)
                .where(card_presentation_artifact.c.artifact_id == artifact_id)
                .values(artifact_id="f" * 64)
            )

        assert _current(connection, source) is None
        assert (
            published_artifact_for_signal(
                connection,
                account_id=source.account_id,
                signal_key=source.signal_key,
                binding=_binding(source),
                language=source.language,
                artifact_id=artifact_id,
            )
            is None
        )


def test_duplicate_active_rows_are_omitted_if_storage_is_corrupt(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
) -> None:
    with engine.begin() as connection:
        _publish(connection, source=source, payload=fallback, metadata=metadata)
        original = dict(
            connection.execute(sa.select(card_presentation_artifact)).mappings().one()
        )
        connection.exec_driver_sql("DROP INDEX uq_card_presentation_active_publication")
        duplicate = dict(original)
        duplicate.update(artifact_id="d" * 64, version=2)
        connection.execute(sa.insert(card_presentation_artifact).values(**duplicate))

        assert _current(connection, source) is None


def test_batch_reader_uses_one_account_scoped_artifact_select_for_multiple_signals(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
) -> None:
    with engine.begin() as connection:
        second_signal = materialize_boamp(
            connection,
            BOAMP_PUBLICATION_ONLY,
            target_icp_id=source.target_icp_id,
        )
        second_source = build_presentation_input(
            connection,
            account_id=source.account_id,
            signal_key=second_signal.signal_key,
            language="fr",
        )
        _publish(connection, source=source, payload=fallback, metadata=metadata)
        _publish(
            connection,
            source=second_source,
            payload=factual_fallback(second_source),
            metadata=metadata,
        )

    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    sa.event.listen(engine, "before_cursor_execute", capture)
    try:
        with engine.connect() as connection:
            presentations = published_for_signals(
                connection,
                account_id=source.account_id,
                bindings={
                    source.signal_key: _binding(source),
                    second_source.signal_key: _binding(second_source),
                },
                language="fr",
            )
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)

    artifact_selects = [sql for sql in statements if "card_presentation_artifact" in sql]
    assert set(presentations) == {source.signal_key, second_source.signal_key}
    assert len(artifact_selects) == 1
    assert "target_icp.account_id" in artifact_selects[0]
    assert "materialized_signal.invalidated_at IS NULL" in artifact_selects[0]


def test_fallback_provider_or_model_metadata_is_rejected_before_insert(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
) -> None:
    for field in (
        "provider",
        "model_id",
        "prompt_version",
        "qa_provider",
        "qa_model_id",
    ):
        metadata = AttemptMetadata(
            generator_version="factual-fallback-v1",
            qa_policy_version="factual-qa-v1",
            **{field: "forbidden-id"},
        )
        with engine.begin() as connection, pytest.raises(PresentationPublicationConflict):
            _publish(connection, source=source, payload=fallback, metadata=metadata)
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(card_presentation_artifact)
        ) == 0


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("generator_version", "   "),
        ("qa_policy_version", "-_."),
        ("provider", "https://provider.invalid/key"),
        ("model_id", "secret value"),
        ("prompt_version", "prompt?token=secret"),
    ),
)
def test_attempt_metadata_accepts_only_bounded_nonsecret_identifiers(
    field: str,
    value: str,
) -> None:
    values = {
        "generator_version": "generator-v1",
        "qa_policy_version": "qa-v1",
        field: value,
    }
    with pytest.raises(ValidationError):
        AttemptMetadata(**values)


@pytest.mark.parametrize(
    "created_at",
    (NOW.replace(tzinfo=None), "2026-08-30T10:00:00Z"),
)
def test_append_revalidates_timestamps_without_coercion(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
    created_at,
) -> None:
    with engine.begin() as connection, pytest.raises(PresentationPublicationConflict):
        append_attempt(
            connection,
            source=source,
            payload=fallback,
            qa_status=QaStatus.FALLBACK,
            qa_reasons=REASONS,
            metadata=metadata,
            created_at=created_at,
            publish=True,
        )


def test_append_rejects_a_truthy_non_boolean_publish_flag(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
) -> None:
    with engine.begin() as connection, pytest.raises(PresentationPublicationConflict):
        append_attempt(
            connection,
            source=source,
            payload=fallback,
            qa_status=QaStatus.FALLBACK,
            qa_reasons=REASONS,
            metadata=metadata,
            created_at=NOW,
            publish="false",  # type: ignore[arg-type]
        )
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(card_presentation_artifact)
        ) == 0


def test_append_recursively_revalidates_forged_source_payload_decision_and_metadata(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
) -> None:
    cases = (
        {
            "source": source.model_copy(update={"language": "de"}),
            "payload": fallback,
            "qa_status": QaStatus.FALLBACK,
            "qa_reasons": REASONS,
            "metadata": metadata,
        },
        {
            "source": source,
            "payload": fallback.model_copy(update={"schema_version": "future"}),
            "qa_status": QaStatus.FALLBACK,
            "qa_reasons": REASONS,
            "metadata": metadata,
        },
        {
            "source": source,
            "payload": fallback,
            "qa_status": "UNKNOWN",
            "qa_reasons": REASONS,
            "metadata": metadata,
        },
        {
            "source": source,
            "payload": fallback,
            "qa_status": QaStatus.FALLBACK,
            "qa_reasons": ("x" * 161,),
            "metadata": metadata,
        },
        {
            "source": source,
            "payload": fallback,
            "qa_status": QaStatus.FALLBACK,
            "qa_reasons": REASONS,
            "metadata": metadata.model_copy(update={"generator_version": " "}),
        },
    )
    for values in cases:
        with engine.begin() as connection, pytest.raises(PresentationPublicationConflict):
            append_attempt(
                connection,
                **values,
                created_at=NOW,
                publish=True,
            )
    with engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count()).select_from(card_presentation_artifact)
        ) == 0


def test_postgresql_publication_lock_compiles_as_select_for_update(
    source: PresentationInput,
) -> None:
    sql = str(
        _locked_signal_statement(source).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).upper()
    assert "SELECT" in sql
    assert "MATERIALIZED_SIGNAL" in sql
    assert "TARGET_ICP.ACCOUNT_ID" in sql
    assert "FOR UPDATE OF MATERIALIZED_SIGNAL" in sql


def test_unexpected_sqlalchemy_errors_are_not_hidden(
    engine: sa.Engine,
    source: PresentationInput,
    fallback: CardPresentationPayload,
    metadata: AttemptMetadata,
) -> None:
    connection = engine.connect()
    connection.close()
    with pytest.raises(sa.exc.ResourceClosedError):
        _publish(connection, source=source, payload=fallback, metadata=metadata)
    with pytest.raises(sa.exc.ResourceClosedError):
        published_for_signals(
            connection,
            account_id=source.account_id,
            bindings={source.signal_key: _binding(source)},
            language="fr",
        )
