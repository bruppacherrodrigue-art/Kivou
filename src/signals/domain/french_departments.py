"""Départements français : dérivés du code postal, nommés depuis une table.

Le schéma DECP 2022 publie souvent un code postal sans commune ni département.
Le département est une DÉRIVATION déterministe du code postal publié — pas une
devinette sur la forme d'un code dont on ignorerait le type — et son nom est
un libellé de référentiel, pas un fait de l'avis.

Ce module vit dans `signals.domain` (pas `signals.feed`) pour que les
connecteurs (ex. `signals.connectors.decp`) puissent le dériver au parsing
sans dépendre du feed. `signals.feed.french_departments` le ré-exporte pour
les tests et le code du feed.
"""

from __future__ import annotations

from typing import Any

DEPARTMENTS: dict[str, str] = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence",
    "05": "Hautes-Alpes", "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes",
    "09": "Ariège", "10": "Aube", "11": "Aude", "12": "Aveyron",
    "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze", "2A": "Corse-du-Sud",
    "2B": "Haute-Corse", "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse",
    "24": "Dordogne", "25": "Doubs", "26": "Drôme", "27": "Eure",
    "28": "Eure-et-Loir", "29": "Finistère", "30": "Gard", "31": "Haute-Garonne",
    "32": "Gers", "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine",
    "36": "Indre", "37": "Indre-et-Loire", "38": "Isère", "39": "Jura",
    "40": "Landes", "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire",
    "44": "Loire-Atlantique", "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne",
    "48": "Lozère", "49": "Maine-et-Loire", "50": "Manche", "51": "Marne",
    "52": "Haute-Marne", "53": "Mayenne", "54": "Meurthe-et-Moselle", "55": "Meuse",
    "56": "Morbihan", "57": "Moselle", "58": "Nièvre", "59": "Nord",
    "60": "Oise", "61": "Orne", "62": "Pas-de-Calais", "63": "Puy-de-Dôme",
    "64": "Pyrénées-Atlantiques", "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales",
    "67": "Bas-Rhin", "68": "Haut-Rhin", "69": "Rhône", "70": "Haute-Saône",
    "71": "Saône-et-Loire", "72": "Sarthe", "73": "Savoie", "74": "Haute-Savoie",
    "75": "Paris", "76": "Seine-Maritime", "77": "Seine-et-Marne", "78": "Yvelines",
    "79": "Deux-Sèvres", "80": "Somme", "81": "Tarn", "82": "Tarn-et-Garonne",
    "83": "Var", "84": "Vaucluse", "85": "Vendée", "86": "Vienne",
    "87": "Haute-Vienne", "88": "Vosges", "89": "Yonne", "90": "Territoire de Belfort",
    "91": "Essonne", "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis", "94": "Val-de-Marne",
    "95": "Val-d'Oise", "971": "Guadeloupe", "972": "Martinique", "973": "Guyane",
    "974": "La Réunion", "976": "Mayotte",
}

# NUTS 3 (Eurostat 2024) coïncide avec le département en France. BOAMP eForms
# publie ce référentiel dans `CountrySubentityCode`, souvent sans code postal.
NUTS3_DEPARTMENTS: dict[str, str] = {
    "FR101": "75", "FR102": "77", "FR103": "78", "FR104": "91", "FR105": "92",
    "FR106": "93", "FR107": "94", "FR108": "95", "FRB01": "18", "FRB02": "28",
    "FRB03": "36", "FRB04": "37", "FRB05": "41", "FRB06": "45", "FRC11": "21",
    "FRC12": "58", "FRC13": "71", "FRC14": "89", "FRC21": "25", "FRC22": "39",
    "FRC23": "70", "FRC24": "90", "FRD11": "14", "FRD12": "50", "FRD13": "61",
    "FRD21": "27", "FRD22": "76", "FRE11": "59", "FRE12": "62", "FRE21": "02",
    "FRE22": "60", "FRE23": "80", "FRF11": "67", "FRF12": "68", "FRF21": "08",
    "FRF22": "10", "FRF23": "51", "FRF24": "52", "FRF31": "54", "FRF32": "55",
    "FRF33": "57", "FRF34": "88", "FRG01": "44", "FRG02": "49", "FRG03": "53",
    "FRG04": "72", "FRG05": "85", "FRH01": "22", "FRH02": "29", "FRH03": "35",
    "FRH04": "56", "FRI11": "24", "FRI12": "33", "FRI13": "40", "FRI14": "47",
    "FRI15": "64", "FRI21": "19", "FRI22": "23", "FRI23": "87", "FRI31": "16",
    "FRI32": "17", "FRI33": "79", "FRI34": "86", "FRJ11": "11", "FRJ12": "30",
    "FRJ13": "34", "FRJ14": "48", "FRJ15": "66", "FRJ21": "09", "FRJ22": "12",
    "FRJ23": "31", "FRJ24": "32", "FRJ25": "46", "FRJ26": "65", "FRJ27": "81",
    "FRJ28": "82", "FRK11": "03", "FRK12": "15", "FRK13": "43", "FRK14": "63",
    "FRK21": "01", "FRK22": "07", "FRK23": "26", "FRK24": "38", "FRK25": "42",
    "FRK26": "69", "FRK27": "73", "FRK28": "74", "FRL01": "04", "FRL02": "05",
    "FRL03": "06", "FRL04": "13", "FRL05": "83", "FRL06": "84", "FRM01": "2A",
    "FRM02": "2B", "FRY10": "971", "FRY20": "972", "FRY30": "973", "FRY40": "974",
    "FRY50": "976",
}


def department_from_postal_code(postal_code: str | None) -> str | None:
    """« 92350 » → « 92 », « 20167 » → « 2A », « 97133 » → « 971 », sinon `None`."""
    if not postal_code:
        return None
    code = postal_code.strip()
    if len(code) != 5 or not code.isdigit():
        return None
    if code.startswith("20"):
        return "2A" if int(code) < 20200 else "2B"
    candidate = code[:3] if code[:2] in {"97", "98"} else code[:2]
    return candidate if candidate in DEPARTMENTS else None


def department_label(subdivision_code: str | None) -> str | None:
    """Libellé d'un département depuis ISO 3166-2 ou NUTS 3 français."""
    if not subdivision_code:
        return None
    if subdivision_code.startswith("FR-"):
        return DEPARTMENTS.get(subdivision_code[3:])
    department = NUTS3_DEPARTMENTS.get(subdivision_code)
    return DEPARTMENTS.get(department) if department else None


def location_subdivision(place: dict[str, Any] | None) -> str | None:
    """La subdivision publiée, sinon le département dérivé d'un code postal français."""
    if not place:
        return None
    published = place.get("subdivision_code")
    if published:
        return published
    if place.get("country") != "FR":
        return None
    department = department_from_postal_code(place.get("postal_code"))
    return None if department is None else f"FR-{department}"


__all__ = [
    "DEPARTMENTS",
    "NUTS3_DEPARTMENTS",
    "department_from_postal_code",
    "department_label",
    "location_subdivision",
]
