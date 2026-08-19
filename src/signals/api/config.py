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

# SPEC-014 — alertes client
PUBLIC_APP_URL_ENV = "KIVOU_PUBLIC_APP_URL"
SMTP_HOST_ENV = "SMTP_HOST"
SMTP_PORT_ENV = "SMTP_PORT"
SMTP_USERNAME_ENV = "SMTP_USERNAME"
SMTP_PASSWORD_ENV = "SMTP_PASSWORD"
SMTP_FROM_EMAIL_ENV = "SMTP_FROM_EMAIL"
SMTP_FROM_NAME_ENV = "SMTP_FROM_NAME"
SMTP_USE_TLS_ENV = "SMTP_USE_TLS"

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
    #: CLOSEOUT §3 — AUCUN défaut. Ces trois URL décident d'où revient un client
    #: après avoir payé, et un défaut codé en dur les envoie sur le domaine que
    #: le développeur avait en tête le jour où il l'a écrit. Le précédent
    #: (`app.kivou.ch`) a survécu au changement de domaine produit sans que rien
    #: ne le signale : c'est exactement la panne qu'un défaut silencieux
    #: fabrique. Une absence se voit au démarrage ; un mauvais domaine ne se voit
    #: qu'au premier paiement réel.
    stripe_success_url: str | None = None
    stripe_cancel_url: str | None = None
    stripe_portal_return_url: str | None = None
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

    # ── alertes (SPEC-014) ───────────────────────────────────────────────────
    #: §22 — la base des liens profonds. `None` fait échouer l'envoi en douceur :
    #: les signaux restent en file plutôt que de partir avec un lien cassé.
    #:
    #: CLOSEOUT §3 — elle DOIT inclure le préfixe du routeur navigateur. Le job
    #: d'alerte construit `{public_app_url}/signals/{signal_key}` ; la route
    #: cliente est `/app/signals/{signal_key}`. La base attendue est donc
    #: `https://<hôte>/app`, et non `https://<hôte>` — sinon le lien reçu par
    #: e-mail tombe à côté du signal qu'il annonce.
    #:
    #:     KIVOU_PUBLIC_APP_URL=https://kivou.eu/app
    #:       → https://kivou.eu/app/signals/{signal_key}
    public_app_url: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    #: Jamais journalisé, jamais rendu, jamais écrit dans le dépôt (§23, §39).
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_from_name: str = "Kivou"
    smtp_use_tls: bool = True

    @property
    def stripe_livemode(self) -> bool:
        return self.stripe_mode == "live"

    @property
    def alerts_configured(self) -> bool:
        """Peut-on envoyer une alerte sans produire un lien cassé ?"""
        return bool(self.public_app_url and self.smtp_host and self.smtp_from_email)

    @property
    def public_site_url(self) -> str | None:
        """La RACINE du site, d'où pendent les pages hors application.

        `public_app_url` pointe volontairement sur `/app`, le préfixe du routeur
        navigateur. Mais toutes les routes ne vivent pas dessous : `/login`,
        `/forgot-password` et surtout `/reset-password` sont servies à la
        racine. Construire un lien de réinitialisation sur la base des alertes
        donnerait `…/app/reset-password`, une adresse que le routeur ne connaît
        pas — le lien reçu par e-mail tomberait sur l'application vide.

        Le préfixe est retiré plutôt que redemandé dans une seconde variable :
        deux URL publiques à tenir cohérentes finissent toujours par diverger.
        """
        if self.public_app_url is None:
            return None
        return self.public_app_url.rstrip("/").removesuffix("/app")

    @property
    def password_reset_email_configured(self) -> bool:
        """Le lien de réinitialisation peut-il partir, et être cliquable ?

        Les mêmes trois éléments que pour une alerte, et pour la même raison :
        sans expéditeur il n'y a pas d'envoi, sans base publique il n'y a pas de
        lien. Un e-mail de sécurité mal formé est pire qu'un e-mail absent.
        """
        return bool(self.public_site_url and self.smtp_host and self.smtp_from_email)

    @property
    def billing_return_urls_configured(self) -> bool:
        """Sait-on où renvoyer un client après un paiement ?

        CLOSEOUT §3 — la facturation ne s'ouvre pas sans ces trois URL. Les
        servir depuis un défaut reviendrait à choisir un domaine à la place de
        l'exploitant, et un client reviendrait sur un hôte qui ne lui appartient
        plus.
        """
        return bool(
            self.stripe_success_url and self.stripe_cancel_url and self.stripe_portal_return_url
        )

    @classmethod
    def from_environment(cls) -> ApiConfig:
        secure = os.environ.get(COOKIE_SECURE_ENV)
        mode = (os.environ.get(STRIPE_MODE_ENV) or DEFAULT_STRIPE_MODE).lower()
        if mode not in STRIPE_MODES:
            raise ValueError(f"{STRIPE_MODE_ENV} doit valoir {STRIPE_MODES}, pas {mode!r}")
        secret_key = os.environ.get(STRIPE_SECRET_KEY_ENV) or None
        _check_key_matches_mode(secret_key, mode)
        success_url = _optional_url(STRIPE_SUCCESS_URL_ENV)
        cancel_url = _optional_url(STRIPE_CANCEL_URL_ENV)
        portal_return_url = _optional_url(STRIPE_PORTAL_RETURN_URL_ENV)
        # CLOSEOUT §3 — une clé Stripe déclare l'INTENTION d'encaisser. À partir
        # de là, ne pas savoir où renvoyer le client est une erreur de
        # configuration, et elle doit s'entendre au démarrage plutôt qu'au
        # premier paiement.
        if secret_key is not None:
            missing = [
                name
                for name, value in (
                    (STRIPE_SUCCESS_URL_ENV, success_url),
                    (STRIPE_CANCEL_URL_ENV, cancel_url),
                    (STRIPE_PORTAL_RETURN_URL_ENV, portal_return_url),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    "facturation activée sans URL de retour : "
                    f"{', '.join(missing)} doivent être définies"
                )
        return cls(
            session_ttl=_duration(SESSION_TTL_ENV, DEFAULT_SESSION_TTL),
            password_reset_ttl=_duration(RESET_TTL_ENV, DEFAULT_RESET_TTL),
            cookie_secure=True if secure is None else secure.lower() not in {"0", "false", "no"},
            allowed_origin=os.environ.get(ALLOWED_ORIGIN_ENV) or None,
            stripe_mode=mode,
            stripe_secret_key=secret_key,
            stripe_webhook_secret=os.environ.get(STRIPE_WEBHOOK_SECRET_ENV) or None,
            stripe_success_url=success_url,
            stripe_cancel_url=cancel_url,
            stripe_portal_return_url=portal_return_url,
            stripe_automatic_tax=_flag(STRIPE_AUTOMATIC_TAX_ENV),
            stripe_founding_coupon_id=os.environ.get(STRIPE_FOUNDING_COUPON_ENV) or None,
            stripe_portal_configuration_id=(
                os.environ.get(STRIPE_PORTAL_CONFIGURATION_ENV) or None
            ),
            public_app_url=_optional_url(PUBLIC_APP_URL_ENV),
            smtp_host=os.environ.get(SMTP_HOST_ENV) or None,
            smtp_port=int(os.environ.get(SMTP_PORT_ENV) or 587),
            smtp_username=os.environ.get(SMTP_USERNAME_ENV) or None,
            smtp_password=os.environ.get(SMTP_PASSWORD_ENV) or None,
            smtp_from_email=os.environ.get(SMTP_FROM_EMAIL_ENV) or None,
            smtp_from_name=os.environ.get(SMTP_FROM_NAME_ENV) or "Kivou",
            smtp_use_tls=os.environ.get(SMTP_USE_TLS_ENV, "1").lower() not in {"0", "false", "no"},
        )


def _optional_url(name: str) -> str | None:
    """Une URL publique facultative, mais forcément absolue et chiffrée.

    §22 — les liens profonds des alertes en dérivent, et §13 les URL de retour
    Stripe. Une base en `http://` enverrait des clients sur un lien non chiffré ;
    mieux vaut refuser au démarrage que le découvrir dans une boîte de réception
    ou après un paiement.

    Elle n'est jamais lue depuis la requête : une URL de succès fournie par le
    client transformerait le paiement en redirection ouverte.
    """
    value = os.environ.get(name)
    if not value:
        return None
    if not value.startswith("https://"):
        raise ValueError(f"{name} doit être une URL https absolue, pas {value!r}")
    return value.rstrip("/")


def _flag(name: str) -> bool:
    """Un drapeau d'environnement. Absent vaut faux : aucun défaut permissif."""
    raw = os.environ.get(name)
    return bool(raw) and raw.lower() in {"1", "true", "yes"}


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
