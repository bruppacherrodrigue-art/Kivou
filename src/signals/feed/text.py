"""Normalisation de texte partagée entre le feed et la liste des entreprises.

Extraite de `companies/listing.py` (PR2b tâche 3) : le filtre plein texte de
`GET /signals` (`feed/query.py`) en a besoin lui aussi, et ne peut pas importer
`companies/listing.py`, qui importe déjà `feed/query.py` — ce serait un cycle.
Ce module ne dépend de rien du domaine, donc les deux côtés peuvent l'importer
sans risque.
"""

from __future__ import annotations

import unicodedata


def normalize_text(value: str) -> str:
    """Casefold, puis strip des diacritiques — insensible casse ET accents."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))
