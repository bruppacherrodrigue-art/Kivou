from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pytest
import sqlalchemy as sa
from test_card_presentation_store import NOW, full_payload, source

from signals.card_intelligence.contracts import GenerationResponse, QaStatus
from signals.card_intelligence.fallback import factual_fallback
from signals.card_intelligence.service import generate_and_publish, publish_factual_fallback
from signals.card_intelligence.store import published_for_signals
from signals.persistence.database import create_database_engine
from signals.persistence.schema import card_presentation_artifact
from signals.qa_signals.contracts import QaDecision, QaResponse


@pytest.fixture
def connection():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE account (account_id VARCHAR(64) PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE target_icp ("
            "target_icp_id VARCHAR(128) PRIMARY KEY, account_id VARCHAR(64) NOT NULL, "
            "matching_revision INTEGER NOT NULL, status VARCHAR(16) NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE materialized_signal ("
            "signal_key VARCHAR(64) PRIMARY KEY, target_icp_id VARCHAR(128) NOT NULL, "
            "revision INTEGER NOT NULL, target_icp_revision INTEGER NOT NULL, "
            "invalidated_at DATETIME)"
        )
        card_presentation_artifact.create(connection)
        connection.execute(sa.text("INSERT INTO account VALUES ('account-1')"))
        connection.execute(
            sa.text("INSERT INTO target_icp VALUES ('icp-1', 'account-1', 2, 'active')")
        )
        connection.execute(
            sa.text("INSERT INTO materialized_signal VALUES ('signal-1', 'icp-1', 3, 2, NULL)")
        )
        yield connection


@dataclass
class Writer:
    responses: list[GenerationResponse]
    model_id: str = "fake-writer"
    provider: str = "fake"
    prompt_version: str = "prompt-v1"
    attempts: list[int] = field(default_factory=list)

    def generate(self, source, *, attempt):
        self.attempts.append(attempt)
        return self.responses.pop(0)


@dataclass
class Qa:
    response: QaResponse
    model_id: str = "fake-qa"
    provider: str = "fake"
    policy_version: str = "qa-v1"
    calls: int = 0

    def review(self, source, payload):
        self.calls += 1
        return self.response


def test_one_regeneration_then_pass_is_published(connection):
    invalid = full_payload().model_copy(
        update={"commercial_importance": "Une capacité de personnel supplémentaire est possible."}
    )
    writer = Writer(
        responses=(
            [GenerationResponse(payload=invalid), GenerationResponse(payload=full_payload())]
        )
    )
    qa = Qa(QaResponse(decision=QaDecision(status=QaStatus.PASS, reasons=("grounded",))))

    result = generate_and_publish(
        connection,
        source=source(),
        generator=writer,
        qa=qa,
        now=NOW,
    )

    assert writer.attempts == [1, 2]
    assert qa.calls == 1, "deterministically invalid copy must never reach QA"
    assert result["qa_status"] == "PASS"
    assert result["version"] == 2


def test_qa_pass_cannot_override_invalid_materials_to_staffing_copy(connection):
    invalid = full_payload().model_copy(
        update={"fit_reason": "Le client pourrait fournir du personnel supplémentaire."}
    )
    writer = Writer(responses=[GenerationResponse(payload=invalid)])
    qa = Qa(QaResponse(decision=QaDecision(status=QaStatus.PASS)))

    result = generate_and_publish(
        connection,
        source=source(),
        generator=writer,
        qa=qa,
        now=NOW,
        max_attempts=1,
    )

    assert qa.calls == 0
    assert result["qa_status"] == "FALLBACK"
    published = published_for_signals(
        connection,
        account_id="account-1",
        bindings={"signal-1": (3, 2)},
        language="fr",
    )
    assert published["signal-1"]["status"] == "FALLBACK"


def test_qa_pass_cannot_override_an_actor_role_inversion(connection):
    invalid = full_payload().model_copy(
        update={
            "award_summary": (
                "Gagneraud Construction est indiqué comme acheteur et Syndicat des crues "
                "comme entreprise attributaire."
            )
        }
    )
    writer = Writer(responses=[GenerationResponse(payload=invalid)])
    qa = Qa(QaResponse(decision=QaDecision(status=QaStatus.PASS)))

    result = generate_and_publish(
        connection,
        source=source(),
        generator=writer,
        qa=qa,
        now=NOW,
        max_attempts=1,
    )

    assert qa.calls == 0
    assert result["qa_status"] == "FALLBACK"


def test_generator_fallback_variant_never_reaches_qa_as_pass(connection):
    writer = Writer(responses=[GenerationResponse(payload=factual_fallback(source()))])
    qa = Qa(QaResponse(decision=QaDecision(status=QaStatus.PASS)))

    result = generate_and_publish(
        connection,
        source=source(),
        generator=writer,
        qa=qa,
        now=NOW,
        max_attempts=1,
    )

    attempts = connection.execute(
        sa.select(card_presentation_artifact).order_by(card_presentation_artifact.c.version)
    ).mappings().all()
    assert qa.calls == 0
    assert [(row["qa_status"], row["published_at"] is not None) for row in attempts] == [
        ("REGENERATE", False),
        ("FALLBACK", True),
    ]
    assert result["qa_status"] == "FALLBACK"


def test_ambiguous_truncated_actor_labels_send_fallback_to_review(connection):
    prefix = (
        "Groupement Entreprise Construction Architecture Energie Infrastructure "
        "Regionale "
    )
    item = source(
        facts=source().facts.model_copy(
            update={
                "winner_name": f"{prefix}Titulaire Alpha",
                "buyer_name": f"{prefix}Acheteur Beta",
            }
        )
    )

    result = publish_factual_fallback(connection, source=item, now=NOW)

    assert result["qa_status"] == "REVIEW"
    assert result["published_at"] is None
    assert "actor_role_collision" in result["qa_reasons"]


def test_review_status_is_stored_but_never_published(connection):
    writer = Writer(responses=[GenerationResponse(payload=full_payload())])
    qa = Qa(QaResponse(decision=QaDecision(status=QaStatus.REVIEW, reasons=("ambiguous",))))
    result = generate_and_publish(
        connection,
        source=source(),
        generator=writer,
        qa=qa,
        now=NOW + dt.timedelta(minutes=1),
    )
    assert result["qa_status"] == "REVIEW"
    assert result["published_at"] is None
    assert published_for_signals(
        connection,
        account_id="account-1",
        bindings={"signal-1": (3, 2)},
        language="fr",
    ) == {}


def test_generation_failure_records_empty_attempt_then_publishes_factual_fallback(connection):
    writer = Writer(
        responses=[GenerationResponse(failure_kind="provider_unavailable")]
    )
    qa = Qa(QaResponse(decision=QaDecision(status=QaStatus.PASS)))

    result = generate_and_publish(
        connection,
        source=source(),
        generator=writer,
        qa=qa,
        now=NOW,
        max_attempts=1,
    )

    attempts = connection.execute(
        sa.select(card_presentation_artifact).order_by(
            card_presentation_artifact.c.version
        )
    ).mappings().all()
    assert [(row["qa_status"], row["payload"]) for row in attempts] == [
        ("REGENERATE", None),
        ("FALLBACK", result["payload"]),
    ]
    assert qa.calls == 0
    assert result["published_at"] is not None
