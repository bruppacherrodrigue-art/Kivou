"""La remise du lien de réinitialisation — le seul e-mail que l'authentification envoie.

Pourquoi ce module est séparé des alertes
─────────────────────────────────────────
Une alerte est un e-mail COMMERCIAL transactionnel : elle annonce des
opportunités, cite un acheteur, renvoie vers un signal, et porte un pied de page
de désinscription. Une réinitialisation est un e-mail de SÉCURITÉ : elle ne
contient qu'un lien à usage unique, ne se désinscrit pas, et ne doit jamais
hériter du vocabulaire produit. Les mélanger dans un même gabarit ferait qu'un
changement de formulation marketing modifierait un e-mail de sécurité.

Ce qui EST réutilisé
────────────────────
Le transport. `SmtpAlertGateway` n'a d'« alerte » que le nom : c'est un client
SMTP authentifié — STARTTLS, connexion, envoi, et une taxinomie d'erreurs qui
distingue déjà le rejouable de l'irrécupérable. En écrire un second exposerait
Kivou à corriger deux fois le même défaut de délai d'attente ou de TLS.

Ce qui ne sort jamais d'ici (§11, §27)
──────────────────────────────────────
Le jeton n'est écrit dans AUCUN journal. L'adresse non plus : un échec d'envoi
produit un code court, rien d'autre. Et surtout, `deliver()` **ne lève jamais** —
voir la note sur l'énumération de comptes plus bas.
"""

from __future__ import annotations

import datetime as dt
import logging
from email.utils import make_msgid
from typing import Protocol
from urllib.parse import urlsplit

from signals.alerts.gateway import AlertDeliveryError, AlertDeliveryGateway, AlertMessage
from signals.transactional_email.links import reset_url as reset_link

LOGGER = logging.getLogger("signals.accounts.reset_delivery")

RESET_COPY_VERSION = "kivou-reset-copy-v0.1"


class PasswordResetDelivery(Protocol):
    """Ce que la route attend d'une remise. Rien de plus."""

    def deliver(self, *, email: str, locale: str, reset_token: str) -> None: ...


SUBJECT: dict[str, str] = {
    "fr": "Réinitialisation de votre mot de passe Kivou",
    "en": "Reset your Kivou password",
}

BODY: dict[str, str] = {
    "fr": (
        "Bonjour,\n\n"
        "Une réinitialisation de mot de passe a été demandée pour ce compte Kivou.\n"
        "Pour choisir un nouveau mot de passe, ouvrez ce lien :\n\n"
        "{link}\n\n"
        "Ce lien est valable {duration} et ne fonctionne qu'une seule fois.\n"
        "Une fois le mot de passe changé, toutes les sessions ouvertes sont fermées.\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message : "
        "votre mot de passe actuel reste valable et rien n'a été modifié.\n"
    ),
    "en": (
        "Hello,\n\n"
        "A password reset was requested for this Kivou account.\n"
        "To choose a new password, open this link:\n\n"
        "{link}\n\n"
        "The link is valid for {duration} and works only once.\n"
        "Once the password is changed, every open session is closed.\n\n"
        "If you did not request this, ignore this message: your current password "
        "still works and nothing has changed.\n"
    ),
}

HOURS: dict[str, str] = {"fr": "{count} heure(s)", "en": "{count} hour(s)"}
MINUTES: dict[str, str] = {"fr": "{count} minute(s)", "en": "{count} minute(s)"}


def _language(locale: str) -> str:
    """La langue du compte, repliée sur le français comme partout ailleurs."""
    return "en" if str(locale).lower().startswith("en") else "fr"


def _duration(ttl: dt.timedelta, language: str) -> str:
    minutes = max(1, int(ttl.total_seconds() // 60))
    if minutes % 60 == 0:
        return HOURS[language].format(count=minutes // 60)
    return MINUTES[language].format(count=minutes)


def _domain(site_url: str) -> str:
    return urlsplit(site_url).hostname or "kivou.eu"


def build_reset_message(
    *,
    email: str,
    locale: str,
    reset_token: str,
    site_url: str,
    ttl: dt.timedelta,
    message_id: str | None = None,
) -> AlertMessage:
    """Le message, en texte simple. Ni HTML, ni image, ni traqueur (§24)."""
    language = _language(locale)
    body = BODY[language].format(
        link=reset_link(site_url, reset_token), duration=_duration(ttl, language)
    )
    return AlertMessage(
        to_email=email,
        subject=SUBJECT[language],
        text_body=body,
        # Identifiant ALÉATOIRE, et c'est délibéré : les alertes utilisent un
        # `Message-ID` déterministe pour que deux envois du même lot soient
        # dédupliqués. Ici ce serait un défaut — deux demandes successives
        # porteraient le même identifiant, et le second e-mail, celui qui porte
        # le jeton encore valable, serait écarté comme doublon.
        # Il ne dérive JAMAIS du jeton, même par empreinte.
        message_id=message_id or make_msgid(idstring="kivou-reset", domain=_domain(site_url)),
        language=language,
    )


class DeferredDelivery:
    """Retient la remise, pour qu'elle ait lieu APRÈS la réponse HTTP.

    Le canal temporel que ceci referme
    ──────────────────────────────────
    Mesuré sur staging le 19 août 2026 : une demande pour une adresse CONNUE
    répondait en 2178 ms, une adresse INCONNUE en 98 ms. Les deux rendaient bien
    202 avec le même corps — mais la DURÉE trahissait l'existence du compte, et
    une poignée de requêtes suffisait à énumérer les clients de Kivou. Une
    réponse générique ne suffit donc pas : il faut aussi un temps générique.

    L'écart vient de l'aller-retour SMTP, qui n'a lieu que s'il y a un jeton à
    envoyer. En sortant cette remise du temps de réponse, les deux chemins
    redeviennent aussi rapides l'un que l'autre.

    Pourquoi une enveloppe plutôt qu'un test dans la route
    ─────────────────────────────────────────────────────
    Parce que la route ne doit RIEN apprendre. Si elle demandait « y a-t-il un
    e-mail à envoyer ? » pour décider de programmer une tâche, elle connaîtrait
    l'existence du compte — et la prochaine personne qui touche à ce code
    pourrait en dériver une branche observable. Ici la route programme
    `flush()` **inconditionnellement** : vider zéro remise coûte le même prix
    que d'en vider une.

    Effet secondaire souhaitable : la remise quitte la transaction qui insère le
    jeton. Le jeton est donc validé avant l'envoi, et non l'inverse.
    """

    def __init__(self, inner: PasswordResetDelivery) -> None:
        self._inner = inner
        self._pending: list[dict[str, str]] = []

    def deliver(self, *, email: str, locale: str, reset_token: str) -> None:
        self._pending.append({"email": email, "locale": locale, "reset_token": reset_token})

    def flush(self) -> None:
        """Exécute les remises retenues. Appelée après la réponse, jamais avant.

        La liste est vidée AVANT l'envoi : une seconde vidange ne rejoue rien,
        et un envoi qui lèverait ne laisserait pas la remise en attente
        indéfiniment.
        """
        pending, self._pending = self._pending, []
        for arguments in pending:
            self._inner.deliver(**arguments)


class SmtpPasswordResetDelivery:
    """L'adaptateur de production, branché dans `asgi.py`.

    `deliver()` n'échoue jamais bruyamment, et c'est une décision de sécurité,
    pas une négligence
    ──────────────────────────────────────────────────────────────────────────
    Une exception qui remonterait jusqu'à la route ferait répondre 500 pour une
    adresse connue et 202 pour une inconnue : exactement l'énumération de
    comptes que la réponse générique de §11 sert à empêcher. L'échec est donc
    journalisé sous forme de CODE — jamais l'adresse, jamais le jeton — et la
    demande reste acceptée. Le jeton expirera sans être utilisé, ce qui est
    l'issue sûre.
    """

    def __init__(
        self, gateway: AlertDeliveryGateway, *, site_url: str, ttl: dt.timedelta
    ) -> None:
        self._gateway = gateway
        self._site_url = site_url
        self._ttl = ttl

    def deliver(self, *, email: str, locale: str, reset_token: str) -> None:
        message = build_reset_message(
            email=email,
            locale=locale,
            reset_token=reset_token,
            site_url=self._site_url,
            ttl=self._ttl,
        )
        try:
            self._gateway.send(message)
        except AlertDeliveryError as error:
            LOGGER.warning("remise du lien de réinitialisation échouée : %s", error.code)
        except Exception:  # noqa: BLE001 — voir la note de classe
            LOGGER.warning("remise du lien de réinitialisation échouée : unexpected_error")
