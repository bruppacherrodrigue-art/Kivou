"""SPEC-009E §21, §44, §45 — l'adapter BOAMP, mesuré sur des avis réels.

Les enregistrements de `tests/fixtures/france/boamp_records.json` sont des avis
BOAMP non modifiés, récupérés le 2026-08-18. Ils couvrent les quatre formes que
le portail publie réellement : eForms avec date de décision, eForms sans,
`FNSimple` et `MAPA`.

Le test central est celui du champ piège. BOAMP expose
`cac:TenderResult/cbc:AwardDate` sur 100 % de ses avis eForms, et 96 % des
valeurs y sont `2000-01-01` ou `1970-01-01`. Mapper ce champ sur son nom aurait
fabriqué des « vient de gagner » datés de l'an 2000.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from signals.connectors.boamp import (
    BOAMP_SOURCE_SYSTEM,
    BoampUnsupportedPayload,
    parse_award_notice,
    supported_payload,
)

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "france"
RECORDS = {
    record["idweb"]: record
    for record in json.loads((FIXTURE / "boamp_records.json").read_text(encoding="utf-8"))[
        "records"
    ]
}

RETRIEVED = dt.datetime(2026, 8, 18, 6, 0, tzinfo=dt.UTC)


def parsed(idweb: str):
    return parse_award_notice(RECORDS[idweb], retrieved_at=RETRIEVED)


# ─── §21 — l'avis devient un PublicEvent canonique ──────────────────────────────


def test_a_boamp_award_notice_becomes_a_canonical_public_event():
    event, awards = parsed("26-80978")
    assert event.provenance.source_system == BOAMP_SOURCE_SYSTEM == "boamp"
    assert event.provenance.source_notice_id == "26-80978"
    assert event.provenance.source_country == "FR"
    assert event.event_type == "award_notice"
    assert event.published_at == dt.date(2026, 8, 18)
    assert awards


def test_the_procedure_identity_comes_from_the_contract_folder_id():
    event, _ = parsed("26-80978")
    assert event.provenance.source_procedure_id == RECORDS["26-80978"]["contractfolderid"]


def test_the_source_url_is_preserved_for_proof():
    event, _ = parsed("26-80978")
    assert event.provenance.source_url == RECORDS["26-80978"]["url_avis"]
    assert event.provenance.retrieved_at == RETRIEVED


def test_the_procedure_buyer_is_carried_on_the_event_not_on_each_award():
    event, _ = parsed("26-80978")
    assert event.procedure_buyers
    assert event.procedure_buyers[0].legal_name == "Ville de Saint Orens de Gameville"


# ─── §21 — les contrats attribués ───────────────────────────────────────────────


def test_each_settled_contract_becomes_one_canonical_award():
    _, awards = parsed("26-80978")
    assert len(awards) >= 2, "cet avis porte plusieurs lots attribués"
    assert {a.source_award_id for a in awards} == {"CON-0001", "CON-0002"}
    assert {a.lot.identifier for a in awards if a.lot} == {"LOT-0001", "LOT-0002"}


def test_the_winner_is_resolved_through_the_tendering_party_chain():
    """LotResult → LotTender → TenderingParty → Tenderer → Organizations/Company."""
    _, awards = parsed("26-80978")
    names = {
        member.organization.legal_name
        for award in awards
        for party in award.awardee_parties
        for member in party.members
    }
    assert "SARL ALCIS TRANSPORTS" in names


def test_the_amount_and_currency_come_from_the_lot_tender():
    _, awards = parsed("26-80922")
    valued = [a for a in awards if a.value is not None]
    assert valued
    assert all(a.value.currency == "EUR" for a in valued)
    assert {str(a.value.amount) for a in valued} == {"1535962.72"}


def test_a_framework_ceiling_is_never_presented_as_an_awarded_amount():
    """26-80978 est un accord-cadre : la source publie un plafond, pas un montant.

    `efac:FrameworkAgreementValues/cbc:MaximumValueAmount` vaut 160 000 et
    280 000 EUR sur ses deux lots. Le reprendre comme valeur du contrat
    afficherait au client une commande qui n'a pas eu lieu.
    """
    raw = json.loads(RECORDS["26-80978"]["donnees"])["EFORMS"]["ContractAwardNotice"]
    extension = raw["ext:UBLExtensions"]["ext:UBLExtension"]["ext:ExtensionContent"][
        "efext:EformsExtension"
    ]
    ceilings = {
        result["efac:FrameworkAgreementValues"]["cbc:MaximumValueAmount"]["#text"]
        for result in extension["efac:NoticeResult"]["efac:LotResult"]
    }
    assert ceilings == {"160000", "280000"}, "le plafond doit être présent dans la fixture"

    _, awards = parsed("26-80978")
    assert all(a.value is None for a in awards)


def test_the_cpv_is_carried_from_the_procurement_project():
    _, awards = parsed("26-80978")
    assert all(a.cpv_main is not None for a in awards)


# ─── §20 — le champ piège ───────────────────────────────────────────────────────


def test_the_tender_result_award_date_sentinel_is_never_mapped():
    """`cac:TenderResult/cbc:AwardDate` vaut `2000-01-01` sur cet avis réel."""
    raw = json.loads(RECORDS["26-80978"]["donnees"])
    tender_result = raw["EFORMS"]["ContractAwardNotice"]["cac:TenderResult"]
    sentinel = tender_result["cbc:AwardDate"]
    assert str(sentinel).startswith("2000-01-01"), "le piège doit être présent dans la fixture"

    _, awards = parsed("26-80978")
    assert all(a.award_date != dt.date(2000, 1, 1) for a in awards)
    assert all(a.award_date is None or a.award_date.year >= 2020 for a in awards)


def test_the_award_date_comes_only_from_bt_1451():
    _, awards = parsed("26-80978")
    assert {a.award_date for a in awards} == {dt.date(2026, 7, 17)}


def test_the_contract_conclusion_date_lands_on_the_signature_field_not_the_award_field():
    """§7 — BT-145 est une conclusion de contrat, pas une décision d'attribution."""
    _, awards = parsed("26-80978")
    assert {a.contract_signature_date for a in awards} == {dt.date(2026, 8, 17)}
    assert all(a.award_date != a.contract_signature_date for a in awards)


def test_an_award_notice_without_bt_1451_leaves_the_award_date_empty():
    _, awards = parsed("26-80922")
    assert awards
    assert all(a.award_date is None for a in awards)
    assert any(a.contract_signature_date is not None for a in awards)


def test_the_publication_date_never_fills_a_missing_award_date():
    event, awards = parsed("26-80922")
    assert event.published_at == dt.date(2026, 8, 18)
    assert all(a.award_date is None for a in awards)


# ─── §21 — les formes non structurées sont refusées, pas devinées ───────────────


@pytest.mark.parametrize("idweb", ["26-81190", "26-80528"])
def test_a_non_eforms_payload_is_refused_rather_than_parsed_from_free_text(idweb: str):
    """`FNSimple` et `MAPA` enferment gagnant, SIRET et montant dans une phrase.

    Les extraire serait de l'inférence sur du texte libre, pas de l'adaptation.
    """
    assert not supported_payload(RECORDS[idweb])
    with pytest.raises(BoampUnsupportedPayload) as excinfo:
        parse_award_notice(RECORDS[idweb], retrieved_at=RETRIEVED)
    assert "eForms" in str(excinfo.value)


def test_the_supported_payload_probe_accepts_eforms():
    assert supported_payload(RECORDS["26-80978"])
    assert supported_payload(RECORDS["26-80922"])


# ─── §37 — idempotence ──────────────────────────────────────────────────────────


def test_parsing_the_same_record_twice_yields_the_same_canonical_identity():
    first_event, first_awards = parsed("26-80978")
    second_event, second_awards = parsed("26-80978")
    assert first_event.natural_key() == second_event.natural_key()
    assert [a.source_identity() for a in first_awards] == [
        a.source_identity() for a in second_awards
    ]


def test_no_identity_is_invented_when_the_source_publishes_none():
    """Un contrat sans identifiant publié rend `None`, jamais une clé fabriquée."""
    _, awards = parsed("26-80978")
    for award in awards:
        identity = award.source_identity()
        assert identity is None or identity.source_award_id in {"CON-0001", "CON-0002"}


# ─── §46 — l'entrée française traverse le moteur existant, inchangé ─────────────


def test_a_french_award_flows_through_contract_understanding_with_full_evidence():
    """§33 — tout fait affiché porte une preuve, quelle que soit la source.

    Le moteur de compréhension n'a pas été modifié pour la France : il reçoit un
    `ContractAward` canonique et n'a aucune raison de savoir d'où il vient. Ce
    test vérifie que c'est bien le cas de bout en bout.
    """
    from signals.understanding import ContractUnderstandingEngine

    engine = ContractUnderstandingEngine()
    for idweb in ("26-80978", "26-80922"):
        event, awards = parsed(idweb)
        for award in awards:
            understanding = engine.understand(award, event)
            assert understanding.evidence_coverage == 1.0
            assert understanding.facts
            for name, fact in understanding.facts.items():
                assert fact.evidence, f"{idweb}/{name} affiché sans preuve"


def test_a_french_award_without_bt_1451_exposes_no_award_date_fact():
    from signals.understanding import ContractUnderstandingEngine

    engine = ContractUnderstandingEngine()
    event, awards = parsed("26-80922")
    understanding = engine.understand(awards[0], event)
    assert "award_date" not in understanding.facts
