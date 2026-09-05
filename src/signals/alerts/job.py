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

Rejouable avec une identité durable
───────────────────────────────────
`signal_alert_delivery` a `(account_id, signal_key)` en clé primaire. Les
reprises déterministes conservent leur lot et leur `Message-ID`. SMTP ne peut
toutefois pas distinguer une acceptation suivie d'une réponse réseau perdue :
ce cas reste explicitement ambigu et peut produire un doublon borné.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import secrets
from collections.abc import Iterator

import sqlalchemy as sa

from signals.accounts.schema import account
from signals.accounts.service import normalize_email
from signals.alerts import content, delivery, lease, policy
from signals.alerts.gateway import (
    AlertDeliveryError,
    AlertDeliveryGateway,
    AlertMessage,
    UncertainDelivery,
)
from signals.billing import service as billing
from signals.billing.access import feed_access
from signals.engagement import analytics, notifications
from signals.engagement.schema import signal_alert_delivery
from signals.feed import policy as feed_policy
from signals.feed import query as feed_query
from signals.feed import view as feed_view
from signals.recency.claim import LANGUAGES
from signals.runtime_events import emit_delivery_event
from signals.transactional_email.links import preferences_url, signal_url


@dataclasses.dataclass(frozen=True)
class AlertOutcome:
    """Ce qu'un cycle a fait, compte par compte. Rendu pour le journal d'exploitation."""

    account_id: str
    cadence: str
    result: str
    signal_count: int = 0
    detail: str | None = None
    retryable: bool | None = None
    attempt: int = 0


@dataclasses.dataclass(frozen=True)
class CycleReport:
    accounts_considered: int
    outcomes: tuple[AlertOutcome, ...]
    execution_status: str = "completed"

    @property
    def already_running(self) -> bool:
        return self.execution_status == "already_running"

    @property
    def has_current_incident(self) -> bool:
        return any(
            outcome.result in {"unknown_delivery_state", "persistence_failed"}
            or (
                outcome.result == "failed"
                and not (
                    outcome.detail == "smtp_recipient_refused"
                    and outcome.retryable is False
                )
            )
            for outcome in self.outcomes
        )

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


def _registered_deliveries(connection: sa.Connection, *, account_id: str) -> set[str]:
    """Signals already assigned to a durable batch or terminal history."""

    rows = connection.execute(
        sa.select(
            signal_alert_delivery.c.signal_key,
            signal_alert_delivery.c.status,
            signal_alert_delivery.c.batch_key,
        ).where(
            signal_alert_delivery.c.account_id == account_id,
        )
    )
    return {
        row.signal_key
        for row in rows
        if row.status != "queued" or row.batch_key is not None
    }


def _accessible_signals(
    connection: sa.Connection,
    *,
    account_id: str,
    as_of: dt.date,
    signal_keys: tuple[str, ...] | None = None,
    enough: int | None = None,
    exclude: frozenset[str] = frozenset(),
) -> list:
    access = feed_access(connection, account_id=account_id, as_of=as_of)
    if not access.entitlements.feed_access:
        return []
    allowed = frozenset(
        billing.feedable_target_icps(
            connection,
            account_id=account_id,
            limit=access.entitlements.max_active_icps,
        )
    )
    if signal_keys is not None:
        admitted = feed_policy.statuses_for(feed_policy.DEFAULT_FRESHNESS)
        assert admitted is not None
        exact: list = []
        for signal_key in signal_keys:
            item = feed_query.owned_signal(
                connection,
                account_id=account_id,
                signal_key=signal_key,
                as_of=as_of,
                allowed_target_icp_ids=allowed,
            )
            if (
                item is not None
                and item.display is not None
                and item.status in admitted
                and item.model_fit != "none"
                and access.is_unlocked(item)
            ):
                exact.append(item)
        return exact
    # `feed_page` n'est PAS un curseur incrémental : chaque appel relance la
    # requête complète bornée au plafond de balayage, réévalue la fraîcheur de
    # toutes les lignes et résout l'identité de tout l'ensemble candidat, avant
    # de trancher en Python. Boucler jusqu'au bout multipliait donc ce travail
    # par le nombre de pages — jusqu'à dix balayages complets par compte et par
    # cycle — pour ne retenir au plus qu'une poignée de signaux.
    #
    # `enough` dit combien de signaux ENVOYABLES suffisent : dès qu'on les a,
    # la pagination s'arrête. Les signaux déjà engagés dans un lot sont écartés
    # ici plutôt qu'après, sans quoi une page entière de doublons donnerait
    # l'illusion d'avoir atteint le quota.
    unlocked: list = []
    offset = 0
    while True:
        page = feed_query.feed_page(
            connection,
            account_id=account_id,
            as_of=as_of,
            freshness=feed_policy.DEFAULT_FRESHNESS,
            allowed_target_icp_ids=allowed,
            limit=feed_policy.MAXIMUM_PAGE_SIZE,
            offset=offset,
        )
        unlocked.extend(
            item
            for item in page.items
            if item.model_fit != "none" and access.is_unlocked(item)
        )
        if not page.has_more:
            return unlocked
        if enough is not None and _sendable_count(unlocked, exclude=exclude) >= enough:
            return unlocked
        offset += page.limit


def _sendable_count(items: list, *, exclude: frozenset[str]) -> int:
    return sum(1 for item in items if item.signal.signal_key not in exclude)


def eligible_signals(
    connection: sa.Connection, *, account_id: str, as_of: dt.date, limit: int
) -> list:
    """Les signaux qu'on a le droit d'envoyer à ce compte, aujourd'hui.

    Tout vient du feed de SPEC-012 : propriété, profil actif dans l'allocation
    du plan, identité affichable, sémantique d'événement courante, ordre
    déterministe. Aucun second modèle de classement n'est introduit (§20).
    """
    registered = _registered_deliveries(connection, account_id=account_id)
    unlocked = [
        item
        for item in _accessible_signals(
            connection,
            account_id=account_id,
            as_of=as_of,
            enough=limit,
            exclude=registered,
        )
        if item.signal.signal_key not in registered
    ]
    return unlocked[:limit]


def _language(locale: str | None) -> str:
    return locale if locale in LANGUAGES else "fr"


def _recipient_context_fingerprint(
    connection: sa.Connection,
    *,
    account_id: str,
    state: billing.BillingState,
    preference: notifications.NotificationPreference,
    cadence: str,
) -> str:
    assert preference.notification_email is not None
    feedable_icps = billing.feedable_target_icps(
        connection,
        account_id=account_id,
        limit=state.entitlements.max_active_icps,
    )
    eligibility_signature = (
        f"plan:{state.plan_code}",
        f"subscription:{state.subscription_status or 'none'}",
        f"cadence:{cadence}",
        f"feed_access:{int(state.entitlements.feed_access)}",
        f"max_active_icps:{state.entitlements.max_active_icps}",
        *(f"target_icp:{target_icp_id}" for target_icp_id in sorted(feedable_icps)),
    )
    return delivery.context_fingerprint(
        account_id=account_id,
        normalized_email=normalize_email(preference.notification_email),
        preference_version=preference.updated_at,
        eligibility_signature=eligibility_signature,
    )


@dataclasses.dataclass(frozen=True)
class _PendingDeliveryEvent:
    batch: delivery.DeliveryBatch
    status: str
    code: str
    retryable: bool
    attempt: int | None = None
    signal_keys: tuple[str, ...] | None = None


def _emit_batch_delivery(
    batch: delivery.DeliveryBatch,
    *,
    status: str,
    code: str,
    retryable: bool,
    attempt: int | None = None,
    signal_keys: tuple[str, ...] | None = None,
) -> None:
    for signal_key in signal_keys or batch.signal_keys:
        emit_delivery_event(
            channel="alert",
            account_ref=batch.account_id,
            signal_ref=signal_key,
            status=status,
            code=code,
            retryable=retryable,
            attempt=batch.attempt_count if attempt is None else attempt,
        )


def _defer_batch_delivery(
    pending: list[_PendingDeliveryEvent],
    batch: delivery.DeliveryBatch,
    *,
    status: str,
    code: str,
    retryable: bool,
    attempt: int | None = None,
    signal_keys: tuple[str, ...] | None = None,
) -> None:
    pending.append(
        _PendingDeliveryEvent(
            batch=batch,
            status=status,
            code=code,
            retryable=retryable,
            attempt=attempt,
            signal_keys=signal_keys,
        )
    )


@contextlib.contextmanager
def _transaction_with_delivery_events(
    engine: sa.Engine,
) -> Iterator[tuple[sa.Connection, list[_PendingDeliveryEvent]]]:
    """Publish transition events only after their transaction commits."""

    pending: list[_PendingDeliveryEvent] = []
    with engine.begin() as connection:
        yield connection, pending
    for event in pending:
        _emit_batch_delivery(
            event.batch,
            status=event.status,
            code=event.code,
            retryable=event.retryable,
            attempt=event.attempt,
            signal_keys=event.signal_keys,
        )


def run_alert_cycle(
    engine: sa.Engine,
    gateway: AlertDeliveryGateway,
    *,
    now: dt.datetime,
    public_app_url: str | None,
    delivery_lease_ttl: dt.timedelta = dt.timedelta(minutes=30),
    job_lease_ttl: dt.timedelta | None = None,
    retry_base: dt.timedelta = dt.timedelta(minutes=15),
    max_attempts: int = 5,
) -> CycleReport:
    """Un cycle complet. Sûr à relancer, et sans horloge cachée.

    `now` est explicite : c'est ce qui permet de tester une cadence hebdomadaire
    sans attendre une semaine, et ce qui garantit qu'un rejeu ne dépend pas de
    l'heure à laquelle il tombe.
    """
    owner_id = secrets.token_hex(16)
    with engine.begin() as connection:
        acquisition = lease.acquire(
            connection,
            owner_id=owner_id,
            now=now,
            ttl=job_lease_ttl or delivery_lease_ttl,
        )
    if acquisition is lease.LeaseAcquisition.ALREADY_RUNNING:
        return CycleReport(0, (), execution_status="already_running")

    try:
        outcomes: list[AlertOutcome] = []
        with engine.connect() as connection:
            accounts = connection.execute(
                sa.select(account.c.account_id, account.c.locale).order_by(
                    account.c.account_id
                )
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
                    delivery_lease_ttl=delivery_lease_ttl,
                    retry_base=retry_base,
                    max_attempts=max_attempts,
                )
            )
        return CycleReport(accounts_considered=len(accounts), outcomes=tuple(outcomes))
    finally:
        with engine.begin() as connection:
            lease.release(connection, owner_id=owner_id)


def _run_for_account(
    engine: sa.Engine,
    gateway: AlertDeliveryGateway,
    *,
    account_id: str,
    locale: str | None,
    now: dt.datetime,
    public_app_url: str | None,
    delivery_lease_ttl: dt.timedelta,
    retry_base: dt.timedelta,
    max_attempts: int,
) -> AlertOutcome:
    with _transaction_with_delivery_events(engine) as (
        connection,
        pending_events,
    ):
        state = billing.billing_state(connection, account_id=account_id)
        cadence = state.entitlements.alert_cadence
        batch = delivery.next_due_batch(connection, account_id=account_id, now=now)
        if cadence not in policy.SENDING_CADENCES:
            if batch is not None:
                _suppress(
                    connection,
                    batch=batch,
                    signal_keys=batch.signal_keys,
                    reason_code="entitlement_lost",
                    cadence=cadence,
                    now=now,
                )
                _defer_batch_delivery(
                    pending_events,
                    batch,
                    status="suppressed",
                    code="entitlement_lost",
                    retryable=False,
                )
                return AlertOutcome(
                    account_id,
                    cadence,
                    "suppressed",
                    len(batch.signal_keys),
                    "entitlement_lost",
                    False,
                    batch.attempt_count,
                )
            return AlertOutcome(account_id, cadence, "not_eligible")

        preference = notifications.preference(connection, account_id=account_id, now=now)
        if not preference.can_receive_email:
            if batch is not None:
                _suppress(
                    connection,
                    batch=batch,
                    signal_keys=batch.signal_keys,
                    reason_code="notifications_disabled",
                    cadence=cadence,
                    now=now,
                )
                _defer_batch_delivery(
                    pending_events,
                    batch,
                    status="suppressed",
                    code="notifications_disabled",
                    retryable=False,
                )
                return AlertOutcome(
                    account_id,
                    cadence,
                    "suppressed",
                    len(batch.signal_keys),
                    "notifications_disabled",
                    False,
                    batch.attempt_count,
                )
            return AlertOutcome(account_id, cadence, "notifications_disabled")

        recipient_context_fingerprint = _recipient_context_fingerprint(
            connection,
            account_id=account_id,
            state=state,
            preference=preference,
            cadence=cadence,
        )
        if batch is not None and (
            batch.recipient_context_fingerprint != recipient_context_fingerprint
        ):
            reason_code = (
                "recipient_context_unverifiable"
                if batch.recipient_context_fingerprint is None
                else "recipient_context_changed"
            )
            _suppress(
                connection,
                batch=batch,
                signal_keys=batch.signal_keys,
                reason_code=reason_code,
                cadence=cadence,
                now=now,
            )
            _defer_batch_delivery(
                pending_events,
                batch,
                status="suppressed",
                code=reason_code,
                retryable=False,
            )
            return AlertOutcome(
                account_id,
                cadence,
                "suppressed",
                len(batch.signal_keys),
                reason_code,
                False,
                batch.attempt_count,
            )

        if batch is None:
            if not policy.is_due(
                cadence,
                last_sent_at=_last_successful_send(
                    connection,
                    account_id=account_id,
                ),
                now=now,
            ):
                return AlertOutcome(account_id, cadence, "not_due")

            if delivery.has_permanent_recipient_refusal(
                connection,
                account_id=account_id,
                recipient_context_fingerprint=recipient_context_fingerprint,
            ):
                return AlertOutcome(
                    account_id,
                    cadence,
                    "recipient_refused",
                    0,
                    "smtp_recipient_refused",
                    False,
                    0,
                )

            signal_limit = 1 if state.is_discovery else policy.MAXIMUM_SIGNALS_PER_EMAIL
            new_items = eligible_signals(
                connection,
                account_id=account_id,
                as_of=now.date(),
                limit=signal_limit,
            )
            if not new_items:
                return AlertOutcome(account_id, cadence, "nothing_to_send")
            batch = delivery.queue_batch(
                connection,
                account_id=account_id,
                signal_keys=(item.signal.signal_key for item in new_items),
                cadence=cadence,
                recipient_context_fingerprint=recipient_context_fingerprint,
                now=now,
            )
            if batch is None:
                return AlertOutcome(account_id, cadence, "nothing_to_send")
            for signal_key in batch.signal_keys:
                analytics.record(
                    connection,
                    account_id=account_id,
                    signal_key=signal_key,
                    event_type="alert_queued",
                    occurred_at=now,
                    properties={"cadence": cadence},
                )

        if not public_app_url:
            # §22 — un lien cassé est pire qu'un e-mail non envoyé. Les signaux
            # restent en file et partiront quand l'URL sera configurée.
            _defer_batch_delivery(
                pending_events,
                batch,
                status="blocked",
                code="public_app_url_missing",
                retryable=False,
            )
            return AlertOutcome(
                account_id,
                cadence,
                "blocked",
                len(batch.signal_keys),
                "public_app_url_missing",
                False,
                batch.attempt_count,
            )

        accessible = _accessible_signals(
            connection,
            account_id=account_id,
            as_of=now.date(),
            signal_keys=batch.signal_keys,
        )
        by_key = {item.signal.signal_key: item for item in accessible}
        inaccessible = tuple(key for key in batch.signal_keys if key not in by_key)
        if inaccessible:
            _suppress(
                connection,
                batch=batch,
                signal_keys=inaccessible,
                reason_code="signal_inaccessible",
                cadence=cadence,
                now=now,
            )
            _defer_batch_delivery(
                pending_events,
                batch,
                status="suppressed",
                code="signal_inaccessible",
                retryable=False,
                signal_keys=inaccessible,
            )
        accessible_keys = tuple(key for key in batch.signal_keys if key in by_key)
        if not accessible_keys:
            return AlertOutcome(
                account_id,
                cadence,
                "suppressed",
                len(inaccessible),
                "signal_inaccessible",
                False,
                batch.attempt_count,
            )
        batch = dataclasses.replace(batch, signal_keys=accessible_keys)
        if batch.attempt_count >= max_attempts:
            terminal_status = delivery.mark_attempt_budget_exhausted(
                connection,
                batch=batch,
                now=now,
                max_attempts=max_attempts,
            )
            analytics.record(
                connection,
                account_id=account_id,
                event_type="alert_failed",
                occurred_at=now,
                properties={
                    "cadence": cadence,
                    "error_code": "attempt_budget_exhausted",
                    "retryable": False,
                },
            )
            _defer_batch_delivery(
                pending_events,
                batch,
                status=terminal_status,
                code="attempt_budget_exhausted",
                retryable=False,
            )
            return AlertOutcome(
                account_id,
                cadence,
                terminal_status,
                len(batch.signal_keys),
                "attempt_budget_exhausted",
                False,
                batch.attempt_count,
            )
        batch = delivery.mark_sending(
            connection,
            batch=batch,
            now=now,
            lease_ttl=delivery_lease_ttl,
            max_attempts=max_attempts,
        )
        lang = _language(locale)
        items = [by_key[key] for key in batch.signal_keys]
        lines = [
            content.line_from_card(
                feed_view.feed_item(item, lang=lang),
                url=signal_url(public_app_url, item.signal.signal_key),
                lang=lang,
            )
            for item in items
        ]
        assert preference.notification_email is not None
        # `public_app_url` est garanti non nul ici : l'absence est traitée plus
        # haut par `public_app_url_missing`, avant toute construction de lot.
        preferences_link = preferences_url(public_app_url)
        remaining_count = 0
        pricing_link = None
        if state.is_discovery:
            page = feed_query.feed_page(
                connection,
                account_id=account_id,
                as_of=now.date(),
                freshness=feed_policy.DEFAULT_FRESHNESS,
                limit=feed_policy.MAXIMUM_PAGE_SIZE,
            )
            remaining_count = max(
                0,
                sum(1 for item in page.items if item.model_fit != "none") - len(lines),
            )
            pricing_link = f"{public_app_url.rstrip('/')}/pricing"
        message = AlertMessage(
            to_email=preference.notification_email,
            subject=content.subject(len(lines), lang=lang),
            text_body=content.render_text(
                lines, lang=lang, preferences_link=preferences_link,
                remaining_count=remaining_count, pricing_link=pricing_link,
            ),
            html_body=content.render_html(
                lines, lang=lang, preferences_link=preferences_link,
                remaining_count=remaining_count, pricing_link=pricing_link,
            ),
            message_id=batch.message_id,
            language=lang,
            preferences_url=preferences_link,
        )

    # L'envoi a lieu HORS transaction : garder une transaction ouverte pendant
    # un appel réseau bloquerait la base le temps d'un timeout SMTP.
    try:
        result = gateway.send(message)
    except UncertainDelivery as error:
        try:
            with engine.begin() as connection:
                delivery.mark_unknown(
                    connection,
                    batch=batch,
                    error_code=error.code,
                    now=now,
                    retry_base=retry_base,
                    max_attempts=max_attempts,
                )
                analytics.record(
                    connection,
                    account_id=account_id,
                    event_type="alert_failed",
                    occurred_at=now,
                    properties={
                        "cadence": cadence,
                        "error_code": error.code,
                        "retryable": batch.attempt_count < max_attempts,
                    },
                )
        except (sa.exc.SQLAlchemyError, delivery.DeliveryStateConflict):
            will_retry = batch.attempt_count < max_attempts
            _emit_batch_delivery(
                batch,
                status="persistence_failed",
                code="delivery_state_persistence_failed",
                retryable=will_retry,
            )
            return AlertOutcome(
                account_id,
                cadence,
                "persistence_failed",
                len(batch.signal_keys),
                "delivery_state_persistence_failed",
                will_retry,
                batch.attempt_count,
            )
        will_retry = batch.attempt_count < max_attempts
        _emit_batch_delivery(
            batch,
            status="unknown_delivery_state",
            code=error.code,
            retryable=will_retry,
        )
        return AlertOutcome(
            account_id,
            cadence,
            "unknown_delivery_state",
            len(batch.signal_keys),
            error.code,
            will_retry,
            batch.attempt_count,
        )
    except AlertDeliveryError as error:
        try:
            with engine.begin() as connection:
                delivery.mark_failed(
                    connection,
                    batch=batch,
                    error_code=error.code,
                    retryable=error.retryable,
                    now=now,
                    retry_base=retry_base,
                    max_attempts=max_attempts,
                )
                analytics.record(
                    connection,
                    account_id=account_id,
                    event_type="alert_failed",
                    occurred_at=now,
                    properties={
                        "cadence": cadence,
                        "error_code": error.code,
                        "retryable": error.retryable
                        and batch.attempt_count < max_attempts,
                    },
                )
        except (sa.exc.SQLAlchemyError, delivery.DeliveryStateConflict):
            will_retry = batch.attempt_count < max_attempts
            _emit_batch_delivery(
                batch,
                status="persistence_failed",
                code="delivery_state_persistence_failed",
                retryable=will_retry,
            )
            return AlertOutcome(
                account_id,
                cadence,
                "persistence_failed",
                len(batch.signal_keys),
                "delivery_state_persistence_failed",
                will_retry,
                batch.attempt_count,
            )
        will_retry = error.retryable and batch.attempt_count < max_attempts
        _emit_batch_delivery(
            batch,
            status="failed",
            code=error.code,
            retryable=will_retry,
        )
        return AlertOutcome(
            account_id,
            cadence,
            "failed",
            len(batch.signal_keys),
            error.code,
            will_retry,
            batch.attempt_count,
        )

    try:
        with engine.begin() as connection:
            delivery.mark_sent(
                connection,
                batch=batch,
                provider_message_id=result.provider_message_id,
                now=now,
            )
            analytics.record(
                connection,
                account_id=account_id,
                event_type="alert_sent",
                occurred_at=now,
                properties={
                    "cadence": cadence,
                    "signal_count": len(batch.signal_keys),
                },
            )
    except (sa.exc.SQLAlchemyError, delivery.DeliveryStateConflict):
        will_retry = batch.attempt_count < max_attempts
        _emit_batch_delivery(
            batch,
            status="persistence_failed",
            code="delivery_state_persistence_failed",
            retryable=will_retry,
        )
        return AlertOutcome(
            account_id,
            cadence,
            "persistence_failed",
            len(batch.signal_keys),
            "delivery_state_persistence_failed",
            will_retry,
            batch.attempt_count,
        )
    _emit_batch_delivery(
        batch,
        status="submitted",
        code="smtp_submission_accepted",
        retryable=False,
    )
    return AlertOutcome(
        account_id,
        cadence,
        "sent",
        len(batch.signal_keys),
        "smtp_submission_accepted",
        False,
        batch.attempt_count,
    )


def _suppress(
    connection: sa.Connection,
    *,
    batch: delivery.DeliveryBatch,
    signal_keys: tuple[str, ...],
    reason_code: str,
    cadence: str,
    now: dt.datetime,
) -> None:
    delivery.mark_suppressed(
        connection,
        batch=batch,
        signal_keys=signal_keys,
        reason_code=reason_code,
        now=now,
    )
    analytics.record(
        connection,
        account_id=batch.account_id,
        event_type="alert_suppressed",
        occurred_at=now,
        properties={
            "cadence": cadence,
            "reason_code": reason_code,
            "signal_count": len(signal_keys),
        },
    )
