"""Configuration de l'application — un objet typé, pas un framework de réglages.

Tout vient de l'environnement, rien du code source. Cinq valeurs suffisent au
MVP, et aucune n'a de défaut dangereux : les durées ont un défaut raisonnable,
l'URL de base et l'origine autorisée n'en ont aucun quand la sécurité en dépend.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import os

SESSION_COOKIE_NAME = "kivou_session"

SESSION_TTL_ENV = "KIVOU_SESSION_TTL_SECONDS"
RESET_TTL_ENV = "KIVOU_PASSWORD_RESET_TTL_SECONDS"
COOKIE_SECURE_ENV = "KIVOU_COOKIE_SECURE"
ALLOWED_ORIGIN_ENV = "KIVOU_ALLOWED_ORIGIN"

DEFAULT_SESSION_TTL = dt.timedelta(days=14)
DEFAULT_RESET_TTL = dt.timedelta(hours=1)


def _duration(name: str, default: dt.timedelta) -> dt.timedelta:
    raw = os.environ.get(name)
    if not raw:
        return default
    seconds = int(raw)
    if seconds <= 0:
        raise ValueError(f"{name} doit être un nombre de secondes positif")
    return dt.timedelta(seconds=seconds)


@dataclasses.dataclass(frozen=True)
class ApiConfig:
    """Ce dont l'application a besoin pour démarrer, et rien de plus."""

    session_ttl: dt.timedelta = DEFAULT_SESSION_TTL
    password_reset_ttl: dt.timedelta = DEFAULT_RESET_TTL
    #: §7 — `Secure` en production. Relâché explicitement en local, jamais par défaut.
    cookie_secure: bool = True
    #: §8 — l'origine du frontend. `None` désactive la validation, ce qui n'est
    #: acceptable qu'en test et doit se voir dans la configuration.
    allowed_origin: str | None = None

    @classmethod
    def from_environment(cls) -> ApiConfig:
        secure = os.environ.get(COOKIE_SECURE_ENV)
        return cls(
            session_ttl=_duration(SESSION_TTL_ENV, DEFAULT_SESSION_TTL),
            password_reset_ttl=_duration(RESET_TTL_ENV, DEFAULT_RESET_TTL),
            cookie_secure=True if secure is None else secure.lower() not in {"0", "false", "no"},
            allowed_origin=os.environ.get(ALLOWED_ORIGIN_ENV) or None,
        )
