from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pytest
import sqlalchemy as sa
from feed_helpers import (
    BOAMP_AGING,
    make_account,
    make_icp,
    materialize_boamp,
)

from signals.card_intelligence.contracts import (
    CardPresentationPayload,
    ClaimKind,
    GenerationResponse,
    PresentationClaim,
    PresentationInput,
    PresentationVariant,
    TargetRole,
    TargetRoleKind,
)
from signals.card_intelligence.fallback import factual_fallback
from signals.card_intelligence.input import build_presentation_input
from signals.card_intelligence.service import (
    FACTUAL_GENERATOR_VERSION,
    FACTUAL_QA_POLICY_VERSION,
    MAX_CANDIDATE_ATTEMPTS,
    publish_factual_fallback,
    run_offline_candidate_pipeline,
)
from signals.card_intelligence.validation import validate_payload
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import (
    card_presentation_artifact,
    contract_award,
    materialized_signal,
    source_event,
)
from signals.qa_signals.contracts import QaDecision, QaStatus

NOW = dt.datetime(2026, 8, 30, 12, 0, tzinfo=dt.UTC)


@dataclass(frozen=True)
class PersistedCase:
    account_id: str
    target_icp_id: str
    signal_key: str
    award_key: str


@pytest.fixture
def engine(tmp_path) -> sa.Engine:
    database = create_database_engine(
        f"sqlite+pysqlite:///{tmp_path / 'card-intelligence-service.db'}"
    )
    migrate_to_latest(database)
    return database


@pytest.fixture
def persisted_case(engine: sa.Engine) -> PersistedCase:
    with engine.begin() as connection:
        account_id = make_account(
            connection,
            "offline-card-service@test.invalid",
            "Kivou Matériaux",
        )
        target_icp_id = make_icp(connection, account_id, label="Intrants France")
        signal = materialize_boamp(
            connection,
            BOAMP_AGING,
            target_icp_id=target_icp_id,
        )
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == signal.signal_key)
            .values(icp_matched_needs=["materials_or_components"])
        )
    return PersistedCase(
        account_id=account_id,
        target_icp_id=target_icp_id,
        signal_key=signal.signal_key,
        award_key=signal.materialization_award_key,
    )


def _build(
    engine: sa.Engine,
    case: PersistedCase,
    *,
    language: str = "fr",
    signal_key: str | None = None,
) -> PresentationInput:
    with engine.connect() as connection:
        return build_presentation_input(
            connection,
            account_id=case.account_id,
            signal_key=signal_key or case.signal_key,
            language=language,
        )


@pytest.fixture
def source(engine: sa.Engine, persisted_case: PersistedCase) -> PresentationInput:
    return _build(engine, persisted_case)


def _field_ref(source: PresentationInput, column: str) -> str:
    return next(ref for ref in source.facts.evidence_refs if ref.endswith(f":{column}"))


def _full_payload(source: PresentationInput) -> CardPresentationPayload:
    awardee_ref = _field_ref(source, "awardee_parties")
    buyer_ref = _field_ref(source, "procedure_buyers")
    publication_ref = _field_ref(source, "published_on")
    headline = f"Attribution publiée pour {source.facts.winner_name}."
    buyer = source.facts.buyer_name or "Acheteur non publié"
    summary = f"Acheteur : {buyer}. Attributaire : {source.facts.winner_name}."
    importance = "Les matériaux représentent une opportunité commerciale à examiner."
    fit = "L'adéquation concerne le besoin ICP de matériaux."
    timing = "Le calendrier commercial reste à vérifier."
    action = "Examiner le besoin de matériaux avec la fonction achats."
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
                rationale="Le besoin de matériaux relève de la fonction achats.",
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
                claim_id="FACT_AWARD_CONTEXT",
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
                claim_id="RECOMMENDATION_ACTION",
                kind=ClaimKind.RECOMMENDATION,
                text=action,
                evidence_refs=(awardee_ref,),
            ),
        ),
    )


def _replace_public_text(
    payload: CardPresentationPayload,
    field_name: str,
    text: str,
) -> CardPresentationPayload:
    data = payload.model_dump(mode="python")
    previous = data[field_name]
    data[field_name] = text
    for claim in data["claims"]:
        if claim["text"] == previous:
            claim["text"] = text
            break
    return CardPresentationPayload.model_validate(data)


def _rows(connection: sa.Connection) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in connection.execute(
            sa.select(card_presentation_artifact).order_by(
                card_presentation_artifact.c.version
            )
        ).mappings()
    ]


@dataclass
class FakeGenerator:
    responses: list[object]
    provider: object = "offline-generator"
    model_id: object = "org/card-model-v1"
    prompt_version: object = "card-prompt-v1"
    generator_version: object = "offline-generator-v1"
    calls: list[tuple[PresentationInput, int]] = field(default_factory=list)

    def generate(self, source: PresentationInput, *, attempt: int) -> GenerationResponse:
        self.calls.append((source, attempt))
        if not self.responses:
            raise AssertionError("unexpected generator call")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response  # type: ignore[return-value]


@dataclass
class FakeQa:
    decisions: list[object]
    provider: object = "offline-qa"
    model_id: object = "org/qa-model-v1"
    policy_version: object = "qa-policy-v1"
    seen: list[tuple[PresentationInput, CardPresentationPayload]] = field(default_factory=list)

    def review(
        self,
        source: PresentationInput,
        payload: CardPresentationPayload,
    ) -> QaDecision:
        self.seen.append((source, payload))
        if not self.decisions:
            raise AssertionError("unexpected QA call")
        decision = self.decisions.pop(0)
        if isinstance(decision, BaseException):
            raise decision
        return decision  # type: ignore[return-value]


@pytest.mark.parametrize("language", ("fr", "en"))
def test_direct_factual_fallback_publishes_the_exact_server_renderer(
    engine: sa.Engine,
    persisted_case: PersistedCase,
    language: str,
) -> None:
    source = _build(engine, persisted_case, language=language)
    expected = factual_fallback(source)

    with engine.begin() as connection:
        result = publish_factual_fallback(connection, source=source, now=NOW)
        rows = _rows(connection)

    assert len(rows) == 1
    assert result["qa_status"] == "FALLBACK"
    assert result["payload_variant"] == "FACTUAL_FALLBACK"
    assert result["payload"] == expected.model_dump(mode="json")
    assert result["published_at"] == NOW
    assert rows[0]["generator_version"] == FACTUAL_GENERATOR_VERSION
    assert rows[0]["qa_policy_version"] == FACTUAL_QA_POLICY_VERSION
    assert rows[0]["provider"] is None
    assert rows[0]["model_id"] is None
    assert rows[0]["prompt_version"] is None
    assert rows[0]["qa_provider"] is None
    assert rows[0]["qa_model_id"] is None


def test_valid_full_qa_pass_is_private_then_distinct_factual_fallback_is_published(
    engine: sa.Engine,
    source: PresentationInput,
) -> None:
    candidate = _full_payload(source)
    assert validate_payload(candidate, source).errors == ("full_variant_not_authorized",)
    generator = FakeGenerator([GenerationResponse(payload=candidate)])
    qa = FakeQa([QaDecision(status=QaStatus.PASS, reasons=("grounded",))])

    with engine.begin() as connection:
        result = run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
        )
        rows = _rows(connection)

    assert [row["version"] for row in rows] == [1, 2]
    assert rows[0]["qa_status"] == "PASS"
    assert rows[0]["payload_variant"] == "FULL"
    assert rows[0]["published_at"] is None
    assert rows[0]["provider"] == "offline-generator"
    assert rows[0]["qa_provider"] == "offline-qa"
    assert rows[1]["qa_status"] == "FALLBACK"
    assert rows[1]["payload_variant"] == "FACTUAL_FALLBACK"
    assert rows[1]["published_at"] is not None
    assert rows[1]["provider"] is None
    assert rows[1]["qa_provider"] is None
    assert result["artifact_id"] == rows[1]["artifact_id"]
    assert qa.seen == [(source, candidate)]


def test_qa_receives_candidate_without_a_rewrite_and_cannot_replace_its_payload(
    engine: sa.Engine,
    source: PresentationInput,
) -> None:
    candidate = _full_payload(source)
    before = candidate.model_dump(mode="json")
    generator = FakeGenerator([GenerationResponse(payload=candidate)])
    qa = FakeQa([QaDecision(status=QaStatus.REVIEW, reasons=("manual_review",))])

    with engine.begin() as connection:
        result = run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
        )
        rows = _rows(connection)

    assert qa.seen[0][1] == candidate
    assert qa.seen[0][1].model_dump(mode="json") == before
    assert candidate.model_dump(mode="json") == before
    assert rows[0]["payload"] == before
    assert rows[0]["qa_status"] == "REVIEW"
    assert result["payload"] == factual_fallback(source).model_dump(mode="json")


def test_qa_payload_mutation_is_rejected_and_only_the_original_stays_private(
    engine: sa.Engine,
    source: PresentationInput,
) -> None:
    candidate = _full_payload(source)
    original = candidate.model_dump(mode="json")
    generator = FakeGenerator([GenerationResponse(payload=candidate)])

    class MutatingQa(FakeQa):
        def review(
            self,
            source: PresentationInput,
            payload: CardPresentationPayload,
        ) -> QaDecision:
            self.seen.append((source, payload))
            object.__setattr__(payload, "headline", "Réécriture QA interdite")
            return QaDecision(status=QaStatus.PASS, reasons=("forged_pass",))

    qa = MutatingQa([])

    with engine.begin() as connection:
        result = run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
        )
        rows = _rows(connection)

    assert rows[0]["qa_status"] == "REVIEW"
    assert rows[0]["qa_reasons"] == ["qa_payload_mutation"]
    assert rows[0]["payload"] == original
    assert rows[0]["published_at"] is None
    assert result["qa_status"] == "FALLBACK"


@pytest.mark.parametrize(
    "invalid_text",
    (
        "Recruter du personnel en urgence pour livrer les matériaux.",
        "Ce besoin de matériaux exige immédiatement des effectifs supplémentaires.",
    ),
)
def test_materials_to_staffing_candidate_never_reaches_qa(
    engine: sa.Engine,
    source: PresentationInput,
    invalid_text: str,
) -> None:
    invalid = _replace_public_text(
        _full_payload(source),
        "recommended_action",
        invalid_text,
    )
    assert "materials_staffing_mismatch" in validate_payload(invalid, source).errors
    generator = FakeGenerator(
        [GenerationResponse(payload=invalid), GenerationResponse(payload=invalid)]
    )
    qa = FakeQa([QaDecision(status=QaStatus.PASS)])

    with engine.begin() as connection:
        result = run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
        )
        rows = _rows(connection)

    assert [attempt for _, attempt in generator.calls] == [1, 2]
    assert qa.seen == []
    assert [row["qa_status"] for row in rows] == ["REGENERATE", "REGENERATE", "FALLBACK"]
    assert all("materials_staffing_mismatch" in row["qa_reasons"] for row in rows[:2])
    assert result["qa_status"] == "FALLBACK"


def test_inverted_buyer_and_awardee_never_reaches_qa(
    engine: sa.Engine,
    source: PresentationInput,
) -> None:
    inverted = _replace_public_text(
        _full_payload(source),
        "award_summary",
        (
            f"{source.facts.winner_name} a attribué le marché à "
            f"{source.facts.buyer_name}."
        ),
    )
    assert "actor_role_inversion" in validate_payload(inverted, source).errors
    generator = FakeGenerator(
        [GenerationResponse(payload=inverted), GenerationResponse(payload=inverted)]
    )
    qa = FakeQa([QaDecision(status=QaStatus.PASS)])

    with engine.begin() as connection:
        run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
        )
        rows = _rows(connection)

    assert qa.seen == []
    assert [row["qa_status"] for row in rows] == ["REGENERATE", "REGENERATE", "FALLBACK"]
    assert all("actor_role_inversion" in row["qa_reasons"] for row in rows[:2])


def test_publication_date_presented_as_award_date_never_reaches_qa(
    engine: sa.Engine,
    source: PresentationInput,
) -> None:
    assert source.facts.publication_date is not None
    invalid = _replace_public_text(
        _full_payload(source),
        "award_summary",
        f"Date d'attribution : {source.facts.publication_date:%d/%m/%Y}.",
    )
    assert "publication_as_award_date" in validate_payload(invalid, source).errors
    generator = FakeGenerator(
        [GenerationResponse(payload=invalid), GenerationResponse(payload=invalid)]
    )
    qa = FakeQa([QaDecision(status=QaStatus.PASS)])

    with engine.begin() as connection:
        run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
        )
        rows = _rows(connection)

    assert qa.seen == []
    assert [row["qa_status"] for row in rows] == ["REGENERATE", "REGENERATE", "FALLBACK"]
    assert all("publication_as_award_date" in row["qa_reasons"] for row in rows[:2])


def test_qa_regenerate_permits_exactly_one_second_generation(
    engine: sa.Engine,
    source: PresentationInput,
) -> None:
    first = _full_payload(source)
    second = _replace_public_text(
        first,
        "commercial_importance",
        "Les matériaux constituent une piste commerciale à qualifier.",
    )
    assert validate_payload(second, source).errors == ("full_variant_not_authorized",)
    generator = FakeGenerator(
        [GenerationResponse(payload=first), GenerationResponse(payload=second)]
    )
    qa = FakeQa(
        [
            QaDecision(status=QaStatus.REGENERATE, reasons=("tighten_copy",)),
            QaDecision(status=QaStatus.PASS, reasons=("grounded",)),
        ]
    )

    with engine.begin() as connection:
        result = run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
        )
        rows = _rows(connection)

    assert [attempt for _, attempt in generator.calls] == [1, 2]
    assert [row["qa_status"] for row in rows] == ["REGENERATE", "PASS", "FALLBACK"]
    assert rows[0]["published_at"] is None
    assert rows[1]["published_at"] is None
    assert result["version"] == 3


@pytest.mark.parametrize(
    ("responses", "expected_reason"),
    (
        (
            [
                GenerationResponse(failure_kind="secret-provider-timeout"),
                GenerationResponse(failure_kind="secret-provider-timeout"),
            ],
            "generation_failed",
        ),
        ([RuntimeError("api-key=must-not-leak"), RuntimeError("second-secret")], "generation_exception"),
    ),
    ids=("declared-failure", "exception"),
)
def test_generation_failure_is_private_bounded_and_never_leaks_details(
    engine: sa.Engine,
    source: PresentationInput,
    responses: list[object],
    expected_reason: str,
) -> None:
    generator = FakeGenerator(responses)
    qa = FakeQa([QaDecision(status=QaStatus.PASS)])

    with engine.begin() as connection:
        result = run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
        )
        rows = _rows(connection)

    assert qa.seen == []
    assert [row["qa_status"] for row in rows] == ["REGENERATE", "REGENERATE", "FALLBACK"]
    assert all(row["qa_reasons"] == [expected_reason] for row in rows[:2])
    assert "secret" not in repr(rows)
    assert "api-key" not in repr(rows)
    assert result["qa_status"] == "FALLBACK"


@pytest.mark.parametrize(
    ("decision", "expected_reason"),
    (
        (RuntimeError("qa-token=must-not-leak"), "qa_exception"),
        (
            QaDecision.model_construct(status="PASS", reasons=("x" * 161,)),
            "qa_decision_invalid",
        ),
        ({"status": "PASS", "reasons": []}, "qa_decision_invalid"),
    ),
    ids=("exception", "forged-contract", "wrong-return-type"),
)
def test_invalid_qa_outcome_fails_closed_without_leaking_or_rewriting(
    engine: sa.Engine,
    source: PresentationInput,
    decision: object,
    expected_reason: str,
) -> None:
    candidate = _full_payload(source)
    generator = FakeGenerator([GenerationResponse(payload=candidate)])
    qa = FakeQa([decision])

    with engine.begin() as connection:
        result = run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
        )
        rows = _rows(connection)

    assert len(qa.seen) == 1
    assert rows[0]["qa_status"] == "REVIEW"
    assert rows[0]["qa_reasons"] == [expected_reason]
    assert rows[0]["payload"] == candidate.model_dump(mode="json")
    assert "qa-token" not in repr(rows)
    assert result["qa_status"] == "FALLBACK"


@pytest.mark.parametrize(
    ("decision", "private_status", "public_cause"),
    (
        (
            QaDecision(
                status=QaStatus.REVIEW,
                reasons=("qa-token=must-not-leak",),
            ),
            "REVIEW",
            "qa_review_requested",
        ),
        (
            QaDecision(
                status=QaStatus.FALLBACK,
                reasons=("qa-token=must-not-leak",),
            ),
            "REVIEW",
            "qa_requested_fallback",
        ),
        (
            QaDecision(
                status=QaStatus.REGENERATE,
                reasons=("qa-token=must-not-leak",),
            ),
            "REGENERATE",
            "qa_regeneration_exhausted",
        ),
    ),
    ids=("review", "fallback", "regenerate-at-limit"),
)
def test_non_pass_qa_decisions_remain_private_then_use_canonical_fallback(
    engine: sa.Engine,
    source: PresentationInput,
    decision: QaDecision,
    private_status: str,
    public_cause: str,
) -> None:
    candidate = _full_payload(source)
    generator = FakeGenerator([GenerationResponse(payload=candidate)])
    qa = FakeQa([decision])

    with engine.begin() as connection:
        result = run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
            max_attempts=1,
        )
        rows = _rows(connection)

    assert [row["qa_status"] for row in rows] == [private_status, "FALLBACK"]
    assert "qa-token=must-not-leak" in rows[0]["qa_reasons"]
    assert rows[0]["published_at"] is None
    assert rows[1]["qa_reasons"] == ["deterministic_factual_fallback", public_cause]
    assert "qa-token=must-not-leak" not in repr(rows[1])
    assert "qa-token=must-not-leak" not in repr(result)
    assert result["payload"] == factual_fallback(source).model_dump(mode="json")


def test_generator_supplied_fallback_is_private_and_never_sent_to_qa_or_promoted(
    engine: sa.Engine,
    source: PresentationInput,
) -> None:
    supplied = factual_fallback(source)
    generator = FakeGenerator([GenerationResponse(payload=supplied)])
    qa = FakeQa([QaDecision(status=QaStatus.PASS)])

    with engine.begin() as connection:
        result = run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
        )
        rows = _rows(connection)

    assert qa.seen == []
    assert [row["qa_status"] for row in rows] == ["REVIEW", "FALLBACK"]
    assert rows[0]["published_at"] is None
    assert rows[0]["qa_reasons"] == ["generator_fallback_not_authorized"]
    assert rows[1]["payload"] == supplied.model_dump(mode="json")
    assert rows[0]["artifact_id"] != rows[1]["artifact_id"]
    assert result["artifact_id"] == rows[1]["artifact_id"]


def test_forged_generation_response_is_private_and_retry_is_bounded(
    engine: sa.Engine,
    source: PresentationInput,
) -> None:
    forged = GenerationResponse.model_construct(
        payload=_full_payload(source),
        failure_kind="both-results",
    )
    generator = FakeGenerator([forged, forged])
    qa = FakeQa([QaDecision(status=QaStatus.PASS)])

    with engine.begin() as connection:
        run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
        )
        rows = _rows(connection)

    assert [attempt for _, attempt in generator.calls] == [1, 2]
    assert qa.seen == []
    assert [row["qa_reasons"] for row in rows[:2]] == [
        ["generation_response_invalid"],
        ["generation_response_invalid"],
    ]


def test_invalid_protocol_metadata_fails_before_calls_and_published_row_is_clean(
    engine: sa.Engine,
    source: PresentationInput,
) -> None:
    generator = FakeGenerator(
        [GenerationResponse(payload=_full_payload(source))],
        provider="https://secret-provider.invalid/key",
    )
    qa = FakeQa([QaDecision(status=QaStatus.PASS)])

    with engine.begin() as connection:
        result = run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
        )
        rows = _rows(connection)

    assert generator.calls == []
    assert qa.seen == []
    assert [row["qa_status"] for row in rows] == ["REVIEW", "FALLBACK"]
    assert rows[0]["qa_reasons"] == ["candidate_metadata_invalid"]
    assert rows[0]["provider"] is None
    assert rows[0]["model_id"] is None
    assert rows[0]["prompt_version"] is None
    assert rows[0]["qa_provider"] is None
    assert rows[0]["qa_model_id"] is None
    assert rows[1]["provider"] is None
    assert rows[1]["model_id"] is None
    assert rows[1]["prompt_version"] is None
    assert rows[1]["qa_provider"] is None
    assert rows[1]["qa_model_id"] is None
    assert "secret-provider" not in repr(rows)
    assert result["qa_status"] == "FALLBACK"


def test_ambiguous_buyer_awardee_fallback_is_review_only_and_not_published(
    engine: sa.Engine,
    persisted_case: PersistedCase,
) -> None:
    organization = {
        "legal_name": "Entreprise Homonyme SA",
        "identifiers": [{"scheme": "SIRET", "value": "11111111111111"}],
        "country": "FR",
    }
    awardees = [
        {
            "is_group": False,
            "members": [{"role": "winner", "organization": organization}],
        }
    ]
    with engine.begin() as connection:
        event_key = connection.execute(
            sa.select(contract_award.c.event_key).where(
                contract_award.c.award_key == persisted_case.award_key
            )
        ).scalar_one()
        connection.execute(
            sa.update(source_event)
            .where(source_event.c.event_key == event_key)
            .values(procedure_buyers=[organization])
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == persisted_case.award_key)
            .values(awardee_parties=awardees)
        )
    source = _build(engine, persisted_case)
    assert "actor_role_ambiguous" in validate_payload(factual_fallback(source), source).errors

    with engine.begin() as connection:
        result = publish_factual_fallback(connection, source=source, now=NOW)
        rows = _rows(connection)

    assert len(rows) == 1
    assert result["qa_status"] == "REVIEW"
    assert result["published_at"] is None
    assert "actor_role_ambiguous" in result["qa_reasons"]
    assert rows[0]["published_at"] is None


def test_attempt_versions_are_monotonic_across_retries_qa_and_publication(
    engine: sa.Engine,
    source: PresentationInput,
) -> None:
    invalid = _replace_public_text(
        _full_payload(source),
        "recommended_action",
        "Recruter du personnel pour répondre au besoin de matériaux.",
    )
    valid = _full_payload(source)
    generator = FakeGenerator(
        [GenerationResponse(payload=invalid), GenerationResponse(payload=valid)]
    )
    qa = FakeQa([QaDecision(status=QaStatus.PASS, reasons=("grounded",))])

    with engine.begin() as connection:
        result = run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
        )
        rows = _rows(connection)

    assert [row["version"] for row in rows] == [1, 2, 3]
    assert [row["qa_status"] for row in rows] == ["REGENERATE", "PASS", "FALLBACK"]
    assert result["version"] == 3


def test_unexpected_sqlalchemy_error_from_persistence_is_not_masked(
    engine: sa.Engine,
    source: PresentationInput,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from signals.card_intelligence import service

    error = sa.exc.OperationalError("insert", {}, RuntimeError("database unavailable"))

    def fail_append(*args, **kwargs):
        raise error

    monkeypatch.setattr(service, "append_attempt", fail_append)
    with engine.begin() as connection, pytest.raises(sa.exc.OperationalError) as raised:
        publish_factual_fallback(connection, source=source, now=NOW)

    assert raised.value is error


def test_sqlalchemy_error_from_generator_boundary_is_not_misreported_as_provider_failure(
    engine: sa.Engine,
    source: PresentationInput,
) -> None:
    error = sa.exc.OperationalError("provider-db", {}, RuntimeError("offline"))
    generator = FakeGenerator([error])
    qa = FakeQa([])

    with engine.begin() as connection, pytest.raises(sa.exc.OperationalError) as raised:
        run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
        )

    assert raised.value is error


@pytest.mark.parametrize("max_attempts", (0, 3, -1, True, "2", None))
def test_invalid_max_attempts_fail_before_metadata_or_provider_calls(
    engine: sa.Engine,
    source: PresentationInput,
    max_attempts: object,
) -> None:
    generator = FakeGenerator([GenerationResponse(payload=_full_payload(source))])
    qa = FakeQa([QaDecision(status=QaStatus.PASS)])

    with engine.begin() as connection, pytest.raises(ValueError, match="max_attempts"):
        run_offline_candidate_pipeline(
            connection,
            source=source,
            generator=generator,
            qa=qa,
            now=NOW,
            max_attempts=max_attempts,  # type: ignore[arg-type]
        )

    assert generator.calls == []
    assert qa.seen == []
    assert MAX_CANDIDATE_ATTEMPTS == 2
