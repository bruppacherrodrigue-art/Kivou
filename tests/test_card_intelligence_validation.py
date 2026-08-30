from __future__ import annotations

import datetime as dt
import json
import pathlib
from dataclasses import dataclass
from decimal import Decimal

import pytest
import sqlalchemy as sa
from feed_helpers import (
    BOAMP_AGING,
    BOAMP_PUBLICATION_ONLY,
    make_account,
    make_icp,
    materialize_boamp,
)

from signals.accounts.schema import target_icp
from signals.card_intelligence.contracts import (
    ClaimKind,
    PresentationInput,
    PresentationVariant,
    SourceFacts,
    TargetIcpSnapshot,
)
from signals.card_intelligence.fallback import factual_fallback
from signals.card_intelligence.input import (
    PresentationInputUnavailable,
    build_presentation_input,
)
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import (
    contract_award,
    evidence,
    materialized_signal,
    source_event,
)

NOW = dt.datetime(2026, 8, 30, 9, 0, tzinfo=dt.UTC)
AWARDEE_FIELD_REF = "source-field:v1:contract_award:award-1:awardee_parties"
BUYER_FIELD_REF = "source-field:v1:source_event:event-1:procedure_buyers"
AMOUNT_FIELD_REF = "source-field:v1:contract_award:award-1:amount_currency"
LOCATION_FIELD_REF = "source-field:v1:contract_award:award-1:place_of_performance"
AWARD_DATE_FIELD_REF = "source-field:v1:contract_award:award-1:award_date"
NOTIFICATION_DATE_FIELD_REF = "source-field:v1:contract_award:award-1:contract_notification_date"
PUBLICATION_DATE_FIELD_REF = "source-field:v1:source_event:event-1:published_on"
PERSISTED_WINNER_REF = "evidence:v1:winner-proof:winner"
PERSISTED_BUYER_REF = "evidence:v1:buyer-proof:procedure_buyers"
DIRECT_FIELD_REFS = (
    AWARDEE_FIELD_REF,
    BUYER_FIELD_REF,
    AMOUNT_FIELD_REF,
    LOCATION_FIELD_REF,
    AWARD_DATE_FIELD_REF,
    NOTIFICATION_DATE_FIELD_REF,
    PUBLICATION_DATE_FIELD_REF,
)


def _icp_snapshot() -> TargetIcpSnapshot:
    return TargetIcpSnapshot.from_json_value(
        {
            "offer_summary": "Materiaux de construction",
            "offers": ["materials_and_components"],
            "secondary_offers": [],
            "buyer_trades": ["building_construction"],
            "secondary_buyer_trades": [],
            "territories": ["CH", "FR"],
            "minimum_contract_value": {
                "currency": "CHF",
                "minimum_amount": 1000.0,
                "maximum_amount": None,
            },
        }
    )


@pytest.fixture
def source() -> PresentationInput:
    return PresentationInput(
        account_id="account-1",
        signal_key="signal-1",
        signal_revision=3,
        target_icp_id="icp-1",
        target_icp_revision=2,
        language="fr",
        target_icp_label="Intrants de chantier",
        target_icp_customer_input=_icp_snapshot(),
        icp_matched_needs=("materials_or_components",),
        facts=SourceFacts(
            winner_name="Egli Gartenbau AG Sursee",
            buyer_name="Gemeinde Root",
            award_title="FOURNITURE LOT 7 ACCORD-CADRE ADMINISTRATIF",
            amount=Decimal("250000.00"),
            currency="CHF",
            location="Root, CH",
            award_date=dt.date(2026, 5, 19),
            contract_notification_date=dt.date(2026, 5, 22),
            publication_date=dt.date(2026, 8, 15),
            source_system="simap",
            source_notice_id="notice-123",
            evidence_refs=(
                *DIRECT_FIELD_REFS,
                PERSISTED_WINNER_REF,
                PERSISTED_BUYER_REF,
            ),
        ),
    )


@pytest.mark.parametrize(
    ("language", "headline_marker", "buyer_marker", "award_date_marker"),
    (
        ("fr", "Attribution publiée", "Acheteur publié", "Date d'attribution publiée"),
        ("en", "Published award", "Published buyer", "Published award date"),
    ),
)
def test_fallback_is_factual_grounded_and_language_bound(
    source, language, headline_marker, buyer_marker, award_date_marker
):
    payload = factual_fallback(source.model_copy(update={"language": language}))

    assert payload.variant is PresentationVariant.FACTUAL_FALLBACK
    assert headline_marker.casefold() in payload.headline.casefold()
    assert buyer_marker.casefold() in payload.award_summary.casefold()
    assert any(award_date_marker.casefold() in claim.text.casefold() for claim in payload.claims)
    assert payload.commercial_importance is None
    assert payload.fit_reason is None
    assert payload.timing is None
    assert payload.recommended_action is None
    assert payload.target_roles == ()
    assert payload.fit_need_categories == ()
    assert all(claim.kind is ClaimKind.FACT for claim in payload.claims)
    assert all(claim.evidence_refs for claim in payload.claims)


@pytest.mark.parametrize(
    ("language", "missing"),
    (("fr", "Acheteur non publié"), ("en", "buyer is not published")),
)
def test_fallback_discloses_a_missing_buyer_without_commercial_claims(source, language, missing):
    facts = source.facts.model_copy(update={"buyer_name": None})
    payload = factual_fallback(source.model_copy(update={"language": language, "facts": facts}))

    assert missing.casefold() in payload.award_summary.casefold()
    assert any(missing.casefold() in unknown.text.casefold() for unknown in payload.unknowns)
    assert payload.commercial_importance is None
    assert payload.target_roles == ()


def test_fallback_never_reuses_the_administrative_title(source):
    raw_title = "FOURNITURE LOT 7 ACCORD-CADRE ADMINISTRATIF"
    facts = source.facts.model_copy(update={"award_title": raw_title})
    payload = factual_fallback(source.model_copy(update={"facts": facts}))

    rendered = payload.model_dump_json()
    assert raw_title not in rendered
    assert "award_title" not in rendered


def test_fallback_never_cuts_long_actor_names_into_a_new_fact(source):
    long_winner = "  " + "Societe attributaire tres longue " * 12 + "SA  "
    long_buyer = "\n" + "Collectivite acheteuse tres longue " * 12 + "Ville\t"
    facts = source.facts.model_copy(update={"winner_name": long_winner, "buyer_name": long_buyer})

    payload = factual_fallback(source.model_copy(update={"facts": facts}))
    rendered = payload.model_dump_json()

    assert len(payload.headline) <= 160
    assert len(payload.award_summary) <= 420
    assert all(claim.text.strip() for claim in payload.claims)
    assert "..." not in rendered and "…" not in rendered
    assert "Societe attributaire tres longue Societe" not in rendered
    assert "Collectivite acheteuse tres longue Collectivite" not in rendered


def test_fallback_deduplicates_and_bounds_evidence_to_sixteen(source):
    winner_refs = tuple(f"evidence:v1:{index:064x}:winner" for index in range(20))
    raw_refs = (*DIRECT_FIELD_REFS, *winner_refs, winner_refs[3], winner_refs[7])
    facts = source.facts.model_copy(update={"evidence_refs": raw_refs})
    payload = factual_fallback(source.model_copy(update={"facts": facts}))

    claims = {claim.claim_id: claim for claim in payload.claims}
    assert claims["FACT_HEADLINE"].evidence_refs[0] == AWARDEE_FIELD_REF
    assert len(claims["FACT_HEADLINE"].evidence_refs) == 16
    assert len(set(claims["FACT_HEADLINE"].evidence_refs)) == 16
    assert claims["FACT_LOCATION"].evidence_refs == (LOCATION_FIELD_REF,)
    assert claims["FACT_PUBLICATION_DATE"].evidence_refs == (PUBLICATION_DATE_FIELD_REF,)


def test_fallback_unknowns_are_bounded_proven_and_only_describe_absent_facts(source):
    assert factual_fallback(source).unknowns == ()
    facts = source.facts.model_copy(
        update={
            "buyer_name": None,
            "amount": None,
            "currency": None,
            "location": None,
            "award_date": None,
            "contract_notification_date": None,
            "publication_date": None,
            "evidence_refs": tuple(
                ref for ref in source.facts.evidence_refs if ref != PERSISTED_BUYER_REF
            ),
        }
    )

    unknowns = factual_fallback(source.model_copy(update={"facts": facts})).unknowns

    assert len(unknowns) == 6
    assert len(unknowns) <= 8
    assert all(unknown.text and len(unknown.text) <= 240 for unknown in unknowns)
    assert all(unknown.evidence_refs for unknown in unknowns)

    by_text = {unknown.text: unknown for unknown in unknowns}
    assert by_text["Acheteur non publié."].evidence_refs == (BUYER_FIELD_REF,)
    assert by_text["Date d'attribution non publiée."].evidence_refs == (AWARD_DATE_FIELD_REF,)
    assert by_text["Date de notification du contrat non publiée."].evidence_refs == (
        NOTIFICATION_DATE_FIELD_REF,
    )


def test_fallback_fails_closed_when_a_present_fact_lacks_its_field_proof(source):
    facts = source.facts.model_copy(
        update={
            "evidence_refs": tuple(
                ref for ref in source.facts.evidence_refs if ref != LOCATION_FIELD_REF
            )
        }
    )
    with pytest.raises(ValueError, match="place_of_performance"):
        factual_fallback(source.model_copy(update={"facts": facts}))


@pytest.mark.parametrize("language", ("fr", "en"))
def test_publication_date_is_never_substituted_for_an_absent_award_date(source, language):
    facts = source.facts.model_copy(
        update={
            "award_date": None,
            "contract_notification_date": None,
            "publication_date": dt.date(2026, 8, 15),
        }
    )
    payload = factual_fallback(source.model_copy(update={"language": language, "facts": facts}))
    texts = [claim.text.casefold() for claim in payload.claims]
    unknowns = [unknown.text.casefold() for unknown in payload.unknowns]

    if language == "fr":
        assert not any("date d'attribution publiée" in text for text in texts)
        assert any("date de publication" in text and "2026" in text for text in texts)
        assert any("date d'attribution non publiée" in text for text in unknowns)
    else:
        assert not any("published award date" in text for text in texts)
        assert any("publication date" in text and "2026" in text for text in texts)
        assert any("award date is not published" in text for text in unknowns)


def test_fallback_keeps_buyer_and_awardee_in_their_source_roles(source):
    payload = factual_fallback(source)
    summary = payload.award_summary

    assert summary.index("Gemeinde Root") < summary.index("Egli Gartenbau AG Sursee")
    assert "Acheteur publié : Gemeinde Root" in summary
    assert "Attributaire publié : Egli Gartenbau AG Sursee" in summary


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@dataclass(frozen=True)
class PersistedCase:
    account_id: str
    other_account_id: str
    target_icp_id: str
    signal_key: str
    award_key: str


@pytest.fixture
def persisted_case(engine) -> PersistedCase:
    with engine.begin() as connection:
        account_id = make_account(connection, "alice-card@test.invalid", "Alice Materiaux")
        other_account_id = make_account(connection, "bob-card@test.invalid", "Bob Materiaux")
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


def _build(engine, case: PersistedCase, *, account_id: str | None = None):
    with engine.connect() as connection:
        return build_presentation_input(
            connection,
            account_id=account_id or case.account_id,
            signal_key=case.signal_key,
            language="fr",
        )


def _assert_unavailable(engine, case: PersistedCase, *, account_id: str | None = None):
    with pytest.raises(PresentationInputUnavailable) as error:
        _build(engine, case, account_id=account_id)
    assert str(error.value) == "presentation input unavailable"


def test_input_is_built_from_the_current_tenant_owned_rows(engine, persisted_case):
    statements: list[tuple[str, object]] = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        statements.append((statement, parameters))

    sa.event.listen(engine, "before_cursor_execute", capture)
    try:
        source = _build(engine, persisted_case)
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)

    assert source.account_id == persisted_case.account_id
    assert source.signal_key == persisted_case.signal_key
    assert source.signal_revision == 1
    assert source.target_icp_id == persisted_case.target_icp_id
    assert source.target_icp_revision == 1
    assert source.target_icp_customer_input.offers == ("materials_and_components",)
    assert source.facts.winner_name == "SARL ALCIS TRANSPORTS"
    assert source.facts.buyer_name == "Ville de Saint Orens de Gameville"
    assert source.facts.award_date == dt.date(2026, 7, 17)
    assert source.facts.contract_notification_date is None
    assert source.facts.publication_date == dt.date(2026, 8, 18)
    assert source.facts.evidence_refs
    assert len(source.facts.evidence_refs) <= 32
    assert all(ref.startswith("source-field:v1:") for ref in source.facts.evidence_refs[:7])
    assert source.facts.evidence_refs[0].endswith(":awardee_parties")
    assert source.facts.evidence_refs[1].endswith(":procedure_buyers")
    select_sql = next(sql for sql, _ in statements if "FROM target_icp" in sql)
    assert "target_icp.account_id = ?" in select_sql
    assert "materialized_signal.invalidated_at IS NULL" in select_sql
    assert "materialized_signal.target_icp_revision = target_icp.matching_revision" in select_sql


@pytest.mark.parametrize("foreign", (True, False))
def test_input_does_not_reveal_a_foreign_or_unknown_signal(engine, persisted_case, foreign):
    account_id = persisted_case.other_account_id if foreign else "account-does-not-exist"
    _assert_unavailable(engine, persisted_case, account_id=account_id)


def test_input_rejects_an_invalidated_signal(engine, persisted_case):
    with engine.begin() as connection:
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == persisted_case.signal_key)
            .values(invalidated_at=NOW, invalidation_reason="icp_updated")
        )
    _assert_unavailable(engine, persisted_case)


@pytest.mark.parametrize(
    "values",
    (
        {"status": "draft"},
        {"plan_limit_code": "territory_limit_exceeded", "plan_limited_at": NOW},
    ),
)
def test_input_rejects_a_draft_or_plan_limited_icp(engine, persisted_case, values):
    with engine.begin() as connection:
        connection.execute(
            sa.update(target_icp)
            .where(target_icp.c.target_icp_id == persisted_case.target_icp_id)
            .values(**values)
        )
    _assert_unavailable(engine, persisted_case)


def test_input_rejects_a_stale_icp_revision(engine, persisted_case):
    with engine.begin() as connection:
        connection.execute(
            sa.update(target_icp)
            .where(target_icp.c.target_icp_id == persisted_case.target_icp_id)
            .values(matching_revision=2)
        )
    _assert_unavailable(engine, persisted_case)


@pytest.mark.parametrize(
    "customer_input",
    (
        {
            "offers": ["materials_and_components"],
            "buyer_trades": [],
            "territories": ["FR"],
            "minimum_contract_value": {"currency": "CHF", "minimum_amount": "1000"},
        },
        {
            "offers": ["materials_and_components"],
            "buyer_trades": [],
            "territories": ["FR"],
            "minimum_contract_value": {"currency": "CHF", "minimum_amount": 1000.0},
            "unexpected": True,
        },
    ),
)
def test_input_rejects_coercive_or_invalid_icp_json(engine, persisted_case, customer_input):
    with engine.begin() as connection:
        connection.execute(
            sa.update(target_icp)
            .where(target_icp.c.target_icp_id == persisted_case.target_icp_id)
            .values(customer_input=customer_input)
        )
    _assert_unavailable(engine, persisted_case)


def test_input_rejects_an_award_without_persisted_evidence(engine, persisted_case):
    with engine.begin() as connection:
        connection.execute(
            sa.delete(evidence).where(evidence.c.award_key == persisted_case.award_key)
        )
    _assert_unavailable(engine, persisted_case)


def test_location_and_publication_claims_never_borrow_winner_or_buyer_evidence(
    engine, persisted_case
):
    with engine.begin() as connection:
        connection.execute(
            sa.delete(evidence).where(
                evidence.c.award_key == persisted_case.award_key,
                evidence.c.anchors_ref.not_in(("winner", "procedure_buyers")),
            )
        )

    source = _build(engine, persisted_case)
    payload = factual_fallback(source)
    claims = {claim.claim_id: claim for claim in payload.claims}
    unrelated = {ref for ref in source.facts.evidence_refs if ref.startswith("evidence:v1:")}

    assert unrelated
    location_refs = claims["FACT_LOCATION"].evidence_refs
    publication_refs = claims["FACT_PUBLICATION_DATE"].evidence_refs
    assert location_refs
    assert publication_refs
    assert location_refs[0].startswith("source-field:v1:contract_award:")
    assert location_refs[0].endswith(":place_of_performance")
    assert publication_refs[0].startswith("source-field:v1:source_event:")
    assert publication_refs[0].endswith(":published_on")
    assert set(location_refs).isdisjoint(unrelated)
    assert set(publication_refs).isdisjoint(unrelated)
    assert all(ref.endswith(":place_of_performance") for ref in location_refs)
    assert all(ref.endswith(":published_on") for ref in publication_refs)


def test_input_rejects_an_award_without_a_published_winner(engine, persisted_case):
    with engine.begin() as connection:
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == persisted_case.award_key)
            .values(winner_status="undisclosed", awardee_parties=[])
        )
    _assert_unavailable(engine, persisted_case)


def test_input_preserves_all_published_buyers_without_selecting_a_principal(engine, persisted_case):
    buyers = [
        {"legal_name": "Ville Alpha", "identifiers": [], "country": "FR"},
        {"legal_name": "Commune Beta", "identifiers": [], "country": "FR"},
        {"legal_name": "Ville Alpha", "identifiers": [], "country": "FR"},
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
            .values(procedure_buyers=buyers)
        )

    source = _build(engine, persisted_case)
    assert source.facts.buyer_name == "Ville Alpha ; Commune Beta"
    assert source.facts.winner_name == "SARL ALCIS TRANSPORTS"


def test_input_never_confuses_buyer_and_awardee(engine, persisted_case):
    source = _build(engine, persisted_case)
    payload = factual_fallback(source)

    assert source.facts.buyer_name == "Ville de Saint Orens de Gameville"
    assert source.facts.winner_name == "SARL ALCIS TRANSPORTS"
    assert "Acheteur publié : Ville de Saint Orens de Gameville" in payload.award_summary
    assert "Attributaire publié : SARL ALCIS TRANSPORTS" in payload.award_summary


def test_input_keeps_publication_separate_when_award_date_is_absent(engine):
    with engine.begin() as connection:
        account_id = make_account(connection, "publication-only@test.invalid", "Publication")
        target_icp_id = make_icp(connection, account_id, label="Publication seulement")
        signal = materialize_boamp(
            connection,
            BOAMP_PUBLICATION_ONLY,
            target_icp_id=target_icp_id,
        )
    case = PersistedCase(
        account_id=account_id,
        other_account_id="unused",
        target_icp_id=target_icp_id,
        signal_key=signal.signal_key,
        award_key=signal.materialization_award_key,
    )

    source = _build(engine, case)
    assert source.facts.award_date is None
    assert source.facts.publication_date is not None
    payload = factual_fallback(source)
    assert not any("Date d'attribution publiée" in claim.text for claim in payload.claims)
    assert any("Date de publication" in claim.text for claim in payload.claims)


def test_input_matched_needs_are_copied_from_the_exact_materialized_row(engine, persisted_case):
    with engine.connect() as connection:
        stored = connection.execute(
            sa.select(materialized_signal.c.icp_matched_needs).where(
                materialized_signal.c.signal_key == persisted_case.signal_key
            )
        ).scalar_one()
    source = _build(engine, persisted_case)
    assert source.icp_matched_needs == tuple(stored)
    assert json.loads(source.model_dump_json())["icp_matched_needs"] == stored
