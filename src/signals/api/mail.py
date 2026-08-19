"""Le transport SMTP, construit UNE fois à partir de la configuration.

Pourquoi ce module minuscule existe
───────────────────────────────────
Deux programmes envoient des e-mails : le cycle d'alerte (`python -m
signals.alerts`) et l'application HTTP (le lien de réinitialisation). Tous deux
lisent les mêmes sept variables et les recopient dans le même objet. Écrit deux
fois, ce mapping finit par diverger — typiquement quand un réglage s'ajoute et
n'est câblé que d'un côté ; le symptôme est alors qu'un type d'e-mail part et
l'autre non, sans rien dans les journaux.

Il ne construit PAS de politique : il ne décide ni s'il faut envoyer, ni à qui,
ni quoi. Il rend le tuyau.
"""

from __future__ import annotations

from signals.alerts.gateway import SmtpAlertGateway, SmtpConfiguration
from signals.api.config import ApiConfig


def smtp_transport(config: ApiConfig) -> SmtpAlertGateway:
    """Le client SMTP authentifié décrit par l'environnement.

    Lève si l'hôte ou l'expéditeur manquent — appeler cette fabrique suppose
    d'avoir déjà vérifié `alerts_configured` ou
    `password_reset_email_configured`. Mieux vaut refuser de construire un
    transport inutilisable que d'en rendre un qui échouera au premier envoi.
    """
    return SmtpAlertGateway(
        SmtpConfiguration(
            host=config.smtp_host or "",
            port=config.smtp_port,
            username=config.smtp_username,
            password=config.smtp_password,
            from_email=config.smtp_from_email or "",
            from_name=config.smtp_from_name,
            use_tls=config.smtp_use_tls,
        )
    )
