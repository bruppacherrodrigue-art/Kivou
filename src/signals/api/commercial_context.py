"""Offer-specific commercial framing; never invents an order, budget or start date."""

from __future__ import annotations

_OFFERS = {
    "materials_and_components": (
        "materials_or_components",
        "matériaux et composants",
        "materials and components",
    ),
    "equipment_rental": ("equipment_or_rental", "location de matériel", "equipment rental"),
    "staffing_and_labour": (
        "workforce_capacity",
        "personnel et main-d’œuvre",
        "staffing and labour",
    ),
    "transport_and_logistics": (
        "logistics_and_transport",
        "transport et logistique",
        "transport and logistics",
    ),
    "specialist_subcontracting": (
        "specialist_subcontracting",
        "sous-traitance spécialisée",
        "specialist subcontracting",
    ),
    "safety_equipment": ("safety_and_ppe", "équipements de sécurité", "safety equipment"),
    "waste_and_environmental_services": (
        "waste_and_environment",
        "déchets et services environnementaux",
        "waste and environmental services",
    ),
}


def commercial_context(
    detail: dict, *, offers: tuple[str, ...], selected_offer: str | None, lang: str
) -> dict | None:
    categories = {
        item.get("category")
        for item in detail.get("analysis", {}).get("plausible_needs", {}).get("items", [])
        if item.get("targeted_by_your_profile")
    }
    eligible = [offer for offer in offers if offer in _OFFERS and _OFFERS[offer][0] in categories]
    if selected_offer is not None:
        eligible = [offer for offer in eligible if offer == selected_offer]
    if not eligible:
        return None
    fr = lang == "fr"
    labels = [_OFFERS[offer][1 if fr else 2] for offer in eligible]
    offer_label = (" et " if fr else " and ").join(labels)
    contract = detail.get("contract", {})
    facts = detail.get("notice_facts") or {}
    title = facts.get("title") or contract.get("lot_title") or contract.get("title")
    locality = (contract.get("location") or {}).get("locality")
    context = str(title) if title else ("Ce marché" if fr else "This contract")
    if locality:
        context += (" à " if fr else " in ") + str(locality)
    holder = detail.get("company", {}).get("name")
    if fr:
        reason = f"{context} : une opportunité de positionner votre offre de {offer_label}"
        reason += f" auprès de {holder}." if holder else " auprès du titulaire."
    else:
        reason = f"{context}: an opportunity to put your {offer_label} offering forward"
        reason += f" to {holder}." if holder else " to the contract holder."
    return {"reason": reason, "offer_category": selected_offer, "zone_label": locality}
