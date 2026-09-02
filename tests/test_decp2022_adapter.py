"""SPEC-009E R1 §1, §2 — l'adapter DECP sur le jeu de données COURANT.

`tests/fixtures/france/decp2022_records.json` contient quatre enregistrements
réels non modifiés de `decp-2022-marches-valides`, le jeu en vigueur (arrêté du
22 décembre 2022), récupérés le 2026-08-18.

SPEC-009E avait mesuré `decp-v3-marches-valides` — le jeu **hérité** de
l'arrêté du 22 mars 2019, figé à février 2024. Toutes les conclusions de
fraîcheur qui en découlaient étaient fausses.

Le jeu courant apporte aussi son propre piège de remplissage : la chaîne
littérale `"CDL"` occupe les champs vides sur la totalité des enregistrements
observés. Elle doit être traitée comme une absence, jamais comme une valeur.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from signals.connectors.decp import (
    DECP_DATASET,
    DECP_DATE_SEMANTICS,
    DECP_SOURCE_SYSTEM,
    buyer_siret,
    parse_contract,
    winner_sirets,
)

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "france"
PAYLOAD = json.loads((FIXTURE / "decp2022_records.json").read_text(encoding="utf-8"))
RECORDS = {record["id"]: record for record in PAYLOAD["records"]}

NOMINAL = "2026T06966"
GROUPEMENT = "26S"
TVA_ONLY = "26MAPA024"

RETRIEVED = dt.datetime(2026, 8, 18, 6, 0, tzinfo=dt.UTC)


def parsed(identifier: str):
    return parse_contract(RECORDS[identifier], retrieved_at=RETRIEVED)


# ─── §1 — le jeu courant, et le fait qu'il soit courant ─────────────────────────


def test_the_adapter_targets_the_current_dataset_not_the_legacy_one():
    assert DECP_DATASET == "decp-2022-marches-valides"
    assert PAYLOAD["dataset"] == DECP_DATASET


def test_a_current_decp_record_becomes_a_canonical_award():
    event, contract = parsed(NOMINAL)
    assert event.provenance.source_system == DECP_SOURCE_SYSTEM == "decp"
    assert event.provenance.source_notice_id == NOMINAL
    assert event.provenance.source_country == "FR"
    assert contract.event_ref == event.ref()
    assert contract.source_award_id == NOMINAL


def test_the_publication_date_is_the_open_data_publication():
    event, _ = parsed(NOMINAL)
    assert event.published_at == dt.date(2026, 8, 17)


# ─── §2 — la notification a désormais son propre champ ─────────────────────────


def test_the_notification_date_lands_on_its_own_canonical_field():
    _, contract = parsed(NOMINAL)
    assert contract.contract_notification_date == dt.date(2026, 8, 17)


def test_the_notification_date_never_becomes_an_award_date():
    """R1 §2 — non négociable, vérifié sur les quatre enregistrements réels."""
    for identifier, record in RECORDS.items():
        _, contract = parse_contract(record, retrieved_at=RETRIEVED)
        assert contract.award_date is None, identifier


def test_the_notification_date_never_becomes_a_signature_date_either():
    """R1 §2 — la conclusion et la notification sont deux actes distincts."""
    for identifier, record in RECORDS.items():
        _, contract = parse_contract(record, retrieved_at=RETRIEVED)
        assert contract.contract_signature_date is None, identifier


def test_the_declared_semantics_point_at_the_notification_field():
    spec = DECP_DATE_SEMANTICS["datenotification"]
    assert spec["canonical_field"] == "contract_notification_date"
    assert spec["can_represent_award_date"] == "NO"
    assert DECP_DATE_SEMANTICS["datepublicationdonnees"]["can_represent_award_date"] == "NO"


# ─── le piège de remplissage du jeu courant ────────────────────────────────────


def test_the_cdl_filler_string_is_treated_as_an_absence():
    """`CDL` occupe les champs vides sur 100 % des enregistrements observés."""
    assert RECORDS[NOMINAL]["titulaire_id_2"] == "CDL"
    _, contract = parsed(NOMINAL)
    members = [m for party in contract.awardee_parties for m in party.members]
    assert len(members) == 1, "le remplissage ne doit pas créer un second titulaire"


def test_a_cdl_framework_identifier_does_not_become_a_contract_reference():
    assert RECORDS[NOMINAL]["idaccordcadre"] == "CDL"
    _, contract = parsed(NOMINAL)
    assert contract.contract_reference is None


# ─── titulaires : SIRET, groupement, identifiant étranger ──────────────────────


def test_a_single_titulaire_is_carried_with_its_siret():
    _, contract = parsed(NOMINAL)
    identifiers = [
        (i.scheme, i.value)
        for party in contract.awardee_parties
        for member in party.members
        for i in member.organization.identifiers
    ]
    assert identifiers == [("SIRET", "30102983100031")]
    assert winner_sirets(RECORDS[NOMINAL]) == ("30102983100031",)


def test_several_titulaires_make_one_group_not_several_contracts():
    """Cet enregistrement réel porte trois titulaires sur un seul marché."""
    _, contract = parsed(GROUPEMENT)
    parties = contract.awardee_parties
    assert len(parties) == 1, "un marché, un groupement — pas trois contrats"
    assert parties[0].is_group
    assert {m.role for m in parties[0].members} == {"consortium_member"}
    assert winner_sirets(RECORDS[GROUPEMENT]) == (
        "43172809600014",
        "50478920700017",
        "51763797100089",
    )


def test_a_non_siret_identifier_keeps_its_declared_scheme():
    """Un titulaire italien porte un numéro de TVA, pas un SIRET."""
    record = RECORDS[TVA_ONLY]
    assert record["titulaire_typeidentifiant_1"] == "TVA"
    assert winner_sirets(record) == (), "un numéro de TVA n'est pas un SIRET"
    _, contract = parsed(TVA_ONLY)
    identifiers = [
        (i.scheme, i.value)
        for party in contract.awardee_parties
        for member in party.members
        for i in member.organization.identifiers
    ]
    assert identifiers == [("TVA", "IT03876500277")]


def test_no_winner_legal_name_is_invented_because_the_schema_has_none():
    """Le schéma 2022 ne comporte AUCUN champ de raison sociale du titulaire."""
    assert not any(key.startswith("titulaire_denomination") for key in RECORDS[NOMINAL])
    _, contract = parsed(NOMINAL)
    names = {m.organization.legal_name for party in contract.awardee_parties for m in party.members}
    assert names == {"30102983100031"}


def test_the_buyer_is_identified_by_siret_and_never_named():
    assert "acheteur_nom" not in RECORDS[NOMINAL]
    event, _ = parsed(NOMINAL)
    assert buyer_siret(RECORDS[NOMINAL]) == "21220295600018"
    assert [(i.scheme, i.value) for o in event.procedure_buyers for i in o.identifiers] == [
        ("SIRET", "21220295600018")
    ]


# ─── montant, CPV, durée, lieu ─────────────────────────────────────────────────


def test_the_amount_is_carried_as_the_maximum_the_source_declares_it_to_be():
    """Le schéma dit « montant HT forfaitaire ou estimé maximum »."""
    _, contract = parsed(NOMINAL)
    assert contract.value is not None
    assert str(contract.value.amount) == "57988.0"
    assert contract.value.currency == "EUR"


def test_the_cpv_check_digit_is_split_from_the_code():
    _, contract = parsed(NOMINAL)
    assert contract.cpv_main is not None
    assert contract.cpv_main.code == "45000000"
    assert contract.cpv_main.check_digit == "7"


def test_the_place_of_performance_uses_the_code_and_its_declared_type():
    _, contract = parsed(NOMINAL)
    place = contract.place_of_performance
    assert place is not None
    assert place.country == "FR"
    assert place.locality is None, "le schéma 2022 ne publie aucun nom de commune"


def test_a_postal_code_and_a_department_code_are_not_confused():
    """`lieuexecution_typecode` dit ce que le code est ; le deviner serait faux."""
    assert RECORDS[NOMINAL]["lieuexecution_typecode"] == "Code département"
    _, contract = parsed(NOMINAL)
    assert contract.place_of_performance.postal_code is None


def test_a_postal_code_also_yields_its_department():
    """Le département se lit dans le code postal publié ; le libellé reste au feed."""
    record = dict(RECORDS[NOMINAL])
    record["lieuexecution_typecode"] = "Code postal"
    record["lieuexecution_code"] = "92350"
    _, contract = parse_contract(record, retrieved_at=RETRIEVED)
    place = contract.place_of_performance
    assert place.postal_code == "92350"
    assert place.subdivision_code == "FR-92"
    assert place.subdivision_scheme == "ISO-3166-2"
    assert place.locality is None


def test_the_duration_in_months_is_carried():
    _, contract = parsed(NOMINAL)
    assert contract.duration is not None
    assert contract.duration.value == 14
    assert contract.duration.unit == "month"


# ─── §37 idempotence ───────────────────────────────────────────────────────────


def test_parsing_the_same_record_twice_yields_the_same_identity():
    first_event, first = parsed(NOMINAL)
    second_event, second = parsed(NOMINAL)
    assert first_event.natural_key() == second_event.natural_key()
    assert first.source_identity() == second.source_identity()


def test_a_record_without_an_identifier_is_refused_rather_than_given_one():
    with pytest.raises(ValueError, match="id"):
        parse_contract({"datenotification": "2026-08-17"}, retrieved_at=RETRIEVED)
