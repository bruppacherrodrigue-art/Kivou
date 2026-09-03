"""Subdivisions FR/CH : départements français et cantons suisses.

Les départements vivent déjà dans `signals.domain.french_departments`
(dérivés du code postal DECP) — ce module les ré-exporte pour qu'un appelant
n'ait qu'un seul référentiel de subdivisions à connaître, FR et CH confondus.
Les cantons suisses n'ont pas d'équivalent « dérivé d'un code postal » : SIMAP
publie directement le code ISO 3166-2 (`CH-VD`), donc une simple table de
libellés suffit — pas de dérivation à écrire.
"""

from __future__ import annotations

from signals.domain.french_departments import DEPARTMENTS as FRENCH_DEPARTMENTS
from signals.domain.french_departments import department_label

SWISS_CANTONS: dict[str, str] = {
    "AG": "Argovie",
    "AI": "Appenzell Rhodes-Intérieures",
    "AR": "Appenzell Rhodes-Extérieures",
    "BE": "Berne",
    "BL": "Bâle-Campagne",
    "BS": "Bâle-Ville",
    "FR": "Fribourg",
    "GE": "Genève",
    "GL": "Glaris",
    "GR": "Grisons",
    "JU": "Jura",
    "LU": "Lucerne",
    "NE": "Neuchâtel",
    "NW": "Nidwald",
    "OW": "Obwald",
    "SG": "Saint-Gall",
    "SH": "Schaffhouse",
    "SO": "Soleure",
    "SZ": "Schwytz",
    "TG": "Thurgovie",
    "TI": "Tessin",
    "UR": "Uri",
    "VD": "Vaud",
    "VS": "Valais",
    "ZG": "Zoug",
    "ZH": "Zurich",
}


def _canton_label(subdivision_code: str | None) -> str | None:
    if not subdivision_code or not subdivision_code.startswith("CH-"):
        return None
    return SWISS_CANTONS.get(subdivision_code[3:])


def subdivision_label(code: str | None) -> str | None:
    """Le libellé d'une subdivision `FR-92` ou `CH-VD`, `None` sinon."""
    return department_label(code) or _canton_label(code)


__all__ = [
    "FRENCH_DEPARTMENTS",
    "SWISS_CANTONS",
    "subdivision_label",
]
