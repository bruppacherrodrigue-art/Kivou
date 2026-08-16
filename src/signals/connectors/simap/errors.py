"""Erreurs du connecteur SIMAP — explicites, jamais silencieuses."""

from __future__ import annotations


class SimapError(Exception):
    """Racine des erreurs SIMAP."""


class SimapHttpError(SimapError):
    """L'API simap.ch a répondu autrement qu'attendu."""

    def __init__(self, message: str, *, status_code: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class SimapAuthRequiredError(SimapHttpError):
    """La ressource existe mais exige un rôle (acheteur, soumissionnaire).

    Distinguée d'une panne : c'est un état normal de la plateforme, pas une
    erreur à réessayer. SPEC-003 mesure cette frontière, elle ne la contourne pas.
    """


class SimapParseError(SimapError):
    """La réponse n'est pas une publication d'adjudication exploitable."""


class SimapMappingError(SimapError):
    """La publication est lisible mais ne peut pas être traduite sans inventer un fait."""
