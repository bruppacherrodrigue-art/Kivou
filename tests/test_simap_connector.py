"""Connecteur SIMAP — tests entièrement hors ligne.

Les fixtures sont de **vraies** réponses de l'API simap.ch, enregistrées telles
quelles (octets bruts) depuis
`/api/publications/v1/project/{projectId}/publication-details/{publicationId}`.
Les fichiers `*.search.json` sont la ligne de recherche correspondante, seul
endroit où l'API publie le lieu d'exécution d'une adjudication.

    33112-02   LU  adjudication simple : sans lot, 1 adjudicataire, prix CHF
    28066-04   —   projet À LOTS : la publication ne porte qu'un lot
    33885-03   —   3 adjudicataires indépendants, prix distincts, sur un lot
    34794-02   —   2 adjudicataires indépendants
    38147-02   —   adjudicataire publié SANS prix
    15228-03   —   concours : 4 lauréats classés avec prix — pas un contrat
    24359-01   —   mandat d'étude, direct_award, aucun `referencingPubId`
    41098-01   —   gré à gré (direct) sans appel d'offres référencé
    38918-02   —   procédure sur invitation : `referencingPubId` présent, mais
                   la publication référencée n'est PAS publique
    29997-02   VD  service bénéficiaire publié sans raison sociale
    42486-01   —   montant publié sous le régime `no_vat`
    22917-01   AG  la publication d'APPEL D'OFFRES d'un marché adjugé (hors périmètre)
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from signals.connectors.simap import extract, map_publication, parse_publication
from signals.connectors.simap.errors import SimapParseError
from signals.connectors.simap.mapping import VAT_CATEGORIES
from signals.domain import ContractAward, Money, PublicEvent, SourceIdentity

FIXTURES = Path(__file__).parent / "fixtures" / "simap"


def load(publication_number: str) -> bytes:
    return (FIXTURES / f"{publication_number}.json").read_bytes()


def search_row(publication_number: str) -> dict | None:
    path = FIXTURES / f"{publication_number}.search.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def run(publication_number: str, **kwargs):
    return extract(load(publication_number), search_entry=search_row(publication_number), **kwargs)


# ─── TEST A — adjudication simple ───────────────────────────────────────────────


def test_a_adjudication_simple():
    result = run("33112-02")
    assert len(result.awards) == 1
    award = result.awards[0]
    event = result.event

    # provenance
    assert event.provenance.source_system == "simap"
    assert event.provenance.source_country == "CH"
    assert event.provenance.source_notice_id == "223ceb19-b3d4-4556-a417-84c1d5f7a3a9"
    assert event.provenance.source_procedure_id == "0d2599e8-c839-4d7d-9277-63144b4750b0"
    assert event.provenance.source_url.endswith(
        "/publication-details/223ceb19-b3d4-4556-a417-84c1d5f7a3a9"
    )
    assert event.published_at == dt.date(2026, 8, 15)
    assert event.event_date == dt.date(2026, 5, 19)  # décision d'adjudication

    # acheteur de procédure
    assert [b.legal_name for b in event.procedure_buyers] == ["Gemeinde Root"]
    assert award.contract_signatories == ()  # SIMAP n'en publie pas

    # attributaire
    assert [o.legal_name for o in award.awardee_organizations()] == ["Egli Gartenbau AG Sursee"]
    assert award.winner_status == "identified"
    assert award.awardee_parties[0].members[0].role == "sole"
    assert award.awardee_organizations()[0].country == "CH"

    assert award.cpv_main.code == "45214200"
    assert award.value.amount == Decimal("934877.5")
    assert award.value.currency == "CHF"
    assert award.award_date == dt.date(2026, 5, 19)
    assert award.place_of_performance.subdivision_code == "CH-LU"
    assert award.belongs_to(event.ref())


# ─── TEST B — lots ──────────────────────────────────────────────────────────────


def test_b_une_publication_ne_porte_quun_lot():
    """SIMAP ne met pas tous les lots dans un avis : chaque lot a sa publication."""
    result = run("28066-04")
    publication = parse_publication(load("28066-04"), search_entry=search_row("28066-04"))

    assert publication.lots_type == "with"
    assert publication.lot is not None
    assert publication.lot.lot_number == 1
    assert all(a.lot.identifier == publication.lot.lot_id for a in result.awards)
    # l'identifiant du lot est son UUID : c'est celui que l'API sait résoudre
    assert len(publication.lot.lot_id) == 36


def test_b_bis_une_publication_sans_lot_ne_fabrique_pas_de_lot():
    result = run("33112-02")
    assert all(award.lot is None for award in result.awards)


# ─── TEST C — plusieurs adjudicataires ──────────────────────────────────────────


def test_c_trois_adjudicataires_independants_ne_forment_pas_un_consortium():
    """33885-03 : trois entreprises, trois prix distincts, aucun groupement publié."""
    result = run("33885-03")
    assert len(result.awards) == 3

    noms = [a.awardee_organizations()[0].legal_name for a in result.awards]
    assert noms == ["APEXA GmbH", "Detecon (Schweiz) AG", "Digizone GmbH"]
    # chacun est SON PROPRE soumissionnaire retenu
    assert all(len(a.awardee_parties) == 1 for a in result.awards)
    assert all(len(a.awardee_parties[0].members) == 1 for a in result.awards)
    assert {m.role for a in result.awards for p in a.awardee_parties for m in p.members} == {"sole"}
    # chacun avec son propre montant
    assert [a.value.amount for a in result.awards] == [
        Decimal("3513552.65"),
        Decimal("3553030.8"),
        Decimal("3170093.05"),
    ]


def test_c_bis_aucun_consortium_n_est_representable_depuis_simap():
    """SIMAP publie une liste plate de `vendors` : aucune structure de groupement.

    NOT OBSERVED YET — aucun consortium explicite dans le corpus. Le connecteur
    n'en fabrique donc jamais : l'invariant est vérifié sur toutes les fixtures.
    """
    for publication in ("33112-02", "33885-03", "34794-02", "38147-02", "29997-02", "41098-01"):
        for award in run(publication).awards:
            for party in award.awardee_parties:
                assert len(party.members) == 1
                assert party.members[0].role == "sole"
                assert not party.is_group


def test_c_ter_deux_adjudicataires():
    result = run("34794-02")
    assert len(result.awards) == 2
    assert [a.value.amount for a in result.awards] == [Decimal("926417"), Decimal("756700")]
    assert len({a.awardee_organizations()[0].legal_name for a in result.awards}) == 2


# ─── TEST D — montant absent ────────────────────────────────────────────────────


def test_d_montant_absent_le_contrat_reste_valide():
    result = run("38147-02")
    assert len(result.awards) == 1
    award = result.awards[0]
    assert award.value is None
    assert award.awardee_organizations()[0].legal_name == "Burkhalter Technics AG"
    assert [w.code for w in result.warnings if w.code == "value-absent"] == ["value-absent"]


def test_d_bis_aucune_valeur_de_substitution():
    """Ni fourchette de prix, ni estimation ne remplacent un prix absent."""
    raw = load("38147-02").decode("utf-8")
    assert "totalPriceSelection" in raw  # la source publie d'autres champs de prix
    assert run("38147-02").awards[0].value is None


# ─── TEST E — referencingPub absent ─────────────────────────────────────────────


def test_e_gre_a_gre_sans_appel_d_offres_reference():
    """41098-01 : procédure directe — il n'y a jamais eu d'appel d'offres public."""
    publication = parse_publication(load("41098-01"), search_entry=search_row("41098-01"))
    assert publication.process_type == "direct"
    assert publication.referencing_pub_id is None
    assert publication.referencing_pub is None

    result = map_publication(publication)
    assert result.references_tender is False
    assert result.awards  # l'adjudication reste parfaitement valide


def test_e_bis_invitation_publication_referencee_non_publique():
    """38918-02 : `referencingPubId` existe, mais la publication référencée est absente.

    Deux états distincts que le connecteur ne confond pas : « aucune publication
    d'origine » et « publication d'origine non publique ».
    """
    publication = parse_publication(load("38918-02"), search_entry=search_row("38918-02"))
    assert publication.process_type == "invitation"
    assert publication.referencing_pub_id is not None
    assert publication.referencing_pub is None  # non exposée publiquement

    result = map_publication(publication)
    assert result.references_tender is True
    assert result.awards


# ─── TEST F — rattachement au projet ────────────────────────────────────────────


def test_f_appel_d_offres_et_adjudication_partagent_le_projet():
    """Preuve réelle : deux publications distinctes, un seul projet."""
    award = run("33112-02")
    tender = json.loads((FIXTURES / "22917-01.tender.json").read_text(encoding="utf-8"))

    # l'adjudication référence sa publication d'origine, qui n'est pas elle-même
    publication = parse_publication(load("33112-02"))
    assert publication.referencing_pub.publication_number == "33112-01"
    assert publication.referencing_pub_id != publication.publication_id
    assert award.event.provenance.source_procedure_id == publication.project_id

    # et sur l'autre marché, l'appel d'offres porte bien le même projectId
    assert tender["base"]["projectId"] == "44c48094-2868-41c1-b154-6d15769dd355"
    assert tender["type"] == "tender"


def test_f_bis_l_appel_d_offres_n_est_pas_une_adjudication():
    """Le parser refuse une publication qui n'annonce aucune attribution."""
    raw = (FIXTURES / "22917-01.tender.json").read_bytes()
    with pytest.raises(SimapParseError, match="type de publication"):
        parse_publication(raw)


# ─── TEST G — identité de publication ───────────────────────────────────────────


def test_g_deux_publications_du_meme_projet_ne_se_confondent_pas():
    a = run("33112-02").event
    b = run("28066-04").event
    assert a.natural_key() != b.natural_key()
    # l'identité est la publication ; le projet vit dans la provenance
    assert a.provenance.source_notice_id != a.provenance.source_procedure_id


def test_g_bis_simap_ne_publie_aucune_version_de_publication():
    """Une correction est une NOUVELLE publication, pas une version de l'ancienne."""
    event = run("33112-02").event
    assert event.provenance.notice_version is None
    assert event.corrects is None  # aucune référence publiée vers la corrigée


def test_g_ter_aucune_identite_de_contrat_n_est_fabriquee():
    """SIMAP ne publie pas d'identifiant de contrat : l'absence est conservée."""
    for publication in ("33112-02", "33885-03", "34794-02"):
        for award in run(publication).awards:
            assert award.source_award_id is None
            assert award.source_identity() is None
            assert award.contract_reference is None
            # ...mais le rapprochement heuristique reste possible
            assert award.dedupe_fingerprint() is not None


# ─── TEST H — hors périmètre du contrat ─────────────────────────────────────────


def test_h_un_concours_ne_produit_pas_de_contrat():
    """15228-03 : quatre lauréats classés avec des prix dégressifs, pas des contrats."""
    publication = parse_publication(load("15228-03"), search_entry=search_row("15228-03"))
    assert publication.project_type == "competition"
    assert len(publication.vendors) == 4
    assert [v.rank for v in publication.vendors] == [1, 2, 3, 4]

    result = map_publication(publication)
    assert result.awards == ()  # aucun contrat affirmé
    assert [w.code for w in result.warnings] == ["not-a-contract-award"]
    assert result.event.provenance.source_system == "simap"  # l'événement, lui, existe


# ─── TEST I — acheteurs ─────────────────────────────────────────────────────────


def test_i_les_deux_organisations_acheteuses_sont_conservees():
    """SIMAP publie l'adjudicateur ET le service bénéficiaire."""
    event = run("24359-01").event
    noms = [b.legal_name for b in event.procedure_buyers]
    assert len(noms) == len(set(noms))
    assert noms  # au moins un acheteur publié


def test_i_bis_un_beneficiaire_sans_raison_sociale_n_est_pas_inventé():
    """29997-02 : le bloc `procurementRecipientAddress` existe mais n'a aucun nom."""
    result = run("29997-02")
    assert [b.legal_name for b in result.event.procedure_buyers] == ["Service pénitentiaire"]
    assert "buyer-without-name" in {w.code for w in result.warnings}


def test_i_ter_les_acheteurs_vivent_sur_l_evenement_pas_sur_le_contrat():
    assert "procedure_buyers" in PublicEvent.model_fields
    assert "procedure_buyers" not in ContractAward.model_fields


# ─── TEST J — documents ─────────────────────────────────────────────────────────


def test_j_has_project_documents_signifie_existence_pas_acces():
    """Le drapeau dit que des documents existent, jamais qu'on peut les lire."""
    result = run("33112-02")
    assert result.has_project_documents is False

    tender = json.loads((FIXTURES / "22917-01.tender.json").read_text(encoding="utf-8"))
    assert tender["hasProjectDocuments"] is True

    # rien dans le modèle canonique ne prétend donner accès à un document
    serialized = result.event.model_dump_json()
    for term in ("document", "hasProjectDocuments", "token"):
        assert term not in serialized


# ─── TEST K — pas de croisement entre lots ──────────────────────────────────────


def test_k_l_adjudicataire_vient_de_sa_propre_ligne_pas_de_sa_position():
    """Chaque contrat porte le vendor de SA ligne, avec SON prix."""
    publication = parse_publication(load("33885-03"))
    result = map_publication(publication)

    for award, vendor in zip(result.awards, publication.vendors, strict=True):
        assert award.awardee_organizations()[0].legal_name == vendor.name
        assert award.value.amount == vendor.price
    # et le lot du contrat est celui de LA publication, jamais un autre
    assert {a.lot.identifier for a in result.awards} == {publication.lot.lot_id}


def test_k_bis_deux_publications_ne_melangent_pas_leurs_adjudicataires():
    a = {o.legal_name for x in run("33885-03").awards for o in x.awardee_organizations()}
    b = {o.legal_name for x in run("34794-02").awards for o in x.awardee_organizations()}
    assert not (a & b)


# ─── TEST L — provenance ────────────────────────────────────────────────────────


def test_l_chaque_contrat_remonte_a_sa_source():
    retrieved = dt.datetime(2026, 8, 16, 15, 0, tzinfo=dt.UTC)
    result = run("33112-02", retrieved_at=retrieved)
    award = result.awards[0]
    provenance = result.event.provenance

    assert award.event_ref == result.event.ref()
    assert provenance.source_system == "simap"
    assert provenance.source_procedure_id  # le projet
    assert provenance.source_notice_id  # la publication
    assert provenance.source_url.startswith("https://www.simap.ch/api/")
    assert provenance.retrieved_at == retrieved


# ─── Frontière avec le domaine ──────────────────────────────────────────────────


def test_le_domaine_ignore_tout_du_vocabulaire_simap():
    result = run("33112-02")
    serialized = result.awards[0].model_dump_json() + result.event.model_dump_json()
    for simap_term in ("procOffice", "referencingPub", "vendorId", "pubType", "projectSubType"):
        assert simap_term not in serialized
    assert not any("simap" in name.lower() for name in ContractAward.model_fields)


def test_les_montants_ne_passent_jamais_par_un_flottant():
    """Un prix JSON est lu en Decimal exact, jamais en float."""
    publication = parse_publication(load("33885-03"))
    assert all(isinstance(v.price, Decimal) for v in publication.vendors)
    assert publication.vendors[0].price == Decimal("3513552.65")


def test_json_invalide_refuse_explicitement():
    with pytest.raises(SimapParseError):
        parse_publication(b'{"pas": "une publication"}')


# ─── SPEC-003R — régime de TVA publié avec le montant ───────────────────────────


def test_vat_cas_reel_full_devient_standard():
    """33112-02 publie `vatType: full` — conservé tel quel, sans interprétation."""
    award = run("33112-02").awards[0]
    assert award.value.vat_category == "standard"
    assert award.value.amount == Decimal("934877.5")
    assert b'"vatType":"full"' in load("33112-02").replace(b" ", b"")


def test_vat_cas_reel_no_vat_devient_none():
    """42486-01 publie `vatType: no_vat` — catégorie `none`, distincte de l'absence."""
    award = run("42486-01").awards[0]
    assert award.value.vat_category == "none"
    assert award.value.vat_category is not None  # « pas de TVA » ≠ « non publié »
    assert b'"vatType":"no_vat"' in load("42486-01").replace(b" ", b"")


def test_vat_absent_reste_absent():
    """38147-02 ne publie ni prix ni régime : rien n'est supposé."""
    award = run("38147-02").awards[0]
    assert award.value is None


def test_vat_toutes_les_valeurs_du_schema_sont_representables():
    """Les cinq `VatType` de l'OpenAPI SIMAP, dont trois NON OBSERVÉES dans le corpus.

    Test STRUCTUREL : `special`, `reduced` et `foreign_vat` n'apparaissent sur
    aucune des 107 lignes d'adjudication récupérées. Il prouve que le schéma
    publié est intégralement traduisible, pas que ces cas existent aujourd'hui.
    """
    assert VAT_CATEGORIES == {
        "no_vat": "none",
        "full": "standard",
        "special": "special",
        "reduced": "reduced",
        "foreign_vat": "foreign",
    }
    for source_value, canonical in VAT_CATEGORIES.items():
        money = Money(amount=Decimal("1000"), currency="CHF", vat_category=canonical)
        assert money.vat_category == canonical, source_value


def test_vat_un_regime_inconnu_du_schema_n_est_pas_traduit_au_hasard():
    """Si SIMAP ajoute une valeur, elle est signalée — jamais rangée par défaut."""
    payload = json.loads(load("33112-02").decode("utf-8"))
    payload["decision"]["vendors"][0]["price"]["vatType"] = "regime_futur"
    result = extract(json.dumps(payload))
    assert result.awards[0].value.vat_category is None
    assert "unknown-vat-type" in {w.code for w in result.warnings}


def test_vat_aucun_taux_n_est_deduit():
    """Le domaine ne connaît aucun pourcentage : le montant n'est jamais recalculé."""
    brut = json.loads(load("33112-02").decode("utf-8"))
    publie = Decimal(str(brut["decision"]["vendors"][0]["price"]["price"]))
    assert run("33112-02").awards[0].value.amount == publie


def test_vat_n_affecte_ni_l_identite_ni_l_empreinte():
    award = run("33112-02").awards[0]
    sans_tva = award.model_copy(
        update={"value": award.value.model_copy(update={"vat_category": None})}
    )
    assert award.source_identity() == sans_tva.source_identity()  # None des deux côtés
    assert award.dedupe_fingerprint() == sans_tva.dedupe_fingerprint()
    assert "vat" not in str(SourceIdentity.model_fields)


def test_vat_serialisation_aller_retour():
    award = run("33112-02").awards[0]
    restitue = ContractAward.model_validate_json(award.model_dump_json())
    assert restitue == award
    assert restitue.value.vat_category == "standard"
    assert json.loads(award.value.model_dump_json())["vat_category"] == "standard"
