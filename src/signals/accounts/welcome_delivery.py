"""Welcome mail sent once when a prospect turns a temporary link into an account."""

from __future__ import annotations

from email.utils import make_msgid
from typing import Protocol
from urllib.parse import quote, urlsplit

from signals.alerts.gateway import AlertDeliveryError, AlertDeliveryGateway, AlertMessage
from signals.runtime_events import emit_delivery_event


class WelcomeDelivery(Protocol):
    def deliver(
        self,
        *,
        email: str,
        locale: str,
        signal_key: str | None,
        signal_holder: str,
        signal_subject: str,
        signal_location: str,
        unsubscribe_url: str,
    ) -> None: ...


def build_welcome_message(
    *,
    email: str,
    locale: str,
    signal_key: str | None,
    signal_holder: str,
    signal_subject: str,
    signal_location: str,
    unsubscribe_url: str,
    site_url: str,
    message_id: str | None = None,
) -> AlertMessage:
    language = "en" if str(locale).lower().startswith("en") else "fr"
    login = f"{site_url}/login"
    signal = (
        f"{site_url}/app/signals/{quote(signal_key, safe='')}"
        if signal_key
        else f"{site_url}/app/signals"
    )
    reminder = " · ".join(
        value.strip()
        for value in (signal_holder, signal_subject, signal_location)
        if value and value.strip()
    )
    if language == "fr":
        subject = "Bienvenue sur Kivou — votre accès est créé"
        body = (
            "Bonjour,\n\n"
            "Votre accès Kivou est créé. Vous pouvez désormais retrouver vos signaux "
            f"à tout moment :\n{login}\n\n"
            f"Votre premier signal\n{reminder}\n{signal}\n\n"
            "Vous ne souhaitez plus recevoir ces messages :\n"
            f"{unsubscribe_url}\n"
        )
    else:
        subject = "Welcome to Kivou — your access is ready"
        body = (
            "Hello,\n\n"
            "Your Kivou access is ready. You can return to your signals at any time:\n"
            f"{login}\n\n"
            f"Your first signal\n{reminder}\n{signal}\n\n"
            "Stop receiving these messages:\n"
            f"{unsubscribe_url}\n"
        )
    domain = urlsplit(site_url).hostname or "kivou.eu"
    return AlertMessage(
        to_email=email,
        subject=subject,
        text_body=body,
        message_id=message_id or make_msgid(idstring="kivou-welcome", domain=domain),
        language=language,
        preferences_url=unsubscribe_url,
    )


class DeferredWelcomeDelivery:
    """Keep SMTP outside the account-claiming transaction and response time."""

    def __init__(self, inner: WelcomeDelivery) -> None:
        self._inner = inner
        self._pending: list[dict[str, str | None]] = []

    def deliver(self, **values: str | None) -> None:
        self._pending.append(values)

    def flush(self) -> None:
        pending, self._pending = self._pending, []
        for values in pending:
            self._inner.deliver(**values)  # type: ignore[arg-type]


class SmtpWelcomeDelivery:
    def __init__(self, gateway: AlertDeliveryGateway, *, site_url: str) -> None:
        self._gateway = gateway
        self._site_url = site_url.rstrip("/")

    def deliver(self, **values: str | None) -> None:
        message = build_welcome_message(site_url=self._site_url, **values)  # type: ignore[arg-type]
        try:
            self._gateway.send(message)
        except AlertDeliveryError as error:
            emit_delivery_event(
                channel="account_welcome",
                status="failed",
                code=error.code,
                retryable=error.retryable,
                attempt=1,
            )
        except Exception:  # noqa: BLE001 — never expose SMTP/recipient details to the route
            emit_delivery_event(
                channel="account_welcome",
                status="failed",
                code="unexpected_error",
                retryable=False,
                attempt=1,
            )
        else:
            emit_delivery_event(
                channel="account_welcome",
                status="submitted",
                code="smtp_submission_accepted",
                retryable=False,
                attempt=1,
            )
