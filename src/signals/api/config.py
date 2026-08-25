"""Configuration de l'application — un objet typé, pas un framework de réglages.

Tout vient de l'environnement, rien du code source. Cinq valeurs suffisent au
MVP, et aucune n'a de défaut dangereux : les durées ont un défaut raisonnable,
l'URL de base et l'origine autorisée n'en ont aucun quand la sécurité en dépend.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import os
import re
from urllib.parse import urlsplit

SESSION_COOKIE_NAME = "kivou_session"
ATTRIBUTION_COOKIE_NAME = "kivou_attribution"

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
SMTP_TLS_MODE_ENV = "SMTP_TLS_MODE"
SMTP_TIMEOUT_ENV = "SMTP_TIMEOUT_SECONDS"
SMTP_REPLY_TO_ENV = "SMTP_REPLY_TO_EMAIL"
ALERT_LEASE_SECONDS_ENV = "KIVOU_ALERT_LEASE_SECONDS"
ALERT_MAX_ATTEMPTS_ENV = "KIVOU_ALERT_MAX_ATTEMPTS"
ALERT_RETRY_BASE_SECONDS_ENV = "KIVOU_ALERT_RETRY_BASE_SECONDS"
INSTANTLY_WEBHOOK_SECRET_ENV = "KIVOU_INSTANTLY_WEBHOOK_SECRET"
INSTANTLY_WEBHOOK_WORKSPACE_ENV = "KIVOU_INSTANTLY_WORKSPACE_REF"
INSTANTLY_WEBHOOK_FINGERPRINT_KEY_ENV = "KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY"
INSTANTLY_WEBHOOK_FINGERPRINT_KEY_VERSION_ENV = (
    "KIVOU_INSTANTLY_WEBHOOK_FINGERPRINT_KEY_VERSION"
)
SUPPRESSION_IDENTITY_KEY_ENV = "KIVOU_SUPPRESSION_HMAC_KEY"
SUPPRESSION_IDENTITY_KEY_VERSION_ENV = "KIVOU_SUPPRESSION_HMAC_KEY_VERSION"
ATTRIBUTION_HMAC_KEY_ENV = "KIVOU_ATTRIBUTION_HMAC_KEY"
ATTRIBUTION_HMAC_KEY_VERSION_ENV = "KIVOU_ATTRIBUTION_HMAC_KEY_VERSION"
COCKPIT_OPERATOR_ACCOUNT_IDS_ENV = "KIVOU_COCKPIT_OPERATOR_ACCOUNT_IDS"
ACQUISITION_ENVIRONMENT_ENV = "KIVOU_ACQUISITION_ENVIRONMENT"

STRIPE_MODES: tuple[str, ...] = ("test", "live")
DEFAULT_STRIPE_MODE = "test"

SESSION_TTL_ENV = "KIVOU_SESSION_TTL_SECONDS"
RESET_TTL_ENV = "KIVOU_PASSWORD_RESET_TTL_SECONDS"
COOKIE_SECURE_ENV = "KIVOU_COOKIE_SECURE"
ALLOWED_ORIGIN_ENV = "KIVOU_ALLOWED_ORIGIN"

DEFAULT_SESSION_TTL = dt.timedelta(days=14)
DEFAULT_RESET_TTL = dt.timedelta(hours=1)
DEFAULT_SMTP_TIMEOUT_SECONDS = 30
DEFAULT_ALERT_LEASE_TTL = dt.timedelta(minutes=30)
# The versioned service is killed after 20 minutes. Keeping ten minutes of
# margin prevents a second host from reclaiming the database lease while the
# first process is still being terminated.
MINIMUM_ALERT_LEASE_SECONDS = 30 * 60
DEFAULT_ALERT_MAX_ATTEMPTS = 5
DEFAULT_ALERT_RETRY_BASE = dt.timedelta(minutes=15)


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
    #: §22 — l'origine des liens profonds. `None` fait échouer l'envoi en douceur :
    #: les signaux restent en file plutôt que de partir avec un lien cassé.
    #:
    #: RTL-05 — elle ne porte AUCUN chemin. Les constructeurs serveur ajoutent
    #: `/reset-password`, `/app/signals/{signal_key}` ou `/app/notifications`.
    #:
    #:     KIVOU_PUBLIC_APP_URL=https://kivou.eu
    public_app_url: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    #: Jamais journalisé, jamais rendu, jamais écrit dans le dépôt (§23, §39).
    smtp_password: str | None = dataclasses.field(default=None, repr=False)
    smtp_from_email: str | None = None
    smtp_from_name: str = "Kivou"
    #: `None` quand la configuration est incomplète : aucun mode n'est SUPPOSÉ.
    smtp_tls_mode: str | None = "starttls"
    smtp_timeout_seconds: int = DEFAULT_SMTP_TIMEOUT_SECONDS
    smtp_reply_to_email: str | None = None
    #: Code MACHINE expliquant pourquoi l'e-mail est indisponible, `None` quand
    #: il l'est. Ni valeur ni identifiant : il part dans un journal.
    smtp_unavailable_reason: str | None = None
    alert_lease_ttl: dt.timedelta = DEFAULT_ALERT_LEASE_TTL
    alert_max_attempts: int = DEFAULT_ALERT_MAX_ATTEMPTS
    alert_retry_base: dt.timedelta = DEFAULT_ALERT_RETRY_BASE

    # SPEC-026 — absent by default: the provider-specific route fails closed.
    instantly_webhook_secret: str | None = dataclasses.field(default=None, repr=False)
    instantly_webhook_workspace_ref: str | None = None
    instantly_webhook_fingerprint_key: bytes | None = dataclasses.field(
        default=None, repr=False
    )
    instantly_webhook_fingerprint_key_version: str | None = None
    suppression_identity_key: bytes | None = dataclasses.field(default=None, repr=False)
    suppression_identity_key_version: str | None = None

    # SPEC-028 — both absent by default. The secret is attribution integrity,
    # never authentication, and is excluded from dataclass repr.
    attribution_hmac_key: bytes | None = dataclasses.field(default=None, repr=False)
    attribution_hmac_key_version: str | None = None

    # SPEC-030 — empty by default, so no SaaS customer can read the internal cockpit.
    cockpit_operator_account_ids: frozenset[str] = frozenset()

    # SPEC-031 — workers never infer production. The absent default is deliberately
    # unusable as autonomous-readiness evidence.
    acquisition_environment: str = "UNCONFIGURED"

    @property
    def stripe_livemode(self) -> bool:
        return self.stripe_mode == "live"

    @property
    def instantly_webhook_configured(self) -> bool:
        """The complete local ingress boundary is available, or none of it is."""
        return all(
            value is not None
            for value in (
                self.instantly_webhook_secret,
                self.instantly_webhook_workspace_ref,
                self.instantly_webhook_fingerprint_key,
                self.instantly_webhook_fingerprint_key_version,
                self.suppression_identity_key,
                self.suppression_identity_key_version,
            )
        )

    @property
    def alerts_configured(self) -> bool:
        """Peut-on envoyer une alerte sans produire un lien cassé ?"""
        return bool(self.public_app_url and self.smtp_host and self.smtp_from_email)

    @property
    def smtp_use_tls(self) -> bool:
        """Compatibilité interne jusqu'à la migration de la passerelle SMTP."""
        return self.smtp_tls_mode == "starttls"

    @property
    def public_site_url(self) -> str | None:
        """Compatibilité de nom : la valeur est déjà l'origine du site."""
        return self.public_app_url

    @property
    def password_reset_email_configured(self) -> bool:
        """Le lien de réinitialisation peut-il partir, ET être cliquable ?

        Les mêmes trois éléments que pour une alerte, et pour la même raison :
        sans expéditeur il n'y a pas d'envoi, sans hôte SMTP il n'y a pas de
        transport, et sans base publique le lien ne mène nulle part. Une remise
        câblée sans l'un des trois enverrait un message inutilisable — ou
        n'enverrait rien en silence, ce qui est pire.
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
        allowed_origin = os.environ.get(ALLOWED_ORIGIN_ENV) or None
        mode = (os.environ.get(STRIPE_MODE_ENV) or DEFAULT_STRIPE_MODE).lower()
        if mode not in STRIPE_MODES:
            raise ValueError(f"{STRIPE_MODE_ENV} doit valoir {STRIPE_MODES}, pas {mode!r}")
        secret_key = os.environ.get(STRIPE_SECRET_KEY_ENV) or None
        _check_key_matches_mode(secret_key, mode)
        success_url = _optional_url(STRIPE_SUCCESS_URL_ENV)
        cancel_url = _optional_url(STRIPE_CANCEL_URL_ENV)
        portal_return_url = _optional_url(STRIPE_PORTAL_RETURN_URL_ENV)
        public_origin = _public_origin(PUBLIC_APP_URL_ENV, allowed_origin=allowed_origin)
        smtp = _smtp_environment(public_origin=public_origin)
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
        attribution_key_raw = os.environ.get(ATTRIBUTION_HMAC_KEY_ENV) or None
        attribution_key_version = os.environ.get(ATTRIBUTION_HMAC_KEY_VERSION_ENV) or None
        if bool(attribution_key_raw) != bool(attribution_key_version):
            raise ValueError(
                f"{ATTRIBUTION_HMAC_KEY_ENV} et {ATTRIBUTION_HMAC_KEY_VERSION_ENV} "
                "doivent être configurés ensemble"
            )
        if attribution_key_raw is not None and len(attribution_key_raw.encode()) < 16:
            raise ValueError(f"{ATTRIBUTION_HMAC_KEY_ENV} est trop courte")
        instantly = _instantly_webhook_environment()
        acquisition_environment = resolve_acquisition_environment()
        return cls(
            session_ttl=_duration(SESSION_TTL_ENV, DEFAULT_SESSION_TTL),
            password_reset_ttl=_duration(RESET_TTL_ENV, DEFAULT_RESET_TTL),
            cookie_secure=True if secure is None else secure.lower() not in {"0", "false", "no"},
            allowed_origin=allowed_origin,
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
            public_app_url=public_origin,
            smtp_host=smtp["host"],
            smtp_port=smtp["port"],
            smtp_username=smtp["username"],
            smtp_password=smtp["password"],
            smtp_from_email=smtp["from_email"],
            smtp_from_name=smtp["from_name"],
            smtp_tls_mode=smtp["tls_mode"],
            smtp_timeout_seconds=smtp["timeout_seconds"],
            smtp_reply_to_email=smtp["reply_to_email"],
            smtp_unavailable_reason=smtp.get("unavailable_reason"),
            alert_lease_ttl=dt.timedelta(
                seconds=_bounded_integer(
                    ALERT_LEASE_SECONDS_ENV,
                    default=int(DEFAULT_ALERT_LEASE_TTL.total_seconds()),
                    minimum=MINIMUM_ALERT_LEASE_SECONDS,
                    maximum=3600,
                )
            ),
            alert_max_attempts=_bounded_integer(
                ALERT_MAX_ATTEMPTS_ENV,
                default=DEFAULT_ALERT_MAX_ATTEMPTS,
                minimum=1,
                maximum=10,
            ),
            alert_retry_base=dt.timedelta(
                seconds=_bounded_integer(
                    ALERT_RETRY_BASE_SECONDS_ENV,
                    default=int(DEFAULT_ALERT_RETRY_BASE.total_seconds()),
                    minimum=60,
                    maximum=86400,
                )
            ),
            instantly_webhook_secret=instantly[0],
            instantly_webhook_workspace_ref=instantly[1],
            instantly_webhook_fingerprint_key=instantly[2],
            instantly_webhook_fingerprint_key_version=instantly[3],
            suppression_identity_key=instantly[4],
            suppression_identity_key_version=instantly[5],
            attribution_hmac_key=(
                attribution_key_raw.encode("utf-8") if attribution_key_raw else None
            ),
            attribution_hmac_key_version=attribution_key_version,
            cockpit_operator_account_ids=_account_ref_allowlist(
                COCKPIT_OPERATOR_ACCOUNT_IDS_ENV
            ),
            acquisition_environment=acquisition_environment,
        )


def _instantly_webhook_environment() -> tuple[
    str | None,
    str | None,
    bytes | None,
    str | None,
    bytes | None,
    str | None,
]:
    """Read one atomic ingress group without ever rendering supplied values."""
    names = (
        INSTANTLY_WEBHOOK_SECRET_ENV,
        INSTANTLY_WEBHOOK_WORKSPACE_ENV,
        INSTANTLY_WEBHOOK_FINGERPRINT_KEY_ENV,
        INSTANTLY_WEBHOOK_FINGERPRINT_KEY_VERSION_ENV,
        SUPPRESSION_IDENTITY_KEY_ENV,
        SUPPRESSION_IDENTITY_KEY_VERSION_ENV,
    )
    values = tuple(os.environ.get(name) or None for name in names)
    if not any(values):
        return (None, None, None, None, None, None)
    missing = [name for name, value in zip(names, values, strict=True) if value is None]
    if missing:
        raise ValueError(
            "configuration webhook Instantly incomplète : "
            f"{', '.join(missing)} doivent être définies avec le groupe complet"
        )

    secret, workspace, fingerprint_key, fingerprint_version, suppression_key, suppression_version = (
        value for value in values if value is not None
    )
    for name, value in (
        (INSTANTLY_WEBHOOK_SECRET_ENV, secret),
        (INSTANTLY_WEBHOOK_FINGERPRINT_KEY_ENV, fingerprint_key),
        (SUPPRESSION_IDENTITY_KEY_ENV, suppression_key),
    ):
        if len(value.encode("utf-8")) < 16:
            raise ValueError(f"{name} doit contenir au moins 16 octets")
    for name, value, maximum in (
        (INSTANTLY_WEBHOOK_WORKSPACE_ENV, workspace, 128),
        (INSTANTLY_WEBHOOK_FINGERPRINT_KEY_VERSION_ENV, fingerprint_version, 64),
        (SUPPRESSION_IDENTITY_KEY_VERSION_ENV, suppression_version, 64),
    ):
        if value != value.strip():
            raise ValueError(f"{name} ne doit pas contenir d'espaces périphériques")
        if len(value) > maximum:
            raise ValueError(f"{name} dépasse la longueur maximale autorisée")
    return (
        secret,
        workspace,
        fingerprint_key.encode("utf-8"),
        fingerprint_version,
        suppression_key.encode("utf-8"),
        suppression_version,
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


def _public_origin(name: str, *, allowed_origin: str | None) -> str | None:
    """La racine publique du site — origine nue, sans chemin.

    Les constructeurs de liens ajoutent eux-mêmes ce qu'il faut, et les routes
    sont ASYMÉTRIQUES : `/reset-password` vit à la racine, `/app/signals/…` et
    `/app/notifications` sous `/app`. Accepter ici un préfixe `/app` produirait
    donc `…/app/reset-password` — un lien de réinitialisation mort — et
    `…/app/app/signals/…`. Un client ne pourrait plus changer son mot de passe,
    et rien dans les tests ne le dirait.

    `KIVOU_ALLOWED_ORIGIN` est FACULTATIVE : un déploiement même origine n'a pas
    à la déclarer. Quand elle existe, l'accord est strict, et `*` est refusé —
    il reviendrait à laisser n'importe quelle origine se faire passer pour
    l'application.
    """
    value = os.environ.get(name)
    if not value:
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError(
            f"{name} doit être la racine publique en https, sans chemin, "
            "sans identifiants, sans paramètre ni fragment"
        )
    normalized = f"https://{parsed.netloc}"
    if allowed_origin is not None:
        declared = allowed_origin.rstrip("/")
        if declared == "*":
            raise ValueError("KIVOU_ALLOWED_ORIGIN ne peut pas valoir '*'")
        if normalized != declared:
            raise ValueError(f"{name} doit correspondre à l'origine autorisée")
    return normalized


def _bounded_integer(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} doit être un entier") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} doit être compris entre {minimum} et {maximum}")
    return value


def _email_address(name: str) -> str | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    from pydantic import TypeAdapter, ValidationError
    from pydantic.networks import EmailStr

    try:
        return str(TypeAdapter(EmailStr).validate_python(raw))
    except ValidationError as error:
        raise ValueError(f"{name} doit être une adresse e-mail valide") from error


def _smtp_environment(*, public_origin: str | None) -> dict[str, object]:
    names = (
        SMTP_HOST_ENV,
        SMTP_PORT_ENV,
        SMTP_USERNAME_ENV,
        SMTP_PASSWORD_ENV,
        SMTP_FROM_EMAIL_ENV,
        SMTP_FROM_NAME_ENV,
        SMTP_TLS_MODE_ENV,
        SMTP_TIMEOUT_ENV,
        SMTP_REPLY_TO_ENV,
    )
    configured = any(name in os.environ for name in names)
    if not configured:
        return {
            "host": None,
            "port": 587,
            "username": None,
            "password": None,
            "from_email": None,
            "from_name": "Kivou",
            "tls_mode": "starttls",
            "timeout_seconds": DEFAULT_SMTP_TIMEOUT_SECONDS,
            "reply_to_email": None,
        }

    host = (os.environ.get(SMTP_HOST_ENV) or "").strip() or None
    from_email_raw = os.environ.get(SMTP_FROM_EMAIL_ENV) or None
    tls_mode = (os.environ.get(SMTP_TLS_MODE_ENV) or "").strip().lower() or None
    missing = [
        name
        for name, value in (
            (PUBLIC_APP_URL_ENV, public_origin),
            (SMTP_HOST_ENV, host),
            (SMTP_FROM_EMAIL_ENV, from_email_raw),
            (SMTP_TLS_MODE_ENV, tls_mode),
        )
        if value is None
    ]
    if missing:
        # Une configuration SMTP incomplète rend l'E-MAIL indisponible, jamais
        # l'API. Lever ici empêchait le démarrage de tout le service — feed,
        # facturation, authentification comprises — pour un transport
        # accessoire, et transformait une variable oubliée en panne totale.
        #
        # Le motif est un code MACHINE nommant les variables absentes : ni
        # valeur, ni identifiant, puisqu'il partira dans un journal.
        return {
            "host": None,
            "port": 587,
            "username": None,
            "password": None,
            "from_email": None,
            "from_name": "Kivou",
            # Pas de repli sur STARTTLS : supposer un mode de chiffrement que
            # l'exploitant n'a pas déclaré reviendrait à choisir sa sécurité à
            # sa place. `host` étant `None`, aucun envoi n'aura lieu.
            "tls_mode": None,
            "timeout_seconds": DEFAULT_SMTP_TIMEOUT_SECONDS,
            "reply_to_email": None,
            "unavailable_reason": "smtp_configuration_incomplete:" + ",".join(sorted(missing)),
        }

    username = os.environ.get(SMTP_USERNAME_ENV) or None
    password = os.environ.get(SMTP_PASSWORD_ENV) or None
    if bool(username) != bool(password):
        raise ValueError(
            f"{SMTP_USERNAME_ENV} et {SMTP_PASSWORD_ENV} doivent être configurés ensemble"
        )
    if tls_mode not in {"starttls", "implicit_tls"}:
        raise ValueError(f"{SMTP_TLS_MODE_ENV} doit valoir starttls ou implicit_tls")

    return {
        "host": host,
        "port": _bounded_integer(SMTP_PORT_ENV, default=587, minimum=1, maximum=65535),
        "username": username,
        "password": password,
        "from_email": _email_address(SMTP_FROM_EMAIL_ENV),
        "from_name": os.environ.get(SMTP_FROM_NAME_ENV) or "Kivou",
        "tls_mode": tls_mode,
        "timeout_seconds": _bounded_integer(
            SMTP_TIMEOUT_ENV,
            default=DEFAULT_SMTP_TIMEOUT_SECONDS,
            minimum=1,
            maximum=60,
        ),
        "reply_to_email": _email_address(SMTP_REPLY_TO_ENV),
    }


def resolve_acquisition_environment() -> str:
    """Return only an explicit deployment identity; never infer production."""
    value = (os.environ.get(ACQUISITION_ENVIRONMENT_ENV) or "UNCONFIGURED").upper()
    if value not in {"UNCONFIGURED", "STAGING", "PRODUCTION"}:
        raise ValueError(
            f"{ACQUISITION_ENVIRONMENT_ENV} doit valoir UNCONFIGURED, STAGING ou PRODUCTION"
        )
    return value


def _flag(name: str) -> bool:
    """Un drapeau d'environnement. Absent vaut faux : aucun défaut permissif."""
    raw = os.environ.get(name)
    return bool(raw) and raw.lower() in {"1", "true", "yes"}


def _account_ref_allowlist(name: str) -> frozenset[str]:
    raw = os.environ.get(name) or ""
    values = tuple(value.strip() for value in raw.split(",") if value.strip())
    if len(values) > 100:
        raise ValueError(f"{name} contient trop de comptes")
    invalid = next(
        (value for value in values if re.fullmatch(r"[A-Za-z0-9:_-]{1,64}", value) is None),
        None,
    )
    if invalid is not None:
        raise ValueError(f"{name} contient une référence de compte invalide")
    return frozenset(values)


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
