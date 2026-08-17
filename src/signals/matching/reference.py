"""Huit ICPs de référence — des fixtures de benchmark, jamais des clients réels.

SPEC-008 §31. Ils couvrent délibérément les cas que le moteur doit savoir
traiter *et* ceux qu'il doit savoir refuser :

- des offres locales (géographie requise) et une offre distante (géographie
  ignorée) ;
- des ICPs très stricts (seuil élevé, exclusions, fenêtre courte) et des ICPs
  larges ;
- des besoins primaires et secondaires ;
- des territoires, des devises et des fraîcheurs différents ;
- **un contrôle négatif** : l'ICP « déchets » vise une catégorie que le Need
  Graph ne produit pas aujourd'hui (`waste_and_environment` sort du top-3). Il
  doit rendre zéro `show` sans erreur — c'est le résultat attendu, pas un bug.

Les libellés sont en français et en anglais ; le matching, lui, ne lit que les
champs canoniques (§8).
"""

from __future__ import annotations

from signals.matching.icp import TargetICP, Territory, ValueThreshold

REFERENCE_ICPS: tuple[TargetICP, ...] = (
    TargetICP(
        icp_id="icp-staffing-ch",
        name="Agence d'intérim BTP — Suisse",
        offer_summary="Mise à disposition de personnel qualifié pour chantiers et sites.",
        primary_need_categories=("workforce_capacity",),
        secondary_need_categories=("specialist_subcontracting",),
        geography_basis="place_of_performance",
        geography_policy="required",
        territories=(Territory(country="CH"),),
        excluded_contract_types=("it_digital", "research"),
        value_thresholds=(ValueThreshold(currency="CHF", minimum_amount=250_000),),
        unknown_value_policy="allow_with_penalty",
        maximum_signal_age_days=90,
        preferred_timings=("immediate", "near_term", "recurring"),
    ),
    TargetICP(
        icp_id="icp-plant-hire-ch",
        name="Loueur d'engins de chantier — Suisse",
        offer_summary="Location de pelles, grues et matériel de terrassement avec ou sans opérateur.",
        primary_need_categories=("equipment_or_rental",),
        secondary_need_categories=("logistics_and_transport",),
        geography_basis="place_of_performance",
        geography_policy="required",
        territories=(Territory(country="CH"),),
        included_contract_types=("construction",),
        excluded_contract_types=("it_digital", "business_services", "financial_insurance"),
        value_thresholds=(ValueThreshold(currency="CHF", minimum_amount=500_000),),
        unknown_value_policy="exclude",
        maximum_signal_age_days=60,
        preferred_timings=("immediate", "near_term"),
    ),
    TargetICP(
        icp_id="icp-materials-eu",
        name="Négoce de matériaux de construction — zone euro",
        offer_summary="Fourniture de matériaux et composants pour le bâtiment et le génie civil.",
        primary_need_categories=("materials_or_components",),
        secondary_need_categories=("equipment_or_rental",),
        geography_basis="place_of_performance",
        geography_policy="required",
        territories=(
            Territory(country="FR"),
            Territory(country="DE"),
            Territory(country="ES"),
            Territory(country="IT"),
            Territory(country="PT"),
            Territory(country="BE"),
            Territory(country="NL"),
        ),
        included_contract_types=("construction",),
        value_thresholds=(ValueThreshold(currency="EUR", minimum_amount=200_000),),
        unknown_value_policy="allow_with_penalty",
        maximum_signal_age_days=120,
        preferred_timings=("near_term", "medium_term"),
    ),
    TargetICP(
        icp_id="icp-ppe-safety-ch",
        name="Fournisseur EPI et sécurité chantier — Suisse",
        offer_summary="Équipements de protection individuelle et protections collectives.",
        primary_need_categories=("safety_and_ppe",),
        secondary_need_categories=("workforce_capacity",),
        geography_basis="place_of_performance",
        geography_policy="preferred",
        territories=(Territory(country="CH"),),
        included_contract_types=("construction",),
        value_thresholds=(ValueThreshold(currency="CHF", minimum_amount=100_000),),
        unknown_value_policy="allow_neutral",
        maximum_signal_age_days=180,
    ),
    TargetICP(
        icp_id="icp-waste-ch",
        name="Collecte et traitement de déchets de chantier — Suisse",
        offer_summary="Évacuation de déblais, gravats et déchets de construction.",
        # Contrôle négatif assumé : le Need Graph ne produit pas cette catégorie
        # aujourd'hui — attendu zéro `show`, sans erreur.
        primary_need_categories=("waste_and_environment",),
        geography_basis="place_of_performance",
        geography_policy="required",
        territories=(Territory(country="CH"),),
        included_contract_types=("construction",),
        value_thresholds=(ValueThreshold(currency="CHF", minimum_amount=150_000),),
        unknown_value_policy="allow_neutral",
        maximum_signal_age_days=120,
    ),
    TargetICP(
        icp_id="icp-subcontracting-eu",
        name="Sous-traitance technique spécialisée — Europe de l'Ouest",
        offer_summary="Lots techniques spécialisés en construction, ingénierie et systèmes.",
        primary_need_categories=("specialist_subcontracting",),
        secondary_need_categories=("workforce_capacity",),
        geography_basis="place_of_performance",
        geography_policy="preferred",
        territories=(
            Territory(country="FR"),
            Territory(country="DE"),
            Territory(country="CH"),
            Territory(country="BE"),
            Territory(country="AT"),
        ),
        excluded_sectors=("defence_security",),
        value_thresholds=(
            ValueThreshold(currency="EUR", minimum_amount=500_000),
            ValueThreshold(currency="CHF", minimum_amount=500_000),
        ),
        unknown_value_policy="allow_with_penalty",
        maximum_signal_age_days=90,
        preferred_timings=("near_term", "medium_term"),
    ),
    TargetICP(
        icp_id="icp-national-supplier",
        name="Fournisseur multirégional — capacité et matériaux",
        offer_summary="Groupe national couvrant plusieurs pays, offre large sur les intrants de chantier.",
        primary_need_categories=("workforce_capacity", "materials_or_components"),
        secondary_need_categories=("equipment_or_rental", "safety_and_ppe"),
        geography_basis="either",
        geography_policy="preferred",
        territories=(
            Territory(country="CH"),
            Territory(country="FR"),
            Territory(country="DE"),
            Territory(country="IT"),
            Territory(country="ES"),
            Territory(country="PL"),
        ),
        value_thresholds=(
            ValueThreshold(currency="CHF", minimum_amount=100_000),
            ValueThreshold(currency="EUR", minimum_amount=100_000),
        ),
        unknown_value_policy="allow_neutral",
        maximum_signal_age_days=180,
    ),
    TargetICP(
        icp_id="icp-remote-specialist",
        name="Cabinet de spécialistes à distance — sans contrainte de zone",
        offer_summary="Expertise technique délivrée à distance, indépendante du lieu d'exécution.",
        primary_need_categories=("specialist_subcontracting",),
        geography_basis="ignore",
        geography_policy="ignored",
        excluded_contract_types=("medical_supply", "equipment_supply"),
        unknown_value_policy="allow_neutral",
        maximum_signal_age_days=365,
    ),
)

REFERENCE_ICP_LIBRARY_VERSION = "reference-icps-v0.1"
