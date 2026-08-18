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

STRIPE_MODE_ENV = "KIVOU_STRIPE_MODE"
STRIPE_SECRET_KEY_ENV = "STRIPE_SECRET_KEY"
STRIPE_WEBHOOK_SECRET_ENV = "STRIPE_WEBHOOK_SECRET"
STRIPE_SUCCESS_URL_ENV = "STRIPE_SUCCESS_URL"
STRIPE_CANCEL_URL_ENV = "STRIPE_CANCEL_URL"
STRIPE_PORTAL_RETURN_URL_ENV = "STRIPE_PORTAL_RETURN_URL"
STRIPE_AUTOMATIC_TAX_ENV = "STRIPE_AUTOMATIC_TAX_ENABLED"
STRIPE_FOUNDING_COUPON_ENV = "STRIPE_FOUNDING_COUPON_ID"
STRIPE_PORTAL_CONFIGURATION_ENV = "STRIPE_PORTAL_CONFIGURATION_ID"

STRIPE_MODES: tuple[str, ...] = ("test", "live")
DEFAULT_STRIPE_MODE = "test"

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

    # ── Stripe (SPEC-013) ────────────────────────────────────────────────────
    #: §30 — `test` ou `live`, jamais déduit. Un objet Stripe du mauvais mode
    #: fait échouer l'appel plutôt que de mélanger deux univers de données.
    stripe_mode: str = DEFAULT_STRIPE_MODE
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_success_url: str = "https://app.kivou.ch/billing/success"
    stripe_cancel_url: str = "https://app.kivou.ch/billing/cancel"
    stripe_portal_return_url: str = "https://app.kivou.ch/billing"
    #: §29 — désactivée par défaut. La fiscalité est une décision, pas un défaut :
    #: l'activer sans immatriculation produirait des factures fausses.
    stripe_automatic_tax: bool = False
    #: §7, §33 — la remise fondateur, jamais saisissable par le client.
    stripe_founding_coupon_id: str | None = None
    #: R1 §9 — la configuration de portail à utiliser. `None` laisse Stripe
    #: appliquer la configuration PAR DÉFAUT du compte — ce qui, sur un compte
    #: partagé avec un autre projet, afficherait la marque de ce projet. Le
    #: champ existe pour que la bonne configuration s'applique sans changer une
    #: ligne de code le jour où elle est créée.
    stripe_portal_configuration_id: str | None = None

    @property
    def stripe_livemode(self) -> bool:
        return self.stripe_mode == "live"

    @classmethod
    def from_environment(cls) -> ApiConfig:
        secure = os.environ.get(COOKIE_SECURE_ENV)
        mode = (os.environ.get(STRIPE_MODE_ENV) or DEFAULT_STRIPE_MODE).lower()
        if mode not in STRIPE_MODES:
            raise ValueError(f"{STRIPE_MODE_ENV} doit valoir {STRIPE_MODES}, pas {mode!r}")
        secret_key = os.environ.get(STRIPE_SECRET_KEY_ENV) or None
        _check_key_matches_mode(secret_key, mode)
        return cls(
            session_ttl=_duration(SESSION_TTL_ENV, DEFAULT_SESSION_TTL),
            password_reset_ttl=_duration(RESET_TTL_ENV, DEFAULT_RESET_TTL),
            cookie_secure=True if secure is None else secure.lower() not in {"0", "false", "no"},
            allowed_origin=os.environ.get(ALLOWED_ORIGIN_ENV) or None,
            stripe_mode=mode,
            stripe_secret_key=secret_key,
            stripe_webhook_secret=os.environ.get(STRIPE_WEBHOOK_SECRET_ENV) or None,
            stripe_success_url=_url(STRIPE_SUCCESS_URL_ENV, cls.stripe_success_url),
            stripe_cancel_url=_url(STRIPE_CANCEL_URL_ENV, cls.stripe_cancel_url),
            stripe_portal_return_url=_url(
                STRIPE_PORTAL_RETURN_URL_ENV, cls.stripe_portal_return_url
            ),
            stripe_automatic_tax=_flag(STRIPE_AUTOMATIC_TAX_ENV),
            stripe_founding_coupon_id=os.environ.get(STRIPE_FOUNDING_COUPON_ENV) or None,
            stripe_portal_configuration_id=(
                os.environ.get(STRIPE_PORTAL_CONFIGURATION_ENV) or None
            ),
        )


def _flag(name: str) -> bool:
    """Un drapeau d'environnement. Absent vaut faux : aucun défaut permissif."""
    raw = os.environ.get(name)
    return bool(raw) and raw.lower() in {"1", "true", "yes"}


def _url(name: str, default: str) -> str:
    """Une URL de retour, forcément absolue et chiffrée.

    §13 — elle vient de la configuration, jamais de la requête : une URL de
    succès fournie par le client transformerait le paiement en redirection
    ouverte.
    """
    value = os.environ.get(name) or default
    if not value.startswith("https://"):
        raise ValueError(f"{name} doit être une URL https absolue, pas {value!r}")
    return value


def _check_key_matches_mode(secret_key: str | None, mode: str) -> None:
    """§30 — une clé de test avec un mode `live` (ou l'inverse) s'arrête net.

    C'est la panne la plus coûteuse de toute intégration Stripe : elle ne se
    voit qu'au moment où un vrai client paie sur des objets de test, ou
    l'inverse. Le contrôle porte sur le préfixe, seule information non secrète
    de la clé — sa valeur n'est jamais journalisée ni rendue.
    """
    if secret_key is None:
        return
    is_test_key = secret_key.startswith(("sk_test_", "rk_test_"))
    is_live_key = secret_key.startswith(("sk_live_", "rk_live_"))
    if mode == "test" and is_live_key:
        raise ValueError("clé Stripe de production configurée avec KIVOU_STRIPE_MODE=test")
    if mode == "live" and is_test_key:
        raise ValueError("clé Stripe de test configurée avec KIVOU_STRIPE_MODE=live")
