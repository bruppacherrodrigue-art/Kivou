"""One-item, lease-protected worker for durable prospect-send requests."""

from __future__ import annotations

import datetime as dt
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.persistence.schema import prospect_send_item, prospect_send_request, prospect_target
from signals.prospection_actions.delivery import (
    AssistedInstantlyDelivery,
    AssistedInstantlyProvider,
    ReconciliationRequired,
)
from signals.prospection_actions.service import DeliveryTarget

LEASE = dt.timedelta(minutes=5)
RETRY_DELAY = dt.timedelta(minutes=1)
_TERMINAL = ("sent", "failed")


@dataclass(frozen=True)
class WorkerOutcome:
    status: str
    request_id: str | None = None
    target_id: str | None = None


@dataclass(frozen=True)
class _Claim:
    request: dict[str, object]
    item: dict[str, object]
    target: dict[str, object]
    lease_id: str
    clock: Callable[[], dt.datetime]


class ProspectSendWorker:
    def __init__(
        self,
        engine: Engine,
        *,
        provider: AssistedInstantlyProvider,
        provider_account_id: str,
        kill_switch_path: Path = Path("/etc/kivou/acquisition.disabled"),
        clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self._engine = engine
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self._delivery = AssistedInstantlyDelivery(
            provider=provider, provider_account_id=provider_account_id
        )
        self._kill_switch_path = kill_switch_path

    def run_once(self, *, worker_ref: str, now: dt.datetime | None = None) -> WorkerOutcome:
        now = now or self._clock()
        if now.tzinfo is None or not worker_ref or len(worker_ref) > 320:
            raise ValueError("worker_ref and now must be bounded and timezone-aware")
        claim = self._claim(worker_ref=worker_ref, now=now)
        if claim is None:
            return WorkerOutcome("idle")
        try:
            return self._process(claim)
        except Exception as error:  # noqa: BLE001 - provider boundary is made durable
            return self._retry(claim, error=error)

    @contextmanager
    def _transaction(self) -> Iterator[sa.Connection]:
        with self._engine.begin() as connection:
            if connection.dialect.name == "sqlite":
                # Acquire the write lock before reading eligibility, including
                # after another worker's in-flight provider call releases it.
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            yield connection

    @contextmanager
    def _mutation_guard(self, claim: _Claim) -> Iterator[sa.Connection | None]:
        """Fence reconcile, mutation and persistence with the claimant's row lock.

        Instantly has no idempotency fence. The request lock is deliberately held
        across these network calls; lease duration and HTTP inactivity timeouts
        cannot prevent an in-flight mutation from being reclaimed.
        """
        with self._transaction() as connection:
            request = sa.select(prospect_send_request.c.lease_id).where(
                prospect_send_request.c.request_id == claim.request["request_id"],
                prospect_send_request.c.status == "running",
            )
            if connection.dialect.name == "postgresql":
                request = request.with_for_update()
            if connection.scalar(request) != claim.lease_id:
                yield None
                return
            item = sa.select(prospect_send_item.c.status).where(
                prospect_send_item.c.request_id == claim.request["request_id"],
                prospect_send_item.c.target_id == claim.target["target_id"],
            )
            if connection.dialect.name == "postgresql":
                item = item.with_for_update()
            if connection.scalar(item) not in ("running", *_TERMINAL):
                yield None
                return
            target = sa.select(prospect_target.c.target_id).where(
                prospect_target.c.target_id == claim.target["target_id"]
            )
            if connection.dialect.name == "postgresql":
                target = target.with_for_update()
            if connection.scalar(target) is None:
                yield None
                return
            yield connection
            # A waiting claimant must see a fresh lease when the guard commits.
            # If the operation released the request, this update matches nothing.
            now = claim.clock()
            connection.execute(
                sa.update(prospect_send_request)
                .where(
                    prospect_send_request.c.request_id == claim.request["request_id"],
                    prospect_send_request.c.lease_id == claim.lease_id,
                    prospect_send_request.c.status == "running",
                )
                .values(lease_expires_at=now + LEASE, updated_at=now)
            )

    def _claim(self, *, worker_ref: str, now: dt.datetime) -> _Claim | None:
        started = self._clock()
        seed = now

        # Explicit now seeds deterministic runs while elapsed provider time is
        # always sampled afresh. This closure belongs to one claim, not a worker.
        def clock() -> dt.datetime:
            return seed + (self._clock() - started)

        try:
            with self._transaction() as connection:
                return self._claim_locked(connection, worker_ref=worker_ref, clock=clock)
        except sa.exc.OperationalError as error:
            if self._engine.dialect.name == "sqlite" and getattr(
                error.orig, "sqlite_errorcode", None
            ) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                # A long provider call can outlast SQLite's busy timeout. The
                # claimant did not acquire the guard and must skip this turn.
                return None
            raise

    def _claim_locked(
        self, connection: sa.Connection, *, worker_ref: str, clock: Callable[[], dt.datetime]
    ) -> _Claim | None:
        now = clock()
        queued_items = prospect_send_item.alias("queued_items")
        nonterminal = sa.exists(
            sa.select(sa.literal(1)).where(
                queued_items.c.request_id == prospect_send_request.c.request_id,
                queued_items.c.status.not_in(_TERMINAL),
            )
        )
        request_reclaimable = sa.or_(
            prospect_send_request.c.status.in_(("queued", "waiting")),
            sa.and_(
                prospect_send_request.c.status == "running",
                prospect_send_request.c.lease_expires_at <= now,
            ),
        )
        item_due = sa.or_(
            sa.and_(
                prospect_send_item.c.status.in_(("queued", "verification_pending")),
                prospect_send_item.c.next_attempt_at <= now,
            ),
            sa.and_(
                prospect_send_item.c.status == "running",
                prospect_send_request.c.lease_expires_at <= now,
            ),
            # A terminal row is only an activation-retry carrier once there is
            # no ordinary item left.  It must never starve a queued sibling.
            sa.and_(
                prospect_send_item.c.status.in_(_TERMINAL),
                ~nonterminal,
                prospect_send_request.c.next_attempt_at <= now,
            ),
        )
        candidate = (
            sa.select(prospect_send_item.c.request_id, prospect_send_item.c.target_id)
            .join(
                prospect_send_request,
                prospect_send_request.c.request_id == prospect_send_item.c.request_id,
            )
            .where(request_reclaimable, item_due)
            .order_by(prospect_send_item.c.next_attempt_at, prospect_send_item.c.position)
            .limit(1)
        )
        if connection.dialect.name == "postgresql":
            candidate = candidate.with_for_update(of=prospect_send_request, skip_locked=True)
        row = connection.execute(candidate).mappings().one_or_none()
        if row is None:
            return None
        # Re-read due/item state after acquiring the request row lock. In
        # PostgreSQL the candidate's joined item may come from an older snapshot.
        eligible = connection.execute(
            candidate.where(
                prospect_send_item.c.request_id == row["request_id"],
                prospect_send_item.c.target_id == row["target_id"],
            )
        ).first()
        if eligible is None:
            return None
        now = clock()
        lease_id = str(uuid.uuid4())
        claimed = connection.execute(
            sa.update(prospect_send_request)
            .where(
                prospect_send_request.c.request_id == row["request_id"],
                request_reclaimable,
                sa.or_(
                    prospect_send_request.c.lease_id.is_(None),
                    prospect_send_request.c.lease_expires_at <= now,
                ),
            )
            .values(
                status="running",
                attempt_count=prospect_send_request.c.attempt_count + 1,
                claimed_by=worker_ref,
                lease_id=lease_id,
                lease_expires_at=now + LEASE,
                started_at=sa.func.coalesce(prospect_send_request.c.started_at, now),
                updated_at=now,
                error=None,
            )
        )
        if claimed.rowcount != 1:
            return None
        request = dict(
            connection.execute(
                sa.select(prospect_send_request).where(
                    prospect_send_request.c.request_id == row["request_id"]
                )
            )
            .mappings()
            .one()
        )
        item_query = sa.select(prospect_send_item).where(
            prospect_send_item.c.request_id == row["request_id"],
            prospect_send_item.c.target_id == row["target_id"],
        )
        if connection.dialect.name == "postgresql":
            item_query = item_query.with_for_update()
        item = dict(connection.execute(item_query).mappings().one())
        target_query = sa.select(prospect_target).where(
            prospect_target.c.target_id == row["target_id"]
        )
        if connection.dialect.name == "postgresql":
            target_query = target_query.with_for_update()
        target = dict(connection.execute(target_query).mappings().one())
        if item["status"] not in _TERMINAL:
            connection.execute(
                sa.update(prospect_send_item)
                .where(
                    prospect_send_item.c.request_id == row["request_id"],
                    prospect_send_item.c.target_id == row["target_id"],
                    self._lease_matches(row["request_id"], lease_id),
                )
                .values(
                    status="running",
                    attempt_count=prospect_send_item.c.attempt_count + 1,
                    updated_at=now,
                )
            )
        return _Claim(request=request, item=item, target=target, lease_id=lease_id, clock=clock)

    @staticmethod
    def _lease_matches(request_id: str, lease_id: str):
        return sa.exists(
            sa.select(sa.literal(1)).where(
                prospect_send_request.c.request_id == request_id,
                prospect_send_request.c.lease_id == lease_id,
                prospect_send_request.c.status == "running",
            )
        )

    def _process(self, claim: _Claim) -> WorkerOutcome:
        request_id = str(claim.request["request_id"])
        target_id = str(claim.target["target_id"])
        if claim.item["status"] not in _TERMINAL:
            with self._mutation_guard(claim) as connection:
                if connection is None:
                    return WorkerOutcome("lost", request_id, target_id)
                if completed := self._finish_already_sent(claim, connection):
                    return completed
        if claim.item["status"] in _TERMINAL:
            with self._engine.connect() as connection:
                final_status = self._counts(connection, request_id)[3]
            if final_status is None:
                return WorkerOutcome("lost", request_id, target_id)
            campaign_id = claim.request.get("provider_campaign_id") or claim.target.get(
                "provider_campaign_id"
            )
            return self._finalize(
                claim,
                campaign_id=str(campaign_id or ""),
                status=final_status,
            )
        campaign_id = claim.request.get("provider_campaign_id") or claim.target.get(
            "provider_campaign_id"
        )
        if not campaign_id:
            with self._mutation_guard(claim) as connection:
                if connection is None:
                    return WorkerOutcome("lost", request_id, target_id)
                if completed := self._finish_already_sent(claim, connection):
                    return completed
                try:
                    campaign_id = self._delivery.find_campaign(claim.request, at=claim.clock())
                    if not campaign_id:
                        if self._kill_switch_path.exists():
                            return self._wait(
                                claim, error="kill switch active", connection=connection
                            )
                        campaign_id = self._delivery.ensure_campaign(
                            claim.request, at=claim.clock()
                        )
                except Exception as error:  # noqa: BLE001 - public durable retry
                    return self._retry(claim, error=error, connection=connection)
                if not self._persist_campaign(
                    claim, campaign_id, now=claim.clock(), connection=connection
                ):
                    return WorkerOutcome("lost", request_id, target_id)
        instantly_id = claim.item.get("instantly_id") or claim.target.get("instantly_id")
        imported = False
        if not instantly_id:
            with self._mutation_guard(claim) as connection:
                if connection is None:
                    return WorkerOutcome("lost", request_id, target_id)
                if completed := self._finish_already_sent(claim, connection):
                    return completed
                try:
                    instantly_id = self._delivery.find_lead(
                        str(campaign_id), str(claim.target["email_address"])
                    )
                    if not instantly_id:
                        if self._kill_switch_path.exists():
                            return self._wait(
                                claim, error="kill switch active", connection=connection
                            )
                        instantly_id = self._delivery.import_target(
                            str(campaign_id), self._delivery_target(claim.target)
                        )
                        imported = True
                except Exception as error:  # noqa: BLE001 - public durable retry
                    return self._retry(claim, error=error, connection=connection)
                if not self._persist_lead(
                    claim,
                    str(campaign_id),
                    instantly_id,
                    now=claim.clock(),
                    connection=connection,
                ):
                    return WorkerOutcome("lost", request_id, target_id)

        verification = self._delivery.verification(str(instantly_id))
        if verification.status == "pending":
            return self._wait(
                claim,
                verification_status=verification.verification_status,
                instantly_id=str(instantly_id),
            )
        if verification.status == "failed":
            return self._failed(
                claim,
                campaign_id=str(campaign_id),
                instantly_id=str(instantly_id),
                verification_status=verification.verification_status,
                error_code=str(verification.error_code),
            )
        return self._accepted(
            claim,
            campaign_id=str(campaign_id),
            instantly_id=str(instantly_id),
            imported=imported,
        )

    def _finish_already_sent(
        self, claim: _Claim, connection: sa.Connection
    ) -> WorkerOutcome | None:
        """Reuse accepted state under request/item/target locks without provider calls.

        Terminal items remain activation retry carriers. A nonterminal item may
        observe a target accepted elsewhere, including during verification GET.
        """
        request_id = str(claim.request["request_id"])
        target_id = str(claim.target["target_id"])
        target = (
            connection.execute(
                sa.select(prospect_target.c.instantly_id, prospect_target.c.instantly_accepted_at)
                .join(
                    prospect_send_item,
                    prospect_send_item.c.target_id == prospect_target.c.target_id,
                )
                .where(
                    prospect_target.c.target_id == target_id,
                    prospect_target.c.status == "sent",
                    prospect_send_item.c.request_id == request_id,
                    prospect_send_item.c.status == "running",
                    self._lease_matches(request_id, claim.lease_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if target is None:
            return None
        now = claim.clock()
        connection.execute(
            sa.update(prospect_send_item)
            .where(
                prospect_send_item.c.request_id == request_id,
                prospect_send_item.c.target_id == target_id,
                self._lease_matches(request_id, claim.lease_id),
            )
            .values(
                status="sent",
                instantly_id=target["instantly_id"] or prospect_send_item.c.instantly_id,
                verification_status=1,
                completed_at=target["instantly_accepted_at"] or now,
                updated_at=now,
                error_code=None,
                error_message=None,
            )
        )
        _, sent, _, final_status = self._counts(connection, request_id)
        request = (
            connection.execute(
                sa.select(prospect_send_request).where(
                    prospect_send_request.c.request_id == request_id
                )
            )
            .mappings()
            .one()
        )
        activation = (request["result"] or {}).get("activation")
        activated = isinstance(activation, dict) and activation.get("state") == "active"
        activation_due = sent and request["provider_campaign_id"] and not activated
        status = "waiting" if final_status is None or activation_due else final_status
        self._release_with_counts(
            connection,
            claim,
            now=now,
            status=status,
            next_attempt=now if status == "waiting" else None,
            completed=status != "waiting",
        )
        return WorkerOutcome(status, request_id, target_id)

    @staticmethod
    def _delivery_target(row: dict[str, object]) -> DeliveryTarget:
        return DeliveryTarget(
            target_id=str(row["target_id"]),
            email=str(row["email_address"]),
            company_name=str(row["company_name"]),
            director_name=row.get("director_name"),
            subject=str(row["mail_subject"]),
            text=str(row["mail_text"]),
            html=str(row["mail_html"]),
        )

    def _persist_campaign(
        self, claim: _Claim, campaign_id: str, *, now: dt.datetime, connection: sa.Connection
    ) -> bool:
        request_id = str(claim.request["request_id"])
        updated = connection.execute(
            sa.update(prospect_send_request)
            .where(
                prospect_send_request.c.request_id == request_id,
                prospect_send_request.c.lease_id == claim.lease_id,
                prospect_send_request.c.status == "running",
            )
            .values(provider_campaign_id=campaign_id, updated_at=now)
        )
        if updated.rowcount != 1:
            return False
        connection.execute(
            sa.update(prospect_target)
            .where(
                prospect_target.c.target_id == claim.target["target_id"],
                prospect_target.c.send_request_id == request_id,
                self._lease_matches(request_id, claim.lease_id),
            )
            .values(provider_campaign_id=campaign_id, updated_at=now)
        )
        return True

    def _persist_lead(
        self,
        claim: _Claim,
        campaign_id: str,
        instantly_id: str,
        *,
        now: dt.datetime,
        connection: sa.Connection,
    ) -> bool:
        request_id = str(claim.request["request_id"])
        item = connection.execute(
            sa.update(prospect_send_item)
            .where(
                prospect_send_item.c.request_id == request_id,
                prospect_send_item.c.target_id == claim.target["target_id"],
                self._lease_matches(request_id, claim.lease_id),
            )
            .values(instantly_id=instantly_id, updated_at=now)
        )
        if item.rowcount != 1:
            return False
        connection.execute(
            sa.update(prospect_target)
            .where(
                prospect_target.c.target_id == claim.target["target_id"],
                prospect_target.c.send_request_id == request_id,
                self._lease_matches(request_id, claim.lease_id),
            )
            .values(
                provider_campaign_id=campaign_id,
                instantly_id=instantly_id,
                updated_at=now,
            )
        )
        return True

    def _wait(
        self,
        claim: _Claim,
        *,
        verification_status: int | None = None,
        instantly_id: str | None = None,
        error: str | None = None,
        connection: sa.Connection | None = None,
    ) -> WorkerOutcome:
        request_id = str(claim.request["request_id"])
        transaction = (
            nullcontext(connection) if connection is not None else self._mutation_guard(claim)
        )
        with transaction as guarded_connection:
            if guarded_connection is None:
                return WorkerOutcome("lost", request_id, str(claim.target["target_id"]))
            if completed := self._finish_already_sent(claim, guarded_connection):
                return completed
            now = claim.clock()
            next_attempt = now + RETRY_DELAY
            current_status = guarded_connection.scalar(
                sa.select(prospect_send_item.c.status).where(
                    prospect_send_item.c.request_id == request_id,
                    prospect_send_item.c.target_id == claim.target["target_id"],
                    self._lease_matches(request_id, claim.lease_id),
                )
            )
            if current_status is None:
                return WorkerOutcome("lost", request_id, str(claim.target["target_id"]))
            terminal = current_status in _TERMINAL
            item = guarded_connection.execute(
                sa.update(prospect_send_item)
                .where(
                    prospect_send_item.c.request_id == request_id,
                    prospect_send_item.c.target_id == claim.target["target_id"],
                    self._lease_matches(request_id, claim.lease_id),
                )
                .values(
                    status=(
                        str(current_status)
                        if terminal
                        else ("verification_pending" if instantly_id else "queued")
                    ),
                    instantly_id=instantly_id or prospect_send_item.c.instantly_id,
                    verification_status=(
                        prospect_send_item.c.verification_status
                        if terminal
                        else verification_status
                    ),
                    error_code=(
                        prospect_send_item.c.error_code
                        if terminal
                        else ("instantly_provider_error" if error else None)
                    ),
                    error_message=(
                        prospect_send_item.c.error_message
                        if terminal
                        else (error[:1000] if error else None)
                    ),
                    next_attempt_at=next_attempt,
                    updated_at=now,
                )
            )
            if item.rowcount != 1:
                return WorkerOutcome("lost", request_id, str(claim.target["target_id"]))
            self._release_with_counts(
                guarded_connection,
                claim,
                now=now,
                status="waiting",
                next_attempt=next_attempt,
                error=error[:1000] if error else None,
            )
        return WorkerOutcome("waiting", request_id, str(claim.target["target_id"]))

    def _retry(
        self, claim: _Claim, *, error: Exception, connection: sa.Connection | None = None
    ) -> WorkerOutcome:
        public_error = "Instantly provider request failed"
        if isinstance(error, ReconciliationRequired):
            message = str(error)
            public_error = (
                message
                if message
                in {
                    "reconciliation_required: multiple campaigns",
                    "reconciliation_required: multiple leads",
                }
                else "reconciliation_required: ambiguous provider state"
            )
        return self._wait(claim, error=public_error, connection=connection)

    def _accepted(
        self,
        claim: _Claim,
        *,
        campaign_id: str,
        instantly_id: str,
        imported: bool,
    ) -> WorkerOutcome:
        request_id = str(claim.request["request_id"])
        target_id = str(claim.target["target_id"])
        with self._mutation_guard(claim) as connection:
            if connection is None:
                return WorkerOutcome("lost", request_id, target_id)
            if completed := self._finish_already_sent(claim, connection):
                return completed
            now = claim.clock()
            item = connection.execute(
                sa.update(prospect_send_item)
                .where(
                    prospect_send_item.c.request_id == request_id,
                    prospect_send_item.c.target_id == target_id,
                    self._lease_matches(request_id, claim.lease_id),
                )
                .values(
                    status="sent",
                    instantly_id=instantly_id,
                    verification_status=1,
                    error_code=None,
                    error_message=None,
                    completed_at=now,
                    updated_at=now,
                )
            )
            if item.rowcount != 1:
                return WorkerOutcome("lost", request_id, target_id)
            connection.execute(
                sa.update(prospect_target)
                .where(
                    prospect_target.c.target_id == target_id,
                    prospect_target.c.send_request_id == request_id,
                    self._lease_matches(request_id, claim.lease_id),
                )
                .values(
                    status="sent",
                    provider_campaign_id=campaign_id,
                    instantly_id=instantly_id,
                    instantly_accepted_at=now,
                    instantly_credit_units=prospect_target.c.instantly_credit_units
                    + (1 if imported else 0),
                    instantly_request_count=prospect_target.c.instantly_request_count + 1,
                    version=prospect_target.c.version + 1,
                    updated_at=now,
                )
            )
            final_status = self._counts(connection, request_id)[3]
            if final_status is None:
                self._release_with_counts(
                    connection, claim, now=now, status="waiting", next_attempt=now
                )
                return WorkerOutcome("waiting", request_id, target_id)
        return self._finalize(claim, campaign_id=campaign_id, status=final_status)

    def _failed(
        self,
        claim: _Claim,
        *,
        campaign_id: str,
        instantly_id: str,
        verification_status: int | None,
        error_code: str,
    ) -> WorkerOutcome:
        request_id = str(claim.request["request_id"])
        target_id = str(claim.target["target_id"])
        with self._mutation_guard(claim) as connection:
            if connection is None:
                return WorkerOutcome("lost", request_id, target_id)
            if completed := self._finish_already_sent(claim, connection):
                return completed
            now = claim.clock()
            item = connection.execute(
                sa.update(prospect_send_item)
                .where(
                    prospect_send_item.c.request_id == request_id,
                    prospect_send_item.c.target_id == target_id,
                    self._lease_matches(request_id, claim.lease_id),
                )
                .values(
                    status="failed",
                    instantly_id=instantly_id,
                    verification_status=verification_status,
                    error_code=error_code,
                    error_message=error_code.replace("_", " ")[:1000],
                    completed_at=now,
                    updated_at=now,
                )
            )
            if item.rowcount != 1:
                return WorkerOutcome("lost", request_id, target_id)
            connection.execute(
                sa.update(prospect_target)
                .where(
                    prospect_target.c.target_id == target_id,
                    prospect_target.c.send_request_id == request_id,
                    self._lease_matches(request_id, claim.lease_id),
                )
                .values(
                    status="approved",
                    provider_campaign_id=campaign_id,
                    instantly_id=instantly_id,
                    send_request_id=None,
                    delivery_error=error_code.replace("_", " ")[:1000],
                    version=prospect_target.c.version + 1,
                    updated_at=now,
                )
            )
            final_status = self._counts(connection, request_id)[3]
            if final_status is None:
                self._release_with_counts(
                    connection, claim, now=now, status="waiting", next_attempt=now
                )
                return WorkerOutcome("waiting", request_id, target_id)
        return self._finalize(claim, campaign_id=campaign_id, status=final_status)

    def _counts(
        self, connection: sa.Connection, request_id: str
    ) -> tuple[int, int, int, str | None]:
        processed, sent, failed, total = connection.execute(
            sa.select(
                sa.func.count().filter(prospect_send_item.c.status.in_(_TERMINAL)),
                sa.func.count().filter(prospect_send_item.c.status == "sent"),
                sa.func.count().filter(prospect_send_item.c.status == "failed"),
                sa.func.count(),
            ).where(prospect_send_item.c.request_id == request_id)
        ).one()
        processed, sent, failed, total = map(int, (processed, sent, failed, total))
        final = None
        if processed == total:
            final = "completed" if failed == 0 else ("partial" if sent else "failed")
        return processed, sent, failed, final

    def _release_with_counts(
        self,
        connection: sa.Connection,
        claim: _Claim,
        *,
        now: dt.datetime,
        status: str,
        next_attempt: dt.datetime | None,
        completed: bool = False,
        error: str | None = None,
    ) -> bool:
        request_id = str(claim.request["request_id"])
        processed, sent, failed, _ = self._counts(connection, request_id)
        update = connection.execute(
            sa.update(prospect_send_request)
            .where(
                prospect_send_request.c.request_id == request_id,
                prospect_send_request.c.lease_id == claim.lease_id,
                prospect_send_request.c.status == "running",
            )
            .values(
                status=status,
                processed_count=processed,
                sent_count=sent,
                failed_count=failed,
                next_attempt_at=next_attempt,
                lease_id=None,
                lease_expires_at=None,
                updated_at=now,
                completed_at=now if completed else None,
                error=error,
            )
        )
        return update.rowcount == 1

    def _finalize(self, claim: _Claim, *, campaign_id: str, status: str) -> WorkerOutcome:
        request_id = str(claim.request["request_id"])
        target_id = str(claim.target["target_id"])
        with self._mutation_guard(claim) as connection:
            if connection is None:
                return WorkerOutcome("lost", request_id, target_id)
            if status in {"completed", "partial"}:
                result = self._result(claim, connection=connection)
                activation = result.get("activation")
                activated = isinstance(activation, dict) and activation.get("state") == "active"
                if not activated and not campaign_id:
                    return self._wait(
                        claim, error="campaign id missing for activation", connection=connection
                    )
                try:
                    if not activated and not self._delivery.campaign_active(campaign_id):
                        if self._kill_switch_path.exists():
                            return self._wait(
                                claim, error="activation deferred", connection=connection
                            )
                        self._delivery.activate(campaign_id)
                except Exception:  # noqa: BLE001 - terminal item remains terminal on retry
                    return self._wait(
                        claim, error="Instantly activation failed", connection=connection
                    )
                if not self._set_result(
                    claim,
                    {"activation": {"state": "active"}},
                    now=claim.clock(),
                    connection=connection,
                ):
                    return WorkerOutcome("lost", request_id, target_id)
            if not self._release_with_counts(
                connection,
                claim,
                now=claim.clock(),
                status=status,
                next_attempt=None,
                completed=True,
            ):
                return WorkerOutcome("lost", request_id, target_id)
        return WorkerOutcome(status, request_id, target_id)

    def _result(self, claim: _Claim, *, connection: sa.Connection) -> dict[str, object]:
        result = connection.scalar(
            sa.select(prospect_send_request.c.result).where(
                prospect_send_request.c.request_id == claim.request["request_id"],
                prospect_send_request.c.lease_id == claim.lease_id,
                prospect_send_request.c.status == "running",
            )
        )
        return dict(result) if isinstance(result, dict) else {}

    def _set_result(
        self,
        claim: _Claim,
        values: dict[str, object],
        *,
        now: dt.datetime,
        connection: sa.Connection,
    ) -> bool:
        current = self._result(claim, connection=connection)
        return (
            connection.execute(
                sa.update(prospect_send_request)
                .where(
                    prospect_send_request.c.request_id == claim.request["request_id"],
                    prospect_send_request.c.lease_id == claim.lease_id,
                    prospect_send_request.c.status == "running",
                )
                .values(result={**current, **values}, updated_at=now)
            ).rowcount
            == 1
        )


__all__ = ["ProspectSendWorker", "WorkerOutcome"]
