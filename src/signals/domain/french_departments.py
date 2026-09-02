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
    """« FR-92 » → « Hauts-de-Seine ». Tout autre référentiel rend `None`."""
    if not subdivision_code or not subdivision_code.startswith("FR-"):
        return None
    return DEPARTMENTS.get(subdivision_code[3:])


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
    "department_from_postal_code",
    "department_label",
    "location_subdivision",
]
