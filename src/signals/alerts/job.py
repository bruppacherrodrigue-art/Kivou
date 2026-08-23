"""Le cycle d'alerte — une fonction, rejouable, sans agent permanent.

Ni Celery, ni Redis, ni Kafka (§25)
───────────────────────────────────
`run_alert_cycle(now=…)` est une fonction appelable par `cron` ou un
minuteur `systemd` sur un VPS. Une file de tâches ajouterait un composant à
surveiller, à redémarrer et à sauvegarder, pour un envoi quotidien.

L'ORDRE des contrôles est la garantie (§29)
──────────────────────────────────────────
    CANDIDAT EN FILE
    →  AVANT L'ENVOI : propriété, fraîcheur COURANTE, identité affichable,
       droit du plan COURANT
    →  envoi

Un signal mis en file quand le compte payait ne part pas parce qu'il payait
hier. Le droit est réévalué au moment de l'envoi, pas au moment de la mise
en file — sinon une résiliation de la veille laisserait partir la piste
commerciale qu'elle vient justement de fermer.

Rejouable sans dégât
────────────────────
`signal_alert_delivery` a `(account_id, signal_key)` en clé primaire et ne
passe à `sent` qu'après un envoi confirmé. Relancer le job n'envoie donc
jamais deux fois le même signal au même compte.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import sqlalchemy as sa

from signals.accounts.schema import account
from signals.alerts import content, policy
from signals.alerts.gateway import (
    AlertDeliveryError,
    AlertDeliveryGateway,
    AlertMessage,
    UncertainDelivery,
    message_id,
)
from signals.billing import service as billing
from signals.billing.access import feed_access
from signals.engagement import analytics, notifications
from signals.engagement.schema import signal_alert_delivery
from signals.feed import policy as feed_policy
from signals.feed import query as feed_query
from signals.feed import view as feed_view
from signals.recency.claim import LANGUAGES
from signals.transactional_email.links import signal_url


@dataclasses.dataclass(frozen=True)
class AlertOutcome:
    """Ce qu'un cycle a fait, compte par compte. Rendu pour le journal d'exploitation."""

    account_id: str
    cadence: str
    result: str
    signal_count: int = 0
    detail: str | None = None


@dataclasses.dataclass(frozen=True)
class CycleReport:
    accounts_considered: int
    outcomes: tuple[AlertOutcome, ...]

    @property
    def sent(self) -> tuple[AlertOutcome, ...]:
        return tuple(outcome for outcome in self.outcomes if outcome.result == "sent")

    @property
    def signals_sent(self) -> int:
        return sum(outcome.signal_count for outcome in self.sent)


def _last_successful_send(connection: sa.Connection, *, account_id: str) -> dt.datetime | None:
    value = connection.execute(
        sa.select(sa.func.max(signal_alert_delivery.c.sent_at)).where(
            signal_alert_delivery.c.account_id == account_id,
            signal_alert_delivery.c.status == "sent",
        )
    ).scalar_one_or_none()
    return billing.aware_datetime(value)


def _already_alerted(connection: sa.Connection, *, account_id: str) -> set[str]:
    """Les signaux déjà envoyés avec succès — jamais renvoyés (§19)."""
    rows = connection.execute(
        sa.select(signal_alert_delivery.c.signal_key).where(
            signal_alert_delivery.c.account_id == account_id,
            signal_alert_delivery.c.status == "sent",
        )
    ).scalars()
    return set(rows)


def eligible_signals(
    connection: sa.Connection, *, account_id: str, as_of: dt.date, limit: int
) -> list:
    """Les signaux qu'on a le droit d'envoyer à ce compte, aujourd'hui.

    Tout vient du feed de SPEC-012 : propriété, profil actif dans l'allocation
    du plan, identité affichable, sémantique d'événement courante, ordre
    déterministe. Aucun second modèle de classement n'est introduit (§20).
    """
    access = feed_access(connection, account_id=account_id, as_of=as_of)
    if not access.entitlements.feed_access:
        return []
    allowed = frozenset(
        billing.feedable_target_icps(
            connection, account_id=account_id, limit=access.entitlements.max_active_icps
        )
    )
    page = feed_query.feed_page(
        connection,
        account_id=account_id,
        as_of=as_of,
        # §16 — uniquement les NOUVEAUTÉS au sens de la politique de fraîcheur.
        # Un `aging_award` reste exact, il n'est simplement pas une nouvelle.
        freshness=feed_policy.DEFAULT_FRESHNESS,
        allowed_target_icp_ids=allowed,
        limit=feed_policy.MAXIMUM_PAGE_SIZE,
    )
    already = _already_alerted(connection, account_id=account_id)
    # §29 — le droit du plan est réévalué ICI, à l'instant de l'envoi.
    unlocked = [
        item
        for item in page.items
        if access.is_unlocked(item) and item.signal.signal_key not in already
    ]
    return unlocked[:limit]


def _queue(
    connection: sa.Connection, *, account_id: str, items: list, cadence: str, now: dt.datetime
) -> None:
    for item in items:
        key = item.signal.signal_key
        existing = connection.execute(
            sa.select(signal_alert_delivery.c.attempt_count).where(
                signal_alert_delivery.c.account_id == account_id,
                signal_alert_delivery.c.signal_key == key,
            )
        ).scalar_one_or_none()
        if existing is None:
            connection.execute(
                sa.insert(signal_alert_delivery).values(
                    account_id=account_id,
                    signal_key=key,
                    status="queued",
                    cadence=cadence,
                    queued_at=now,
                    attempt_count=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            analytics.record(
                connection,
                account_id=account_id,
                signal_key=key,
                event_type="alert_queued",
                occurred_at=now,
                properties={"cadence": cadence},
            )


def _mark_sent(
    connection: sa.Connection,
    *,
    account_id: str,
    keys: list[str],
    provider_message_id: str,
    now: dt.datetime,
) -> None:
    connection.execute(
        sa.update(signal_alert_delivery)
        .where(
            signal_alert_delivery.c.account_id == account_id,
            signal_alert_delivery.c.signal_key.in_(keys),
        )
        .values(
            status="sent",
            sent_at=now,
            provider_message_id=provider_message_id,
            attempt_count=signal_alert_delivery.c.attempt_count + 1,
            updated_at=now,
        )
    )


def _mark_failed(
    connection: sa.Connection,
    *,
    account_id: str,
    keys: list[str],
    status: str,
    error_code: str,
    now: dt.datetime,
) -> None:
    connection.execute(
        sa.update(signal_alert_delivery)
        .where(
            signal_alert_delivery.c.account_id == account_id,
            signal_alert_delivery.c.signal_key.in_(keys),
        )
        .values(
            status=status,
            failed_at=now,
            last_error_code=error_code,
            attempt_count=signal_alert_delivery.c.attempt_count + 1,
            updated_at=now,
        )
    )


def _language(locale: str | None) -> str:
    return locale if locale in LANGUAGES else "fr"


def run_alert_cycle(
    engine: sa.Engine,
    gateway: AlertDeliveryGateway,
    *,
    now: dt.datetime,
    public_app_url: str | None,
) -> CycleReport:
    """Un cycle complet. Sûr à relancer, et sans horloge cachée.

    `now` est explicite : c'est ce qui permet de tester une cadence hebdomadaire
    sans attendre une semaine, et ce qui garantit qu'un rejeu ne dépend pas de
    l'heure à laquelle il tombe.
    """
    outcomes: list[AlertOutcome] = []
    with engine.connect() as connection:
        accounts = connection.execute(
            sa.select(account.c.account_id, account.c.locale).order_by(account.c.account_id)
        ).all()

    for row in accounts:
        outcomes.append(
            _run_for_account(
                engine,
                gateway,
                account_id=row.account_id,
                locale=row.locale,
                now=now,
                public_app_url=public_app_url,
            )
        )
    return CycleReport(accounts_considered=len(accounts), outcomes=tuple(outcomes))


def _run_for_account(
    engine: sa.Engine,
    gateway: AlertDeliveryGateway,
    *,
    account_id: str,
    locale: str | None,
    now: dt.datetime,
    public_app_url: str | None,
) -> AlertOutcome:
    with engine.begin() as connection:
        state = billing.billing_state(connection, account_id=account_id)
        cadence = state.entitlements.alert_cadence
        if cadence not in policy.SENDING_CADENCES:
            # Discovery, ou un plan sans alerte : rien n'est mis en file.
            return AlertOutcome(account_id, cadence, "not_eligible")

        preference = notifications.preference(connection, account_id=account_id, now=now)
        if not preference.can_receive_email:
            return AlertOutcome(account_id, cadence, "notifications_disabled")

        if not policy.is_due(
            cadence, last_sent_at=_last_successful_send(connection, account_id=account_id), now=now
        ):
            return AlertOutcome(account_id, cadence, "not_due")

        items = eligible_signals(
            connection,
            account_id=account_id,
            as_of=now.date(),
            limit=policy.MAXIMUM_SIGNALS_PER_EMAIL,
        )
        if not items:
            return AlertOutcome(account_id, cadence, "nothing_to_send")

        if not public_app_url:
            # §22 — un lien cassé est pire qu'un e-mail non envoyé. Les signaux
            # restent en file et partiront quand l'URL sera configurée.
            _queue(connection, account_id=account_id, items=items, cadence=cadence, now=now)
            return AlertOutcome(
                account_id, cadence, "blocked", len(items), "public_app_url_missing"
            )

        _queue(connection, account_id=account_id, items=items, cadence=cadence, now=now)
        lang = _language(locale)
        lines = [
            content.line_from_card(
                feed_view.feed_item(item, lang=lang),
                url=signal_url(public_app_url, item.signal.signal_key),
                lang=lang,
            )
            for item in items
        ]
        keys = [item.signal.signal_key for item in items]
        batch_key = f"{now.date().isoformat()}:{':'.join(sorted(keys))}"
        message = AlertMessage(
            to_email=preference.notification_email,
            subject=content.subject(len(lines), lang=lang),
            text_body=content.render_text(lines, lang=lang),
            message_id=message_id(account_id=account_id, batch_key=batch_key),
            language=lang,
        )

    # L'envoi a lieu HORS transaction : garder une transaction ouverte pendant
    # un appel réseau bloquerait la base le temps d'un timeout SMTP.
    try:
        result = gateway.send(message)
    except UncertainDelivery as error:
        with engine.begin() as connection:
            _mark_failed(
                connection,
                account_id=account_id,
                keys=keys,
                status="unknown_delivery_state",
                error_code=error.code,
                now=now,
            )
            analytics.record(
                connection,
                account_id=account_id,
                event_type="alert_failed",
                occurred_at=now,
                properties={"cadence": cadence, "error_code": error.code, "retryable": False},
            )
        return AlertOutcome(account_id, cadence, "unknown_delivery_state", len(keys), error.code)
    except AlertDeliveryError as error:
        with engine.begin() as connection:
            _mark_failed(
                connection,
                account_id=account_id,
                keys=keys,
                status="failed",
                error_code=error.code,
                now=now,
            )
            analytics.record(
                connection,
                account_id=account_id,
                event_type="alert_failed",
                occurred_at=now,
                properties={
                    "cadence": cadence,
                    "error_code": error.code,
                    "retryable": error.retryable,
                },
            )
        return AlertOutcome(account_id, cadence, "failed", len(keys), error.code)

    with engine.begin() as connection:
        _mark_sent(
            connection,
            account_id=account_id,
            keys=keys,
            provider_message_id=result.provider_message_id,
            now=now,
        )
        analytics.record(
            connection,
            account_id=account_id,
            event_type="alert_sent",
            occurred_at=now,
            properties={"cadence": cadence, "signal_count": len(keys)},
        )
    return AlertOutcome(account_id, cadence, "sent", len(keys))
