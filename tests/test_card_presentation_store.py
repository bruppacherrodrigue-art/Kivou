from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from signals.card_intelligence.contracts import (
    ArtifactKind,
    CardPresentationPayload,
    ClaimKind,
    PresentationClaim,
    PresentationInput,
    PresentationVariant,
    QaStatus,
    SourceFacts,
)
from signals.card_intelligence.fallback import factual_fallback
from signals.card_intelligence.store import (
    ForeignOrStalePresentationInput,
    PresentationPublicationConflict,
    _current_owned_signal_query,
    append_attempt,
    published_for_signals,
)
from signals.persistence.database import create_database_engine
from signals.persistence.schema import card_presentation_artifact

NOW = dt.datetime(2026, 8, 30, 9, 0, tzinfo=dt.UTC)
EVIDENCE = "source:decp:notice-1"


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
        connection.execute(sa.text("INSERT INTO account VALUES ('account-2')"))
        connection.execute(
            sa.text("INSERT INTO target_icp VALUES ('icp-1', 'account-1', 2, 'active')")
        )
        connection.execute(
            sa.text("INSERT INTO materialized_signal VALUES ('signal-1', 'icp-1', 3, 2, NULL)")
        )
        yield connection


def source(**updates) -> PresentationInput:
    item = PresentationInput(
        account_id="account-1",
        signal_key="signal-1",
        signal_revision=3,
        target_icp_id="icp-1",
        target_icp_revision=2,
        language="fr",
        target_icp_label="Matériaux",
        target_icp_customer_input={"offers": ["materials_and_components"]},
        icp_matched_needs=("materials_or_components",),
        facts=SourceFacts(
            winner_name="Gagneraud Construction",
            buyer_name="Syndicat des crues",
            source_system="decp",
            source_notice_id="notice-1",
            evidence_refs=(EVIDENCE,),
        ),
    )
    return item.model_copy(update=updates)


def full_payload() -> CardPresentationPayload:
    return CardPresentationPayload(
        variant=PresentationVariant.FULL,
        headline="Un lot attribué à Gagneraud Construction",
        award_summary=(
            "Syndicat des crues est indiqué comme acheteur et Gagneraud Construction "
            "comme entreprise attributaire."
        ),
        commercial_importance="Un chantier de génie civil est documenté.",
        fit_reason="Les matériaux et composants correspondent au profil ciblé.",
        timing="Le calendrier d'exécution reste à qualifier.",
        recommended_action="Vérifier le calendrier avant une approche.",
        target_roles=("SITE_PROCUREMENT_MANAGER",),
        fit_need_categories=("materials_or_components",),
        claims=(
            PresentationClaim(
                claim_id="FACT_AWARDEE",
                kind=ClaimKind.FACT,
                text="Gagneraud Construction est l'attributaire publié.",
                evidence_refs=(EVIDENCE,),
            ),
            PresentationClaim(
                claim_id="RECOMMEND_QUALIFY",
                kind=ClaimKind.RECOMMENDATION,
                text="Qualifier le calendrier.",
                evidence_refs=(EVIDENCE,),
            ),
        ),
    )


def append(connection, *, payload, status, when=NOW, publish=False):
    return append_attempt(
        connection,
        source=source(),
        kind=ArtifactKind.SIGNAL_CARD,
        payload=payload,
        qa_status=status,
        qa_reasons=("test",),
        prompt_version="prompt-v1",
        model_id="fake-writer",
        provider="fake",
        qa_model_id="fake-qa",
        qa_provider="fake",
        qa_policy_version="qa-v1",
        created_at=when,
        publish=publish,
    )


def test_only_pass_or_fallback_publication_is_returned_and_latest_wins(connection):
    first = append(
        connection,
        payload=factual_fallback(source()),
        status=QaStatus.FALLBACK,
        publish=True,
    )
    review = append(connection, payload=full_payload(), status=QaStatus.REVIEW)
    assert review["published_at"] is None
    second = append(
        connection,
        payload=full_payload(),
        status=QaStatus.PASS,
        when=NOW + dt.timedelta(seconds=1),
        publish=True,
    )

    published = published_for_signals(
        connection,
        account_id="account-1",
        bindings={"signal-1": (3, 2)},
        language="fr",
    )
    assert published["signal-1"]["artifact_id"] == second["artifact_id"]
    assert published["signal-1"]["status"] == "PASS"
    old = connection.execute(
        sa.select(card_presentation_artifact).where(
            card_presentation_artifact.c.artifact_id == first["artifact_id"]
        )
    ).mappings().one()
    assert old["superseded_at"] is not None


def test_tenant_and_revision_binding_fail_closed(connection):
    foreign = source(account_id="account-2")
    with pytest.raises(ForeignOrStalePresentationInput):
        append_attempt(
            connection,
            source=foreign,
            kind=ArtifactKind.SIGNAL_CARD,
            payload=factual_fallback(foreign),
            qa_status=QaStatus.FALLBACK,
            qa_reasons=("test",),
            prompt_version="fallback-v1",
            model_id=None,
            provider=None,
            qa_model_id=None,
            qa_provider=None,
            qa_policy_version="qa-v1",
            created_at=NOW,
            publish=True,
        )

    append(
        connection,
        payload=factual_fallback(source()),
        status=QaStatus.FALLBACK,
        publish=True,
    )
    assert published_for_signals(
        connection,
        account_id="account-1",
        bindings={"signal-1": (4, 2)},
        language="fr",
    ) == {}
    assert published_for_signals(
        connection,
        account_id="account-2",
        bindings={"signal-1": (3, 2)},
        language="fr",
    ) == {}


def test_direct_publish_cannot_bypass_deterministic_validation_or_supersede_current(
    connection,
):
    current = append(
        connection,
        payload=factual_fallback(source()),
        status=QaStatus.FALLBACK,
        publish=True,
    )
    inverted = full_payload().model_copy(
        update={
            "award_summary": (
                "Gagneraud Construction est indiqué comme acheteur et Syndicat des crues "
                "comme entreprise attributaire."
            )
        }
    )

    with pytest.raises(PresentationPublicationConflict, match="actor_role_mismatch"):
        append(
            connection,
            payload=inverted,
            status=QaStatus.PASS,
            when=NOW + dt.timedelta(seconds=1),
            publish=True,
        )

    rows = connection.execute(sa.select(card_presentation_artifact)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["artifact_id"] == current["artifact_id"]
    assert rows[0]["superseded_at"] is None


def test_status_variant_mismatch_cannot_supersede_current_publication(connection):
    current = append(
        connection,
        payload=full_payload(),
        status=QaStatus.PASS,
        publish=True,
    )

    with pytest.raises(
        PresentationPublicationConflict,
        match="PASS cannot publish FACTUAL_FALLBACK",
    ):
        append(
            connection,
            payload=factual_fallback(source()),
            status=QaStatus.PASS,
            when=NOW + dt.timedelta(seconds=1),
            publish=True,
        )

    rows = connection.execute(sa.select(card_presentation_artifact)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["artifact_id"] == current["artifact_id"]
    assert rows[0]["superseded_at"] is None


def test_invalidated_signal_and_changed_icp_never_publish_or_read_stale_content(connection):
    append(
        connection,
        payload=factual_fallback(source()),
        status=QaStatus.FALLBACK,
        publish=True,
    )
    connection.execute(
        sa.text("UPDATE materialized_signal SET invalidated_at = :now WHERE signal_key = 'signal-1'"),
        {"now": NOW},
    )
    assert published_for_signals(
        connection,
        account_id="account-1",
        bindings={"signal-1": (3, 2)},
        language="fr",
    ) == {}

    connection.execute(
        sa.text("UPDATE materialized_signal SET invalidated_at = NULL WHERE signal_key = 'signal-1'")
    )
    connection.execute(
        sa.text("UPDATE target_icp SET matching_revision = 3 WHERE target_icp_id = 'icp-1'")
    )
    with pytest.raises(ForeignOrStalePresentationInput):
        append(
            connection,
            payload=factual_fallback(source()),
            status=QaStatus.FALLBACK,
            publish=True,
        )
    assert published_for_signals(
        connection,
        account_id="account-1",
        bindings={"signal-1": (3, 2)},
        language="fr",
    ) == {}

    connection.execute(
        sa.text(
            "UPDATE target_icp SET matching_revision = 2, status = 'inactive' "
            "WHERE target_icp_id = 'icp-1'"
        )
    )
    with pytest.raises(ForeignOrStalePresentationInput):
        append(
            connection,
            payload=factual_fallback(source()),
            status=QaStatus.FALLBACK,
            publish=True,
        )


def test_reader_ignores_malformed_published_json_instead_of_raising(connection):
    row = append(
        connection,
        payload=factual_fallback(source()),
        status=QaStatus.FALLBACK,
        publish=True,
    )
    connection.execute(
        sa.update(card_presentation_artifact)
        .where(card_presentation_artifact.c.artifact_id == row["artifact_id"])
        .values(payload="malformed")
    )
    assert published_for_signals(
        connection,
        account_id="account-1",
        bindings={"signal-1": (3, 2)},
        language="fr",
    ) == {}


def test_database_rejects_null_published_payload_and_two_active_publications(connection):
    empty = append(
        connection,
        payload=None,
        status=QaStatus.REGENERATE,
    )
    with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
        connection.execute(
            sa.update(card_presentation_artifact)
            .where(card_presentation_artifact.c.artifact_id == empty["artifact_id"])
            .values(qa_status="PASS", published_at=NOW)
        )

    first = append(
        connection,
        payload=factual_fallback(source()),
        status=QaStatus.FALLBACK,
        when=NOW + dt.timedelta(seconds=1),
        publish=True,
    )
    append(
        connection,
        payload=full_payload(),
        status=QaStatus.PASS,
        when=NOW + dt.timedelta(seconds=2),
        publish=True,
    )
    with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
        connection.execute(
            sa.update(card_presentation_artifact)
            .where(card_presentation_artifact.c.artifact_id == first["artifact_id"])
            .values(superseded_at=None)
        )


def test_version_allocation_locks_the_materialized_signal_on_postgresql():
    sql = str(
        _current_owned_signal_query(source()).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "FOR UPDATE OF materialized_signal" in sql
