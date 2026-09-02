"""Build concise commercial readings from exact Phase A source snapshots."""

from __future__ import annotations

import datetime as dt

from signals.phase_a_btp.contracts import (
    AwardSnapshot,
    OfficialFacts,
    PotentialNeed,
    ShowcaseSignal,
)
from signals.phase_a_btp.eligibility import evaluate
from signals.understanding.text import plain_text

_ROLES: dict[str, tuple[str, ...]] = {
    "roadworks_civil": (
        "Conducteur de travaux",
        "Responsable matériel",
        "Responsable achats chantier",
    ),
    "earthworks_demolition": (
        "Conducteur de travaux",
        "Responsable matériel",
        "Responsable achats chantier",
    ),
    "technical_installation": (
        "Responsable d’affaires",
        "Conducteur de travaux",
        "Responsable achats projet",
    ),
    "interior_finishing": (
        "Conducteur de travaux",
        "Responsable achats chantier",
    ),
    "rail_infrastructure": (
        "Directeur de projet",
        "Conducteur de travaux",
        "Responsable approvisionnements",
    ),
    "special_civil": (
        "Directeur de travaux",
        "Conducteur de travaux",
        "Responsable approvisionnements",
    ),
    "equipment_hire": ("Responsable matériel", "Conducteur de travaux"),
    "general_building": (
        "Directeur de travaux",
        "Conducteur de travaux",
        "Responsable achats chantier",
    ),
}


def _location(award: AwardSnapshot) -> str:
    assert award.location is not None
    values = (
        award.location.locality,
        award.location.postal_code,
        award.location.subdivision_code,
        award.location.country,
    )
    return ", ".join(dict.fromkeys(value for value in values if value))


def _subject(element: str) -> tuple[str, str]:
    prefix, _, value = element.partition(" : ")
    return prefix, value.strip() or element


def _potential_need(element: str) -> PotentialNeed:
    kind, subject = _subject(element)
    if kind.startswith("Matériau"):
        statement = f"La fourniture de {subject} pourrait être à qualifier pour ce marché."
    elif kind.startswith("Équipement"):
        statement = f"La fourniture, la location ou la mise en service de {subject} pourrait être à qualifier."
    elif kind.startswith("Spécialité"):
        statement = f"Une capacité spécialisée en {subject} pourrait être à qualifier pour l’exécution."
    elif kind.startswith("Ouvrage"):
        statement = f"Un besoin de prestations ciblées sur {subject} pourrait être à qualifier auprès de l’attributaire."
    elif kind.startswith("Lot précis"):
        statement = f"Un besoin de fournitures ou prestations adapté au lot « {subject} » pourrait être à qualifier."
    elif kind.startswith("Prestation détaillée"):
        statement = "Un appui ciblé sur la prestation détaillée publiée pourrait être à qualifier."
    elif kind.startswith("Durée"):
        statement = f"Une capacité d’exécution compatible avec la durée « {subject} » pourrait être à qualifier."
    elif kind.startswith("Calendrier"):
        statement = "Une disponibilité compatible avec le calendrier publié pourrait être à qualifier."
    else:
        statement = f"Une capacité d’intervention sur le lieu publié « {subject} » pourrait être à qualifier."
    return PotentialNeed(statement=statement, based_on=element)


def _needs(elements: tuple[str, ...]) -> tuple[PotentialNeed, ...]:
    priority = sorted(
        elements,
        key=lambda value: (
            value.startswith("Lieu d’exécution"),
            value.startswith("Durée"),
            value.startswith("Calendrier"),
            value.startswith("Prestation détaillée"),
            value,
        ),
    )
    selected: list[PotentialNeed] = []
    seen_statements: set[str] = set()
    for element in priority:
        need = _potential_need(element)
        if need.statement in seen_statements:
            continue
        selected.append(need)
        seen_statements.add(need.statement)
        if len(selected) == 3:
            break
    if not selected:
        raise ValueError("a visible commercial signal requires one specific potential need")
    return tuple(selected)


def _specialty(award: AwardSnapshot) -> str:
    if award.trade_domain:
        return award.trade_domain
    cpv = award.cpv_main or ""
    if cpv.startswith("451"):
        return "earthworks_demolition"
    if cpv.startswith("453"):
        return "technical_installation"
    if cpv.startswith("454"):
        return "interior_finishing"
    if cpv.startswith("455"):
        return "equipment_hire"
    if cpv.startswith("45234"):
        return "rail_infrastructure"
    if cpv.startswith(("4524", "4525")):
        return "special_civil"
    if cpv.startswith("4523"):
        return "roadworks_civil"
    return "general_building"


def build_showcase_signal(award: AwardSnapshot, *, as_of: dt.date) -> ShowcaseSignal:
    eligibility = evaluate(award, as_of=as_of)
    if not eligibility.visible_dashboard:
        raise ValueError("showcase signals must be visible")
    assert award.awardee_name and award.event_date and award.source_url and award.cpv_main
    object_text = plain_text(award.title or award.lot_title or award.description)
    assert object_text
    specialty = _specialty(award)
    needs = _needs(eligibility.operational_elements)
    evidence_subject = _subject(needs[0].based_on)[1]
    offer_labels = {
        "materials_and_components": "une offre de fournitures pour chantiers",
        "equipment_rental": "une offre de location de matériel de chantier",
        "specialist_subcontracting": "une offre de sous-traitance spécialisée",
        "staffing_and_labour": "une offre de renfort de personnel de chantier",
        "transport_and_logistics": "une offre de logistique de chantier",
        "safety_equipment": "une offre d’équipements de sécurité",
        "waste_and_environmental_services": "une offre de services environnementaux de chantier",
    }
    offer = next(
        (offer_labels[value] for value in award.target_offers if value in offer_labels),
        award.target_offer_summary.strip() or "l’offre déclarée du fournisseur",
    )
    fit_reason = f"Ce signal peut correspondre à {offer} car la source publie {evidence_subject}."
    to_qualify: list[str] = []
    if not award.dce_document_ids:
        to_qualify.append("Quantités, références et exigences techniques exactes")
    if not award.contract_start_date or not award.contract_end_date:
        to_qualify.append("Calendrier détaillé d’exécution")
    to_qualify.append("Interlocuteur opérationnel responsable du marché")
    roles = _ROLES.get(specialty, _ROLES["general_building"])
    return ShowcaseSignal(
        opportunity_key=award.opportunity_key,
        signal_key=award.signal_key,
        award_key=award.award_key,
        specialty=specialty,
        specificity_score=len(eligibility.concrete_information) + len(eligibility.operational_elements),
        official_facts=OfficialFacts(
            awardee=award.awardee_name,
            buyer=award.buyer_name,
            object=object_text,
            lot=award.lot_title,
            amount=(
                f"{award.amount} {award.currency}"
                if award.amount is not None and award.currency is not None
                else None
            ),
            date=award.event_date,
            location=_location(award),
            cpv=award.cpv_main,
            source_system=award.source_system,
            source_country=award.source_country,
            source_notice_id=award.source_notice_id,
            source_url=award.source_url,
        ),
        operational_elements=eligibility.operational_elements,
        potential_needs=needs,
        fit_reason=fit_reason,
        recommended_action=(
            f"Qualifier auprès du {roles[0].lower()} la nature, le calendrier et le volume "
            f"du besoin lié à {evidence_subject}."
        ),
        contact_roles=roles,
        to_qualify=tuple(to_qualify[:3]),
        visible_dashboard=True,
        outbound_ready=eligibility.outbound_ready,
        outbound_reason=eligibility.outbound_reason,
        freshness_bucket=eligibility.freshness_bucket,
        age_days=eligibility.age_days,
        enrichment_level=eligibility.enrichment_level,
    )
