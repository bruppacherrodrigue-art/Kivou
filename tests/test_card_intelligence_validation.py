from __future__ import annotations

import datetime as dt
import hashlib
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
from pydantic import ValidationError

import signals.card_intelligence.validation as validation_module
from signals.accounts.schema import target_icp
from signals.card_intelligence.contracts import (
    CardPresentationPayload,
    ClaimKind,
    PresentationClaim,
    PresentationInput,
    PresentationUnknown,
    PresentationVariant,
    SourceActor,
    SourceFacts,
    TargetIcpSnapshot,
    TargetRole,
    TargetRoleKind,
)
from signals.card_intelligence.fallback import factual_fallback
from signals.card_intelligence.input import (
    PresentationInputUnavailable,
    _source_field_ref,
    build_presentation_input,
)
from signals.card_intelligence.validation import validate_payload
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import (
    contract_award,
    evidence,
    materialized_signal,
    source_event,
)

NOW = dt.datetime(2026, 8, 30, 9, 0, tzinfo=dt.UTC)
AWARD_BINDING = "a" * 64
EVENT_BINDING = "b" * 64
AWARDEE_FIELD_REF = f"source-field:v1:contract_award:sha256-{AWARD_BINDING}:awardee_parties"
BUYER_FIELD_REF = f"source-field:v1:source_event:sha256-{EVENT_BINDING}:procedure_buyers"
AMOUNT_FIELD_REF = f"source-field:v1:contract_award:sha256-{AWARD_BINDING}:amount"
CURRENCY_FIELD_REF = f"source-field:v1:contract_award:sha256-{AWARD_BINDING}:currency"
LOCATION_FIELD_REF = f"source-field:v1:contract_award:sha256-{AWARD_BINDING}:place_of_performance"
AWARD_DATE_FIELD_REF = f"source-field:v1:contract_award:sha256-{AWARD_BINDING}:award_date"
NOTIFICATION_DATE_FIELD_REF = (
    f"source-field:v1:contract_award:sha256-{AWARD_BINDING}:contract_notification_date"
)
PUBLICATION_DATE_FIELD_REF = f"source-field:v1:source_event:sha256-{EVENT_BINDING}:published_on"
DIRECT_FIELD_REFS = (
    AWARDEE_FIELD_REF,
    BUYER_FIELD_REF,
    AMOUNT_FIELD_REF,
    CURRENCY_FIELD_REF,
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
            source_award_binding=AWARD_BINDING,
            source_event_binding=EVENT_BINDING,
            awardees=(SourceActor(actor_ref="1" * 64, display_name="Egli Gartenbau AG Sursee"),),
            buyers=(SourceActor(actor_ref="2" * 64, display_name="Gemeinde Root"),),
            award_title="FOURNITURE LOT 7 ACCORD-CADRE ADMINISTRATIF",
            amount=Decimal("250000.00"),
            currency="CHF",
            location="Root, CH",
            award_date=dt.date(2026, 5, 19),
            contract_notification_date=dt.date(2026, 5, 22),
            publication_date=dt.date(2026, 8, 15),
            source_system="simap",
            source_notice_id="notice-123",
            evidence_refs=DIRECT_FIELD_REFS,
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
    facts = source.facts.model_copy(update={"buyers": ()})
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
    facts = source.facts.model_copy(
        update={
            "awardees": (SourceActor(actor_ref="1" * 64, display_name=long_winner),),
            "buyers": (SourceActor(actor_ref="2" * 64, display_name=long_buyer),),
        }
    )

    payload = factual_fallback(source.model_copy(update={"facts": facts}))
    rendered = payload.model_dump_json()

    assert len(payload.headline) <= 160
    assert len(payload.award_summary) <= 420
    assert all(claim.text.strip() for claim in payload.claims)
    assert "..." not in rendered and "…" not in rendered
    assert "Societe attributaire tres longue Societe" not in rendered
    assert "Collectivite acheteuse tres longue Collectivite" not in rendered


def test_fallback_never_propagates_more_than_sixteen_deceptive_catalog_extras(source):
    deceptive_refs = (
        "evidence:v1:not-winner:not-winner:winner",
        "evidence:v1:space-anchor: winner ",
        *(f"evidence:v1:{index:064x}:winner" for index in range(18)),
    )
    facts_dump = source.facts.model_dump()
    facts_dump["evidence_refs"] = (*DIRECT_FIELD_REFS, *deceptive_refs)
    facts = SourceFacts.model_validate(facts_dump)
    source_dump = source.model_dump()
    source_dump["facts"] = facts
    forged = PresentationInput.model_validate(source_dump)

    payload = factual_fallback(forged)

    claims = {claim.claim_id: claim for claim in payload.claims}
    assert claims["FACT_HEADLINE"].evidence_refs == (AWARDEE_FIELD_REF,)
    assert claims["FACT_AWARD_CONTEXT"].evidence_refs == (
        AWARDEE_FIELD_REF,
        BUYER_FIELD_REF,
    )
    assert claims["FACT_AMOUNT"].evidence_refs == (
        AMOUNT_FIELD_REF,
        CURRENCY_FIELD_REF,
    )
    assert claims["FACT_LOCATION"].evidence_refs == (LOCATION_FIELD_REF,)
    assert claims["FACT_PUBLICATION_DATE"].evidence_refs == (PUBLICATION_DATE_FIELD_REF,)
    surfaced = {ref for claim in payload.claims for ref in claim.evidence_refs} | {
        ref for unknown in payload.unknowns for ref in unknown.evidence_refs
    }
    assert surfaced <= set(DIRECT_FIELD_REFS)
    assert not any(ref.startswith("evidence:v1:") for ref in surfaced)

    absent_dump = facts.model_dump()
    absent_dump["buyers"] = ()
    absent_facts = SourceFacts.model_validate(absent_dump)
    absent_source_dump = forged.model_dump()
    absent_source_dump["facts"] = absent_facts
    absent_payload = factual_fallback(PresentationInput.model_validate(absent_source_dump))
    absent_claims = {claim.claim_id: claim for claim in absent_payload.claims}
    assert BUYER_FIELD_REF in absent_claims["FACT_AWARD_CONTEXT"].evidence_refs
    buyer_unknown = next(
        unknown for unknown in absent_payload.unknowns if "Acheteur" in unknown.text
    )
    assert buyer_unknown.evidence_refs == (BUYER_FIELD_REF,)


def test_fallback_unknowns_are_bounded_proven_and_only_describe_absent_facts(source):
    assert factual_fallback(source).unknowns == ()
    facts = source.facts.model_copy(
        update={
            "buyers": (),
            "amount": None,
            "currency": None,
            "location": None,
            "award_date": None,
            "contract_notification_date": None,
            "publication_date": None,
        }
    )

    unknowns = factual_fallback(source.model_copy(update={"facts": facts})).unknowns

    assert len(unknowns) == 6
    assert len(unknowns) <= 8
    assert all(unknown.text and len(unknown.text) <= 240 for unknown in unknowns)
    assert all(unknown.evidence_refs for unknown in unknowns)

    by_text = {unknown.text: unknown for unknown in unknowns}
    assert by_text["Acheteur non publié."].evidence_refs == (BUYER_FIELD_REF,)
    assert by_text["Montant non publié."].evidence_refs == (
        AMOUNT_FIELD_REF,
        CURRENCY_FIELD_REF,
    )
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
    with pytest.raises(ValueError, match="source-field evidence"):
        factual_fallback(source.model_copy(update={"facts": facts}))


def test_fallback_rejects_multiple_direct_refs_for_one_source_field(source):
    duplicate = "source-field:v1:contract_award:another-award:awardee_parties"
    facts = source.facts.model_copy(
        update={"evidence_refs": (*source.facts.evidence_refs, duplicate)}
    )
    with pytest.raises(ValueError, match="source-field evidence"):
        factual_fallback(source.model_copy(update={"facts": facts}))


@pytest.mark.parametrize(
    ("owned_ref", "owned_binding"),
    (
        (AWARDEE_FIELD_REF, AWARD_BINDING),
        (BUYER_FIELD_REF, EVENT_BINDING),
    ),
    ids=("award", "event"),
)
def test_fallback_rejects_a_source_field_ref_bound_to_another_source_row(
    source, owned_ref, owned_binding
):
    foreign = owned_ref.replace(owned_binding, "c" * 64)
    refs = tuple(foreign if ref == owned_ref else ref for ref in source.facts.evidence_refs)
    facts = source.facts.model_copy(update={"evidence_refs": refs})
    with pytest.raises(ValidationError, match="source-field evidence"):
        factual_fallback(source.model_copy(update={"facts": facts}))


def test_fallback_rejects_a_malformed_source_field_column(source):
    malformed = AWARDEE_FIELD_REF.removesuffix("awardee_parties") + "description"
    refs = tuple(
        malformed if ref == AWARDEE_FIELD_REF else ref for ref in source.facts.evidence_refs
    )
    facts = source.facts.model_copy(update={"evidence_refs": refs})
    with pytest.raises(ValidationError, match="source-field evidence"):
        factual_fallback(source.model_copy(update={"facts": facts}))


def test_source_field_binding_hashes_exact_key_bytes_without_whitespace_normalization():
    first_key = "award key"
    second_key = "award  key"
    first = _source_field_ref(table="contract_award", row_key=first_key, column="award_date")
    second = _source_field_ref(table="contract_award", row_key=second_key, column="award_date")

    assert first != second
    assert f"sha256-{hashlib.sha256(first_key.encode('utf-8')).hexdigest()}" in first
    assert f"sha256-{hashlib.sha256(second_key.encode('utf-8')).hexdigest()}" in second


@pytest.mark.parametrize(
    "invalid_source",
    (
        lambda source: source.model_copy(update={"language": "de"}),
        lambda source: source.model_copy(
            update={"facts": source.facts.model_copy(update={"award_date": "2026-05-19"})}
        ),
        lambda source: source.model_copy(
            update={"facts": source.facts.model_copy(update={"amount": None})}
        ),
        lambda source: source.model_copy(
            update={
                "facts": source.facts.model_copy(
                    update={
                        "evidence_refs": (
                            *source.facts.evidence_refs,
                            source.facts.evidence_refs[0],
                        )
                    }
                )
            }
        ),
    ),
    ids=("language", "date-type", "amount-currency", "duplicate-evidence"),
)
def test_fallback_revalidates_every_input_contract(source, invalid_source):
    with pytest.raises(ValidationError):
        factual_fallback(invalid_source(source))


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
    assert len(source.facts.evidence_refs) == 8
    assert all(ref.startswith("source-field:v1:") for ref in source.facts.evidence_refs)
    assert source.facts.evidence_refs[0].endswith(":awardee_parties")
    assert source.facts.evidence_refs[1].endswith(":procedure_buyers")
    assert source.facts.evidence_refs[2].endswith(":amount")
    assert source.facts.evidence_refs[3].endswith(":currency")
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


def test_input_rejects_active_but_structurally_incomplete_icp(engine, persisted_case):
    with engine.begin() as connection:
        connection.execute(
            sa.update(target_icp)
            .where(target_icp.c.target_icp_id == persisted_case.target_icp_id)
            .values(customer_input={})
        )

    _assert_unavailable(engine, persisted_case)


def test_input_closes_actual_malformed_sql_json_at_the_result_boundary(engine, persisted_case):
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE target_icp SET customer_input = ? WHERE target_icp_id = ?",
            ("{", persisted_case.target_icp_id),
        )

    _assert_unavailable(engine, persisted_case)


def test_input_closes_actual_malformed_sql_date_at_the_result_boundary(engine, persisted_case):
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE contract_award SET award_date = ? WHERE award_key = ?",
            ("not-a-date", persisted_case.award_key),
        )

    _assert_unavailable(engine, persisted_case)


def test_input_does_not_hide_operational_sqlalchemy_errors(engine, persisted_case):
    connection = engine.connect()
    connection.close()

    with pytest.raises(sa.exc.ResourceClosedError):
        build_presentation_input(
            connection,
            account_id=persisted_case.account_id,
            signal_key=persisted_case.signal_key,
            language="fr",
        )


def test_input_rejects_an_award_without_persisted_evidence(engine, persisted_case):
    with engine.begin() as connection:
        connection.execute(
            sa.delete(evidence).where(evidence.c.award_key == persisted_case.award_key)
        )
    _assert_unavailable(engine, persisted_case)


@pytest.mark.parametrize(
    ("evidence_key", "anchors_ref"),
    (
        ("space-anchor", " winner "),
        ("suffix-spoof", "not-winner:winner"),
        (" malformed:key ", "winner"),
    ),
    ids=("anchor-whitespace", "anchor-suffix", "malformed-key"),
)
def test_persisted_evidence_is_only_an_existence_gate_and_never_public(
    engine, persisted_case, evidence_key, anchors_ref
):
    with engine.begin() as connection:
        template = (
            connection.execute(
                sa.select(evidence).where(evidence.c.award_key == persisted_case.award_key).limit(1)
            )
            .mappings()
            .one()
        )
        connection.execute(
            sa.delete(evidence).where(evidence.c.award_key == persisted_case.award_key)
        )
        gate_row = dict(template)
        gate_row.update(
            evidence_key=evidence_key,
            anchors_kind="award_fact",
            anchors_ref=anchors_ref,
        )
        connection.execute(sa.insert(evidence).values(**gate_row))

    source = _build(engine, persisted_case)
    payload = factual_fallback(source)

    assert len(source.facts.evidence_refs) == 8
    assert all(ref.startswith("source-field:v1:") for ref in source.facts.evidence_refs)
    rendered = payload.model_dump_json()
    assert "evidence:v1:" not in rendered
    assert evidence_key not in rendered
    assert anchors_ref not in rendered
    assert all(
        ref in source.facts.evidence_refs for claim in payload.claims for ref in claim.evidence_refs
    )


def test_input_rejects_an_award_without_a_published_winner(engine, persisted_case):
    with engine.begin() as connection:
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == persisted_case.award_key)
            .values(winner_status="undisclosed", awardee_parties=[])
        )
    _assert_unavailable(engine, persisted_case)


def _persist_homonymous_actors(engine, persisted_case):
    first = {
        "legal_name": "Entreprise Homonyme SA",
        "identifiers": [{"scheme": "SIRET", "value": "11111111111111"}],
        "country": "FR",
    }
    second = {
        "legal_name": "Entreprise Homonyme SA",
        "identifiers": [{"scheme": "SIRET", "value": "22222222222222"}],
        "country": "FR",
    }
    buyers = [first, second, first]
    awardees = [
        {
            "is_group": True,
            "members": [
                {"role": "consortium_lead", "organization": first},
                {"role": "consortium_member", "organization": second},
                {"role": "consortium_member", "organization": first},
            ],
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
            .values(procedure_buyers=buyers)
        )
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == persisted_case.award_key)
            .values(awardee_parties=awardees)
        )
    return first, second


def _actor_ref(organization):
    canonical = json.dumps(
        organization,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_input_preserves_homonymous_actors_and_only_deduplicates_exact_identity(
    engine, persisted_case
):
    first, second = _persist_homonymous_actors(engine, persisted_case)

    source = _build(engine, persisted_case)

    assert source.facts.awardees == (
        SourceActor(actor_ref=_actor_ref(first), display_name="Entreprise Homonyme SA"),
        SourceActor(actor_ref=_actor_ref(second), display_name="Entreprise Homonyme SA"),
    )
    assert source.facts.buyers == source.facts.awardees
    assert source.facts.awardees[0].actor_ref != source.facts.awardees[1].actor_ref


@pytest.mark.parametrize(
    ("language", "buyer_label", "awardee_label", "separator"),
    (
        ("fr", "Acheteurs publiés", "Attributaires publiés", " : "),
        ("en", "Published buyers", "Published awardees", ": "),
    ),
)
def test_fallback_renders_structured_actor_cardinality_without_identity_leaks(
    engine, persisted_case, language, buyer_label, awardee_label, separator
):
    _persist_homonymous_actors(engine, persisted_case)
    source = _build(engine, persisted_case)
    source = PresentationInput.model_validate({**source.model_dump(), "language": language})

    payload = factual_fallback(source)
    rendered = payload.model_dump_json()

    assert f"{buyer_label}{separator}Entreprise Homonyme SA ; Entreprise Homonyme SA" in rendered
    assert f"{awardee_label}{separator}Entreprise Homonyme SA ; Entreprise Homonyme SA" in rendered
    assert "actor_ref" not in rendered
    assert "identifiers" not in rendered
    assert "11111111111111" not in rendered
    assert "22222222222222" not in rendered


def test_input_fails_closed_above_the_actor_cardinality_bound(engine, persisted_case):
    buyers = [
        {
            "legal_name": f"Acheteur {index}",
            "identifiers": [{"scheme": "SIRET", "value": f"{index:014d}"}],
            "country": "FR",
        }
        for index in range(17)
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


def _full_payload(source: PresentationInput) -> CardPresentationPayload:
    headline = f"Attribution publiée pour {source.facts.winner_name}."
    buyer = source.facts.buyer_name or "Acheteur non publié"
    award_summary = f"Acheteur : {buyer}. Attributaire : {source.facts.winner_name}."
    commercial_importance = "Les matériaux représentent une opportunité commerciale à examiner."
    fit_reason = "L'adéquation concerne le besoin ICP de matériaux."
    timing = "Le calendrier commercial reste à vérifier."
    recommended_action = "Examiner le besoin de matériaux avec la fonction achats."
    return CardPresentationPayload(
        variant=PresentationVariant.FULL,
        headline=headline,
        award_summary=award_summary,
        commercial_importance=commercial_importance,
        fit_reason=fit_reason,
        timing=timing,
        recommended_action=recommended_action,
        target_roles=(
            TargetRole(
                role=TargetRoleKind.PROCUREMENT_MANAGER,
                rationale="Le besoin de matériaux relève de la fonction achats.",
                evidence_refs=(AWARDEE_FIELD_REF,),
            ),
        ),
        fit_need_categories=("materials_or_components",),
        claims=(
            PresentationClaim(
                claim_id="FACT_HEADLINE",
                kind=ClaimKind.FACT,
                text=headline,
                evidence_refs=(AWARDEE_FIELD_REF,),
            ),
            PresentationClaim(
                claim_id="FACT_AWARD_CONTEXT",
                kind=ClaimKind.FACT,
                text=award_summary,
                evidence_refs=DIRECT_FIELD_REFS,
            ),
            PresentationClaim(
                claim_id="INFERENCE_IMPORTANCE",
                kind=ClaimKind.INFERENCE,
                text=commercial_importance,
                evidence_refs=(AWARDEE_FIELD_REF,),
                confidence="medium",
            ),
            PresentationClaim(
                claim_id="INFERENCE_FIT",
                kind=ClaimKind.INFERENCE,
                text=fit_reason,
                evidence_refs=(AWARDEE_FIELD_REF,),
                confidence="medium",
            ),
            PresentationClaim(
                claim_id="INFERENCE_TIMING",
                kind=ClaimKind.INFERENCE,
                text=timing,
                evidence_refs=(PUBLICATION_DATE_FIELD_REF,),
                confidence="low",
            ),
            PresentationClaim(
                claim_id="RECOMMENDATION_ACTION",
                kind=ClaimKind.RECOMMENDATION,
                text=recommended_action,
                evidence_refs=(AWARDEE_FIELD_REF,),
            ),
        ),
    )


def _replace_public_text(
    payload: CardPresentationPayload,
    field: str,
    text: str,
) -> CardPresentationPayload:
    data = payload.model_dump(mode="python")
    old_text = data[field]
    data[field] = text
    for claim in data["claims"]:
        if claim["text"] == old_text:
            claim["text"] = text
            break
    return CardPresentationPayload.model_validate(data)


def _assert_full_semantics_clean(
    payload: CardPresentationPayload,
    source: PresentationInput,
) -> None:
    """FULL controls may prove semantics, but FULL is not publishable yet."""

    result = validate_payload(payload, source)

    assert not result.valid
    assert result.errors == ("full_variant_not_authorized",)


def _source_with_actors(
    source: PresentationInput,
    *,
    buyers: tuple[SourceActor, ...],
    awardees: tuple[SourceActor, ...],
    award_date: dt.date | None = dt.date(2026, 5, 19),
) -> PresentationInput:
    facts = source.facts.model_copy(
        update={"buyers": buyers, "awardees": awardees, "award_date": award_date}
    )
    return PresentationInput.model_validate(source.model_copy(update={"facts": facts}))


@pytest.fixture
def full_payload(source) -> CardPresentationPayload:
    return _full_payload(source)


@pytest.fixture
def source_without_award_date(source) -> PresentationInput:
    return _source_with_actors(
        source,
        buyers=(SourceActor(actor_ref="3" * 64, display_name="Ville de Sion"),),
        awardees=(SourceActor(actor_ref="4" * 64, display_name="Acheteur SA"),),
        award_date=None,
    )


@pytest.mark.parametrize(
    ("claim", "expected_error"),
    (
        (
            "La société Acheteur SA a attribué le marché à Ville de Sion le 12 août 2026.",
            "actor_role_inversion",
        ),
        ("Marché attribué le 15 août 2026.", "award_date_unbound"),
        ("Marché attribué le 15 août 26.", "award_date_unbound"),
        ("Awarded on August 15, 2026.", "award_date_unbound"),
        ("Attribution du 15/08/2026 confirmée.", "award_date_unbound"),
        (
            "Besoin urgent de personnel pour livrer les matériaux.",
            "materials_staffing_mismatch",
        ),
    ),
    ids=(
        "roles-inverted",
        "fr-long-date",
        "fr-two-digit-year",
        "en-long-date",
        "numeric-date",
        "materials-to-staffing",
    ),
)
def test_adversarial_claims_fail_closed(
    source_without_award_date, claim, expected_error
):
    payload = _replace_public_text(
        _full_payload(source_without_award_date), "award_summary", claim
    )

    result = validate_payload(payload, source_without_award_date)

    assert expected_error in result.errors


@pytest.mark.parametrize(
    "claim",
    (
        "Date d'attribution : 19 mai 2026.",
        "Attribution du 19/05/2026 confirmée.",
        "Attribué le 19-05-26.",
        "Awarded on May 19, 2026.",
        "Award date: 2026-05-19.",
        "Date de notification du contrat : 22 mai 2026.",
        "Contract notification date: May 22, 26.",
        "Date de publication : 15 août 2026.",
        "Date de publication : 15 aout 26.",
        "Publication date: August 15, 2026.",
    ),
    ids=(
        "award-fr-name",
        "award-fr-slash",
        "award-fr-dash-short-year",
        "award-en-name",
        "award-iso",
        "notification-fr",
        "notification-en-short-year",
        "publication-fr-accented",
        "publication-fr-unaccented-short-year",
        "publication-en",
    ),
)
def test_localized_dates_pass_only_when_bound_to_the_exact_source_field(
    source, full_payload, claim
):
    payload = _replace_public_text(full_payload, "award_summary", claim)

    _assert_full_semantics_clean(payload, source)


def test_publication_date_cannot_be_presented_as_the_award_date(source, full_payload):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        "Date d'attribution : 15 août 2026.",
    )

    errors = validate_payload(payload, source).errors

    assert "award_date_mismatch" in errors
    assert "publication_as_award_date" in errors


@pytest.mark.parametrize(
    "claim",
    (
        "Date d'attribution du projet : 15 août 2026.",
        "Award date for project: August 15, 2026.",
    ),
    ids=("fr", "en"),
)
def test_project_word_never_neutralizes_a_semantic_award_date(
    source, full_payload, claim
):
    payload = _replace_public_text(full_payload, "award_summary", claim)

    errors = validate_payload(payload, source).errors

    assert "award_date_mismatch" in errors
    assert "publication_as_award_date" in errors
    assert "full_variant_not_authorized" in errors


def test_postfixed_award_marker_overrides_a_project_reference_context(
    source, full_payload
):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        "Référence projet : 2026-08-15 est la date d’attribution.",
    )

    errors = validate_payload(payload, source).errors

    assert "award_date_mismatch" in errors
    assert "publication_as_award_date" in errors
    assert "full_variant_not_authorized" in errors


def test_a_real_date_without_a_semantic_date_kind_fails_closed(source, full_payload):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        "Dossier examiné le 19 mai 2026.",
    )

    assert "date_semantics_unbound" in validate_payload(payload, source).errors


def test_invalid_calendar_date_fails_closed(source, full_payload):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        "Date d'attribution : 31 février 2026.",
    )

    assert "date_invalid" in validate_payload(payload, source).errors


@pytest.mark.parametrize(
    "claim",
    (
        "Montant publié : 250 000 CHF.",
        "Code postal de référence : 1200.",
        "Référence CPV 44110000 et projet 2026.",
    ),
    ids=("amount", "postcode", "cpv-project"),
)
def test_isolated_amount_postcode_and_project_numbers_are_not_dates(
    source, full_payload, claim
):
    payload = _replace_public_text(full_payload, "award_summary", claim)

    _assert_full_semantics_clean(payload, source)


def test_factual_renderer_output_passes_the_same_validator(source):
    assert validate_payload(factual_fallback(source), source).valid


@pytest.mark.parametrize("language", ("fr", "en"))
@pytest.mark.parametrize(
    "location",
    ("New York, US", "La Chaux-de-Fonds, CH", "Saint Gallen, CH"),
)
def test_canonical_fallback_structured_locations_bypass_text_heuristics(
    source, language, location
):
    facts = source.facts.model_copy(update={"location": location})
    localized_source = PresentationInput.model_validate(
        source.model_copy(update={"language": language, "facts": facts})
    )
    payload = factual_fallback(localized_source)

    assert validate_payload(payload, localized_source).valid


def test_canonical_fallback_accepts_exact_prefix_related_source_actors(source):
    facts = source.facts.model_copy(
        update={
            "awardees": (
                SourceActor(actor_ref="7" * 64, display_name="Alpha Construction"),
                SourceActor(
                    actor_ref="8" * 64,
                    display_name="Alpha Construction Services SA",
                ),
            )
        }
    )
    actor_source = PresentationInput.model_validate(
        source.model_copy(update={"facts": facts})
    )
    payload = factual_fallback(actor_source)

    assert validate_payload(payload, actor_source).valid


def test_canonical_fallback_does_not_treat_an_awardee_title_as_admin_copy(source):
    facts = source.facts.model_copy(update={"award_title": source.facts.winner_name})
    titled_source = PresentationInput.model_validate(
        source.model_copy(update={"facts": facts})
    )
    payload = factual_fallback(titled_source)

    assert validate_payload(payload, titled_source).valid


def test_canonical_fallback_validation_is_non_rewriting(source):
    payload = factual_fallback(source)
    payload_before = payload.model_dump(mode="python")
    source_before = source.model_dump(mode="python")

    result = validate_payload(payload, source)

    assert result.valid
    assert payload.model_dump(mode="python") == payload_before
    assert source.model_dump(mode="python") == source_before


@pytest.mark.parametrize("error_type", (TypeError, AttributeError))
def test_internal_fallback_renderer_errors_propagate(
    source, monkeypatch, error_type
):
    payload = factual_fallback(source)

    def broken_renderer(_source):
        raise error_type("renderer defect")

    monkeypatch.setattr(validation_module, "factual_fallback", broken_renderer)

    with pytest.raises(error_type, match="renderer defect"):
        validate_payload(payload, source)


def test_full_variant_is_not_authorized_without_an_approved_generation_pipeline(
    source, full_payload
):
    result = validate_payload(full_payload, source)

    assert not result.valid
    assert result.errors == ("full_variant_not_authorized",)


@pytest.mark.parametrize(
    "surface",
    ("headline", "claim", "claim-evidence", "unknown"),
)
def test_only_the_exact_canonical_factual_fallback_is_publishable(source, surface):
    canonical = factual_fallback(source)
    data = canonical.model_dump(mode="python")
    if surface == "headline":
        old_headline = data["headline"]
        data["headline"] = f"{old_headline} vérifiée"
        next(
            claim for claim in data["claims"] if claim["text"] == old_headline
        )["text"] = data["headline"]
    elif surface == "claim":
        data["claims"] = (
            *data["claims"],
            PresentationClaim(
                claim_id="FACT_LOTS",
                kind=ClaimKind.FACT,
                text="Le marché comporte 99 lots.",
                evidence_refs=(AWARDEE_FIELD_REF,),
            ),
        )
    elif surface == "claim-evidence":
        data["claims"][0]["evidence_refs"] = (
            AWARDEE_FIELD_REF,
            AMOUNT_FIELD_REF,
        )
    else:
        data["unknowns"] = (
            PresentationUnknown(
                text="Nombre de lots non publié.",
                evidence_refs=(AWARDEE_FIELD_REF,),
            ),
        )
    candidate = CardPresentationPayload.model_validate(data)

    result = validate_payload(candidate, source)

    assert not result.valid
    assert "factual_fallback_not_canonical" in result.errors


@pytest.mark.parametrize(
    ("claim", "expected_error"),
    (
        ("Examiner ce dossier en urgence.", "unsupported_urgency"),
        ("Proceed immediately with this opportunity.", "unsupported_urgency"),
        ("Contact ASAP.", "unsupported_urgency"),
        ("Emergency procurement response required.", "unsupported_urgency"),
        ("Contacter Mme Dupont.", "invented_person"),
        ("Contact Jane Doe.", "invented_person"),
        ("Cette attribution garantit une vente.", "unsupported_certainty"),
        ("This opportunity will definitely convert.", "unsupported_certainty"),
    ),
    ids=(
        "urgent-fr",
        "immediate-en",
        "asap",
        "emergency",
        "honorific-fr",
        "named-contact-en",
        "guarantee-fr",
        "certainty-en",
    ),
)
def test_urgency_people_and_absolute_certainty_are_never_invented(
    source, full_payload, claim, expected_error
):
    payload = _replace_public_text(full_payload, "recommended_action", claim)

    assert expected_error in validate_payload(payload, source).errors


def test_unicode_actor_labels_are_matched_by_exact_normalized_role(source):
    localized_source = _source_with_actors(
        source,
        buyers=(SourceActor(actor_ref="5" * 64, display_name="Énergie   Genève SA"),),
        awardees=(SourceActor(actor_ref="6" * 64, display_name="Bâtiments Réunis SA"),),
    )
    payload = _replace_public_text(
        _full_payload(localized_source),
        "award_summary",
        "ACHETEUR : Energie Geneve SA. ATTRIBUTAIRE : Batiments Reunis SA.",
    )

    _assert_full_semantics_clean(payload, localized_source)


def test_explicit_actor_labels_cannot_swap_buyer_and_awardee(source, full_payload):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        "Acheteur : Egli Gartenbau AG Sursee. Attributaire : Gemeinde Root.",
    )

    assert "actor_role_inversion" in validate_payload(payload, source).errors


@pytest.mark.parametrize(
    "claim",
    (
        "Egli Gartenbau AG Sursee est l’acheteur",
        "Egli Gartenbau AG Sursee is the buyer",
        "L’acheteur est Egli Gartenbau AG Sursee",
        "The awardee is Gemeinde Root",
    ),
    ids=("actor-first-fr", "actor-first-en", "role-first-fr", "role-first-en"),
)
def test_copular_role_assertions_cannot_invert_buyer_and_awardee(
    source, full_payload, claim
):
    payload = _replace_public_text(full_payload, "award_summary", claim)

    errors = validate_payload(payload, source).errors

    assert "actor_role_inversion" in errors
    assert "full_variant_not_authorized" in errors


def test_cross_role_homonym_is_ambiguous(source):
    homonym_source = _source_with_actors(
        source,
        buyers=(SourceActor(actor_ref="7" * 64, display_name="Entreprise Homonyme SA"),),
        awardees=(SourceActor(actor_ref="8" * 64, display_name="Entreprise Homonyme SA"),),
    )

    errors = validate_payload(_full_payload(homonym_source), homonym_source).errors

    assert "actor_role_ambiguous" in errors


def test_distinct_homonymous_identities_in_one_role_remain_representable(source):
    same_role_source = _source_with_actors(
        source,
        buyers=(
            SourceActor(actor_ref="7" * 64, display_name="Entreprise Homonyme SA"),
            SourceActor(actor_ref="8" * 64, display_name="Entreprise Homonyme SA"),
        ),
        awardees=(SourceActor(actor_ref="9" * 64, display_name="Attributaire Unique SA"),),
    )

    _assert_full_semantics_clean(_full_payload(same_role_source), same_role_source)


@pytest.mark.parametrize(
    "buyer_assertion",
    (
        "Acheteur : Alpha Construction ; Alpha Construction Services SA.",
        "Acheteur : Alpha Construction et Alpha Construction Services SA.",
        "Acheteur : Alpha Construction.",
    ),
    ids=("separator", "conjunction", "end"),
)
def test_exact_short_actor_is_not_a_prefix_collision(
    source, buyer_assertion
):
    actor_source = _source_with_actors(
        source,
        buyers=(
            SourceActor(actor_ref="7" * 64, display_name="Alpha Construction"),
            SourceActor(
                actor_ref="8" * 64,
                display_name="Alpha Construction Services SA",
            ),
        ),
        awardees=(SourceActor(actor_ref="9" * 64, display_name="Bêta Bâtiment SA"),),
    )
    payload = _replace_public_text(
        _full_payload(actor_source),
        "award_summary",
        f"{buyer_assertion} Attributaire : Bêta Bâtiment SA.",
    )

    _assert_full_semantics_clean(payload, actor_source)


def test_truncated_actor_prefix_collision_fails_ambiguous(source):
    collision_source = _source_with_actors(
        source,
        buyers=(
            SourceActor(actor_ref="7" * 64, display_name="Alpha Construction SA"),
            SourceActor(actor_ref="8" * 64, display_name="Alpha Construction Services SA"),
        ),
        awardees=(SourceActor(actor_ref="9" * 64, display_name="Bêta Bâtiment SA"),),
    )
    payload = _replace_public_text(
        _full_payload(collision_source),
        "award_summary",
        "Acheteur : Alpha Construction… Attributaire : Bêta Bâtiment SA.",
    )

    assert "actor_reference_ambiguous" in validate_payload(payload, collision_source).errors


def test_single_actor_truncation_with_ellipsis_fails_ambiguous(source, full_payload):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        "Attributaire : Egli Gartenbau…",
    )

    assert "actor_reference_ambiguous" in validate_payload(payload, source).errors


@pytest.mark.parametrize(
    ("buyer_name", "claim"),
    (
        ("AG", "Diagnostic documenté."),
        ("Ville de Sion", "Lieu : Ville de Sionnet."),
    ),
    ids=("short-substring", "word-boundary"),
)
def test_actor_name_substrings_never_match_another_actor(
    source, buyer_name, claim
):
    bounded_source = _source_with_actors(
        source,
        buyers=(SourceActor(actor_ref="7" * 64, display_name=buyer_name),),
        awardees=(SourceActor(actor_ref="9" * 64, display_name="Bêta Bâtiment SA"),),
    )
    payload = _replace_public_text(
        _full_payload(bounded_source), "award_summary", claim
    )

    _assert_full_semantics_clean(payload, bounded_source)


def test_materials_cannot_be_rewritten_as_staffing(source, full_payload):
    payload = _replace_public_text(
        full_payload,
        "fit_reason",
        "Le besoin de personnel découle des matériaux à livrer.",
    )

    errors = validate_payload(payload, source).errors

    assert "materials_staffing_mismatch" in errors
    assert "commercial_claim_unbound_to_icp" in errors


def test_actor_names_are_masked_before_materials_staffing_validation(source):
    legal_name_source = _source_with_actors(
        source,
        buyers=source.facts.buyers,
        awardees=(SourceActor(actor_ref="9" * 64, display_name="Personnel Matériaux SA"),),
    )

    _assert_full_semantics_clean(_full_payload(legal_name_source), legal_name_source)


def test_materials_claim_without_staffing_has_no_semantic_error(source, full_payload):
    _assert_full_semantics_clean(full_payload, source)


def test_fit_categories_must_be_an_exact_subset_of_current_matched_needs(
    source, full_payload
):
    data = full_payload.model_dump(mode="python")
    data["fit_need_categories"] = (
        "materials_or_components",
        "workforce_capacity",
    )
    payload = CardPresentationPayload.model_validate(data)

    assert "fit_need_unmatched" in validate_payload(payload, source).errors


def test_commercial_claims_must_name_a_current_icp_need(source, full_payload):
    payload = _replace_public_text(
        full_payload,
        "commercial_importance",
        "Cette opportunité mérite une analyse commerciale.",
    )

    assert "commercial_claim_unbound_to_icp" in validate_payload(payload, source).errors


def test_additional_commercial_claims_cannot_introduce_an_unmatched_need(
    source, full_payload
):
    extra = PresentationClaim(
        claim_id="INFERENCE_EXTRA",
        kind=ClaimKind.INFERENCE,
        text="La location d'équipement constitue une autre opportunité.",
        evidence_refs=(AWARDEE_FIELD_REF,),
        confidence="low",
    )
    payload = CardPresentationPayload.model_validate(
        full_payload.model_copy(update={"claims": (*full_payload.claims, extra)})
    )

    assert "commercial_claim_unbound_to_icp" in validate_payload(payload, source).errors


def test_matched_need_must_still_be_backed_by_the_captured_customer_icp(
    source, full_payload
):
    staffing_icp = source.target_icp_customer_input.model_copy(
        update={"offers": ("staffing_and_labour",)}
    )
    forged_source = PresentationInput.model_validate(
        source.model_copy(update={"target_icp_customer_input": staffing_icp})
    )

    assert "icp_need_unbound" in validate_payload(full_payload, forged_source).errors


@pytest.mark.parametrize("surface", ("claim", "role", "unknown"))
def test_claim_role_and_unknown_evidence_stay_inside_the_closed_catalog(
    source, full_payload, surface
):
    foreign = "source-field:v1:contract_award:sha256-" + "f" * 64 + ":amount"
    data = full_payload.model_dump(mode="python")
    if surface == "claim":
        data["claims"][0]["evidence_refs"] = (foreign,)
    elif surface == "role":
        data["target_roles"][0]["evidence_refs"] = (foreign,)
    else:
        data["unknowns"] = (
            PresentationUnknown(text="Information non publiée.", evidence_refs=(foreign,)),
        )
    payload = CardPresentationPayload.model_validate(data)

    assert "evidence_ref_unknown" in validate_payload(payload, source).errors


def test_forged_nested_payload_fails_closed_without_raising(source, full_payload):
    forged_claim = full_payload.claims[0].model_copy(update={"evidence_refs": ()})
    forged_payload = full_payload.model_copy(
        update={"claims": (forged_claim, *full_payload.claims[1:])}
    )

    result = validate_payload(forged_payload, source)

    assert not result.valid
    assert "payload_contract_invalid" in result.errors


def test_forged_nested_source_fails_closed_without_raising(source, full_payload):
    forged_facts = source.facts.model_copy(update={"amount": None})
    forged_source = source.model_copy(update={"facts": forged_facts})

    result = validate_payload(full_payload, forged_source)

    assert not result.valid
    assert "source_contract_invalid" in result.errors


def test_validation_never_rewrites_payload_or_source(source, full_payload):
    payload_before = full_payload.model_dump(mode="python")
    source_before = source.model_dump(mode="python")

    first = validate_payload(full_payload, source)
    second = validate_payload(full_payload, source)

    assert first == second
    assert first.errors == tuple(sorted(set(first.errors)))
    assert full_payload.model_dump(mode="python") == payload_before
    assert source.model_dump(mode="python") == source_before


def test_source_proven_legal_actor_names_are_masked_from_copy_heuristics(source):
    legal_name_source = _source_with_actors(
        source,
        buyers=source.facts.buyers,
        awardees=(SourceActor(actor_ref="9" * 64, display_name="Dr Urgence Garantie SA"),),
    )

    _assert_full_semantics_clean(_full_payload(legal_name_source), legal_name_source)


def test_date_semantics_never_bleed_between_distinct_public_fields(source, full_payload):
    headline = _replace_public_text(
        full_payload,
        "headline",
        "Attribution publiée pour Egli Gartenbau AG Sursee",
    )
    payload = _replace_public_text(
        headline,
        "award_summary",
        "Dossier examiné le 1 janvier 2025.",
    )

    errors = validate_payload(payload, source).errors

    assert "date_semantics_unbound" in errors
    assert "award_date_mismatch" not in errors


def test_normalized_raw_administrative_title_is_never_republished(
    source, full_payload
):
    payload = _replace_public_text(
        full_payload,
        "headline",
        "Fourniture lot 7 accord cadre administratif",
    )

    assert "administrative_title_reused" in validate_payload(payload, source).errors


def test_administrative_title_check_does_not_match_a_numeric_fragment(
    source, full_payload
):
    facts = source.facts.model_copy(update={"award_title": "LOT 7"})
    numeric_source = PresentationInput.model_validate(
        source.model_copy(update={"facts": facts})
    )
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        "Montant documenté : 250 000 CHF pour le projet 1200.",
    )

    _assert_full_semantics_clean(payload, numeric_source)


def test_claimed_amount_must_equal_the_typed_source_value(source, full_payload):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        "Montant publié : 999999 CHF.",
    )

    assert "amount_value_mismatch" in validate_payload(payload, source).errors


def test_actor_claim_must_cite_the_actor_source_field(source, full_payload):
    data = full_payload.model_dump(mode="python")
    headline_claim = next(
        claim for claim in data["claims"] if claim["text"] == data["headline"]
    )
    headline_claim["evidence_refs"] = (AMOUNT_FIELD_REF,)
    payload = CardPresentationPayload.model_validate(data)

    assert "claim_evidence_mismatch" in validate_payload(payload, source).errors


@pytest.mark.parametrize(
    "claim",
    (
        "Acheteur : Société Inventée SA.",
        "Attributaire : Egli Gartenbau.",
    ),
    ids=("unknown-buyer", "truncated-awardee"),
)
def test_every_labeled_actor_assertion_resolves_exactly_to_its_source_role(
    source, full_payload, claim
):
    payload = _replace_public_text(full_payload, "award_summary", claim)

    assert "actor_reference_unbound" in validate_payload(payload, source).errors


def test_every_actor_in_a_labeled_role_list_must_match_the_exact_source_role(
    source, full_payload
):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        (
            "Acheteur : SOCIETE INVENTEE SA et Gemeinde Root. "
            "Attributaire : Egli Gartenbau AG Sursee."
        ),
    )

    errors = validate_payload(payload, source).errors

    assert "actor_reference_unbound" in errors
    assert "full_variant_not_authorized" in errors


@pytest.mark.parametrize(
    ("claim", "expected_error"),
    (
        ("Contacter jean dupont pour le suivi.", "invented_person"),
        ("Jean Dupont suivra ce dossier.", "invented_person"),
        ("Traiter ce dossier en priorité.", "unsupported_urgency"),
        ("La vente issue de cette attribution est assurée.", "unsupported_certainty"),
    ),
    ids=(
        "lowercase-contact",
        "named-owner",
        "priority-urgency",
        "assured-sale",
    ),
)
def test_lowercase_people_priority_and_assured_outcomes_fail_closed(
    source, full_payload, claim, expected_error
):
    payload = _replace_public_text(full_payload, "recommended_action", claim)

    assert expected_error in validate_payload(payload, source).errors


@pytest.mark.parametrize(
    "claim",
    (
        "jean dupont suivra le besoin de matériaux.",
        "Répondre sans attendre au besoin de matériaux.",
        "La vente de matériaux est acquise.",
    ),
    ids=("lowercase-owner", "without-waiting", "sale-acquired"),
)
def test_unapproved_full_copy_cannot_bypass_publication_by_rephrasing(
    source, full_payload, claim
):
    payload = _replace_public_text(full_payload, "recommended_action", claim)

    result = validate_payload(payload, source)

    assert not result.valid
    assert "full_variant_not_authorized" in result.errors


def test_two_qualified_date_pairs_can_share_one_sentence(source, full_payload):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        (
            "Date d'attribution : 19 mai 2026 et "
            "date de publication : 15 août 2026."
        ),
    )

    _assert_full_semantics_clean(payload, source)


def test_iso_project_reference_is_not_treated_as_a_published_date(
    source, full_payload
):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        "Référence projet 2026-05-19.",
    )

    _assert_full_semantics_clean(payload, source)


def test_substantial_normalized_prefix_of_a_long_raw_title_is_rejected(
    source, full_payload
):
    long_title = " ".join(
        (
            "DOSSIER ADMINISTRATIF ACCORD CADRE FOURNITURES TECHNIQUES "
            "PROCEDURE OUVERTE DESCRIPTION OFFICIELLE LOT PRINCIPAL"
        )
        for _ in range(25)
    )
    facts = source.facts.model_copy(update={"award_title": long_title})
    long_title_source = PresentationInput.model_validate(
        source.model_copy(update={"facts": facts})
    )
    copied_prefix = long_title[:400].rsplit(" ", 1)[0]
    payload = _replace_public_text(
        _full_payload(long_title_source),
        "award_summary",
        copied_prefix,
    )

    assert "administrative_title_reused" in validate_payload(
        payload, long_title_source
    ).errors


def test_proven_functional_role_label_is_not_treated_as_a_person(
    source, full_payload
):
    payload = _replace_public_text(
        full_payload,
        "recommended_action",
        "Contacter le responsable des achats au sujet des matériaux.",
    )

    _assert_full_semantics_clean(payload, source)


def test_project_identifier_and_qualified_publication_date_can_share_a_sentence(
    source, full_payload
):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        "Référence projet 2026-05-19 et date de publication : 15 août 2026.",
    )

    _assert_full_semantics_clean(payload, source)


def test_lowercase_currency_cannot_bypass_typed_amount_validation(
    source, full_payload
):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        "Montant publié : 999999 chf.",
    )

    assert "amount_value_mismatch" in validate_payload(payload, source).errors


def test_labeled_amount_without_its_atomic_currency_fails_closed(
    source, full_payload
):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        "Montant publié : 999999.",
    )

    errors = validate_payload(payload, source).errors

    assert "amount_currency_unbound" in errors
    assert "amount_value_mismatch" in errors


def test_labeled_location_must_equal_the_typed_source_location(
    source, full_payload
):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        "Lieu d'exécution publié : Paris, FR.",
    )

    assert "location_value_mismatch" in validate_payload(payload, source).errors


def test_false_location_cannot_be_hidden_before_the_exact_source_location(
    source, full_payload
):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        "Lieu d'exécution : Paris, FR ; source précédente Root, CH.",
    )

    errors = validate_payload(payload, source).errors

    assert "location_value_mismatch" in errors
    assert "full_variant_not_authorized" in errors


def test_functional_role_copy_must_match_a_proven_target_role(
    source, full_payload
):
    payload = _replace_public_text(
        full_payload,
        "recommended_action",
        "Contacter Project Manager au sujet des matériaux.",
    )

    assert "target_role_unbound" in validate_payload(payload, source).errors


def test_typed_date_claim_must_cite_its_exact_date_field(source, full_payload):
    payload = _replace_public_text(
        full_payload,
        "award_summary",
        "Date d'attribution : 19 mai 2026.",
    )
    data = payload.model_dump(mode="python")
    summary_claim = next(
        claim for claim in data["claims"] if claim["text"] == data["award_summary"]
    )
    summary_claim["evidence_refs"] = (AWARDEE_FIELD_REF,)
    forged_evidence = CardPresentationPayload.model_validate(data)

    assert "claim_evidence_mismatch" in validate_payload(
        forged_evidence, source
    ).errors
