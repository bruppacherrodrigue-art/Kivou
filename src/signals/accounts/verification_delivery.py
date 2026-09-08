"""Security email using the existing SMTP transport, without tracking or secrets in logs."""
from email.utils import make_msgid
from urllib.parse import urlsplit

from signals.alerts.gateway import AlertMessage


def build_verification_message(*, email: str, token: str, origin: str) -> AlertMessage:
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
        raise ValueError("verification requires a public HTTPS origin")
    # Fragment is not sent in HTTP requests or written into access logs.
    link = f"{origin.rstrip('/')}/verify-email#{token}"
    return AlertMessage(
        to_email=email,
        subject="Vérifiez votre adresse e-mail Kivou",
        text_body=(
            "Bonjour,\n\nPour confirmer votre adresse e-mail Kivou, ouvrez ce lien puis "
            "cliquez sur le bouton de vérification :\n\n"
            f"{link}\n\n"
            "Ce lien est valable 24 heures et ne fonctionne qu'une seule fois.\n"
            "Les alertes ne sont envoyées qu'après vérification de votre adresse.\n\n"
            "Si vous n'avez pas demandé cette vérification, ignorez ce message.\n"
        ),
        message_id=make_msgid(idstring="kivou-email-verification", domain=parsed.hostname),
        language="fr",
    )
