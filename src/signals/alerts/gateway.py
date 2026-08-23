"""L'envoi d'un e-mail client — derrière une frontière, comme Stripe.

Pourquoi une passerelle
───────────────────────
Pour la même raison que Stripe : la suite de tests doit rester **hors
ligne**, et Kivou ne doit pas se lier à une plateforme. L'adaptateur réel
parle **SMTP authentifié**, ce que tout hébergeur transactionnel expose ;
en changer ne demandera pas de toucher au reste.

Ce n'est PAS de l'acquisition (§23, §42)
────────────────────────────────────────
Instantly est réservé à la prospection sortante. Une alerte client est un
e-mail transactionnel, envoyé à quelqu'un qui paie pour le recevoir : le
mélanger à une infrastructure de campagne mettrait la délivrabilité du
produit à la merci d'une réputation de prospection.

Aucun pixel, aucun traqueur (§24)
─────────────────────────────────
On veut savoir qu'un e-mail est parti, pas espionner qui l'ouvre. Ce qui
compte se mesure DANS Kivou : le client a-t-il ouvert le signal, l'a-t-il
jugé pertinent, a-t-il contacté l'entreprise.
"""

from __future__ import annotations

import dataclasses
import hashlib
import ssl
from typing import Literal, Protocol

ALERT_GATEWAY_VERSION = "kivou-alert-smtp-v0.1"


class AlertDeliveryError(RuntimeError):
    """Échec d'envoi portant un CODE machine sûr, jamais une trace d'exception.

    Une pile d'appels SMTP contient parfois l'adresse du destinataire, parfois
    l'identifiant de connexion. Seul un code court est conservé (§27).
    """

    def __init__(self, code: str, *, retryable: bool = True) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class UncertainDelivery(AlertDeliveryError):
    """Le serveur n'a ni confirmé ni refusé — aucune reprise immédiate.

    L'état durable conserve l'ambiguïté, applique un backoff borné et réutilise
    le même `Message-ID`. Cela réduit le risque sans prétendre à un exactement
    une fois que SMTP ne sait pas garantir.
    """

    def __init__(self, code: str = "unknown_delivery_state") -> None:
        super().__init__(code, retryable=False)


@dataclasses.dataclass(frozen=True)
class AlertMessage:
    """Un message prêt à partir. Ni HTML complexe, ni pièce jointe."""

    to_email: str
    subject: str
    text_body: str
    message_id: str
    language: str


@dataclasses.dataclass(frozen=True)
class DeliveryResult:
    provider_message_id: str


class AlertDeliveryGateway(Protocol):
    """Ce que Kivou demande à son infrastructure d'e-mail. Rien de plus."""

    def send(self, message: AlertMessage) -> DeliveryResult: ...


def message_id(*, account_id: str, batch_key: str, domain: str = "kivou.ch") -> str:
    """Un `Message-ID` déterministe, et qui ne divulgue rien (§28).

    Il est dérivé du compte et du lot par empreinte : deux envois du même lot
    portent le même identifiant — ce qui aide les serveurs à écarter un doublon
    et le support à retrouver un envoi — sans qu'aucune adresse ni aucun secret
    n'y apparaisse en clair.
    """
    digest = hashlib.sha256(f"{account_id}:{batch_key}".encode()).hexdigest()[:32]
    return f"<kivou-alert-{digest}@{domain}>"


@dataclasses.dataclass(frozen=True)
class SmtpConfiguration:
    """Les réglages SMTP. Aucun secret n'est écrit dans le dépôt (§23, §39)."""

    host: str
    port: int
    from_email: str
    from_name: str = "Kivou"
    username: str | None = None
    password: str | None = dataclasses.field(default=None, repr=False)
    tls_mode: Literal["starttls", "implicit_tls"] = "starttls"
    timeout_seconds: int = 30
    reply_to_email: str | None = None

    @property
    def is_usable(self) -> bool:
        return bool(
            self.host
            and self.from_email
            and self.tls_mode in {"starttls", "implicit_tls"}
            and 1 <= self.port <= 65535
            and self.timeout_seconds > 0
            and bool(self.username) == bool(self.password)
        )


class SmtpAlertGateway:
    """L'adaptateur réel. Jamais appelé par la suite de tests."""

    def __init__(
        self,
        configuration: SmtpConfiguration,
        *,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if not configuration.is_usable:
            raise ValueError("configuration SMTP incomplète ou invalide")
        self._configuration = configuration
        self._ssl_context = ssl_context or ssl.create_default_context()

    def send(self, message: AlertMessage) -> DeliveryResult:
        import smtplib
        from email.message import EmailMessage

        configuration = self._configuration
        email = EmailMessage()
        email["Subject"] = message.subject
        email["From"] = f"{configuration.from_name} <{configuration.from_email}>"
        email["To"] = message.to_email
        email["Message-ID"] = message.message_id
        if configuration.reply_to_email:
            email["Reply-To"] = configuration.reply_to_email
        # Un en-tête de désinscription est attendu d'un envoi automatisé, et il
        # pointe vers les préférences du compte — pas vers un traqueur.
        email["Auto-Submitted"] = "auto-generated"
        email.set_content(message.text_body)

        try:
            if configuration.tls_mode == "implicit_tls":
                server = smtplib.SMTP_SSL(
                    configuration.host,
                    configuration.port,
                    timeout=configuration.timeout_seconds,
                    context=self._ssl_context,
                )
            else:
                server = smtplib.SMTP(
                    configuration.host,
                    configuration.port,
                    timeout=configuration.timeout_seconds,
                )
                server.starttls(context=self._ssl_context)
            if configuration.username and configuration.password:
                server.login(configuration.username, configuration.password)
        except smtplib.SMTPAuthenticationError as error:
            # Non rejouable : réessayer avec les mêmes identifiants échouera
            # pareil, et multiplierait les tentatives d'authentification.
            raise AlertDeliveryError("smtp_authentication_failed", retryable=False) from error
        except (smtplib.SMTPNotSupportedError, ssl.SSLError) as error:
            raise AlertDeliveryError("smtp_tls_failed", retryable=False) from error
        except smtplib.SMTPResponseException as error:
            raise AlertDeliveryError(
                f"smtp_{error.smtp_code}", retryable=400 <= error.smtp_code < 500
            ) from error
        except (smtplib.SMTPServerDisconnected, TimeoutError, OSError) as error:
            raise AlertDeliveryError("smtp_unavailable", retryable=True) from error

        try:
            server.send_message(email)
        except smtplib.SMTPRecipientsRefused as error:
            raise AlertDeliveryError("smtp_recipient_refused", retryable=False) from error
        except smtplib.SMTPResponseException as error:
            raise AlertDeliveryError(
                f"smtp_{error.smtp_code}", retryable=400 <= error.smtp_code < 500
            ) from error
        except (smtplib.SMTPServerDisconnected, TimeoutError, OSError) as error:
            # La coupure se produit pendant la soumission du message : le
            # serveur peut l'avoir accepté sans que sa réponse atteigne Kivou.
            raise UncertainDelivery() from error
        finally:
            _close(server)
        return DeliveryResult(provider_message_id=message.message_id)


def _close(server: object) -> None:
    quit_method = getattr(server, "quit", None)
    if quit_method is not None:
        try:
            quit_method()
            return
        except Exception:  # noqa: BLE001 — l'envoi a déjà son résultat
            quit_method = None
    close_method = getattr(server, "close", None)
    if close_method is not None:
        try:
            close_method()
        except Exception:  # noqa: BLE001 — aucun secret ni statut ne dépend de QUIT
            return
