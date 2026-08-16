"""Tests conçus pour faire dire au moteur plus que ce que l'avis publie.

Chaque cas construit une situation où une compréhension trop zélée produirait
une affirmation fausse, et vérifie que le moteur s'abstient ou baisse sa
confiance. Les cas A à J suivent la liste de la SPEC ; plusieurs reprennent des
motifs réellement rencontrés dans le corpus.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from signals.domain import (
    Awardee,
    AwardeeParty,
    ContractAward,
    Duration,
    Money,
    OrganizationRef,
    Provenance,
    PublicEvent,
)
from signals.understanding import ContractUnderstandingEngine

ENGINE = ContractUnderstandingEngine()


def event(country: str = "CH", source: str = "simap") -> PublicEvent:
    return PublicEvent(
        provenance=Provenance(
            source_system=source,
            source_country=country,
            source_notice_id="notice-1",
            source_procedure_id="projet-1",
            source_url="https://example.invalid/avis",
        ),
        event_type="award_notice",
        published_at=dt.date(2026, 8, 1),
        procedure_buyers=(OrganizationRef(legal_name="Acheteur Public", country=country),),
    )


def award(
    *,
    title: str | None = "Marché",
    description: str | None = None,
    cpv: str | None = "45000000",
    value: Money | None = None,
    parties: tuple[AwardeeParty, ...] | None = None,
    **kwargs,
) -> ContractAward:
    base = event()
    return ContractAward(
        event_ref=base.ref(),
        title=title,
        description=description,
        cpv_main=cpv,
        value=value,
        awardee_parties=parties
        or (
            AwardeeParty(
                members=(Awardee(organization=OrganizationRef(legal_name="Titulaire SA")),)
            ),
        ),
        **kwargs,
    )


def understand(contract: ContractAward, source_event: PublicEvent | None = None):
    return ENGINE.understand(contract, source_event or event())


# ─── A — CPV clair, titre muet ──────────────────────────────────────────────────


def test_a_un_titre_inutilisable_ne_prive_pas_du_cpv():
    """Cas réel : les titres `Default lot`, `Lote 1`, `Reihen` du corpus TED."""
    result = understand(award(title="Lote 1", cpv="45215100"))
    assert result.contract_type.value == "construction"
    assert result.contract_type.confidence == "medium"  # le CPV seul ne fait pas « high »
    assert "CPV seul" in result.contract_type.rule


# ─── B — le titre porte l'information que le CPV générique n'a pas ─────────────


def test_b_maintenance_informatique_est_comprise():
    result = understand(award(title="Maintenance de la solution logiciel HOSPILOG", cpv="72267100"))
    assert result.contract_type.value == "it_digital"
    assert result.contract_type.confidence == "high"  # CPV et texte concordent


# ─── C — contradiction franche ─────────────────────────────────────────────────


def test_c_un_cpv_et_un_titre_contradictoires_abaissent_la_confiance():
    """CPV « travaux », titre « nettoyage » : le moteur ne tranche pas à notre place."""
    result = understand(award(title="Services de nettoyage des locaux", cpv="45000000"))
    assert result.contract_type.confidence == "low"
    assert "divergence" in result.contract_type.rule
    # les deux signaux restent visibles dans la trace
    assert len(result.contract_type.evidence) == 2


# ─── D — un mot n'est pas un objet de contrat ──────────────────────────────────


def test_d_le_mot_cloud_dans_une_formation_ne_fait_pas_une_infrastructure():
    result = understand(
        award(
            title="Formation continue des collaborateurs",
            description="Modules de formation incluant une introduction au cloud.",
            cpv="80500000",
        )
    )
    assert result.contract_type.value == "education_services"
    # aucune caractéristique d'infrastructure n'a été fabriquée
    assert all("cloud" not in c.value for c in result.characteristics)


# ─── E — un gros montant ne dit rien de l'intensité opérationnelle ─────────────


def test_e_un_montant_enorme_ne_produit_aucune_intensite():
    result = understand(
        award(
            title="Marché",
            description=None,
            cpv="45000000",
            value=Money(amount=Decimal("25898370"), currency="EUR"),
        )
    )
    assert result.characteristics == ()  # rien n'est publié, rien n'est déduit
    interdits = {"high_staffing_need", "large_workforce", "equipment_need"}
    assert {c.value for c in result.characteristics} & interdits == set()


# ─── F — un groupement ne change pas le contrat ────────────────────────────────


def test_f_un_gagnant_en_groupement_ne_modifie_pas_la_comprehension():
    seul = understand(award(title="Neubau Schulhaus", cpv="45214200"))
    groupe = understand(
        award(
            title="Neubau Schulhaus",
            cpv="45214200",
            parties=(
                AwardeeParty(
                    name="Konsorcjum",
                    members=(
                        Awardee(
                            organization=OrganizationRef(legal_name="A SA"), role="consortium_lead"
                        ),
                        Awardee(
                            organization=OrganizationRef(legal_name="B SA"),
                            role="consortium_member",
                        ),
                    ),
                ),
            ),
        )
    )
    assert seul.contract_type.value == groupe.contract_type.value
    assert seul.sector.value == groupe.sector.value
    # le groupement apparaît comme caractéristique, adossé au fait publié
    assert "consortium_award" in {c.value for c in groupe.characteristics}
    assert all(c.evidence for c in groupe.characteristics)


# ─── G — HTML SIMAP ─────────────────────────────────────────────────────────────


def test_g_une_description_html_donne_un_resume_propre_sans_rien_inventer():
    html = (
        "<p>Die Gemeinde realisiert ein neues Schulhaus.&nbsp;</p>"
        "<p>Der Auftrag umfasst:</p><ul><li>Erdarbeiten</li><li>Belagsarbeiten</li></ul>"
    )
    result = understand(award(title="Gärtnerarbeiten", description=html, cpv="45214200"))
    resume = result.object_summary.value

    assert "<p>" not in resume and "&nbsp;" not in resume
    assert "Erdarbeiten" in resume and "Belagsarbeiten" in resume
    # la preuve, elle, conserve la source telle qu'elle a été publiée
    assert any(e.excerpt and "<p>" in e.excerpt for e in result.object_summary.evidence)


# ─── H — écritures non latines ─────────────────────────────────────────────────


def test_h_un_texte_cyrillique_traverse_sans_corruption():
    titre = "Доставка на лекарствен продукт"
    result = understand(award(title=titre, cpv="33600000"), event(country="BG", source="ted"))
    assert titre in result.object_summary.value
    assert result.contract_type.value == "medical_supply"


# ─── I — description très longue ───────────────────────────────────────────────


def test_i_une_description_tres_longue_reste_factuelle_et_bornee():
    longue = "Prestations détaillées. " * 200
    result = understand(award(title="Marché de services", description=longue, cpv="79822500"))
    resume = result.object_summary.value
    assert len(resume) < 700  # borné, donc lisible
    assert resume.endswith("…")  # la troncature est visible, pas silencieuse
    assert "Prestations détaillées." in resume


# ─── J — titre promotionnel ────────────────────────────────────────────────────


def test_j_un_titre_vague_ne_produit_aucune_inference_commerciale():
    result = understand(
        award(
            title="Un partenariat stratégique innovant pour l'avenir",
            description="Projet ambitieux et structurant pour le territoire.",
            cpv=None,
        )
    )
    assert result.contract_type.value == "unknown"
    assert result.contract_type.confidence == "low"
    assert result.sector.value == "unknown"
    resume = result.object_summary.value.casefold()
    for interdit in ("besoin", "opportunité", "devra", "achètera"):
        assert interdit not in resume


# ─── Garde-fous transverses ────────────────────────────────────────────────────


def test_aucune_information_absente_n_est_completee():
    """Ni valeur, ni durée, ni lieu, ni date : la compréhension reste vide sur ces points."""
    result = understand(award(title="Lot 3", cpv=None))
    assert result.contract_type.value == "unknown"
    assert result.timing.contract_start_date is None
    assert result.timing.days_between_award_and_start is None
    assert result.geography.place_of_performance is None
    assert result.characteristics == ()


def test_une_duree_publiee_devient_une_caracteristique_pas_une_inference():
    court = understand(award(cpv="45000000", duration=Duration(value=6, unit="month")))
    long = understand(award(cpv="45000000", duration=Duration(value=4, unit="year")))
    assert "defined_contract_period" in {c.value for c in court.characteristics}
    assert "long_duration" in {c.value for c in long.characteristics}
    assert all(c.evidence for c in long.characteristics)


def test_la_comprehension_est_toujours_rattachable_a_son_avis():
    contract = award(cpv="45000000")
    result = understand(contract)
    assert result.award_ref == contract.event_ref
    for claim in result.material_claims().values():
        for evidence in claim.evidence:
            assert evidence.source_notice_id == "notice-1"
            assert evidence.source_procedure_id == "projet-1"
