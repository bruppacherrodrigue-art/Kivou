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

# ─── ICP du wedge MVP (WEDGE-HARDENING R1 §15) ──────────────────────────────────

CONSTRUCTION_INPUTS_ICP = TargetICP(
    icp_id="icp-construction-inputs-ch-eu-v0",
    name="Négoce d'intrants de chantier — CH, DE, FR, ES, PT",
    offer_summary=(
        "Matériaux et composants de gros œuvre et de second œuvre livrés sur chantier : "
        "béton et granulats, maçonnerie, charpente, couverture et étanchéité, menuiserie, "
        "cloisons, sols et revêtements."
    ),
    primary_need_categories=("materials_or_components",),
    secondary_need_categories=("equipment_or_rental",),
    # §16 — ce qu'un négociant livre vraiment. Le gros œuvre et le second œuvre
    # sont son marché ; la route et l'ouvrage spécial lui achètent parfois, mais
    # commandent l'essentiel ailleurs (centrale d'enrobés, fournisseur sur plan) ;
    # l'installation technique et la caténaire ferroviaire ne lui achètent rien.
    primary_trade_domains=(
        "general_building",
        "interior_finishing",
        "earthworks_demolition",
    ),
    secondary_trade_domains=("roadworks_civil", "special_civil"),
    geography_basis="place_of_performance",
    geography_policy="required",
    territories=(
        Territory(country="CH"),
        Territory(country="DE"),
        Territory(country="FR"),
        Territory(country="ES"),
        Territory(country="PT"),
    ),
    included_contract_types=("construction",),
    value_thresholds=(
        ValueThreshold(currency="CHF", minimum_amount=100_000),
        ValueThreshold(currency="EUR", minimum_amount=100_000),
    ),
    unknown_value_policy="allow_with_penalty",
    maximum_signal_age_days=120,
    preferred_timings=("near_term", "medium_term"),
)
"""Le wedge que SPEC-009B a isolé, désormais déclaré comme un ICP.

Il vit **hors** de `REFERENCE_ICPS` : la bibliothèque de SPEC-008 est l'archive
d'un banc gelé, et y ajouter un huitième profil rendrait ses mesures
incomparables.

**Le nom dit cinq pays parce que le modèle en autorise cinq.** Le filtre
géographique est une appartenance à un ensemble de codes pays : le lieu
d'exécution doit être publié et valoir CH, DE, FR, ES ou PT. Ni « zone euro »
— qui exclurait la Suisse et engloberait quinze États non ciblés — ni « CH+UE »
— qui en promettrait vingt-sept — ne décrivent cette configuration.

Ces cinq pays sont l'empreinte **observée** des 41 signaux du wedge SPEC-009B
(DE 17, CH 11, FR 7, ES 5, PT 1), et rien de plus. Ils mesurent une couverture,
pas une frontière de marché : les award-lots polonais, tchèques ou roumains du
pool n'ont jamais été éligibles, les deux ICPs sources ne les ciblant pas. Le
corpus n'établit donc pas que le wedge échoue ailleurs — il n'y a pas été
testé."""

WEDGE_ICP_LIBRARY_VERSION = "wedge-icps-v0.1"
