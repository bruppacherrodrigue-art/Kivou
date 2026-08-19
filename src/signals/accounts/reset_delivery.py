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
produit un code court, rien d'autre. Et surtout, `deliver()` **ne lève jamais**
— voir la note sur l'énumération de comptes plus bas.
"""

from __future__ import annotations

import datetime as dt
import logging
from email.utils import make_msgid
from urllib.parse import quote, urlsplit

from signals.alerts.gateway import (
    AlertDeliveryError,
    AlertDeliveryGateway,
    AlertMessage,
)

LOGGER = logging.getLogger("signals.accounts.reset_delivery")

RESET_COPY_VERSION = "kivou-reset-copy-v0.1"

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

DURATION: dict[str, str] = {"fr": "{count} heure(s)", "en": "{count} hour(s)"}
MINUTES: dict[str, str] = {"fr": "{count} minute(s)", "en": "{count} minute(s)"}


def _language(locale: str) -> str:
    """La langue du compte, repliée sur le français comme partout ailleurs."""
    return "en" if str(locale).lower().startswith("en") else "fr"


def _duration(ttl: dt.timedelta, language: str) -> str:
    minutes = max(1, int(ttl.total_seconds() // 60))
    if minutes % 60 == 0:
        return DURATION[language].format(count=minutes // 60)
    return MINUTES[language].format(count=minutes)


def reset_link(site_url: str, reset_token: str) -> str:
    """L'URL exacte que sert le frontend.

    Le contrat vient du routeur client — `<Route path="reset-password">` à la RACINE
    du site, et `useSearchParams().get('token')`. Ce n'est donc PAS
    `public_app_url`, qui pointe sur `/app` : un lien construit à partir de la
    base des alertes tomberait sur une page inexistante.

    Le jeton est encodé : il est produit par `secrets`, donc sûr en URL, mais
    laisser passer une valeur brute dans une chaîne de requête est le genre de
    raccourci qui casse le jour où la génération change.
    """
    return f"{site_url.rstrip('/')}/reset-password?token={quote(reset_token, safe='')}"


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


def _domain(site_url: str) -> str:
    return urlsplit(site_url).hostname or "kivou.eu"


class SmtpPasswordResetDelivery:
    """L'adaptateur de production, branché dans `asgi.py`.

    `deliver()` n'échoue jamais bruyamment, et c'est une décision de sécurité,
    pas une négligence
    ──────────────────────────────────────────────────────────────────────────
    `request_password_reset()` n'appelle cette remise QUE si le compte existe.
    Si une panne SMTP remontait, la route rendrait 500 pour une adresse connue
    et 202 pour une adresse inconnue : la page de demande deviendrait un
    oracle d'existence de compte, exactement ce que la réponse générique
    cherche à empêcher. L'échec est donc journalisé par un code et absorbé.

    Il y a un second effet, tout aussi voulu : la remise a lieu dans la
    transaction qui vient d'insérer le jeton. Laisser remonter l'exception
    annulerait cette insertion — et une personne dont le message est malgré
    tout parti recevrait un lien déjà mort.
    """

    def __init__(self, gateway: AlertDeliveryGateway, *, site_url: str, ttl: dt.timedelta) -> None:
        if not site_url:
            raise ValueError("URL publique requise pour construire un lien de réinitialisation")
        self._gateway = gateway
        self._site_url = site_url
        self._ttl = ttl

    def deliver(self, *, email: str, locale: str, reset_token: str) -> None:
        try:
            message = build_reset_message(
                email=email,
                locale=locale,
                reset_token=reset_token,
                site_url=self._site_url,
                ttl=self._ttl,
            )
            self._gateway.send(message)
        except AlertDeliveryError as error:
            # Un code, jamais une trace : une pile SMTP contient l'adresse du
            # destinataire et parfois l'identifiant de connexion.
            LOGGER.warning("remise du lien de réinitialisation échouée (code=%s)", error.code)
        # BLE001 assumé : voir la note de classe. Aucune panne de remise ne doit
        # pouvoir transformer la réponse générique en signal d'existence.
        except Exception:  # noqa: BLE001
            LOGGER.warning("remise du lien de réinitialisation échouée (code=%s)", "unexpected")
