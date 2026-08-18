"""Le point d'entrée du cycle d'alerte — appelable par `cron` ou `systemd`.

    python -m signals.alerts

Rien de plus : pas d'agent, pas de démon, pas de planificateur. Le programme
lit sa configuration dans l'environnement, exécute un cycle, imprime un résumé
et rend un code de sortie. Un minuteur système fait le reste.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from signals.alerts.gateway import SmtpAlertGateway, SmtpConfiguration
from signals.alerts.job import CycleReport, run_alert_cycle
from signals.api.config import ApiConfig
from signals.persistence.database import create_database_engine


def _gateway(config: ApiConfig) -> SmtpAlertGateway:
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


def summarize(report: CycleReport) -> str:
    """Un résumé lisible dans un journal de cron. Aucune adresse, aucun secret."""
    by_result: dict[str, int] = {}
    for outcome in report.outcomes:
        by_result[outcome.result] = by_result.get(outcome.result, 0) + 1
    parts = ", ".join(f"{name}={count}" for name, count in sorted(by_result.items()))
    return (
        f"comptes examinés={report.accounts_considered} · signaux envoyés="
        f"{report.signals_sent} · {parts or 'aucun'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kivou-alerts", description="Cycle d'alerte Kivou")
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--now",
        default=None,
        help="instant ISO 8601 ; par défaut, l'heure système — c'est le SEUL endroit "
        "où elle est lue, la logique métier la recevant toujours explicitement",
    )
    parser.add_argument("--dry-run", action="store_true", help="n'envoie rien, décrit seulement")
    arguments = parser.parse_args(argv)

    config = ApiConfig.from_environment()
    if not config.alerts_configured:
        print("alertes non configurées : KIVOU_PUBLIC_APP_URL et SMTP requis", file=sys.stderr)
        return 2

    now = dt.datetime.fromisoformat(arguments.now) if arguments.now else dt.datetime.now(tz=dt.UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.UTC)

    engine = create_database_engine(arguments.database_url)
    if arguments.dry_run:
        print("mode simulation : aucun e-mail n'est envoyé")
        return 0

    report = run_alert_cycle(
        engine, _gateway(config), now=now, public_app_url=config.public_app_url
    )
    print(summarize(report))
    return 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
