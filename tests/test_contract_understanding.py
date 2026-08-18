"""Contract Understanding : tables CPV, texte, modèle et moteur déterministe.

Le corpus réel (168 awards TED + SIMAP) commande les choix testés ici :

- **CPV présent sur 168/168** → signal primaire ;
- titres souvent inutilisables (`Default lot`, `Lote 1`, `Reihen`) → le titre
  confirme, il ne décide pas ;
- **55 descriptions SIMAP en HTML** → une vue texte propre est nécessaire ;
- 8 devises (EUR, CHF, RON, HUF, NOK, SEK, PLN, CZK) → aucune échelle
  économique cross-devise n'est défendable, aucune n'est produite.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from signals.domain import (
    Awardee,
    AwardeeParty,
    ContractAward,
    Evidence,
    Location,
    LotRef,
    Money,
    OrganizationRef,
    Provenance,
    PublicEvent,
)
from signals.understanding import (
    ContractUnderstandingEngine,
    contract_type_for_cpv,
    plain_text,
    sector_for_cpv,
)
from signals.understanding.model import Claim, ContractUnderstanding

ENGINE_VERSION = "contract-understanding-v0.3"


# ─── Tables CPV ─────────────────────────────────────────────────────────────────


def test_le_cpv_donne_le_type_de_contrat():
    assert contract_type_for_cpv("45215100") == "construction"
    assert contract_type_for_cpv("72267100") == "it_digital"
    assert contract_type_for_cpv("33600000") == "medical_supply"
    assert contract_type_for_cpv("71410000") == "engineering_architecture"
    assert contract_type_for_cpv("60400000") == "transport_logistics"
    assert contract_type_for_cpv("90910000") == "facility_services"


def test_le_prefixe_le_plus_long_gagne():
    """`79710000` est de la sécurité, pas un service aux entreprises générique."""
    assert contract_type_for_cpv("79822500") == "business_services"
    assert contract_type_for_cpv("79710000") == "security_services"


def test_l_equipement_radio_n_est_pas_un_service_telecom():
    """Corrigé après revue manuelle : 32322000 est un projecteur de scène."""
    assert contract_type_for_cpv("32322000") == "equipment_supply"
    assert contract_type_for_cpv("64200000") == "telecom"


def test_un_cpv_inconnu_ne_devient_pas_une_categorie_plausible():
    assert contract_type_for_cpv("00000000") == "unknown"
    assert contract_type_for_cpv(None) == "unknown"


def test_le_secteur_n_est_pas_le_type_de_contrat():
    """Un marché de fournitures médicales : type `medical_supply`, secteur `healthcare`."""
    assert contract_type_for_cpv("33600000") == "medical_supply"
    assert sector_for_cpv("33600000") == "healthcare"

    # une construction d'école : type construction, secteur éducation
    assert contract_type_for_cpv("45214200") == "construction"
    assert sector_for_cpv("45214200") == "education"


def test_le_secteur_reste_inconnu_quand_le_cpv_ne_le_dit_pas():
    """Une construction générique ne révèle aucun secteur — ne pas en inventer un."""
    assert sector_for_cpv("45000000") == "unknown"
    assert sector_for_cpv(None) == "unknown"


# ─── Texte ──────────────────────────────────────────────────────────────────────


def test_les_paragraphes_html_sont_separes_sans_rien_perdre():
    texte = plain_text("<p>Premier paragraphe.</p><p>Second paragraphe.</p>")
    assert "Premier paragraphe." in texte
    assert "Second paragraphe." in texte
    assert "Premier paragraphe.Second" not in texte  # pas de collage


def test_une_liste_html_reste_lisible():
    texte = plain_text("<ul><li>Erdarbeiten</li><li>Fundationen</li></ul>")
    assert "Erdarbeiten" in texte
    assert "Fundationen" in texte
    assert "ErdarbeitenFundationen" not in texte


def test_les_entites_html_sont_decodees_une_seule_fois():
    """`&amp;amp;` publié par un émetteur reste `&amp;` : on ne corrige pas la source."""
    assert plain_text("A &nbsp;B") == "A B"
    assert plain_text("Kross &amp;amp; Grus") == "Kross &amp; Grus"


def test_un_texte_non_latin_traverse_intact():
    assert plain_text("<p>Б. БРАУН МЕДИКАЛ ЕООД</p>") == "Б. БРАУН МЕДИКАЛ ЕООД"


def test_un_texte_sans_html_est_rendu_tel_quel():
    assert plain_text("Marché de travaux") == "Marché de travaux"
    assert plain_text(None) is None


# ─── Modèle ─────────────────────────────────────────────────────────────────────


def evidence(path: str = "procurement.cpvCode.code") -> Evidence:
    return Evidence(
        source_system="simap", source_kind="publication_field", path=path, raw_value="45214200"
    )


def test_une_affirmation_sure_sans_preuve_est_refusee():
    with pytest.raises(ValidationError, match="sans preuve"):
        Claim(value="construction", confidence="high", rule="cpv+title")


def test_une_affirmation_incertaine_peut_ne_rien_prouver():
    claim = Claim(value="unknown", confidence="low", rule="aucun signal exploitable")
    assert claim.evidence == ()


def test_la_couverture_de_preuve_est_une_formule_documentee():
    """couverture = affirmations matérielles prouvées / affirmations matérielles."""
    prouve = Claim(value="construction", confidence="high", evidence=(evidence(),), rule="cpv")
    # matérielle (elle affirme quelque chose) mais sans preuve : elle abaisse la couverture
    nue = Claim(value="it_digital", confidence="low", rule="lecture du titre seul")
    # « unknown » n'affirme rien : hors du dénominateur
    muette = Claim(value="unknown", confidence="low", rule="aucun signal")

    assert ContractUnderstanding.coverage_of((prouve, prouve)) == 1.0
    assert ContractUnderstanding.coverage_of((prouve, nue)) == 0.5
    assert ContractUnderstanding.coverage_of((prouve, muette)) == 1.0
    assert ContractUnderstanding.coverage_of(()) == 1.0


# ─── Moteur : cas réel SIMAP ────────────────────────────────────────────────────


def simap_award() -> tuple[PublicEvent, ContractAward]:
    """L'adjudication réelle 33112-02 (Gemeinde Root, travaux de jardinage)."""
    event = PublicEvent(
        provenance=Provenance(
            source_system="simap",
            source_country="CH",
            source_notice_id="223ceb19-b3d4-4556-a417-84c1d5f7a3a9",
            source_procedure_id="0d2599e8-c839-4d7d-9277-63144b4750b0",
            source_url="https://www.simap.ch/api/publications/v1/project/x/publication-details/y",
        ),
        event_type="award_notice",
        published_at=dt.date(2026, 8, 15),
        event_date=dt.date(2026, 5, 19),
        procedure_buyers=(OrganizationRef(legal_name="Gemeinde Root", country="CH"),),
    )
    award = ContractAward(
        event_ref=event.ref(),
        title="Neubau Schule Dorf Root: BKP 421 Gärtenerarbeiten",
        description="<p>Die Gemeinde Root realisiert ein neues Schulhaus.&nbsp;</p>",
        cpv_main="45214200",
        value=Money(amount=Decimal("934877.50"), currency="CHF", vat_category="standard"),
        awardee_parties=(
            AwardeeParty(
                members=(Awardee(organization=OrganizationRef(legal_name="Egli Gartenbau AG")),)
            ),
        ),
        place_of_performance=Location(
            country="CH", subdivision_code="CH-LU", subdivision_scheme="ISO-3166-2", locality="Root"
        ),
        award_date=dt.date(2026, 5, 19),
    )
    return event, award


def test_le_moteur_comprend_un_award_simap_reel():
    event, award = simap_award()
    understanding = ContractUnderstandingEngine().understand(award, event)

    assert understanding.contract_type.value == "construction"
    assert understanding.sector.value == "education"
    assert understanding.contract_type.confidence == "high"
    assert understanding.engine_version == ENGINE_VERSION
    assert understanding.award_ref == award.event_ref


def test_chaque_classification_pointe_vers_ses_preuves():
    event, award = simap_award()
    understanding = ContractUnderstandingEngine().understand(award, event)

    preuves = understanding.contract_type.evidence
    assert preuves, "une classification sûre sans preuve n'est pas admissible"
    assert any(p.raw_value == "45214200" for p in preuves)
    assert all(p.source_system == "simap" for p in preuves)


def test_les_faits_critiques_remontent_tous_a_leur_source():
    event, award = simap_award()
    understanding = ContractUnderstandingEngine().understand(award, event)
    prouves = {
        claim_name
        for claim_name, claim in understanding.material_claims().items()
        if claim.evidence
    }
    assert {"contract_type", "winner", "amount", "cpv", "award_date", "procedure_buyers"} <= prouves
    assert understanding.evidence_coverage == 1.0


def test_le_resume_est_factuel_et_verifiable():
    event, award = simap_award()
    understanding = ContractUnderstandingEngine().understand(award, event)
    resume = understanding.object_summary.value

    assert "Egli Gartenbau AG" in resume
    assert "Acheteur publié : Gemeinde Root" in resume
    assert "934877.50 CHF" in resume
    assert award.title in resume  # le titre publié est cité, pas reformulé


def test_le_resume_ne_contient_jamais_un_besoin_commercial():
    """Un résumé contractuel n'est pas un Sales Signal."""
    event, award = simap_award()
    understanding = ContractUnderstandingEngine().understand(award, event)
    resume = understanding.object_summary.value.lower()
    for interdit in (
        "will need",
        "likely",
        "should hire",
        "will buy",
        "probably",
        "aura besoin",
        "devra recruter",
        "va acheter",
        "probablement",
        "wird benötigen",
        "dürfte",
    ):
        assert interdit not in resume


def test_les_caracteristiques_sont_toutes_adossees_a_un_fait_publie():
    event, award = simap_award()
    lot_award = award.model_copy(
        update={"lot": LotRef(identifier="LOT-1", title="Gärtnerarbeiten")}
    )
    understanding = ContractUnderstandingEngine().understand(lot_award, event)

    caracteristiques = {c.value for c in understanding.characteristics}
    assert "several_lots" in caracteristiques
    assert all(c.evidence for c in understanding.characteristics)


def test_aucune_echelle_economique_n_est_produite():
    """8 devises dans le corpus, conversion interdite : le champ n'existe pas."""
    assert "economic_scale" not in ContractUnderstanding.model_fields


def test_aucun_besoin_commercial_n_est_produit():
    interdits = {
        "need_category",
        "resource_need",
        "staffing_need",
        "equipment_need",
        "subcontracting_need",
        "supplier_category",
        "sales_opportunity",
    }
    assert interdits & set(ContractUnderstanding.model_fields) == set()


# ─── Le fait brut n'est jamais touché ───────────────────────────────────────────


def test_l_award_traverse_la_comprehension_intact():
    event, award = simap_award()
    avant = award.model_dump_json()
    ContractUnderstandingEngine().understand(award, event)
    assert award.model_dump_json() == avant


def test_la_comprehension_ne_vit_pas_dans_le_contrat():
    for interdit in ("contract_type", "sector", "object_summary", "understanding"):
        assert interdit not in ContractAward.model_fields


# ─── Timing ─────────────────────────────────────────────────────────────────────


def test_le_timing_ne_recalcule_aucune_date_absente():
    event, award = simap_award()
    understanding = ContractUnderstandingEngine().understand(award, event)
    timing = understanding.timing
    assert timing.award_date == dt.date(2026, 5, 19)
    assert timing.contract_start_date is None
    assert timing.contract_end_date is None
    assert timing.days_between_award_and_start is None  # aucune date de départ publiée


def test_un_delai_derive_l_est_seulement_quand_les_deux_dates_existent():
    event, award = simap_award()
    complet = award.model_copy(
        update={
            "contract_start_date": dt.date(2026, 6, 5),
            "contract_end_date": dt.date(2026, 12, 31),
        }
    )
    timing = ContractUnderstandingEngine().understand(complet, event).timing
    assert timing.days_between_award_and_start == 17
    assert set(timing.derived_from) >= {"award_date", "contract_start_date"}
    assert timing.contract_span_days == 209


# ─── Interface de moteur ────────────────────────────────────────────────────────


def test_le_moteur_par_defaut_est_deterministe():
    """Deux passages sur le même award donnent exactement le même résultat."""
    event, award = simap_award()
    engine = ContractUnderstandingEngine()
    assert engine.understand(award, event) == engine.understand(award, event)


def test_aucun_appel_externe_n_est_effectue():
    """Le moteur de SPEC-005 est purement local : ni réseau, ni modèle de langue."""
    import signals.understanding.engine as engine_module

    source = engine_module.__file__
    with open(source, encoding="utf-8") as handle:
        code = handle.read()
    for interdit in ("httpx", "requests", "openai", "anthropic", "urllib.request"):
        assert interdit not in code


# ─── SPEC-005R — acheteurs de procédure et signataires du contrat ───────────────


def parties_award(
    buyers: tuple[str, ...] = (), signatories: tuple[str, ...] = ()
) -> tuple[PublicEvent, ContractAward]:
    """Un award réduit aux parties, pour isoler la sémantique publiée."""
    event = PublicEvent(
        provenance=Provenance(
            source_system="simap",
            source_country="CH",
            source_notice_id="notice-1",
            source_procedure_id="projet-1",
            source_url="https://example.invalid/avis",
        ),
        event_type="award_notice",
        published_at=dt.date(2026, 8, 1),
        procedure_buyers=tuple(OrganizationRef(legal_name=name, country="CH") for name in buyers),
    )
    award = ContractAward(
        event_ref=event.ref(),
        title="Marché de nettoyage",
        cpv_main="90910000",
        contract_signatories=tuple(
            OrganizationRef(legal_name=name, country="CH") for name in signatories
        ),
        awardee_parties=(
            AwardeeParty(
                members=(Awardee(organization=OrganizationRef(legal_name="Titulaire SA")),)
            ),
        ),
    )
    return event, award


def summarize(buyers=(), signatories=()) -> str:
    event, award = parties_award(buyers, signatories)
    return ContractUnderstandingEngine().understand(award, event).object_summary.value


def test_r_a_un_acheteur_sans_signataire_n_est_pas_declare_signataire():
    """A — l'avis publie un acheteur ; il ne dit pas qui a signé."""
    resume = summarize(buyers=("Gemeinde Root",))
    assert "Acheteur publié : Gemeinde Root" in resume
    assert "attribué par" not in resume
    assert "signataire" not in resume.casefold()


def test_r_b_plusieurs_acheteurs_sont_tous_conserves():
    """B — achat conjoint : aucun n'est promu acheteur principal."""
    resume = summarize(buyers=("Simas Iks", "Sunnfjord Miljøverk Iks"))
    assert "Acheteurs publiés : Simas Iks, Sunnfjord Miljøverk Iks" in resume


def test_r_c_acheteur_et_signataire_identiques_restent_lisibles():
    """C — la même organisation dans les deux rôles, sans perte factuelle."""
    resume = summarize(buyers=("Aéroport Avignon",), signatories=("Aéroport Avignon",))
    assert "Acheteur publié : Aéroport Avignon" in resume
    assert "Signataire du contrat publié : Aéroport Avignon" in resume


def test_r_d_une_centrale_d_achat_n_est_jamais_presentee_comme_signataire():
    """D — cas réel 565986-2026 : CPO LT mène la procédure, l'hôpital signe."""
    resume = summarize(buyers=("Viešoji įstaiga CPO LT",), signatories=("VšĮ Kauno ligoninė",))
    assert "Acheteur publié : Viešoji įstaiga CPO LT" in resume
    assert "Signataire du contrat publié : VšĮ Kauno ligoninė" in resume
    # jamais l'inverse, jamais de fusion
    assert "Signataire du contrat publié : Viešoji įstaiga CPO LT" not in resume
    assert "attribué par Viešoji įstaiga CPO LT" not in resume


def test_r_e_plusieurs_signataires_apparaissent_tous():
    """E — aucun écrasement quand la source en publie plusieurs."""
    resume = summarize(buyers=("Canton",), signatories=("Hôpital A", "Hôpital B"))
    assert "Signataires du contrat publiés : Hôpital A, Hôpital B" in resume


def test_r_les_deux_ensembles_sont_conserves_dans_la_comprehension():
    """La distinction ne reste pas enfermée dans les objets source."""
    event, award = parties_award(buyers=("CPO LT",), signatories=("Hôpital",))
    understanding = ContractUnderstandingEngine().understand(award, event)

    assert [b.legal_name for b in understanding.parties.procedure_buyers] == ["CPO LT"]
    assert [s.legal_name for s in understanding.parties.contract_signatories] == ["Hôpital"]


def test_r_les_deux_roles_sont_deux_faits_distincts_avec_leurs_preuves():
    event, award = parties_award(buyers=("CPO LT",), signatories=("Hôpital",))
    facts = ContractUnderstandingEngine().understand(award, event).facts

    assert facts["procedure_buyers"].value == "CPO LT"
    assert facts["contract_signatories"].value == "Hôpital"
    assert facts["procedure_buyers"].evidence[0].path == "procedure_buyers"
    assert facts["contract_signatories"].evidence[0].path == "contract_signatories"


def test_r_aucun_raccourci_vers_le_premier_acheteur():
    """Non-régression : `procedure_buyers[0]` ne doit désigner aucun « acheteur principal ».

    Ni le résumé, ni les faits, ni les preuves ne doivent porter cette notion :
    la position dans une liste n'est pas un rôle.
    """
    event, award = parties_award(buyers=("Premier", "Second"), signatories=("Tiers",))
    understanding = ContractUnderstandingEngine().understand(award, event)

    chemins = {
        evidence.path
        for claim in understanding.material_claims().values()
        for evidence in claim.evidence
    }
    assert "procedure_buyers[0]" not in chemins
    assert "contract_signatories[0]" not in chemins
    assert "buyer" not in understanding.facts  # plus de champ ambigu

    import signals.understanding.engine as engine_module

    code = Path(engine_module.__file__).read_text(encoding="utf-8")
    assert "procedure_buyers[0]" not in code
    assert "contract_signatories[0]" not in code


def test_r_sans_aucune_partie_publiee_le_resume_n_en_invente_pas():
    resume = summarize()
    assert "Acheteur" not in resume
    assert "Signataire" not in resume
