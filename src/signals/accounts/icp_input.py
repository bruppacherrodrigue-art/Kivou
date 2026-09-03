"""Ce que le client déclare, et comment cela devient un `TargetICP`.

Le modèle moteur parle `NeedCategory`, `TradeDomain`, `geography_basis`,
`unknown_value_policy`, `source_modes_allowed`. Aucun de ces mots n'a de sens
pour quelqu'un qui vend des matériaux de chantier, et §12 interdit de les
exposer. Le contrat d'API est donc **séparé** de la représentation interne, et
la traduction est explicite, déterministe, et lisible d'un seul tenant.

    Cinq questions, et rien de plus
    ───────────────────────────────
    Que vendez-vous ?           `offers`
    À quels corps de métier ?   `buyer_trades`      (facultatif)
    Où pouvez-vous livrer ?     `territories`
    À partir de quel montant ?  `minimum_contract_value`
    Comment le décririez-vous ? `offer_summary`     (déclaratif, inerte)

Le vocabulaire client est stable indépendamment du moteur : si `NeedCategory`
était un jour renommé, `OfferKind` ne bougerait pas et les ICP enregistrés
resteraient lisibles. C'est le seul intérêt d'une table de correspondance qui
ressemble par ailleurs à une quasi-identité.

    Ce qui n'est jamais demandé au client
    ─────────────────────────────────────
    Les pondérations de score, les règles du Need Graph, les seuils de mise au
    point, la politique de valeur inconnue, les modes de source. Ces réglages
    sont des décisions produit ; ils ont une valeur unique, déclarée plus bas, et
    ils ne se négocient pas dans un formulaire.

Rien n'est inventé : une entrée incomplète produit un ICP **incomplet**, jamais
un ICP dont on aurait deviné les cases manquantes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from signals.matching.icp import TargetICP, Territory, ValueThreshold

#: Ce que le client vend, dans ses mots.
OfferKind = Literal[
    "materials_and_components",
    "equipment_rental",
    "staffing_and_labour",
    "transport_and_logistics",
    "specialist_subcontracting",
    "safety_equipment",
    "waste_and_environmental_services",
]

#: À qui il le vend, dans ses mots. `unknown_or_general` n'y figure pas : ce
#: n'est pas un métier, c'est l'absence de métier, et le moteur le refuse.
BuyerTrade = Literal[
    "earthworks_and_demolition",
    "building_construction",
    "roads_and_civil_works",
    "rail_infrastructure",
    "special_civil_engineering",
    "technical_installations",
    "interior_finishing",
    "equipment_hire",
]

_OFFER_TO_NEED: dict[str, str] = {
    "materials_and_components": "materials_or_components",
    "equipment_rental": "equipment_or_rental",
    "staffing_and_labour": "workforce_capacity",
    "transport_and_logistics": "logistics_and_transport",
    "specialist_subcontracting": "specialist_subcontracting",
    "safety_equipment": "safety_and_ppe",
    "waste_and_environmental_services": "waste_and_environment",
}

_TRADE_TO_DOMAIN: dict[str, str] = {
    "earthworks_and_demolition": "earthworks_demolition",
    "building_construction": "general_building",
    "roads_and_civil_works": "roadworks_civil",
    "rail_infrastructure": "rail_infrastructure",
    "special_civil_engineering": "special_civil",
    "technical_installations": "technical_installation",
    "interior_finishing": "interior_finishing",
    "equipment_hire": "equipment_hire",
}

# ─── Décisions produit, identiques pour tous les clients ──────────────────────
#
# Elles ne sont pas demandées parce qu'aucun client n'a l'information pour y
# répondre, et parce qu'un mauvais réglage y produirait un feed silencieux dont
# personne ne saurait diagnostiquer la cause.

GEOGRAPHY_BASIS = "place_of_performance"
"""Le lieu d'EXÉCUTION du marché. `winner_location` est modélisable mais sans
données : aucun avis mesuré ne publie l'adresse du gagnant."""

GEOGRAPHY_POLICY = "required"
"""Un marché dont on ignore le lieu ne peut pas être promis à un fournisseur
local : il ressort `insufficient_data` plutôt qu'en faux positif."""

UNKNOWN_VALUE_POLICY = "allow_with_penalty"
"""Un montant non publié n'est pas une disqualification — beaucoup d'avis n'en
publient pas — mais il ne vaut pas un montant connu."""

MAXIMUM_SIGNAL_AGE_DAYS = 120
"""Au-delà, l'événement n'est plus commercialement actionnable. Aligné sur la
politique de fraîcheur mesurée en SPEC-009D/E."""

PREFERRED_TIMINGS: tuple[str, ...] = ("near_term", "medium_term")
SOURCE_MODES_ALLOWED: tuple[str, ...] = ("metadata_fallback",)


#: L'inverse de `_OFFER_TO_NEED`, pour les rares lecteurs qui partent du besoin
#: — le jeton d'acquisition, qui porte la catégorie de besoin de la campagne et
#: pas le vocabulaire client. La correspondance est injective, donc réversible.
_NEED_TO_OFFER: dict[str, str] = {need: offer for offer, need in _OFFER_TO_NEED.items()}


def offer_for_need(need_ref: str) -> str | None:
    """L'offre client correspondant à une catégorie de besoin moteur, ou rien.

    Rien plutôt qu'un repli : une campagne dont la catégorie ne se traduit pas
    ne doit pas faire cocher une case que le client n'a jamais choisie.
    """
    return _NEED_TO_OFFER.get(need_ref)


class MonetaryThreshold(BaseModel):
    """Le montant à partir duquel un marché vaut la peine d'être regardé."""

    model_config = ConfigDict(extra="forbid")

    currency: str = Field(min_length=3, max_length=3)
    minimum_amount: float = Field(ge=0)
    maximum_amount: float | None = Field(default=None, ge=0)


class TargetIcpInput(BaseModel):
    """L'entrée client. Tous les champs sont facultatifs — un ICP se remplit en plusieurs fois.

    La complétude n'est pas une contrainte de saisie mais un **résultat** :
    `missing_fields()` dit ce qui manque, et l'ICP reste `draft` tant qu'il
    manque quelque chose.
    """

    model_config = ConfigDict(extra="forbid")

    offer_summary: str = ""
    offers: tuple[OfferKind, ...] = ()
    secondary_offers: tuple[OfferKind, ...] = ()
    buyer_trades: tuple[BuyerTrade, ...] = ()
    secondary_buyer_trades: tuple[BuyerTrade, ...] = ()
    #: Codes pays ISO 3166-1 alpha-2, en majuscules.
    territories: tuple[str, ...] = ()
    minimum_contract_value: MonetaryThreshold | None = None

    def missing_fields(self) -> tuple[str, ...]:
        """Ce qui empêche encore de produire un profil de ciblage exploitable."""
        missing: list[str] = []
        if not self.offers:
            missing.append("offers")
        if not self.territories:
            missing.append("territories")
        if self.minimum_contract_value is None:
            missing.append("minimum_contract_value")
        if self.secondary_buyer_trades and not self.buyer_trades:
            # Dire ce qu'on accepte à regret sans dire ce qu'on vise ne décrit rien.
            missing.append("buyer_trades")
        return tuple(missing)

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields()


def to_target_icp(customer_input: TargetIcpInput, *, target_icp_id: str, label: str) -> TargetICP:
    """Traduit l'entrée client en profil moteur. Déterministe, sans invention.

    Lève `ValueError` si l'entrée est incomplète : produire un `TargetICP` en
    devinant les cases vides donnerait un feed dont le client n'aurait jamais
    demandé le contenu.
    """
    missing = customer_input.missing_fields()
    if missing:
        raise ValueError(f"entrée incomplète : {', '.join(missing)}")

    threshold = customer_input.minimum_contract_value
    assert threshold is not None  # garanti par `missing_fields`
    # Les catégories secondaires ne répètent jamais les primaires : le moteur
    # refuse le chevauchement, et un client peut légitimement cocher les deux.
    primary_needs = tuple(dict.fromkeys(_OFFER_TO_NEED[o] for o in customer_input.offers))
    secondary_needs = tuple(
        need
        for need in dict.fromkeys(_OFFER_TO_NEED[o] for o in customer_input.secondary_offers)
        if need not in primary_needs
    )
    primary_trades = tuple(dict.fromkeys(_TRADE_TO_DOMAIN[t] for t in customer_input.buyer_trades))
    secondary_trades = tuple(
        domain
        for domain in dict.fromkeys(
            _TRADE_TO_DOMAIN[t] for t in customer_input.secondary_buyer_trades
        )
        if domain not in primary_trades
    )

    return TargetICP(
        icp_id=target_icp_id,
        name=label,
        offer_summary=customer_input.offer_summary,
        primary_need_categories=primary_needs,
        secondary_need_categories=secondary_needs,
        primary_trade_domains=primary_trades,
        secondary_trade_domains=secondary_trades,
        geography_basis=GEOGRAPHY_BASIS,
        geography_policy=GEOGRAPHY_POLICY,
        territories=tuple(Territory(country=country) for country in customer_input.territories),
        value_thresholds=(
            ValueThreshold(
                currency=threshold.currency,
                minimum_amount=threshold.minimum_amount,
                maximum_amount=threshold.maximum_amount,
            ),
        ),
        unknown_value_policy=UNKNOWN_VALUE_POLICY,
        maximum_signal_age_days=MAXIMUM_SIGNAL_AGE_DAYS,
        preferred_timings=PREFERRED_TIMINGS,
        source_modes_allowed=SOURCE_MODES_ALLOWED,
    )
