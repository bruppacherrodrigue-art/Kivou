"""Reject obvious demonstration addresses before prospecting."""

from __future__ import annotations

import re

_EXACT_MARKERS = ("jean.dupont", "john.doe", "prenom.nom", "domain.com", "email.com")
_PLACEHOLDER_WORDS = frozenset(
    {"exemple", "example", "test", "demo", "yourdomain", "monsite"}
)


def is_placeholder_email(value: object) -> bool:
    email = str(value or "").strip().casefold()
    if any(marker in email for marker in _EXACT_MARKERS):
        return True
    return bool(_PLACEHOLDER_WORDS.intersection(re.findall(r"[a-z0-9]+", email)))


__all__ = ["is_placeholder_email"]
