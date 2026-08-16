"""Les huit scénarios obligatoires de SPEC-001.

Les données sont des fixtures inventées pour l'exercice — seule la FORME imite
SIMAP et TED. Aucun avis réel n'est reproduit ici.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from signals.domain import (
    Awardee,
    AwardeeParty,
    ContractAward,
    Duration,
    Location,
    LotRef,
    Money,
    OrganizationIdentifier,
    OrganizationRef,
    Provenance,
    PublicEvent,
    SourceIdentity,
)


def sole(name: str, **kwargs) -> AwardeeParty:
    """Un soumissionnaire retenu seul — le cas courant."""
    return AwardeeParty(members=(Awardee(organization=OrganizationRef(legal_name=name, **kwargs)),))


def group(*names: str, lead: str | None = None, party_name: str | None = None) -> AwardeeParty:
    """Un groupement : plusieurs organisations, UN soumissionnaire."""
    return AwardeeParty(
        members=tuple(
            Awardee(
                organization=OrganizationRef(legal_name=n),
                role="consortium_lead" if n == lead else "consortium_member",
            )
            for n in names
        ),
        name=party_name,
    )


# ─── Fixtures de forme SIMAP ────────────────────────────────────────────────────

SIMAP_PROVENANCE = Provenance(
    source_system="simap",
    source_country="CH",
    source_notice_id="1483221",
    source_url="https://www.simap.ch/shabforms/servlet/Search?NOTICE_NR=1483221",
    retrieved_at=dt.datetime(2026, 3, 12, 8, 30, tzinfo=dt.UTC),
)

ETAT_DU_VALAIS = OrganizationRef(
    legal_name="Etat du Valais — Service des bâtiments",
    identifiers=(OrganizationIdentifier(scheme="CHE-UID", value="CHE-123.456.789"),),
    country="CH",
    address="Place de la Planta 3, 1950 Sion",
)


def simap_event() -> PublicEvent:
    return PublicEvent(
        provenance=SIMAP_PROVENANCE,
        event_type="award_notice",
        published_at=dt.date(2026, 3, 10),
        event_date=dt.date(2026, 2, 24),
        procedure_buyers=(ETAT_DU_VALAIS,),
    )


# ─── Fixtures de forme TED ──────────────────────────────────────────────────────

TED_PROVENANCE = Provenance(
    source_system="ted",
    source_country="FR",
    source_notice_id="456789-2026",
    notice_version="1",
    source_url="https://ted.europa.eu/en/notice/-/detail/456789-2026",
    retrieved_at=dt.datetime(2026, 3, 12, 8, 31, tzinfo=dt.UTC),
)


def ted_event() -> PublicEvent:
    return PublicEvent(
        provenance=TED_PROVENANCE,
        event_type="award_notice",
        published_at=dt.date(2026, 3, 5),
        event_date=dt.date(2026, 2, 18),
    )


# ─── TEST 1 — Award suisse simple ───────────────────────────────────────────────


def test_1_award_suisse_simple():
    event = simap_event()
    award = ContractAward(
        event_ref=event.ref(),
        lot=LotRef(identifier="1", title="Installations CVC"),
        title="Rénovation énergétique — installations CVC",
        cpv_main="45331000-6",
        value=Money(amount=Decimal("1240000.00"), currency="CHF"),
        contract_signatories=(ETAT_DU_VALAIS,),
        awardee_parties=(
            sole(
                "Thermalp Installations SA",
                identifiers=(OrganizationIdentifier(scheme="CHE-UID", value="CHE-987.654.321"),),
                country="CH",
            ),
        ),
        place_of_performance=Location(
            country="CH", subdivision_code="CH-VS", subdivision_scheme="ISO-3166-2", locality="Sion"
        ),
        award_date=dt.date(2026, 2, 24),
    )

    assert award.belongs_to(event.ref())
    # l'acheteur de la procédure vit sur l'événement, le signataire sur le contrat
    assert [b.legal_name for b in event.procedure_buyers] == [ETAT_DU_VALAIS.legal_name]
    assert [s.legal_name for s in award.contract_signatories] == [ETAT_DU_VALAIS.legal_name]
    assert award.value.currency == "CHF"
    assert str(award.cpv_main) == "45331000-6"
    assert award.cpv_main.code == "45331000"
    assert award.winner_status == "identified"
    assert len(award.awardee_parties) == 1
    assert award.awardee_parties[0].members[0].role == "sole"


# ─── TEST 2 — Award TED simple ──────────────────────────────────────────────────


def test_2_award_ted_simple():
    event = ted_event()
    award = ContractAward(
        event_ref=event.ref(),
        lot=LotRef(identifier="LOT-1"),
        title="Fourniture de matériel réseau",
        cpv_main="32420000-3",
        value=Money(amount=Decimal("2750000"), currency="EUR"),
        contract_signatories=(
            OrganizationRef(
                legal_name="Région Auvergne-Rhône-Alpes",
                identifiers=(OrganizationIdentifier(scheme="EU-VAT", value="FR12345678901"),),
                country="FR",
            ),
        ),
        awardee_parties=(
            sole(
                "Réseaux & Systèmes SAS",
                identifiers=(OrganizationIdentifier(scheme="EU-VAT", value="FR98765432109"),),
                country="FR",
            ),
        ),
        place_of_performance=Location(
            country="FR", subdivision_code="FRK2", subdivision_scheme="NUTS", locality="Lyon"
        ),
        award_date=dt.date(2026, 2, 18),
    )

    assert award.value.currency == "EUR"
    assert award.place_of_performance.subdivision_scheme == "NUTS"
    # Le modèle est le même que pour la Suisse : mêmes champs, mêmes types.
    assert type(award) is ContractAward


def test_2b_les_deux_sources_partagent_exactement_le_meme_modele():
    """Aucun champ, aucune classe n'est propre à une source."""
    ch = simap_event()
    eu = ted_event()
    assert set(PublicEvent.model_fields) == set(type(ch).model_fields) == set(type(eu).model_fields)
    assert type(ch) is type(eu)


# ─── TEST 3 — Montant absent ────────────────────────────────────────────────────


def test_3_montant_absent_ne_fait_pas_echouer_import():
    award = ContractAward(
        event_ref=simap_event().ref(),
        lot=LotRef(identifier="2"),
        title="Prestations d'architecte",
        awardee_parties=(sole("Atelier Rhône Sàrl"),),
    )
    assert award.value is None


def test_3b_un_montant_sans_devise_est_refuse():
    """L'inverse du cas précédent : l'absence est permise, l'à-peu-près non."""
    with pytest.raises(ValueError):
        Money(amount=Decimal("1000"))


# ─── TEST 4 — Plusieurs lots ────────────────────────────────────────────────────


def test_4_plusieurs_lots_sans_collision():
    event = simap_event()
    lots = [
        ("1", "Gros œuvre", "3200000", "Constructions Dupont SA"),
        ("2", "Second œuvre", "1450000", "Finitions Alpines SA"),
        ("3", "Aménagements extérieurs", "620000", "Paysages du Rhône Sàrl"),
    ]
    awards = tuple(
        ContractAward(
            event_ref=event.ref(),
            lot=LotRef(identifier=identifier, title=titre),
            value=Money(amount=Decimal(montant), currency="CHF"),
            awardee_parties=(sole(gagnant),),
            award_date=dt.date(2026, 2, 24),
        )
        for identifier, titre, montant, gagnant in lots
    )

    assert len(awards) == 3
    assert all(a.belongs_to(event.ref()) for a in awards)
    # une seule notice, trois lots, trois contrats qui ne se confondent pas
    assert len({a.lot.identifier for a in awards}) == 3
    assert len({a.dedupe_fingerprint() for a in awards}) == 3


# ─── TEST 5 — Plusieurs gagnants / consortium ───────────────────────────────────


def test_5_consortium_plusieurs_organisations_un_seul_contrat():
    award = ContractAward(
        event_ref=ted_event().ref(),
        lot=LotRef(identifier="LOT-2"),
        value=Money(amount=Decimal("8400000"), currency="EUR"),
        awardee_parties=(
            group(
                "Génie Civil Alpes SA",
                "Tunnels & Ouvrages SAS",
                "Bau Consult GmbH",
                lead="Génie Civil Alpes SA",
            ),
        ),
    )
    # UN soumissionnaire, trois organisations — pas trois soumissionnaires
    assert len(award.awardee_parties) == 1
    assert award.awardee_parties[0].is_group
    assert len(award.awardee_parties[0].members) == 3
    assert sum(m.role == "consortium_lead" for m in award.awardee_parties[0].members) == 1


def test_5b_accord_cadre_meme_lot_plusieurs_attributaires_distincts():
    """Cas où un même lot produit PLUSIEURS contrats — l'inverse du consortium."""
    event = ted_event()
    titulaires = ["Conseil Nord SAS", "Conseil Sud SARL", "Conseil Est SA"]
    awards = tuple(
        ContractAward(
            event_ref=event.ref(),
            lot=LotRef(identifier="LOT-1"),
            source_award_id=f"CTR-{index}",
            awardee_parties=(sole(nom),),
        )
        for index, nom in enumerate(titulaires, start=1)
    )
    # trois contrats indépendants, jamais agrégés en un consortium
    assert len({a.source_identity() for a in awards}) == 3
    assert all(a.awardee_parties[0].members[0].role == "sole" for a in awards)


def test_5e_consortium_et_multi_attributaires_ne_se_confondent_pas():
    """Situation A (un contrat, trois co-titulaires) vs situation B (trois contrats)."""
    event = ted_event()

    consortium = ContractAward(
        event_ref=event.ref(),
        lot=LotRef(identifier="LOT-3"),
        source_award_id="CTR-A",
        awardee_parties=(group("Entreprise A", "Entreprise B", lead="Entreprise A"),),
    )

    independants = tuple(
        ContractAward(
            event_ref=event.ref(),
            lot=LotRef(identifier="LOT-4"),
            source_award_id=f"CTR-{suffixe}",
            awardee_parties=(sole(nom),),
        )
        for suffixe, nom in (("B1", "Entreprise A"), ("B2", "Entreprise B"), ("B3", "Entreprise C"))
    )

    # A : UN contrat, UN soumissionnaire, deux organisations groupées
    assert len(consortium.awardee_parties) == 1
    assert {m.role for m in consortium.awardee_parties[0].members} == {
        "consortium_lead",
        "consortium_member",
    }

    # B : TROIS contrats, un soumissionnaire seul chacun — aucun rôle de groupement
    assert len(independants) == 3
    assert all(len(a.awardee_parties) == 1 for a in independants)
    assert all(len(a.awardee_parties[0].members) == 1 for a in independants)
    assert not any(
        m.role.startswith("consortium")
        for award in independants
        for party in award.awardee_parties
        for m in party.members
    )
    assert len({a.source_identity() for a in independants}) == 3


def test_5c_le_modele_n_impose_pas_de_gagnant_quand_la_source_n_en_publie_pas():
    award = ContractAward(
        event_ref=simap_event().ref(),
        lot=LotRef(identifier="4"),
        winner_status="undisclosed",
    )
    assert award.awardee_parties == ()


def test_5d_gagnant_ambigu_signalable():
    award = ContractAward(
        event_ref=simap_event().ref(),
        winner_status="ambiguous",
        awardee_parties=(sole("Müller AG"), sole("Mueller AG, Zürich")),
    )
    assert award.winner_status == "ambiguous"


# ─── TEST 6 — Dates distinctes ──────────────────────────────────────────────────


def test_6_dates_distinctes():
    event = PublicEvent(
        provenance=SIMAP_PROVENANCE,
        event_type="award_notice",
        published_at=dt.date(2026, 3, 10),
        event_date=dt.date(2026, 2, 24),
    )
    award = ContractAward(
        event_ref=event.ref(),
        award_date=dt.date(2026, 2, 24),
        contract_signature_date=dt.date(2026, 3, 20),
        contract_start_date=dt.date(2026, 4, 1),
        contract_end_date=dt.date(2028, 3, 31),
        duration=Duration(value=24, unit="month"),
        awardee_parties=(sole("Thermalp Installations SA"),),
    )

    assert event.published_at != event.event_date
    assert award.award_date != award.contract_signature_date != award.contract_start_date
    assert award.duration.unit == "month"


def test_6b_dates_absentes_supportees():
    award = ContractAward(
        event_ref=simap_event().ref(),
        awardee_parties=(sole("Atelier Rhône Sàrl"),),
    )
    assert award.award_date is None
    assert award.contract_start_date is None
    assert award.duration is None


def test_6c_duree_jamais_deduite_des_dates():
    """start + end connus n'inventent pas une durée : elle reste absente."""
    award = ContractAward(
        event_ref=simap_event().ref(),
        contract_start_date=dt.date(2026, 4, 1),
        contract_end_date=dt.date(2028, 3, 31),
        winner_status="undisclosed",
    )
    assert award.duration is None


# ─── TEST 7 — Provenance ────────────────────────────────────────────────────────


def test_7_provenance_retrouvable_depuis_l_award():
    event = ted_event()
    award = ContractAward(
        event_ref=event.ref(),
        awardee_parties=(sole("Réseaux & Systèmes SAS"),),
    )

    # depuis le contrat : système source + identifiant de notice
    assert award.event_ref.source_system == "ted"
    assert award.event_ref.source_notice_id == "456789-2026"

    # depuis l'événement : pays de la source + URL d'origine
    assert event.provenance.source_country == "FR"
    assert event.provenance.source_url == "https://ted.europa.eu/en/notice/-/detail/456789-2026"
    assert event.provenance.retrieved_at is not None


def test_7b_correction_rattachee_a_l_evenement_corrige():
    original = ted_event()
    correction = PublicEvent(
        provenance=TED_PROVENANCE.model_copy(update={"notice_version": "2"}),
        event_type="award_correction",
        published_at=dt.date(2026, 3, 18),
        corrects=original.ref(),
    )
    assert correction.corrects == original.ref()
    assert correction.natural_key() != original.natural_key()


# ─── TEST 8 — Identité source certaine VS empreinte de rapprochement ────────────


def test_8_identite_source_quand_la_source_la_publie():
    award = ContractAward(
        event_ref=ted_event().ref(),
        lot=LotRef(identifier="LOT-1"),
        source_award_id="CTR-2026-0041",
        awardee_parties=(sole("Réseaux & Systèmes SAS"),),
    )
    assert award.source_identity() == SourceIdentity(
        source_system="ted",
        source_notice_id="456789-2026",
        notice_version="1",
        lot_identifier="LOT-1",
        source_award_id="CTR-2026-0041",
    )


def test_8b_aucune_identite_certaine_sans_identifiant_publie():
    """(notice, lot) ne suffit pas : un accord-cadre attribue plusieurs contrats au même lot."""
    award = ContractAward(
        event_ref=simap_event().ref(),
        lot=LotRef(identifier="1"),
        awardee_parties=(sole("Thermalp Installations SA"),),
    )
    assert award.source_identity() is None
    # ...mais l'absence d'identité n'empêche pas de rapprocher
    assert award.dedupe_fingerprint() is not None


def test_8c_deux_contrats_indiscernables_par_le_contenu_restent_distincts():
    """LE cas qui interdit de traiter l'empreinte comme une identité.

    Même lot, même gagnant, même montant, même date d'adjudication — et pourtant
    deux contrats, parce que la source publie deux identifiants.
    """
    commun = {
        "event_ref": ted_event().ref(),
        "lot": LotRef(identifier="LOT-7"),
        "value": Money(amount=Decimal("450000"), currency="EUR"),
        "award_date": dt.date(2026, 2, 18),
        "awardee_parties": (sole("Conseil Nord SAS"),),
    }
    premier = ContractAward(**commun, source_award_id="CTR-A")
    second = ContractAward(**commun, source_award_id="CTR-B")

    # l'heuristique les rapproche — c'est son rôle : signaler, pas trancher
    assert premier.dedupe_fingerprint() == second.dedupe_fingerprint()
    # la source, elle, les sépare — et c'est elle qui fait autorité
    assert premier.source_identity() != second.source_identity()
    assert premier != second


def test_8d_sans_identifiant_le_domaine_n_affirme_rien():
    """Deux enregistrements de contenu identique : une PISTE, pas une conclusion."""
    commun = {
        "event_ref": simap_event().ref(),
        "lot": LotRef(identifier="1"),
        "value": Money(amount=Decimal("1240000"), currency="CHF"),
        "award_date": dt.date(2026, 2, 24),
        "awardee_parties": (sole("Thermalp Installations SA"),),
    }
    premier = ContractAward(**commun)
    second = ContractAward(**commun)

    assert premier.dedupe_fingerprint() == second.dedupe_fingerprint()
    assert premier.source_identity() is None
    assert second.source_identity() is None
    # aucune méthode ne prétend produire une identité canonique calculée
    assert not hasattr(premier, "identity")


def test_8e_empreinte_stable_malgre_les_variations_de_forme():
    """Casse, espaces et écriture du montant ne changent pas les faits comparés."""
    base = ContractAward(
        event_ref=simap_event().ref(),
        lot=LotRef(identifier="1"),
        value=Money(amount=Decimal("1240000"), currency="CHF"),
        awardee_parties=(sole("Thermalp Installations SA"),),
        award_date=dt.date(2026, 2, 24),
    )
    variante = ContractAward(
        event_ref=simap_event().ref(),
        lot=LotRef(identifier="1", title="Installations CVC"),
        value=Money(amount=Decimal("1240000.00"), currency="chf"),
        awardee_parties=(sole("THERMALP  INSTALLATIONS SA"),),
        award_date=dt.date(2026, 2, 24),
    )
    assert base.dedupe_fingerprint() == variante.dedupe_fingerprint()


def test_8f_pas_d_empreinte_quand_les_faits_manquent():
    """Une empreinte calculée sur du vide ferait collisionner tous les avis pauvres."""
    rien = ContractAward(event_ref=simap_event().ref(), winner_status="undisclosed")
    assert rien.dedupe_fingerprint() is None

    un_seul_fait = ContractAward(
        event_ref=simap_event().ref(),
        lot=LotRef(identifier="1"),
        winner_status="undisclosed",
    )
    assert un_seul_fait.dedupe_fingerprint() is None


def test_8g_empreinte_distincte_des_qu_un_fait_distingue_les_contrats():
    commun = {
        "event_ref": simap_event().ref(),
        "lot": LotRef(identifier="1"),
        "award_date": dt.date(2026, 2, 24),
    }
    gagnant_a = ContractAward(
        **commun,
        awardee_parties=(sole("Thermalp Installations SA"),),
    )
    gagnant_b = ContractAward(
        **commun,
        awardee_parties=(sole("Chauffage Sion SA"),),
    )
    montant_different = ContractAward(
        **commun,
        value=Money(amount=Decimal("1240000"), currency="CHF"),
        awardee_parties=(sole("Thermalp Installations SA"),),
    )
    autre_lot = ContractAward(
        **{**commun, "lot": LotRef(identifier="2")},
        awardee_parties=(sole("Thermalp Installations SA"),),
    )

    empreintes = {
        gagnant_a.dedupe_fingerprint(),
        gagnant_b.dedupe_fingerprint(),
        montant_different.dedupe_fingerprint(),
        autre_lot.dedupe_fingerprint(),
    }
    assert len(empreintes) == 4


def test_8h_l_empreinte_ignore_l_evenement_pour_permettre_le_rapprochement():
    """Une republication doit pouvoir être rapprochée de son original."""
    commun = {
        "lot": LotRef(identifier="LOT-1"),
        "value": Money(amount=Decimal("2750000"), currency="EUR"),
        "award_date": dt.date(2026, 2, 18),
        "awardee_parties": (sole("Réseaux & Systèmes SAS"),),
    }
    original = ContractAward(event_ref=ted_event().ref(), **commun)
    republication = ContractAward(
        event_ref=TED_PROVENANCE.model_copy(update={"notice_version": "2"}).ref(), **commun
    )

    assert original.event_ref != republication.event_ref
    assert original.dedupe_fingerprint() == republication.dedupe_fingerprint()


def test_8i_deux_portails_au_contenu_identique_ne_sont_pas_declares_identiques():
    """Même lot, même gagnant, même montant, deux portails : rapprochables, pas confondus."""
    commun = {
        "lot": LotRef(identifier="1"),
        "value": Money(amount=Decimal("100000"), currency="EUR"),
        "awardee_parties": (sole("Homonyme SA"),),
        "source_award_id": "1",
    }
    ch = ContractAward(event_ref=simap_event().ref(), **commun)
    eu = ContractAward(event_ref=ted_event().ref(), **commun)

    assert ch.dedupe_fingerprint() == eu.dedupe_fingerprint()
    assert ch.source_identity() != eu.source_identity()
    assert ch.source_identity().source_system != eu.source_identity().source_system


# ─── TEST 9 — Précision temporelle de la publication ────────────────────────────


def test_9_publication_date_seule_conservee_telle_quelle():
    """Cas A : la source ne publie qu'une date. Aucune heure n'est inventée."""
    event = PublicEvent(
        provenance=SIMAP_PROVENANCE,
        event_type="award_notice",
        published_at=dt.date(2026, 8, 16),
    )
    assert event.published_at == dt.date(2026, 8, 16)
    assert not isinstance(event.published_at, dt.datetime)
    assert event.published_precision() == "date"
    # sérialisation : une date reste une date, pas un « 2026-08-16T00:00:00 »
    assert event.model_dump(mode="json")["published_at"] == "2026-08-16"


def test_9b_publication_horodatee_conservee_a_la_seconde_et_au_fuseau():
    """Cas B : la source publie un instant complet. Rien n'est arrondi au jour."""
    instant = dt.datetime(2026, 8, 16, 9, 42, 17, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    event = PublicEvent(
        provenance=TED_PROVENANCE,
        event_type="award_notice",
        published_at=instant,
    )
    assert event.published_at == instant
    assert event.published_at.hour == 9
    assert event.published_at.minute == 42
    assert event.published_at.second == 17
    assert event.published_at.utcoffset() == dt.timedelta(hours=2)
    assert event.published_precision() == "datetime"


def test_9c_la_forme_publiee_par_la_source_decide_de_la_precision():
    """Les deux formes ISO 8601 telles qu'un connecteur les recevra."""
    date_seule = PublicEvent(
        provenance=SIMAP_PROVENANCE, event_type="award_notice", published_at="2026-08-16"
    )
    horodate = PublicEvent(
        provenance=TED_PROVENANCE,
        event_type="award_notice",
        published_at="2026-08-16T09:42:17+02:00",
    )
    assert date_seule.published_precision() == "date"
    assert horodate.published_precision() == "datetime"
    assert horodate.model_dump(mode="json")["published_at"] == "2026-08-16T09:42:17+02:00"


def test_9d_publication_absente_reste_absente():
    event = PublicEvent(provenance=SIMAP_PROVENANCE, event_type="award_notice")
    assert event.published_at is None
    assert event.published_precision() is None


# ─── VÉRIFICATION — complétude de PublicEvent ───────────────────────────────────


def test_public_event_conserve_tout_ce_que_la_source_publie():
    event = PublicEvent(
        provenance=TED_PROVENANCE,
        event_type="award_notice",
        published_at=dt.datetime(2026, 3, 5, 11, 0, tzinfo=dt.UTC),
        event_date=dt.date(2026, 2, 18),
    )
    assert event.provenance.source_system == "ted"
    assert event.provenance.source_country == "FR"
    assert event.provenance.source_notice_id == "456789-2026"
    assert event.provenance.notice_version == "1"
    assert event.provenance.source_url.startswith("https://ted.europa.eu/")
    assert event.event_type == "award_notice"
    assert event.published_precision() == "datetime"
    assert event.event_date == dt.date(2026, 2, 18)


def test_public_event_ne_remplit_pas_les_champs_absents():
    """Une notice SIMAP sans version ni date d'événement ne se voit rien attribuer."""
    event = PublicEvent(
        provenance=Provenance(
            source_system="simap", source_country="CH", source_notice_id="1483221"
        ),
        event_type="award_notice",
    )
    dump = event.model_dump(mode="json")
    assert dump["provenance"]["notice_version"] is None
    assert dump["provenance"]["source_url"] is None
    assert dump["provenance"]["retrieved_at"] is None
    assert dump["published_at"] is None
    assert dump["event_date"] is None
