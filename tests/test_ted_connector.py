"""Connecteur TED — tests entièrement hors ligne.

Les fixtures sont de **vraies** notices TED, téléchargées telles quelles depuis
`https://ted.europa.eu/en/notice/{n°}/xml` (données publiques, Search API v3).
La seule exception est `synthetic_crosslink.xml`, construite pour prouver
l'absence d'appariement par proximité — elle est signalée comme telle.

    550374-2026  FRA  1 lot, 1 contrat, 1 gagnant, valeur EUR
    566131-2026  FIN  5 lots, 10 contrats, aucune valeur d'offre publiée (Åland)
    566075-2026  ROU  accord-cadre : 1 lot, 27 offres, 19 contrats
    566119-2026  POL  groupement de 4 opérateurs avec chef de file
    566152-2026  FRA  lot déclaré infructueux (clos-nw), aucun contrat
    566114-2026  POL  2 lots : un infructueux, un attribué
    565942-2026  ENG  achat conjoint (2 acheteurs), accord-cadre
    566039-2026  DEU  version 02 d'un avis (republication)
    566117-2026  DEU  offres publiées à `-1`, marqueur « montant non communiqué »
    566129-2026  HUN  un groupement figure parmi les PERDANTS, pas parmi les gagnants
    183632-2026  FRA  l'AVIS D'APPEL D'OFFRES du même marché que 550374-2026 (BT-04 partagé)
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
from defusedxml import ElementTree

from signals.connectors.ted import extract, map_notice, parse_notice
from signals.connectors.ted.errors import TedParseError
from signals.domain import (
    Awardee,
    AwardeeParty,
    ContractAward,
    EventRef,
    OrganizationRef,
    PublicEvent,
    SourceIdentity,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ted"


def load(publication_number: str) -> bytes:
    return (FIXTURES / f"{publication_number}.xml").read_bytes()


def awards_by_id(extraction) -> dict[str, ContractAward]:
    return {a.source_award_id: a for a in extraction.awards}


# ─── TEST A — award simple ──────────────────────────────────────────────────────


def test_a_award_simple_notice_reelle():
    result = extract(load("550374-2026"))
    assert len(result.awards) == 1
    award = result.awards[0]

    buyers = result.event.procedure_buyers
    assert [b.legal_name for b in buyers] == ["Société Aéroport Avignon Provence"]
    assert buyers[0].country == "FR"
    assert buyers[0].identifier("TED-BT-501") == "83537486900013"

    assert [o.legal_name for o in award.awardee_organizations()] == [
        "One Security and Safety Services"
    ]
    assert award.winner_status == "identified"
    assert len(award.awardee_parties) == 1
    assert award.awardee_parties[0].members[0].role == "sole"
    assert award.contract_reference == "MP 2026-SAAP-001"  # BT-150

    assert award.lot.identifier == "LOT-0001"
    assert award.cpv_main.code == "79710000"
    assert [c.code for c in award.cpv_additional] == ["79714000"]

    assert award.value.amount == Decimal("192396.26")
    assert award.value.currency == "EUR"

    assert award.award_date == dt.date(2026, 5, 11)  # BT-1451
    assert award.contract_signature_date == dt.date(2026, 5, 29)  # BT-145
    assert award.contract_start_date == dt.date(2026, 6, 1)  # BT-536
    assert award.contract_end_date == dt.date(2026, 12, 31)  # BT-537

    assert award.place_of_performance.country == "FR"
    assert award.place_of_performance.subdivision_scheme == "NUTS"
    assert award.place_of_performance.subdivision_code == "FRL06"

    assert result.event.provenance.source_system == "ted"
    assert result.event.provenance.source_notice_id == "e60ad0f2-da33-4bba-a8be-e114319bbb5d"
    assert award.belongs_to(result.event.ref())
    assert not result.warnings


# ─── TEST B — multi-lot ─────────────────────────────────────────────────────────


def test_b_multi_lot_chaque_contrat_reste_sur_son_lot():
    result = extract(load("566131-2026"))
    assert result.lots == 5
    assert len(result.awards) == 10

    by_lot: dict[str, set[str]] = {}
    for award in result.awards:
        by_lot.setdefault(award.lot.identifier, set()).add(
            award.awardee_organizations()[0].legal_name
        )
    assert sorted(by_lot) == ["LOT-0001", "LOT-0002", "LOT-0003", "LOT-0004", "LOT-0005"]
    assert all(len(names) == 2 for names in by_lot.values())
    assert all(award.belongs_to(result.event.ref()) for award in result.awards)


# ─── TEST C — plusieurs contrats sur un même lot ────────────────────────────────


def test_c_accord_cadre_dix_neuf_contrats_un_seul_lot_sans_collision():
    result = extract(load("566075-2026"))
    assert result.lots == 1
    assert len(result.awards) == 19
    assert {a.lot.identifier for a in result.awards} == {"LOT-0000"}
    assert len({a.source_identity() for a in result.awards}) == 19


def test_c_bis_les_offres_perdantes_ne_deviennent_pas_des_contrats():
    """Le `LotResult` référence les 27 offres reçues ; seules 19 ont un contrat."""
    notice = parse_notice(load("566075-2026"))
    assert len(notice.tenders) == 27
    assert len(notice.contracts) == 19
    assert len(notice.lot_results[0].tender_ids) == 27

    result = map_notice(notice)
    assert len(result.awards) == 19  # pas 27


# ─── TEST D — consortium ────────────────────────────────────────────────────────


def test_d_consortium_un_contrat_quatre_organisations():
    result = extract(load("566119-2026"))
    assert len(result.awards) == 1
    award = result.awards[0]

    # UN soumissionnaire retenu, composé de quatre organisations
    assert len(award.awardee_parties) == 1
    party = award.awardee_parties[0]
    assert party.is_group
    assert len(party.members) == 4
    assert award.winner_status == "identified"
    leads = [m for m in party.members if m.role == "consortium_lead"]
    assert len(leads) == 1
    assert leads[0].organization.legal_name.startswith("Agencja Ochrony")
    assert all(m.role.startswith("consortium") for m in party.members)
    assert party.name is not None  # le nom du groupement est publié


# ─── TEST E — attributaires indépendants ────────────────────────────────────────


def test_e_multi_attributaires_independants_ne_deviennent_pas_un_consortium():
    """566075 : chaque contrat a son titulaire seul ; aucun rôle de groupement."""
    result = extract(load("566075-2026"))
    solos = [a for a in result.awards if len(a.awardee_parties) == 1]
    assert len(solos) == 18
    assert all(len(a.awardee_parties[0].members) == 1 for a in solos)
    assert all(a.awardee_parties[0].members[0].role == "sole" for a in solos)
    assert len({a.awardee_organizations()[0].legal_name for a in solos}) > 1


def test_e_bis_neuf_soumissionnaires_independants_sur_un_seul_contrat():
    """Un contrat référençant 9 offres de 9 soumissionnaires distincts.

    Ils sont conservés comme NEUF parties retenues, pas comme un groupement de
    neuf membres, et pas comme un cas ambigu : la source les nomme toutes.
    """
    result = extract(load("566075-2026"))
    multi = [a for a in result.awards if len(a.awardee_parties) > 1]
    assert len(multi) == 1
    award = multi[0]

    assert len(award.awardee_parties) == 9
    assert all(len(p.members) == 1 for p in award.awardee_parties)
    assert {m.role for p in award.awardee_parties for m in p.members} == {"sole"}
    assert award.winner_status == "identified"  # rien d'ambigu : on sait qui a gagné
    assert len(award.awardee_organizations()) == 9
    assert {w.code for w in result.warnings} >= {"contract-with-several-awardee-parties"}


def test_e_ter_aucun_consortium_n_est_fabrique_sur_l_ensemble_du_corpus():
    """Le rôle `consortium_*` n'apparaît que là où la source publie un groupement."""
    for publication in ("566075-2026", "566131-2026", "566114-2026", "566129-2026"):
        result = extract(load(publication))
        for award in result.awards:
            for party in award.awardee_parties:
                if len(party.members) == 1:
                    assert party.members[0].role == "sole"


# ─── TEST F — montant absent ────────────────────────────────────────────────────


def test_f_montant_absent_les_contrats_restent_valides():
    result = extract(load("566131-2026"))
    assert all(award.value is None for award in result.awards)
    assert len([w for w in result.warnings if w.code == "value-absent"]) == 10
    # le reste des faits est intact
    assert all(award.awardee_parties for award in result.awards)
    assert all(award.contract_signature_date == dt.date(2026, 8, 13) for award in result.awards)


def test_f_ter_un_montant_negatif_est_refuse_pas_stocke():
    """566117-2026 publie `-1` comme marqueur « non communiqué » — pas une valeur."""
    result = extract(load("566117-2026"))
    assert len(result.awards) == 2
    assert all(award.value is None for award in result.awards)
    assert [w.code for w in result.warnings] == ["value-negative-sentinel"] * 2
    # le reste du contrat est conservé
    assert all(award.awardee_parties for award in result.awards)


def test_f_bis_aucun_montant_de_substitution_n_est_utilise():
    """La notice porte des montants d'accord-cadre : aucun ne remplace la valeur du contrat."""
    raw = load("566131-2026").decode("utf-8")
    assert "FrameworkAgreementValues" in raw  # la source EN publie
    result = extract(raw)
    assert all(award.value is None for award in result.awards)  # le connecteur n'en veut pas


# ─── TEST G — lot non attribué ──────────────────────────────────────────────────


def test_g_lot_infructueux_ne_produit_aucun_gagnant():
    result = extract(load("566152-2026"))
    assert result.lots == 1
    assert result.lot_results == 1
    assert result.lots_not_awarded == 1
    assert result.contracts == 0
    assert result.awards == ()


def test_g_bis_notice_mixte_un_lot_attribue_un_lot_infructueux():
    result = extract(load("566114-2026"))
    assert result.lots == 2
    assert result.lots_not_awarded == 1
    assert len(result.awards) == 1
    assert result.awards[0].lot.identifier == "LOT-0002"


# ─── TEST H — anti-cross-link ───────────────────────────────────────────────────


def test_h_le_rattachement_suit_les_references_pas_la_proximite():
    """Fixture synthétique : l'ordre du document contredit exprès les références."""
    result = extract(load("synthetic_crosslink"))
    awards = awards_by_id(result)
    assert len(awards) == 2

    # CON-0001 est écrit juste après TEN-0001 mais référence TEN-0002 → lot 2
    assert awards["CON-0001"].lot.identifier == "LOT-0002"
    assert awards["CON-0001"].awardee_organizations()[0].legal_name == "Gagnant Du Lot Deux"
    assert awards["CON-0001"].value.amount == Decimal("200000")

    # CON-0002 est écrit juste après TEN-0002 mais référence TEN-0001 → lot 1
    assert awards["CON-0002"].lot.identifier == "LOT-0001"
    assert awards["CON-0002"].awardee_organizations()[0].legal_name == "Gagnant Du Lot Un"
    assert awards["CON-0002"].value.amount == Decimal("100000")

    assert awards["CON-0001"].cpv_main.code == "79710000"
    assert awards["CON-0002"].cpv_main.code == "45000000"


def test_h_bis_aucun_gagnant_d_un_autre_lot_sur_une_notice_reelle():
    """566131 : 5 lots × 2 titulaires. Chaque contrat porte le titulaire de SON offre."""
    notice = parse_notice(load("566131-2026"))
    result = map_notice(notice)
    for award in result.awards:
        contract = next(c for c in notice.contracts if c.contract_id == award.source_award_id)
        tender = notice.tenders[contract.tender_ids[0]]
        party = notice.tendering_parties[tender.tendering_party_id]
        expected = {notice.organizations[o].name for o, _ in party.tenderers}
        assert {o.legal_name for o in award.awardee_organizations()} == expected
        assert award.lot.identifier == tender.lot_id


def test_h_quater_un_groupement_perdant_ne_devient_pas_le_gagnant():
    """566129-2026 : cinq soumissionnaires, dont un groupement de 2 — qui a perdu.

    Le contrat va à TPA-0004, un opérateur seul. Un connecteur qui prendrait « le
    groupement de la notice » attribuerait le marché aux mauvaises entreprises.
    """
    notice = parse_notice(load("566129-2026"))
    groupements = [p for p in notice.tendering_parties.values() if len(p.tenderers) > 1]
    assert len(groupements) == 1  # TPA-0003, deux opérateurs

    result = map_notice(notice)
    assert len(result.awards) == 1
    award = result.awards[0]
    assert len(award.awardee_parties) == 1
    assert award.awardee_parties[0].members[0].role == "sole"
    perdants = {notice.organizations[o].name for p in groupements for o, _ in p.tenderers}
    assert award.awardee_organizations()[0].legal_name not in perdants


def test_h_ter_la_date_bouchon_de_la_racine_est_ignoree():
    """`/*/cac:TenderResult/cbc:AwardDate` vaut 2000-01-01 : c'est une exigence UBL."""
    raw = load("synthetic_crosslink").decode("utf-8")
    assert "2000-01-01" in raw
    result = extract(raw)
    assert all(award.award_date is None for award in result.awards)


# ─── TEST I — identifiants ──────────────────────────────────────────────────────


def test_i_les_identifiants_ted_ne_sont_pas_confondus():
    notice = parse_notice(load("550374-2026"))
    result = map_notice(notice)
    award = result.awards[0]
    identity = award.source_identity()

    # identifiant de notice (BT-701, UUID) ≠ numéro de publication au JOUE
    assert identity.source_notice_id == "e60ad0f2-da33-4bba-a8be-e114319bbb5d"
    assert notice.publication_number == "550374-2026"
    assert identity.source_notice_id != notice.publication_number
    assert notice.publication_number in result.event.provenance.source_url

    # version de notice (BT-757)
    assert identity.notice_version == "01"

    # identifiant technique du contrat ≠ référence métier BT-150 ≠ référence d'offre
    assert identity.source_award_id == "CON-0001"
    assert notice.contracts[0].contract_reference == "MP 2026-SAAP-001"
    assert notice.tenders["TEN-0001"].tender_reference == "MP 2026-SAAP-001"
    assert identity.source_award_id != notice.contracts[0].contract_reference


def test_i_bis_identifiant_technique_toujours_unique_dans_la_notice():
    for publication in ("566075-2026", "566131-2026"):
        notice = parse_notice(load(publication))
        technical = [c.contract_id for c in notice.contracts]
        assert len(set(technical)) == len(technical)


def test_i_ter_lots_group_n_est_pas_un_lot():
    """`cbc:ID/@schemeName` distingue `Lot` de `LotsGroup` — le second n'est pas un lot."""
    notice = parse_notice(load("566114-2026"))
    assert all(lot_id.startswith("LOT-") for lot_id in notice.lots)
    assert "GLO-0001" not in notice.lots


# ─── TEST J — provenance ────────────────────────────────────────────────────────


def test_j_provenance_conservee():
    retrieved = dt.datetime(2026, 8, 16, 12, 0, tzinfo=dt.UTC)
    result = extract(load("566039-2026"), retrieved_at=retrieved)
    provenance = result.event.provenance

    assert provenance.source_system == "ted"
    assert provenance.source_country == "DE"
    assert provenance.source_notice_id == "75744b99-26c4-4cdf-bc78-84b3e0b272b0"
    assert provenance.notice_version == "02"
    assert provenance.source_url == "https://ted.europa.eu/en/notice/566039-2026/xml"
    assert provenance.retrieved_at == retrieved
    assert result.event.published_at == dt.date(2026, 8, 14)
    assert result.event.published_precision() == "date"


def test_j_bis_une_version_ulterieure_est_un_evenement_distinct():
    """Même UUID de notice, version différente → clé naturelle différente."""
    version_2 = extract(load("566039-2026")).event
    version_1 = PublicEvent(
        provenance=version_2.provenance.model_copy(update={"notice_version": "01"}),
        event_type="award_notice",
    )
    assert version_2.natural_key() != version_1.natural_key()
    assert version_2.ref().source_notice_id == version_1.ref().source_notice_id


def test_j_ter_aucune_heure_de_publication_inventee():
    """TED publie une date de parution, pas un horodatage."""
    result = extract(load("550374-2026"))
    assert type(result.event.published_at) is dt.date
    assert result.event.event_date is None  # l'adjudication est datée contrat par contrat


# ─── Robustesse & frontière avec le domaine ─────────────────────────────────────


def test_xml_non_eforms_refuse_explicitement():
    with pytest.raises(TedParseError, match="racine inattendue"):
        extract(b"<html><body>pas une notice</body></html>")


def test_xml_illisible_refuse_explicitement():
    with pytest.raises(TedParseError, match="illisible"):
        extract(b"<ContractAwardNotice><oops>")


def test_notice_sans_resultat_refusee():
    with pytest.raises(TedParseError, match="NoticeResult"):
        extract(
            b'<ContractAwardNotice xmlns="urn:oasis:names:specification:ubl:schema:xsd:'
            b'ContractAwardNotice-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:'
            b'xsd:CommonBasicComponents-2"><cbc:ID>x</cbc:ID></ContractAwardNotice>'
        )


def test_le_domaine_ignore_tout_du_vocabulaire_ted():
    """Aucune structure eForms ne fuit dans les objets canoniques produits."""
    result = extract(load("550374-2026"))
    serialized = result.awards[0].model_dump_json() + result.event.model_dump_json()
    for ted_term in ("LotTender", "SettledContract", "TenderingParty", "efac", "eforms", "cbc:"):
        assert ted_term not in serialized

    # Seul emprunt assumé : le NOM DU RÉFÉRENTIEL d'un identifiant, que SPEC-001
    # laisse volontairement libre (« CHE-UID », « EU-VAT », « TED-ORG-ID »…).
    # C'est une donnée qui dit d'où vient la valeur, pas un champ du modèle.
    assert '"scheme":"TED-BT-501"' in serialized
    assert not any("ted" in name.lower() for name in ContractAward.model_fields)
    assert not any("ted" in name.lower() for name in PublicEvent.model_fields)


def test_le_nom_publie_n_est_jamais_reecrit():
    """566131 publie `&amp;amp;` : la double échappée de l'émetteur est conservée."""
    result = extract(load("566131-2026"))
    names = {a.awardee_organizations()[0].legal_name for a in result.awards}
    assert "Widmans Kross &amp; Grus" in names


# ─── SPEC-002R — soumissionnaires, acheteurs, identifiants ──────────────────────


def test_r_a_un_contrat_une_entreprise_seule():
    """A — le cas courant : une party, un membre, rôle `sole`."""
    award = extract(load("550374-2026")).awards[0]
    assert len(award.awardee_parties) == 1
    assert len(award.awardee_parties[0].members) == 1
    assert award.awardee_parties[0].members[0].role == "sole"
    assert not award.awardee_parties[0].is_group


def test_r_b_un_contrat_un_groupement():
    """B — une seule party, plusieurs membres, chef de file désigné par la source."""
    award = extract(load("566119-2026")).awards[0]
    assert len(award.awardee_parties) == 1
    party = award.awardee_parties[0]
    assert party.is_group and len(party.members) == 4
    assert [m.role for m in party.members].count("consortium_lead") == 1


def test_r_c_un_contrat_plusieurs_parties_independantes():
    """C — le motif réel de 566075-2026 : 9 soumissionnaires, aucun groupement."""
    award = next(a for a in extract(load("566075-2026")).awards if len(a.awardee_parties) > 1)
    assert len(award.awardee_parties) == 9
    assert all(not p.is_group for p in award.awardee_parties)
    assert {m.role for p in award.awardee_parties for m in p.members} == {"sole"}


def test_r_d_plusieurs_parties_dont_un_groupement():
    """D — INVARIANT ARCHITECTURAL, cas synthétique.

    Ce motif n'a PAS été observé sur TED : il découle de la structure eForms
    (un contrat peut référencer plusieurs offres, chaque offre pouvant venir
    d'un groupement). Le test prouve que le modèle sait le représenter, il ne
    prétend pas que le cas existe dans les données actuelles.
    """
    seule = AwardeeParty(members=(Awardee(organization=OrganizationRef(legal_name="Solo SA")),))
    groupee = AwardeeParty(
        name="Groupement Alpha",
        members=(
            Awardee(organization=OrganizationRef(legal_name="Alpha SA"), role="consortium_lead"),
            Awardee(organization=OrganizationRef(legal_name="Beta SA"), role="consortium_member"),
        ),
    )
    award = ContractAward(
        event_ref=EventRef(source_system="ted", source_notice_id="synthetique"),
        awardee_parties=(seule, groupee),
    )
    assert [p.is_group for p in award.awardee_parties] == [False, True]
    assert len(award.awardee_organizations()) == 3
    # aucune fusion : le groupement reste un groupement, le solo reste seul
    assert award.awardee_parties[0].members[0].role == "sole"


def test_r_e_achat_conjoint_les_deux_acheteurs_sont_conserves():
    """E — 565942-2026 publie deux `ContractingParty` : les deux sont gardés."""
    result = extract(load("565942-2026"))
    assert len(result.awards) == 2
    assert [b.legal_name for b in result.event.procedure_buyers] == [
        "Simas Iks",
        "Sunnfjord Miljøverk Iks",
    ]
    # aucun des deux n'est promu signataire d'un contrat
    assert all(award.contract_signatories == () for award in result.awards)
    assert not [w for w in result.warnings if "buyer" in w.code]


def test_r_f_procedure_identifier_conserve():
    """F — BT-04, présent sur 46 notices sur 46."""
    result = extract(load("550374-2026"))
    assert result.event.provenance.source_procedure_id == "bbad9844-d1bc-43b1-ad15-b83c65cc9b52"
    # distinct de tous les autres identifiants
    assert result.event.provenance.source_procedure_id != result.event.provenance.source_notice_id
    assert result.event.provenance.source_procedure_id != result.awards[0].source_award_id


def test_r_f_bis_deux_avis_distincts_partagent_la_procedure():
    """F — preuve réelle : l'appel d'offres et l'avis d'adjudication du même marché.

    `183632-2026` est l'avis d'appel d'offres (ContractNotice) — hors périmètre
    du parser, qui n'accepte que les avis d'adjudication. Son BT-04 est donc lu
    directement, à la main, pour la comparaison.
    """
    award_notice = extract(load("550374-2026")).event

    call_for_competition = ElementTree.fromstring(load("183632-2026"))
    cbc = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"
    autre_uuid = call_for_competition.findtext(f"{cbc}ID")
    autre_procedure = call_for_competition.findtext(f"{cbc}ContractFolderID")

    assert autre_uuid != award_notice.provenance.source_notice_id  # deux avis différents
    assert autre_procedure == award_notice.provenance.source_procedure_id  # même procédure


def test_r_f_ter_la_procedure_n_entre_pas_dans_l_identite_de_l_evenement():
    """Plusieurs avis partagent BT-04 : il ne peut pas identifier un événement."""
    result = extract(load("550374-2026"))
    assert result.event.provenance.source_procedure_id not in result.event.natural_key()
    assert "source_procedure_id" not in SourceIdentity.model_fields


def test_r_g_contract_reference_conservee_sans_toucher_a_l_identite():
    """G — BT-150 est un fait métier, pas une identité ni une clé de rapprochement."""
    simple = extract(load("550374-2026")).awards[0]
    cadre = {a.source_award_id: a for a in extract(load("566075-2026")).awards}

    assert simple.contract_reference == "MP 2026-SAAP-001"
    assert cadre["CON-0017"].contract_reference == "8640"
    assert cadre["CON-0016"].contract_reference == "8613"

    # l'identité reste l'identifiant technique
    assert simple.source_identity().source_award_id == "CON-0001"
    assert simple.contract_reference not in str(simple.source_identity().model_dump())

    # et l'empreinte de rapprochement l'ignore
    sans_reference = simple.model_copy(update={"contract_reference": None})
    assert sans_reference.dedupe_fingerprint() == simple.dedupe_fingerprint()


def test_r_h_aucun_role_de_groupement_sans_groupement_publie():
    """H — sur tout le corpus embarqué, `consortium_*` n'apparaît que si la source groupe."""
    for publication in (
        "550374-2026",
        "566075-2026",
        "566114-2026",
        "566117-2026",
        "566129-2026",
        "566131-2026",
        "565942-2026",
        "566039-2026",
    ):
        for award in extract(load(publication)).awards:
            for party in award.awardee_parties:
                roles = {m.role for m in party.members}
                assert (
                    roles == {"sole"}
                    if len(party.members) == 1
                    else roles
                    <= {
                        "consortium_lead",
                        "consortium_member",
                    }
                )


# ─── SPEC-002R2 — acheteurs de procédure vs signataires de contrat ──────────────


def test_r2_a_acheteur_unique_sans_signataire_publie():
    """A — 566116-2026 : un acheteur de procédure, aucun signataire inventé."""
    result = extract(load("566116-2026"))
    assert [b.legal_name for b in result.event.procedure_buyers] == [
        "degewo Nord Wohnungsgesellschaft mbH"
    ]
    assert all(award.contract_signatories == () for award in result.awards)


def test_r2_b_acheteur_unique_et_signataire_explicite():
    """B — 550374-2026 : la même organisation, mais dans deux rôles distincts."""
    result = extract(load("550374-2026"))
    award = result.awards[0]
    nom = "Société Aéroport Avignon Provence"

    assert [b.legal_name for b in result.event.procedure_buyers] == [nom]
    assert [s.legal_name for s in award.contract_signatories] == [nom]
    # les deux faits restent portés séparément, à leur portée respective
    assert "procedure_buyers" in PublicEvent.model_fields
    assert "procedure_buyers" not in ContractAward.model_fields
    assert "contract_signatories" not in PublicEvent.model_fields


def test_r2_c_achat_conjoint_sans_signataire():
    """C — 565942-2026 : deux acheteurs conservés, aucun promu signataire."""
    result = extract(load("565942-2026"))
    assert len(result.event.procedure_buyers) == 2
    assert all(award.contract_signatories == () for award in result.awards)
    assert not any(w.code.startswith("signatory") for w in result.warnings)


def test_r2_d_plusieurs_signataires_conserves():
    """D — INVARIANT ARCHITECTURAL, cas synthétique.

    Sur 289 contrats réels, aucun n'a plus d'un `SignatoryParty`. Le test prouve
    que le modèle ne l'interdit pas ; il n'affirme pas que le cas existe.
    """
    award = ContractAward(
        event_ref=EventRef(source_system="ted", source_notice_id="synthetique"),
        contract_signatories=(
            OrganizationRef(legal_name="Hôpital A"),
            OrganizationRef(legal_name="Hôpital B"),
        ),
        winner_status="undisclosed",
    )
    assert [s.legal_name for s in award.contract_signatories] == ["Hôpital A", "Hôpital B"]


def test_r2_e_signataire_absent_des_acheteurs_de_procedure():
    """E — 565986-2026 : une centrale d'achat mène, une autre entité signe.

    C'est un fait réel, pas une anomalie : `CPO LT` conduit la procédure, l'hôpital
    signe. Les deux sont conservés séparément et le cas est signalé.
    """
    result = extract(load("565986-2026"))
    assert [b.legal_name for b in result.event.procedure_buyers] == ["Viešoji įstaiga CPO LT"]

    for award in result.awards:
        assert [s.legal_name for s in award.contract_signatories] == [
            "VšĮ Lietuvos sveikatos mokslų universiteto Kauno ligoninė"
        ]
    # le signataire n'a pas été ajouté en douce aux acheteurs de la procédure
    assert "Kauno" not in " ".join(b.legal_name for b in result.event.procedure_buyers)
    assert [w.code for w in result.warnings if w.code.startswith("signatory")] == [
        "signatory-outside-procedure-buyers"
    ] * 2


def test_r2_f_bt150_absent_reste_absent():
    """566116-2026 ne publie aucun `efac:ContractReference` — le parsing tient."""
    assert b"ContractReference" not in load("566116-2026")
    result = extract(load("566116-2026"))
    assert len(result.awards) == 1
    assert result.awards[0].contract_reference is None
    # le contrat reste exploitable : identité, lot et attributaire intacts
    assert result.awards[0].source_identity() is not None
    assert result.awards[0].awardee_parties


def test_r2_g_comptage_des_procedures_sur_deux_avis_du_meme_marche():
    """Deux avis distincts, une seule procédure — le compteur ne doit pas doubler."""
    award_notice = extract(load("550374-2026")).event

    cbc = "{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"
    call = ElementTree.fromstring(load("183632-2026"))
    autre_uuid = call.findtext(f"{cbc}ID")
    autre_procedure = call.findtext(f"{cbc}ContractFolderID")
    autre_publication = "183632-2026"

    # identités de notice différentes
    assert autre_uuid != award_notice.provenance.source_notice_id
    # publications différentes
    assert autre_publication not in (award_notice.provenance.source_url or "")
    # même procédure
    assert autre_procedure == award_notice.provenance.source_procedure_id
    # la paire ne compte que pour UNE procédure
    procedures = {autre_procedure, award_notice.provenance.source_procedure_id}
    assert len(procedures) == 1
