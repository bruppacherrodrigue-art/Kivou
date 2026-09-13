from __future__ import annotations

import copy
import datetime as dt
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from signals.connectors.boamp import BoampUnsupportedPayload, parse_award_notice
from signals.persistence.identity import award_key

NOW = dt.datetime(2026, 9, 13, 10, tzinfo=dt.UTC)
FIXTURE = Path(__file__).parent / "fixtures/france/boamp_notice_facts_minimal.json"


def record():
    return json.loads(FIXTURE.read_text())


def notice(raw):
    return raw["donnees"]["EFORMS"]["ContractAwardNotice"]


def extension(raw):
    return notice(raw)["ext:UBLExtensions"]["ext:UBLExtension"]["ext:ExtensionContent"][
        "efext:EformsExtension"
    ]


def extract(raw, *, publication=None):
    module = "signals.connectors.boamp.facts"
    assert importlib.util.find_spec(module), "BOAMP notice facts extractor is not implemented"
    event, awards = publication or parse_award_notice(raw, retrieved_at=NOW)
    return importlib.import_module(module).extract_boamp_notice_facts(
        raw, event=event, awards=awards, collected_at=NOW
    )


def test_facts_align_exactly_with_each_event_award_lot_and_winning_organization():
    raw = record()
    event, awards = parse_award_notice(raw, retrieved_at=NOW)
    extracted = extract(raw)
    assert len(extracted.awards) == 2
    first, second = extracted.awards
    assert first.event_key == event.ref().key()
    assert first.award_key == award_key(awards[0])
    assert (first.source_award_id, first.lot_identifier) == ("CON-1", "LOT-1")
    assert first.title.value == "Marché couverture"
    assert first.lot_description.value == "Rénovation de la couverture."
    assert second.lot_description.value == "Remplacement des fenêtres."
    assert first.published_on.value == dt.date(2026, 9, 12)
    assert first.winning_parties[0].members[0].organization_ref == "ORG-1"
    assert second.winning_parties[0].members[0].organization_ref == "ORG-2"
    assert first.winning_parties[0].members[0].email.value == "winner-one@example.test"
    assert second.winning_parties[0].members[0].email.value == "winner-two@example.test"
    assert first.buyers[0].name.value == "Collectivité exemple"
    payload = first.model_dump_json()
    assert "buyer@example.test" not in payload
    assert "court@example.test" not in payload
    assert first.buyers[0].email is None


def test_facts_have_versioned_source_metadata_and_resolvable_paths():
    extracted = extract(record())
    first = extracted.awards[0]
    assert first.source.source_notice_id == "26-fixture-facts"
    assert first.source.notice_version == "01"
    assert first.source.content_hash == extracted.snapshot.content_hash
    assert first.source.collected_at == NOW
    assert first.source.extractor_version.startswith("boamp-notice-facts-")
    assert first.source.source_url.startswith("https://www.boamp.fr/")
    assert first.lot_description.source_path.endswith(
        "/cac:ProcurementProjectLot/0/cac:ProcurementProject/cbc:Description"
    )
    assert (
        first.winning_parties[0]
        .members[0]
        .email.source_path.endswith(
            "/efac:Organization/2/efac:Company/cac:Contact/cbc:ElectronicMail"
        )
    )


def test_decimal_money_is_exact_and_awarded_minimum_maximum_are_not_interchanged():
    first, second = extract(record()).awards
    assert first.awarded_value.value == "1234567.8912"
    assert first.minimum_value.value == "100.01"
    assert first.maximum_value.value == "9007199254740993.1234"
    assert first.maximum_value.currency == "EUR"
    assert second.awarded_value.currency == "CHF"
    assert second.minimum_value is None and second.maximum_value is None


@pytest.mark.parametrize("unit", ["DAY", "WEEK", "MONTH", "YEAR"])
def test_duration_preserves_decimal_unit_scope_without_inventing_start_or_total(unit):
    raw = record()
    project = notice(raw)["cac:ProcurementProjectLot"][0]["cac:ProcurementProject"]
    project["cac:PlannedPeriod"]["cbc:DurationMeasure"]["@unitCode"] = unit
    facts = extract(raw).awards[0]
    assert facts.duration.value == "26.5"
    assert facts.duration.unit == unit
    assert facts.duration.scope == "contract"
    assert facts.duration.period_kind == "unspecified"
    assert facts.maximum_renewals.value == "3"
    assert "start_date" not in facts.model_dump_json()
    assert "106" not in facts.duration.model_dump_json()


def test_missing_or_free_text_duration_and_ceiling_do_not_fill_other_facts():
    raw = record()
    project = notice(raw)["cac:ProcurementProjectLot"][0]["cac:ProcurementProject"]
    project.pop("cac:PlannedPeriod")
    project["cbc:Description"] = "Le calendrier sera précisé ultérieurement, environ 12 mois."
    extension(raw)["efac:NoticeResult"]["efac:LotTender"][0].pop("cac:LegalMonetaryTotal")
    facts = extract(raw).awards[0]
    assert facts.duration is None
    assert facts.awarded_value is None
    assert facts.maximum_value.value == "9007199254740993.1234"


def test_singleton_arrays_are_followed_without_changing_identity():
    raw = record()
    ext = extension(raw)
    result = ext["efac:NoticeResult"]
    for key in ["efac:LotResult", "efac:LotTender", "efac:TenderingParty", "efac:SettledContract"]:
        result[key] = result[key][:1]
    notice(raw)["cac:ProcurementProjectLot"] = notice(raw)["cac:ProcurementProjectLot"][:1]
    publication = parse_award_notice(raw, retrieved_at=NOW)
    result["efac:LotTender"][0]["efac:TenderingParty"] = [
        result["efac:LotTender"][0]["efac:TenderingParty"]
    ]
    ext["efac:Organizations"] = [ext["efac:Organizations"]]
    first = extract(raw, publication=publication).awards[0]
    assert first.winning_parties[0].members[0].organization_ref == "ORG-1"


@pytest.mark.parametrize(
    "breakage", ["contract_tender", "tender_lot", "duplicate_org", "buyer_winner"]
)
def test_contradictory_or_nonwinning_identity_is_never_attached(breakage):
    raw = record()
    publication = parse_award_notice(raw, retrieved_at=NOW)
    ext = extension(raw)
    result = ext["efac:NoticeResult"]
    if breakage == "contract_tender":
        result["efac:SettledContract"][0]["efac:LotTender"]["cbc:ID"] = "TEN-2"
    elif breakage == "tender_lot":
        result["efac:LotTender"][0]["efac:TenderLot"]["cbc:ID"] = "LOT-2"
    elif breakage == "buyer_winner":
        result["efac:TenderingParty"][0]["efac:Tenderer"]["cbc:ID"] = "ORG-BUYER"
    else:
        org = copy.deepcopy(ext["efac:Organizations"]["efac:Organization"][2])
        org["efac:Company"]["cac:Contact"]["cbc:ElectronicMail"] = "contradictory@example.test"
        ext["efac:Organizations"]["efac:Organization"].append(org)
    extracted = extract(raw, publication=publication)
    assert [fact.lot_identifier for fact in extracted.awards] == ["LOT-2"]
    assert extracted.rejections[0].award_key == award_key(publication[1][0])


def test_changed_notice_or_wrong_event_award_alignment_is_rejected():
    raw = record()
    event, awards = parse_award_notice(raw, retrieved_at=NOW)
    wrong = event.model_copy(
        update={
            "provenance": event.provenance.model_copy(update={"source_notice_id": "another-notice"})
        }
    )
    with pytest.raises(ValueError, match="notice|event"):
        extract(raw, publication=(wrong, awards))
    wrong_award = awards[0].model_copy(update={"event_ref": wrong.ref()})
    assert extract(raw, publication=(event, (wrong_award,))).awards == ()


def test_group_members_remain_in_one_winning_party():
    raw = record()
    extension(raw)["efac:NoticeResult"]["efac:TenderingParty"][0]["efac:Tenderer"] = [
        {"cbc:ID": "ORG-1"},
        {"cbc:ID": "ORG-2"},
    ]
    facts = extract(raw).awards[0]
    assert len(facts.winning_parties) == 1
    assert [m.organization_ref for m in facts.winning_parties[0].members] == ["ORG-1", "ORG-2"]


def test_same_winners_in_different_groupings_are_not_aligned():
    from signals.connectors.boamp.facts import _aligned_winners

    _, awards = parse_award_notice(record(), retrieved_at=NOW)
    party = awards[0].awardee_parties[0]
    member = party.members[0]
    members = tuple(
        member.model_copy(
            update={"organization": member.organization.model_copy(update={"legal_name": name})}
        )
        for name in ("A", "B", "C", "D")
    )
    award = awards[0].model_copy(
        update={
            "awardee_parties": (
                party.model_copy(update={"members": members[:2]}),
                party.model_copy(update={"members": members[2:]}),
            )
        }
    )
    fact_party = extract(record()).awards[0].winning_parties[0]
    fact_member = fact_party.members[0]
    fact_members = tuple(
        fact_member.model_copy(update={"name": fact_member.name.model_copy(update={"value": name})})
        for name in ("A", "B", "C", "D")
    )
    regrouped = (
        fact_party.model_copy(update={"members": (fact_members[0], fact_members[2])}),
        fact_party.model_copy(update={"members": (fact_members[1], fact_members[3])}),
    )
    assert not _aligned_winners(award, regrouped)


def test_notice_cancellation_does_not_assert_market_cancellation():
    raw = record()
    extension(raw)["efac:Changes"] = {
        "efac:ChangeReason": {"cbc:ReasonCode": "cancel"},
        "efac:Change": {"efbc:ChangeDescription": "Avis annulé pour erreur de rédaction."},
    }
    facts = extract(raw).awards[0]
    assert facts.notice_status == "notice_cancelled"
    assert facts.notice_change_reason.value == "Avis annulé pour erreur de rédaction."
    assert "market_cancel" not in facts.model_dump_json()


@pytest.mark.parametrize("kind", ["MAPA", "DSP", "FNSimple"])
def test_unsupported_notice_families_are_not_newly_adapted(kind):
    raw = record()
    publication = parse_award_notice(raw, retrieved_at=NOW)
    raw["donnees"] = {kind: {"text": "Durée 12 mois, titulaire exemple"}}
    with pytest.raises(BoampUnsupportedPayload):
        extract(raw, publication=publication)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", 26.5])
def test_invalid_or_float_decimal_facts_are_omitted(bad):
    raw = record()
    publication = parse_award_notice(raw, retrieved_at=NOW)
    notice(raw)["cac:ProcurementProjectLot"][0]["cac:ProcurementProject"]["cac:PlannedPeriod"][
        "cbc:DurationMeasure"
    ]["#text"] = bad
    assert extract(raw, publication=publication).awards[0].duration is None


def test_tribunal_role_cannot_be_published_as_a_winner_contact_even_if_chain_says_so():
    raw = record()
    notice(raw)["cac:ProcurementProjectLot"][0]["cac:TenderingTerms"] = {
        "cac:AppealTerms": {
            "cac:AppealReceiverParty": {"cac:PartyIdentification": {"cbc:ID": "ORG-COURT"}}
        }
    }
    extension(raw)["efac:NoticeResult"]["efac:TenderingParty"][0]["efac:Tenderer"] = {
        "cbc:ID": "ORG-COURT"
    }
    extracted = extract(raw)
    assert [fact.lot_identifier for fact in extracted.awards] == ["LOT-2"]


@pytest.mark.parametrize("location", ["contract", "tender"])
def test_present_but_contradictory_reference_ids_are_not_treated_as_missing(location):
    raw = record()
    publication = parse_award_notice(raw, retrieved_at=NOW)
    result = extension(raw)["efac:NoticeResult"]
    if location == "contract":
        result["efac:SettledContract"][0]["efac:LotTender"]["cbc:ID"] = ["TEN-1", "TEN-2"]
    else:
        result["efac:LotTender"][0]["efac:TenderLot"]["cbc:ID"] = ["LOT-1", "LOT-2"]
    assert [fact.lot_identifier for fact in extract(raw, publication=publication).awards] == [
        "LOT-2"
    ]


def test_contract_lot_reference_must_match_result_and_canonical_award():
    raw = record()
    extension(raw)["efac:NoticeResult"]["efac:SettledContract"][0]["efac:TenderLot"] = {
        "cbc:ID": "LOT-2"
    }
    assert [fact.lot_identifier for fact in extract(raw).awards] == ["LOT-2"]


def test_explicit_initial_duration_and_renewals_do_not_manufacture_a_maximum():
    raw = record()
    project = notice(raw)["cac:ProcurementProjectLot"][0]["cac:ProcurementProject"]
    project.pop("cac:PlannedPeriod")
    project["cbc:Description"] = "Durée initiale 12 mois, reconductible trois fois."
    facts = extract(raw).awards[0]
    assert facts.duration.value == "12"
    assert facts.initial_duration.period_kind == "initial"
    assert facts.maximum_renewals.value == "3"
    assert facts.maximum_duration is None


def test_explicit_purchase_order_maximum_does_not_become_contract_duration():
    raw = record()
    project = notice(raw)["cac:ProcurementProjectLot"][0]["cac:ProcurementProject"]
    project.pop("cac:PlannedPeriod")
    project["cbc:Description"] = (
        "Il s'agit d'un accord cadre à bons de commande. "
        "La durée maximale d'exécution des bons de commande est de 12 mois. "
        "La date de début d'exécution indiquée dans la publicité n'a pas de valeur contractuelle."
    )
    facts = extract(raw).awards[0]
    assert facts.duration.value == "12"
    assert facts.duration.scope == "purchase_order"
    assert facts.duration.period_kind == "maximum"
    assert facts.initial_duration is None
    assert facts.maximum_duration == facts.duration
    assert "start_date" not in facts.model_dump_json()


def test_explicit_years_remain_years_with_initial_and_total_separate():
    raw = record()
    project = notice(raw)["cac:ProcurementProjectLot"][0]["cac:ProcurementProject"]
    project.pop("cac:PlannedPeriod")
    project["cbc:Note"] = (
        "Le marché est conclu pour une première période d’un an. "
        "Il est renouvelable trois fois pour une période d’un an, "
        "sans que sa durée totale ne puisse excéder quatre années."
    )
    facts = extract(raw).awards[0]
    assert facts.initial_duration.value == "1" and facts.initial_duration.unit == "YEAR"
    assert facts.maximum_duration.value == "4" and facts.maximum_duration.unit == "YEAR"
    assert facts.initial_duration.source_path.endswith("/cbc:Note")


@pytest.mark.parametrize("scope", ["works", "contract"])
def test_structured_duration_scope_distinguishes_works_from_partnership_contract(scope):
    raw = record()
    project = notice(raw)["cac:ProcurementProjectLot"][0]["cac:ProcurementProject"]
    project["cbc:ProcurementTypeCode"] = "works"
    project["cbc:Description"] = (
        "Travaux relatifs à la construction du futur collège de Levens - lot n°2."
        if scope == "works"
        else "Marché de partenariat portant sur la construction et le financement."
    )
    project["cac:PlannedPeriod"]["cbc:DurationMeasure"]["#text"] = (
        "24" if scope == "works" else "240"
    )
    facts = extract(raw).awards[0]
    assert facts.duration.scope == scope
    assert facts.duration.value == ("24" if scope == "works" else "240")


def test_contradictory_initial_text_durations_do_not_choose_the_first_number():
    raw = record()
    project = notice(raw)["cac:ProcurementProjectLot"][0]["cac:ProcurementProject"]
    project.pop("cac:PlannedPeriod")
    project["cbc:Description"] = "Durée initiale : 12 mois. Durée initiale : 24 mois."
    assert extract(raw).awards[0].duration is None


def linked_tender_fixture():
    raw = record()
    raw["contractfolderid"] = "procedure-exact"
    notice(raw)["cbc:ContractFolderID"] = "procedure-exact"
    notice(raw)["cac:ProcurementProject"]["cbc:ID"] = "24N0739"
    raw["annonce_lie"] = ["25-prior-fixture"]
    notice(raw)["cac:ProcurementProjectLot"][0]["cac:ProcurementProject"].pop("cac:PlannedPeriod")
    prior = copy.deepcopy(raw)
    prior.update(
        idweb="25-prior-fixture",
        nature="APPEL_OFFRE",
        dateparution="2025-01-11",
        url_avis="https://www.boamp.fr/pages/avis/?q=idweb:25-prior-fixture",
    )
    prior_notice = prior["donnees"]["EFORMS"].pop("ContractAwardNotice")
    prior["donnees"]["EFORMS"]["ContractNotice"] = prior_notice
    project = prior_notice["cac:ProcurementProjectLot"][0]["cac:ProcurementProject"]
    project["cbc:Description"] = "Durée (hors reconduction) : 12 mois. Durée maximale : 48 mois."
    return raw, prior


def test_related_tender_durations_keep_their_own_notice_provenance_and_snapshot():
    raw, prior = linked_tender_fixture()
    event, awards = parse_award_notice(raw, retrieved_at=NOW)
    module = importlib.import_module("signals.connectors.boamp.facts")
    extracted = module.extract_boamp_notice_facts(
        raw, event=event, awards=awards, collected_at=NOW, related_records=(prior,)
    )
    facts = extracted.awards[0]
    assert facts.initial_duration.value == "12"
    assert facts.maximum_duration.value == "48"
    assert facts.initial_duration.source_notice_id == "25-prior-fixture"
    assert facts.initial_duration.notice_kind == "contract_notice"
    assert facts.initial_duration.source_url == prior["url_avis"]
    assert "/EFORMS/ContractNotice/" in facts.initial_duration.source_path
    assert len(extracted.related_snapshots) == 1
    assert facts.initial_duration.source_snapshot_key == extracted.related_snapshots[0].snapshot_key


@pytest.mark.parametrize(
    "mismatch", ["lot", "procedure", "procedure_metadata", "buyer", "reference", "unreferenced"]
)
def test_related_tender_requires_exact_prior_notice_procedure_business_reference_and_lot(mismatch):
    raw, prior = linked_tender_fixture()
    tender = prior["donnees"]["EFORMS"]["ContractNotice"]
    if mismatch == "lot":
        tender["cac:ProcurementProjectLot"][0]["cbc:ID"] = "LOT-wrong"
    elif mismatch == "procedure":
        prior["contractfolderid"] = tender["cbc:ContractFolderID"] = "contradictory-procedure"
    elif mismatch == "procedure_metadata":
        prior["contractfolderid"] = "contradictory-procedure"
    elif mismatch == "buyer":
        tender["ext:UBLExtensions"]["ext:UBLExtension"]["ext:ExtensionContent"][
            "efext:EformsExtension"
        ]["efac:Organizations"]["efac:Organization"][0]["efac:Company"]["cac:PartyLegalEntity"][
            "cbc:CompanyID"
        ] = "99999999900019"
    elif mismatch == "reference":
        tender["cac:ProcurementProject"]["cbc:ID"] = "wrong-reference"
    else:
        raw["annonce_lie"] = []
    event, awards = parse_award_notice(raw, retrieved_at=NOW)
    module = importlib.import_module("signals.connectors.boamp.facts")
    facts = module.extract_boamp_notice_facts(
        raw, event=event, awards=awards, collected_at=NOW, related_records=(prior,)
    ).awards[0]
    assert facts.duration is None
    assert facts.initial_duration is None and facts.maximum_duration is None


def test_different_notice_uuids_do_not_contradict_an_exact_procedure_link():
    from signals.connectors.boamp.facts import extract_boamp_notice_facts

    raw, prior = linked_tender_fixture()
    notice(raw)["cbc:ID"] = "award-notice-uuid"
    prior["donnees"]["EFORMS"]["ContractNotice"]["cbc:ID"] = "prior-notice-uuid"
    event, awards = parse_award_notice(raw, retrieved_at=NOW)
    facts = extract_boamp_notice_facts(
        raw, event=event, awards=awards, collected_at=NOW, related_records=(prior,)
    ).awards[0]
    assert facts.initial_duration.value == "12"
