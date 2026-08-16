"""Le CPV, signal primaire de compréhension.

Pourquoi le CPV et pas le titre : sur les 168 adjudications réelles du corpus,
**le CPV est présent 168 fois**, tandis que les titres publiés valent souvent
`Default lot`, `Lote 1`, `Reihen` ou `1`. Le titre confirme une lecture, il ne
la décide pas.

Deux tables, parce que **le secteur n'est pas le type de contrat** : des
fournitures médicales sont un marché de fournitures (`medical_supply`) dans le
secteur de la santé ; une école neuve est un marché de travaux (`construction`)
dans le secteur de l'éducation.

Les tables restent délibérément courtes. Le vocabulaire CPV compte des milliers
de codes ; seules les divisions et les quelques sous-divisions qui portent une
information non ambiguë sont reprises. Le préfixe le plus long l'emporte, et un
code non couvert donne `unknown` — jamais une catégorie plausible.
"""

from __future__ import annotations

from typing import Literal

ContractType = Literal[
    "construction",
    "engineering_architecture",
    "it_digital",
    "telecom",
    "transport_logistics",
    "medical_supply",
    "social_health_services",
    "facility_services",
    "security_services",
    "business_services",
    "education_services",
    "energy_utilities",
    "equipment_supply",
    "maintenance_repair",
    "research",
    "financial_insurance",
    "unknown",
]

Sector = Literal[
    "healthcare",
    "education",
    "transport",
    "energy",
    "environment",
    "defence_security",
    "public_administration",
    "culture_recreation",
    "housing",
    "unknown",
]

# Préfixe CPV → type de contrat. Le préfixe le plus long gagne.
CPV_TYPE_RULES: dict[str, ContractType] = {
    # travaux
    "45": "construction",
    # ingénierie et architecture
    "71": "engineering_architecture",
    # informatique
    "48": "it_digital",
    "72": "it_digital",
    # télécommunications : la division 64 couvre les SERVICES postaux et télécom.
    # La division 32 est de l'ÉQUIPEMENT radio/TV/multimédia — un projecteur de
    # scène (32322000) n'est pas un marché de télécommunications ; la revue
    # manuelle du corpus l'a montré.
    "64": "telecom",
    # transport et logistique (services)
    "60": "transport_logistics",
    "63": "transport_logistics",
    # santé
    "33": "medical_supply",
    "85": "social_health_services",
    # services de propreté, environnement, restauration
    "90": "facility_services",
    "55": "facility_services",
    "98": "facility_services",
    # services aux entreprises ; la sécurité s'en détache
    "79": "business_services",
    "797": "security_services",
    "66": "financial_insurance",
    "73": "research",
    "80": "education_services",
    # énergie
    "09": "energy_utilities",
    "65": "energy_utilities",
    # entretien et réparation
    "50": "maintenance_repair",
    # fournitures et équipements
    "03": "equipment_supply",
    "14": "equipment_supply",
    "15": "equipment_supply",
    "16": "equipment_supply",
    "18": "equipment_supply",
    "19": "equipment_supply",
    "22": "equipment_supply",
    "24": "equipment_supply",
    "30": "equipment_supply",
    "31": "equipment_supply",
    "32": "equipment_supply",
    "34": "equipment_supply",
    "35": "equipment_supply",
    "37": "equipment_supply",
    "38": "equipment_supply",
    "39": "equipment_supply",
    "41": "equipment_supply",
    "42": "equipment_supply",
    "43": "equipment_supply",
    "44": "equipment_supply",
}

# Préfixe CPV → secteur, UNIQUEMENT lorsque le code le dit explicitement.
# Un `45000000` générique ne révèle aucun secteur : il reste `unknown`.
CPV_SECTOR_RULES: dict[str, Sector] = {
    "33": "healthcare",
    "85": "healthcare",
    "45215": "healthcare",  # bâtiments de santé
    "80": "education",
    "45214": "education",  # bâtiments scolaires et universitaires
    "60": "transport",
    "63": "transport",
    "34": "transport",
    "45234": "transport",  # voies ferrées, aérodromes
    "09": "energy",
    "65": "energy",
    "45251": "energy",  # centrales
    "90": "environment",
    "35": "defence_security",
    "797": "defence_security",
    "75": "public_administration",
    "92": "culture_recreation",
    "45212": "culture_recreation",  # bâtiments de loisirs et de sport
    "45211": "housing",  # bâtiments d'habitation
}


def _longest_prefix_match(code: str | None, rules: dict[str, str]) -> str | None:
    if not code:
        return None
    for length in range(min(len(code), 8), 0, -1):
        found = rules.get(code[:length])
        if found:
            return found
    return None


def contract_type_for_cpv(code: str | None) -> ContractType:
    """Type de contrat déduit du CPV, ou `unknown` si le code n'est pas couvert."""
    return _longest_prefix_match(code, CPV_TYPE_RULES) or "unknown"  # type: ignore[return-value]


def sector_for_cpv(code: str | None) -> Sector:
    """Secteur déduit du CPV **lorsqu'il l'exprime**, sinon `unknown`."""
    return _longest_prefix_match(code, CPV_SECTOR_RULES) or "unknown"  # type: ignore[return-value]
