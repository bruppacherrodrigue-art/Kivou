"""La bibliothèque de règles v0.4 — mécanisme, pression, conditions négatives.

SPEC-007R1 §19 : chaque règle déclare explicitement ses deux rôles. Un besoin
`medium` exige **au moins un mécanisme ET au moins une pression** ; deux faits
du même rôle ne suffisent jamais (§8).

Les conditions négatives vivent à trois endroits, du plus général au plus fin :

- `DELIVERABLE_OVERLAP` — ce que le gagnant fournit déjà n'est jamais son besoin
  (§17) ;
- les **mécanismes** de chaque règle — un logiciel n'appelle pas d'engins, une
  prestation intellectuelle pas de matériaux, un chantier de nature inconnue ni
  l'un ni l'autre (§14) ;
- les **pressions** restreintes de certaines règles — les services sociaux
  exigent une échelle réelle, pas une période contractuelle (§15).

`logistics_and_transport` n'a **aucune règle** en v0.4 : la livraison est
inhérente à une fourniture, et aucun fait canonique ne démontre une
distribution structurée au-delà du livrable (§16). La catégorie reste dans la
taxonomie pour un futur mode documentaire.
"""

from __future__ import annotations

from dataclasses import dataclass

from signals.needs.model import Externalisability, NeedCategory

RULE_LIBRARY_VERSION = "need-rules-v0.5"


@dataclass(frozen=True)
class NeedRule:
    """Une inférence commerciale possible, et les deux rôles qui la fondent."""

    rule_id: str
    category: NeedCategory
    # Rôle A — au moins un doit tenir : pourquoi cette ressource, pour ce travail.
    mechanism_predicates: tuple[str, ...]
    # Rôle B — au moins un doit tenir : pourquoi un appoint est plausible.
    pressure_predicates: tuple[str, ...]
    statement_template: str
    reasoning_template: str
    externalisability: Externalisability


DELIVERABLE_OVERLAP: dict[str, frozenset[NeedCategory]] = {
    "transport_logistics": frozenset({"logistics_and_transport"}),
    "equipment_supply": frozenset(
        {"equipment_or_rental", "materials_or_components", "logistics_and_transport"}
    ),
    "medical_supply": frozenset({"materials_or_components", "logistics_and_transport"}),
}
"""§17 — CONTRACT DELIVERABLE ≠ RESOURCE NEED. Le gagnant d'un marché de
transport vend du transport ; lui « découvrir » un besoin de transport serait
répéter le contrat, pas produire un signal."""

PROFILE_OVERLAP: dict[str, frozenset[NeedCategory]] = {
    "equipment_hire_as_deliverable": frozenset({"equipment_or_rental"}),
}
"""Louer des engins avec opérateur (CPV 455) EST le livrable : ce chantier-là
n'a pas « besoin » de location de matériel."""

ALL_PRESSURES = (
    "large_scale",
    "known_nontrivial_scale",
    "long_recurring_duration",
    "parallel_lots_with_scale",
    "distinct_specialties",
    "near_term_start",
)
"""Les pressions ouvertes à une règle sans restriction particulière. Ni
`defined_period` ni `several_lots` seul n'y figurent — ils n'en sont pas (§11-§12)."""


RULE_LIBRARY: tuple[NeedRule, ...] = (
    NeedRule(
        rule_id="workforce-human-intensive-v1",
        category="workforce_capacity",
        mechanism_predicates=("human_intensive_type",),
        pressure_predicates=ALL_PRESSURES,
        statement_template=(
            "Une capacité de personnel supplémentaire pourrait être nécessaire "
            "pour tenir la charge d'exécution du marché."
        ),
        reasoning_template=(
            "Le contrat porte sur un travail à forte intensité de main-d'œuvre et "
            "d'une ampleur qui pourrait dépasser les effectifs en place : un "
            "renfort — interne, intérimaire ou sous-traité — est plausible."
        ),
        externalisability="mixed",
    ),
    NeedRule(
        rule_id="workforce-social-health-v1",
        category="workforce_capacity",
        mechanism_predicates=("social_health_service",),
        # §15 — ni `several_lots` ni `defined_period` : il faut une échelle réelle
        # ou un service récurrent doté d'une échelle connue.
        pressure_predicates=("large_scale", "recurring_with_scale"),
        statement_template=(
            "Une capacité de personnel qualifié pourrait être mobilisée pour "
            "assurer la prestation sur la durée."
        ),
        reasoning_template=(
            "Le contrat est un service à la personne d'ampleur ou durablement "
            "récurrent : une mobilisation d'effectifs supplémentaires est "
            "plausible pendant l'exécution."
        ),
        externalisability="mixed",
    ),
    NeedRule(
        rule_id="equipment-construction-machinery-v1",
        category="equipment_or_rental",
        mechanism_predicates=("construction_machinery",),
        pressure_predicates=ALL_PRESSURES,
        statement_template=(
            "Une capacité temporaire d'engins ou de matériel de chantier pourrait "
            "être commercialement pertinente."
        ),
        reasoning_template=(
            "Le corps de métier publié compte parmi ceux qui mobilisent des engins "
            "au-delà du parc courant : si l'exécution comporte de tels travaux, une "
            "location ou un complément d'équipement est plausible."
        ),
        externalisability="mixed",
    ),
    NeedRule(
        rule_id="equipment-transport-fleet-v1",
        category="equipment_or_rental",
        mechanism_predicates=("transport_fleet",),
        pressure_predicates=ALL_PRESSURES,
        statement_template=(
            "Un renfort de flotte ou de matériel roulant pourrait être nécessaire "
            "pour absorber le volume du marché."
        ),
        reasoning_template=(
            "Le marché de transport pourrait solliciter la flotte au-delà de sa "
            "capacité disponible : une location ou une acquisition de véhicules "
            "est plausible."
        ),
        externalisability="mixed",
    ),
    NeedRule(
        rule_id="materials-construction-v1",
        category="materials_or_components",
        mechanism_predicates=("construction_materials",),
        pressure_predicates=ALL_PRESSURES,
        statement_template=(
            "Un approvisionnement en matériaux ou composants pourrait accompagner "
            "l'exécution des travaux."
        ),
        reasoning_template=(
            "Le corps de métier publié consomme des matériaux et des composants en "
            "volume : si l'objet du lot en relève, des achats d'approvisionnement "
            "sont plausibles auprès de négoces ou de fabricants."
        ),
        externalisability="external_plausible",
    ),
    NeedRule(
        rule_id="subcontracting-separable-specialties-v1",
        category="specialist_subcontracting",
        mechanism_predicates=("separable_specialties",),
        pressure_predicates=ALL_PRESSURES,
        statement_template=(
            "Le recours à des sous-traitants spécialisés pourrait être pertinent "
            "sur certaines composantes du marché."
        ),
        reasoning_template=(
            "Le marché réunit des spécialités techniquement séparables et une "
            "ampleur qui rend plausible la couverture d'une partie par des "
            "sous-traitants spécialisés."
        ),
        externalisability="external_plausible",
    ),
    NeedRule(
        rule_id="safety-ppe-construction-v1",
        category="safety_and_ppe",
        mechanism_predicates=("construction_site",),
        pressure_predicates=ALL_PRESSURES,
        statement_template=(
            "Un approvisionnement en équipements de protection pourrait accompagner "
            "la montée en charge du chantier."
        ),
        reasoning_template=(
            "Un chantier soumis aux obligations de sécurité mobilise des EPI et des "
            "protections collectives proportionnés à son ampleur : un achat "
            "complémentaire est plausible."
        ),
        externalisability="external_plausible",
    ),
    NeedRule(
        rule_id="waste-construction-debris-v1",
        category="waste_and_environment",
        mechanism_predicates=("construction_debris",),
        pressure_predicates=ALL_PRESSURES,
        statement_template=(
            "Une capacité d'évacuation et de traitement des déchets de chantier "
            "pourrait être requise."
        ),
        reasoning_template=(
            "Les travaux génèrent des déblais et des gravats dont le volume suit "
            "l'ampleur du chantier : un prestataire de collecte ou de traitement "
            "est plausible."
        ),
        externalisability="external_plausible",
    ),
)
