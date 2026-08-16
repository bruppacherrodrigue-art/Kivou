"""Ce que le modèle REFUSE — et ce qu'il normalise sans rien inventer."""

from __future__ import annotations

import datetime as dt
import inspect
import re
from decimal import Decimal
from typing import get_args

import pytest
from pydantic import ValidationError

from signals.domain import (
    Awardee,
    AwardeeParty,
    ContractAward,
    CpvCode,
    Duration,
    EventRef,
    Location,
    Money,
    OrganizationIdentifier,
    OrganizationRef,
    Provenance,
    PublicEvent,
    SourceIdentity,
    SourceSystem,
)
from signals.domain import awards as awards_module

EVENT_REF = EventRef(source_system="simap", source_notice_id="1483221")
PROVENANCE = Provenance(source_system="simap", source_country="CH", source_notice_id="1483221")
GAGNANT = (
    AwardeeParty(
        members=(Awardee(organization=OrganizationRef(legal_name="Thermalp Installations SA")),)
    ),
)


# ─── Immuabilité & fermeture ────────────────────────────────────────────────────


def test_un_fait_publie_est_immuable():
    award = ContractAward(event_ref=EVENT_REF, awardee_parties=GAGNANT)
    with pytest.raises(ValidationError):
        award.award_date = dt.date(2026, 2, 24)


def test_un_champ_propre_a_une_source_est_refuse():
    """Le modèle canonique ne se laisse pas contaminer par le vocabulaire d'un portail."""
    with pytest.raises(ValidationError):
        ContractAward(event_ref=EVENT_REF, awardee_parties=GAGNANT, simap_projekt_id="42")


# ─── Argent ─────────────────────────────────────────────────────────────────────


def test_montant_flottant_refuse():
    with pytest.raises(ValueError, match="flottant"):
        Money(amount=1240000.10, currency="CHF")


def test_devise_normalisee_en_majuscules():
    assert Money(amount=Decimal("1"), currency=" chf ").currency == "CHF"


def test_devise_invalide_refusee():
    with pytest.raises(ValidationError):
        Money(amount=Decimal("1"), currency="francs")


def test_montant_negatif_refuse():
    with pytest.raises(ValidationError):
        Money(amount=Decimal("-1"), currency="CHF")


def test_montant_zero_accepte():
    """0 est une valeur publiée, pas une absence — les deux ne se confondent pas."""
    assert Money(amount=Decimal("0"), currency="EUR").amount == 0


def test_canonical_amount_absorbe_les_ecritures_equivalentes():
    a = Money(amount=Decimal("1000"), currency="CHF")
    b = Money(amount=Decimal("1000.00"), currency="CHF")
    assert a.canonical_amount() == b.canonical_amount() == "1000"


# ─── CPV ────────────────────────────────────────────────────────────────────────


def test_cpv_accepte_la_forme_imprimee():
    cpv = CpvCode.model_validate("45331000-6")
    assert (cpv.code, cpv.check_digit) == ("45331000", "6")


def test_cpv_sans_chiffre_de_controle_ne_l_invente_pas():
    assert CpvCode.model_validate("45331000").check_digit is None


def test_cpv_malforme_refuse():
    with pytest.raises(ValidationError):
        CpvCode.model_validate("4533-XX")


# ─── Localisation ───────────────────────────────────────────────────────────────


def test_code_de_subdivision_sans_referentiel_refuse():
    with pytest.raises(ValidationError, match="paire"):
        Location(country="CH", subdivision_code="CH-VS")


def test_localisation_vide_refusee():
    with pytest.raises(ValidationError, match="vide"):
        Location()


def test_pays_normalise():
    assert Location(country="ch").country == "CH"


def test_les_deux_referentiels_coexistent():
    suisse = Location(country="CH", subdivision_code="CH-VS", subdivision_scheme="ISO-3166-2")
    europe = Location(country="FR", subdivision_code="FRK2", subdivision_scheme="NUTS")
    assert type(suisse) is type(europe)


# ─── Organisation ───────────────────────────────────────────────────────────────


def test_organisation_sans_nom_refusee():
    with pytest.raises(ValidationError):
        OrganizationRef(legal_name="   ")


def test_identifiant_par_referentiel():
    org = OrganizationRef(
        legal_name="Thermalp Installations SA",
        identifiers=(
            OrganizationIdentifier(scheme="CHE-UID", value="CHE-987.654.321"),
            OrganizationIdentifier(scheme="SIMAP-ORG-ID", value="55321"),
        ),
    )
    assert org.identifier("CHE-UID") == "CHE-987.654.321"
    assert org.identifier("EU-VAT") is None


# ─── Attributaires ──────────────────────────────────────────────────────────────


def test_undisclosed_avec_attributaire_refuse():
    with pytest.raises(ValidationError, match="undisclosed"):
        ContractAward(event_ref=EVENT_REF, winner_status="undisclosed", awardee_parties=GAGNANT)


def test_identified_sans_attributaire_refuse():
    with pytest.raises(ValidationError, match="au moins un attributaire"):
        ContractAward(event_ref=EVENT_REF, winner_status="identified")


def test_attributaire_unique_avec_role_de_consortium_refuse():
    with pytest.raises(ValidationError, match="'sole'"):
        AwardeeParty(
            members=(
                Awardee(
                    organization=OrganizationRef(legal_name="Thermalp Installations SA"),
                    role="consortium_lead",
                ),
            )
        )


def test_consortium_avec_role_sole_refuse():
    with pytest.raises(ValidationError, match="n'admet pas le rôle"):
        AwardeeParty(
            members=(
                Awardee(organization=OrganizationRef(legal_name="A SA"), role="sole"),
                Awardee(organization=OrganizationRef(legal_name="B SA"), role="consortium_member"),
            )
        )


def test_consortium_a_deux_chefs_de_file_refuse():
    with pytest.raises(ValidationError, match="un seul"):
        AwardeeParty(
            members=(
                Awardee(organization=OrganizationRef(legal_name="A SA"), role="consortium_lead"),
                Awardee(organization=OrganizationRef(legal_name="B SA"), role="consortium_lead"),
            )
        )


def test_consortium_sans_chef_de_file_accepte():
    """Beaucoup d'avis ne désignent pas de chef de file : ne pas en inventer un."""
    party = AwardeeParty(
        members=(
            Awardee(organization=OrganizationRef(legal_name="A SA"), role="consortium_member"),
            Awardee(organization=OrganizationRef(legal_name="B SA"), role="consortium_member"),
        )
    )
    assert len(party.members) == 2
    assert party.is_group


# ─── Dates & durée ──────────────────────────────────────────────────────────────


def test_fin_de_contrat_anterieure_au_debut_refusee():
    with pytest.raises(ValidationError, match="antérieure"):
        ContractAward(
            event_ref=EVENT_REF,
            awardee_parties=GAGNANT,
            contract_start_date=dt.date(2026, 4, 1),
            contract_end_date=dt.date(2026, 3, 1),
        )


def test_duree_nulle_refusee():
    with pytest.raises(ValidationError):
        Duration(value=0, unit="month")


# ─── Événement & provenance ─────────────────────────────────────────────────────


def test_provenance_sans_identifiant_de_notice_refusee():
    with pytest.raises(ValidationError):
        Provenance(source_system="ted", source_country="FR", source_notice_id="")


def test_source_inconnue_refusee():
    with pytest.raises(ValidationError):
        Provenance(source_system="boamp", source_country="FR", source_notice_id="1")


def test_un_avis_ordinaire_ne_corrige_rien():
    with pytest.raises(ValidationError, match="ne corrige aucun"):
        PublicEvent(
            provenance=Provenance(
                source_system="ted", source_country="FR", source_notice_id="456789-2026"
            ),
            event_type="award_notice",
            corrects=EventRef(source_system="ted", source_notice_id="111111-2026"),
        )


def test_une_correction_ne_traverse_pas_les_systemes():
    with pytest.raises(ValidationError, match="même système source"):
        PublicEvent(
            provenance=Provenance(
                source_system="ted", source_country="FR", source_notice_id="456789-2026"
            ),
            event_type="award_correction",
            corrects=EventRef(source_system="simap", source_notice_id="1483221"),
        )


def test_un_evenement_ne_se_corrige_pas_lui_meme():
    provenance = Provenance(
        source_system="ted", source_country="FR", source_notice_id="456789-2026"
    )
    with pytest.raises(ValidationError, match="lui-même"):
        PublicEvent(
            provenance=provenance,
            event_type="award_correction",
            corrects=provenance.ref(),
        )


# ─── Identité source vs empreinte heuristique ───────────────────────────────────


def test_l_ancien_champ_d_identite_calculee_n_existe_plus():
    """Garde-fou : `award_identifier` conflait identité source et discriminant calculé."""
    with pytest.raises(ValidationError):
        ContractAward(event_ref=EVENT_REF, awardee_parties=GAGNANT, award_identifier="CTR-1")


def test_le_domaine_n_expose_aucune_identite_calculee():
    award = ContractAward(event_ref=EVENT_REF, awardee_parties=GAGNANT)
    assert not hasattr(award, "identity")
    assert not hasattr(award, "content_fingerprint")


def test_identite_source_refusee_sans_identifiant_de_contrat():
    with pytest.raises(ValidationError):
        SourceIdentity(source_system="simap", source_notice_id="1483221")


# ─── Précision temporelle ───────────────────────────────────────────────────────


def test_une_date_n_est_jamais_promue_en_datetime():
    event = PublicEvent(
        provenance=PROVENANCE, event_type="award_notice", published_at=dt.date(2026, 8, 16)
    )
    assert type(event.published_at) is dt.date


def test_un_datetime_n_est_jamais_tronque_en_date():
    instant = dt.datetime(2026, 8, 16, 23, 59, 59, tzinfo=dt.UTC)
    event = PublicEvent(provenance=PROVENANCE, event_type="award_notice", published_at=instant)
    assert type(event.published_at) is dt.datetime
    assert event.published_at == instant


def test_datetime_sans_fuseau_conserve_tel_quel():
    """Certaines sources publient une heure locale sans décalage : ne pas en inventer un."""
    event = PublicEvent(
        provenance=PROVENANCE,
        event_type="award_notice",
        published_at="2026-08-16T09:42:17",
    )
    assert event.published_precision() == "datetime"
    assert event.published_at.utcoffset() is None


def test_publication_illisible_refusee():
    with pytest.raises(ValidationError):
        PublicEvent(provenance=PROVENANCE, event_type="award_notice", published_at="16.08.2026")


# ─── Confinement du vocabulaire de source ───────────────────────────────────────


def test_ajouter_un_portail_ne_touche_pas_contract_award():
    """Aucun nom de portail n'apparaît dans le module des contrats attribués."""
    source = inspect.getsource(awards_module)
    for portail in get_args(SourceSystem):
        assert not re.search(rf"\b{portail}\b", source, flags=re.IGNORECASE), portail
