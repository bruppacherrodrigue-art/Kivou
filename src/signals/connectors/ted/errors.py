"""Erreurs du connecteur TED — explicites, jamais silencieuses."""

from __future__ import annotations


class TedError(Exception):
    """Racine des erreurs TED."""


class TedHttpError(TedError):
    """L'API ou le site TED a répondu autrement qu'attendu."""

    def __init__(self, message: str, *, status_code: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class TedParseError(TedError):
    """Le XML n'est pas une notice eForms exploitable.

    Levée avant toute tentative de mapping : mieux vaut refuser une notice que
    produire un contrat construit sur une structure mal comprise.
    """


class TedMappingError(TedError):
    """La notice est lisible mais ne peut pas être traduite sans inventer un fait."""
