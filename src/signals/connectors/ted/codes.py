"""Tables de correspondance entre codes TED et codes canoniques.

eForms publie les pays en **ISO 3166-1 alpha-3** (`FRA`, `DEU`) ; le modèle
canonique utilise l'alpha-2 (`FR`, `DE`). La conversion est une normalisation
déterministe, pas une inférence : `FRA` et `FR` désignent le même pays.

La table couvre l'UE, l'EEE et les pays tiers réellement rencontrés sur TED.
Un code absent n'est **jamais** deviné : `alpha2()` retourne `None` et l'appelant
émet un avertissement. Mieux vaut un pays manquant qu'un pays inventé.
"""

from __future__ import annotations

_ALPHA3_TO_ALPHA2 = {
    # Union européenne
    "AUT": "AT",
    "BEL": "BE",
    "BGR": "BG",
    "CYP": "CY",
    "CZE": "CZ",
    "DEU": "DE",
    "DNK": "DK",
    "ESP": "ES",
    "EST": "EE",
    "FIN": "FI",
    "FRA": "FR",
    "GRC": "GR",
    "HRV": "HR",
    "HUN": "HU",
    "IRL": "IE",
    "ITA": "IT",
    "LTU": "LT",
    "LUX": "LU",
    "LVA": "LV",
    "MLT": "MT",
    "NLD": "NL",
    "POL": "PL",
    "PRT": "PT",
    "ROU": "RO",
    "SVK": "SK",
    "SVN": "SI",
    "SWE": "SE",
    # EEE / AELE
    "CHE": "CH",
    "ISL": "IS",
    "LIE": "LI",
    "NOR": "NO",
    # Territoires et dépendances rencontrés
    "ALA": "AX",
    "FRO": "FO",
    "GGY": "GG",
    "GIB": "GI",
    "GLP": "GP",
    "GRL": "GL",
    "GUF": "GF",
    "IMN": "IM",
    "JEY": "JE",
    "MTQ": "MQ",
    "MYT": "YT",
    "NCL": "NC",
    "PYF": "PF",
    "REU": "RE",
    "SPM": "PM",
    "WLF": "WF",
    "BLM": "BL",
    "MAF": "MF",
    "ABW": "AW",
    "CUW": "CW",
    "SXM": "SX",
    # Pays tiers fréquents sur TED
    "ALB": "AL",
    "AND": "AD",
    "ARE": "AE",
    "ARG": "AR",
    "ARM": "AM",
    "AUS": "AU",
    "AZE": "AZ",
    "BIH": "BA",
    "BLR": "BY",
    "BRA": "BR",
    "CAN": "CA",
    "CHN": "CN",
    "COL": "CO",
    "EGY": "EG",
    "GBR": "GB",
    "GEO": "GE",
    "IND": "IN",
    "ISR": "IL",
    "JPN": "JP",
    "KOR": "KR",
    "MAR": "MA",
    "MCO": "MC",
    "MDA": "MD",
    "MEX": "MX",
    "MKD": "MK",
    "MNE": "ME",
    "NZL": "NZ",
    "RUS": "RU",
    "SGP": "SG",
    "SMR": "SM",
    "SRB": "RS",
    "THA": "TH",
    "TUN": "TN",
    "TUR": "TR",
    "UKR": "UA",
    "USA": "US",
    "VAT": "VA",
    "VNM": "VN",
    "XKX": "XK",
    "ZAF": "ZA",
}


def alpha2(code: str | None) -> str | None:
    """Convertit un code pays eForms en alpha-2, ou `None` si inconnu."""
    if not code:
        return None
    return _ALPHA3_TO_ALPHA2.get(code.strip().upper())
