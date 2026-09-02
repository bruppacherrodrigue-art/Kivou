"""Ré-export du référentiel des départements français.

L'implémentation vit dans `signals.domain.french_departments` pour que les
connecteurs (ex. `signals.connectors.decp`) puissent la dériver au parsing
sans dépendre du feed. Ce module ré-exporte pour le code et les tests du feed.
"""

from __future__ import annotations

from signals.domain.french_departments import (
    DEPARTMENTS,
    department_from_postal_code,
    department_label,
    location_subdivision,
)

__all__ = [
    "DEPARTMENTS",
    "department_from_postal_code",
    "department_label",
    "location_subdivision",
]
