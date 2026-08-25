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
from signals.runtime_events import configure_runtime_event_logging


class _SafeArgumentParser(argparse.ArgumentParser):
    """Reject invalid arguments without reflecting possibly secret values."""

    def error(self, _message: str) -> None:
        self.exit(2, "configuration_invalid\n")


def _gateway(config: ApiConfig) -> SmtpAlertGateway:
    return SmtpAlertGateway(
        SmtpConfiguration(
            host=config.smtp_host or "",
            port=config.smtp_port,
            username=config.smtp_username,
            password=config.smtp_password,
            from_email=config.smtp_from_email or "",
            from_name=config.smtp_from_name,
            tls_mode=config.smtp_tls_mode,
            timeout_seconds=config.smtp_timeout_seconds,
            reply_to_email=config.smtp_reply_to_email,
        )
    )


def summarize(report: CycleReport) -> str:
    """Un résumé lisible dans un journal de cron. Aucune adresse, aucun secret."""
    if report.already_running:
        return "status=already_running"
    by_result: dict[str, int] = {}
    for outcome in report.outcomes:
        by_result[outcome.result] = by_result.get(outcome.result, 0) + 1
    parts = ", ".join(f"{name}={count}" for name, count in sorted(by_result.items()))
    return (
        f"comptes examinés={report.accounts_considered} · signaux envoyés="
        f"{report.signals_sent} · {parts or 'aucun'}"
    )


def main(argv: list[str] | None = None) -> int:
    configure_runtime_event_logging()
    parser = _SafeArgumentParser(prog="kivou-alerts", description="Cycle d'alerte Kivou")
    parser.add_argument(
        "--now",
        default=None,
        help="instant ISO 8601 ; par défaut, l'heure système — c'est le SEUL endroit "
        "où elle est lue, la logique métier la recevant toujours explicitement",
    )
    parser.add_argument("--dry-run", action="store_true", help="n'envoie rien, décrit seulement")
    arguments = parser.parse_args(argv)

    try:
        config = ApiConfig.from_environment()
        if not config.alerts_configured:
            raise ValueError("transactional alert configuration is incomplete")
        now = (
            dt.datetime.fromisoformat(arguments.now)
            if arguments.now
            else dt.datetime.now(tz=dt.UTC)
        )
        if now.tzinfo is None:
            now = now.replace(tzinfo=dt.UTC)
        engine = create_database_engine()
    except (RuntimeError, ValueError):
        print("configuration_invalid", file=sys.stderr)
        return 2

    if arguments.dry_run:
        print("status=dry_run no_delivery_attempted=true")
        return 0

    try:
        report = run_alert_cycle(
            engine,
            _gateway(config),
            now=now,
            public_app_url=config.public_app_url,
            delivery_lease_ttl=config.alert_lease_ttl,
            job_lease_ttl=config.alert_lease_ttl,
            retry_base=config.alert_retry_base,
            max_attempts=config.alert_max_attempts,
        )
    except Exception:  # noqa: BLE001 - sanitized process boundary, never exception text
        print("runtime_failed", file=sys.stderr)
        return 1
    print(summarize(report))
    return 1 if report.has_current_incident else 0


if __name__ == "__main__":  # pragma: no cover - point d'entrée
    raise SystemExit(main())
