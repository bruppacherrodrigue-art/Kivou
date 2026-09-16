"""One-item, lease-protected worker for durable prospect-send requests."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field, replace
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
MAX_BATCH_LIMIT = 25
DEFAULT_BATCH_LIMIT = MAX_BATCH_LIMIT


@dataclass(frozen=True)
class WorkerOutcome:
    status: str
    request_id: str | None = None
    target_id: str | None = None


@dataclass
class _Operations:
    ready_reads: dict[str, list[str]] = field(default_factory=dict)
    phase_reads: list[str] = field(default_factory=list)
    ready_mutations: set[str] = field(default_factory=set)


class _DeclareOperation(Exception):
    def __init__(self, key: str | None, replay_reads: list[str]) -> None:
        self.key = key
        self.replay_reads = replay_reads


@dataclass(frozen=True)
class _Claim:
    request: dict[str, object]
    item: dict[str, object]
    target: dict[str, object]
    lease_id: str
    clock: Callable[[], dt.datetime]
    operations: _Operations = field(default_factory=_Operations)


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
        for _ in range(100):
            try:
                return self._process(claim)
            except _DeclareOperation as operation:
                if outcome := self._declare_operation(claim, operation):
                    return outcome
            except Exception as error:  # noqa: BLE001 - provider boundary is made durable
                return self._retry(claim, error=error)
        return self._retry(claim, error=ReconciliationRequired("declaration limit"))

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
                sa.or_(
                    prospect_send_item.c.error_code.is_(None),
                    prospect_send_item.c.error_code != "recovery_already_accepted",
                ),
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
        with self._mutation_guard(claim) as connection:
            if connection is None:
                return WorkerOutcome("lost", request_id, target_id)
            if completed := self._check_target(claim, connection):
                return completed
            claim = replace(
                claim,
                request=dict(
                    connection.execute(
                        sa.select(prospect_send_request).where(
                            prospect_send_request.c.request_id == request_id
                        )
                    )
                    .mappings()
                    .one()
                ),
                item=dict(
                    connection.execute(
                        sa.select(prospect_send_item).where(
                            prospect_send_item.c.request_id == request_id,
                            prospect_send_item.c.target_id == target_id,
                        )
                    )
                    .mappings()
                    .one()
                ),
                target=dict(
                    connection.execute(
                        sa.select(prospect_target).where(prospect_target.c.target_id == target_id)
                    )
                    .mappings()
                    .one()
                ),
            )
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
            claim.operations.phase_reads = []
            with self._mutation_guard(claim) as connection:
                if connection is None:
                    return WorkerOutcome("lost", request_id, target_id)
                if completed := self._check_target(claim, connection):
                    return completed
                try:
                    campaign_id = self._delivery.find_campaign(
                        claim.request,
                        at=claim.clock(),
                        before_read=lambda cursor: self._require_read(
                            claim, f"campaign:list:{cursor}"
                        ),
                    )
                    if not campaign_id:
                        if self._kill_switch_path.exists():
                            return self._wait(
                                claim, error="kill switch active", connection=connection
                            )
                        self._require_mutation(claim, "campaign:create")
                        campaign_id = self._delivery.ensure_campaign(
                            claim.request, at=claim.clock()
                        )
                except _DeclareOperation:
                    raise
                except Exception as error:  # noqa: BLE001 - public durable retry
                    return self._retry(claim, error=error, connection=connection)
                if not self._persist_campaign(
                    claim, campaign_id, now=claim.clock(), connection=connection
                ):
                    return WorkerOutcome("lost", request_id, target_id)
        instantly_id = claim.item.get("instantly_id") or claim.target.get("instantly_id")
        if not instantly_id:
            claim.operations.phase_reads = []
            with self._mutation_guard(claim) as connection:
                if connection is None:
                    return WorkerOutcome("lost", request_id, target_id)
                if completed := self._check_target(claim, connection):
                    return completed
                try:
                    instantly_id = self._delivery.find_lead(
                        str(campaign_id),
                        str(claim.target["email_address"]),
                        before_read=lambda cursor: self._require_read(
                            claim, f"lead:{target_id}:list:{cursor}"
                        ),
                    )
                    if not instantly_id:
                        if self._kill_switch_path.exists():
                            return self._wait(
                                claim, error="kill switch active", connection=connection
                            )
                        self._require_mutation(claim, f"lead:{target_id}:import")
                        instantly_id = self._delivery.import_target(
                            str(campaign_id), self._delivery_target(claim.target)
                        )
                except _DeclareOperation:
                    raise
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
                self._confirm_import(claim, connection)

        claim.operations.phase_reads = []
        with self._mutation_guard(claim) as connection:
            if connection is None:
                return WorkerOutcome("lost", request_id, target_id)
            if completed := self._check_target(claim, connection):
                return completed
            self._require_read(claim, f"lead:{target_id}:verification")
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
        )

    def _check_target(self, claim: _Claim, connection: sa.Connection) -> WorkerOutcome | None:
        if completed := self._finish_already_sent(claim, connection):
            return completed
        item = (
            connection.execute(
                sa.select(prospect_send_item).where(
                    prospect_send_item.c.request_id == claim.request["request_id"],
                    prospect_send_item.c.target_id == claim.target["target_id"],
                )
            )
            .mappings()
            .one()
        )
        if item["status"] in _TERMINAL:
            return None
        target = (
            connection.execute(
                sa.select(prospect_target).where(
                    prospect_target.c.target_id == claim.target["target_id"],
                )
            )
            .mappings()
            .one()
        )
        if (
            target["status"] != "approved"
            or target["send_request_id"] != item["request_id"]
            or target["version"] != item["expected_version"]
        ):
            return self._reject_changed_target(claim, connection, "target_changed_after_enqueue")
        if (
            item["instantly_id"]
            and target["instantly_id"]
            and (item["instantly_id"] != target["instantly_id"])
        ):
            return self._reject_changed_target(claim, connection, "lead_binding_conflict")
        campaign_id = connection.scalar(
            sa.select(prospect_send_request.c.provider_campaign_id).where(
                prospect_send_request.c.request_id == item["request_id"],
            )
        )
        target_campaign = target["provider_campaign_id"]
        if (target["instantly_id"] and not target_campaign) or (
            campaign_id and target_campaign and campaign_id != target_campaign
        ):
            return self._reject_changed_target(claim, connection, "campaign_binding_conflict")
        if target_campaign and not campaign_id:
            connection.execute(
                sa.update(prospect_send_request)
                .where(
                    prospect_send_request.c.request_id == item["request_id"],
                )
                .values(provider_campaign_id=target_campaign, updated_at=claim.clock())
            )
        if target["instantly_id"] and not item["instantly_id"]:
            # Snapshot reused exposure while its binding is still authorized.
            # A correction during verification GET can clear the target cache,
            # but must not erase this request's evidence for activation safety.
            connection.execute(
                sa.update(prospect_send_item)
                .where(
                    prospect_send_item.c.request_id == item["request_id"],
                    prospect_send_item.c.target_id == item["target_id"],
                    self._lease_matches(str(item["request_id"]), claim.lease_id),
                )
                .values(instantly_id=target["instantly_id"], updated_at=claim.clock())
            )
        return None

    def _reject_changed_target(
        self, claim: _Claim, connection: sa.Connection, code: str
    ) -> WorkerOutcome:
        now = claim.clock()
        request_id, target_id = str(claim.request["request_id"]), str(claim.target["target_id"])
        connection.execute(
            sa.update(prospect_send_item)
            .where(
                prospect_send_item.c.request_id == request_id,
                prospect_send_item.c.target_id == target_id,
                self._lease_matches(request_id, claim.lease_id),
            )
            .values(
                status="failed",
                error_code=code,
                error_message=code.replace("_", " "),
                completed_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            sa.update(prospect_target)
            .where(
                prospect_target.c.target_id == target_id,
                prospect_target.c.send_request_id == request_id,
                prospect_target.c.status != "sent",
            )
            .values(send_request_id=None)
        )
        request = (
            connection.execute(
                sa.select(prospect_send_request).where(
                    prospect_send_request.c.request_id == request_id
                )
            )
            .mappings()
            .one()
        )
        exposed_lead = connection.scalar(
            sa.select(prospect_send_item.c.instantly_id).where(
                prospect_send_item.c.request_id == request_id,
                prospect_send_item.c.target_id == target_id,
            )
        )
        campaign_id = request["provider_campaign_id"]
        receipt = self._accounting(claim, connection).get(f"lead:{target_id}:import", {})
        # A cancelled, never-exposed sibling must not prevent valid siblings
        # from sending. An import intent is conservative evidence even after a
        # crash rolled back the local lead ID or an edit changed its binding.
        exposed = campaign_id and (
            exposed_lead
            or (
                receipt.get("zero_matches")
                and receipt.get("campaign_id", campaign_id) == campaign_id
            )
        )
        if exposed:
            self._set_result(claim, {"activation_blocked": code}, now=now, connection=connection)
        result = self._result(claim, connection=connection)
        blocked = result.get("activation_blocked")
        _, sent, _, final_status = self._counts(connection, request_id)
        status = final_status or "waiting"
        if blocked or (sent and self._activation_due(campaign_id, result)):
            status = "waiting"
        error = self._blocked_error(blocked) if blocked else code
        self._release_with_counts(
            connection,
            claim,
            now=now,
            status=status,
            next_attempt=(now + RETRY_DELAY if blocked else now) if status == "waiting" else None,
            completed=status != "waiting",
            error=error,
        )
        return WorkerOutcome(status, request_id, target_id)

    @staticmethod
    def _require_read(claim: _Claim, label: str) -> None:
        ready = claim.operations.ready_reads.get(label)
        if not ready:
            raise _DeclareOperation(None, [*claim.operations.phase_reads, label])
        ready.pop(0)
        claim.operations.phase_reads.append(label)

    @staticmethod
    def _require_mutation(claim: _Claim, key: str) -> None:
        if key not in claim.operations.ready_mutations:
            # Called only after a complete scan established absence/inactivity.
            raise _DeclareOperation(key, list(claim.operations.phase_reads))
        # A receipt deduplicates import credit, never future POST attempts. The
        # in-memory permit is consumed even if this attempt returns 429 or fails.
        claim.operations.ready_mutations.remove(key)

    @staticmethod
    def _read_phase(label: str) -> str:
        # Cursor identities are transient replay information, not ledger keys.
        return label.split(":list:", 1)[0] + ":list" if ":list:" in label else label

    def _accounting(self, claim: _Claim, connection: sa.Connection) -> dict[str, dict]:
        ledger = self._result(claim, connection=connection).get("accounting", {})
        accounting = {}
        for key, entry in ledger.items():
            if entry.get("kind") != "read":
                accounting[key] = dict(entry)
                continue
            phase = self._read_phase(key)
            previous = accounting.get(phase, {})
            # Compact legacy per-cursor receipts without changing historical
            # target totals. One aggregate and one current receipt per phase.
            accounting[phase] = {
                "kind": "read",
                "receipt": entry.get("receipt"),
                "read_count": previous.get("read_count", 0)
                + entry.get("read_count", entry.get("attempts", 0)),
            }
        return accounting

    def _declare_operation(
        self, claim: _Claim, operation: _DeclareOperation
    ) -> WorkerOutcome | None:
        """Durably declare HTTP attempts before calling the provider.

        Mutation keys identify one logical operation through ambiguous retries;
        attempt_count and target totals increment before EACH new POST attempt.
        Each reconciliation/verification read gets a distinct receipt, including
        re-reads required after declaring a mutation and reopening the guard.
        A crash can leave a declared attempt without a response; these counters
        audit declared attempts, not a claim of exact provider billing.
        """
        ready: dict[str, list[str]] = {}
        with self._mutation_guard(claim) as connection:
            if connection is None:
                return WorkerOutcome(
                    "lost", str(claim.request["request_id"]), str(claim.target["target_id"])
                )
            if outcome := self._check_target(claim, connection):
                return outcome
            accounting = self._accounting(claim, connection)
            requests = 0
            if operation.key is not None:
                request = (
                    connection.execute(
                        sa.select(prospect_send_request).where(
                            prospect_send_request.c.request_id == claim.request["request_id"]
                        )
                    )
                    .mappings()
                    .one()
                )
                previous = accounting.get(operation.key, {})
                accounting[operation.key] = {
                    "kind": "mutation",
                    "confirmed": False,
                    "zero_matches": True,
                    **previous,
                    "attempt_count": int(previous.get("attempt_count", bool(previous))) + 1,
                    "campaign_id": request["provider_campaign_id"],
                }
                if operation.key == "campaign:create":
                    # The exact prior name was fully scanned and absent. Any
                    # new creation uses the full identity, including a legacy
                    # retry; reopening the guard re-scans this declared name.
                    accounting[operation.key]["campaign_name"] = self._delivery.campaign_name(
                        {
                            "request_id": request["request_id"],
                            "request_day": request["request_day"],
                        },
                        at=claim.clock(),
                    )
                requests += 1
            for label in operation.replay_reads:
                token = str(uuid.uuid4())
                phase = self._read_phase(label)
                previous = accounting.get(phase, {})
                accounting[phase] = {
                    "kind": "read",
                    "receipt": token,
                    "read_count": int(previous.get("read_count", 0)) + 1,
                }
                ready.setdefault(label, []).append(token)
                requests += 1
            now = claim.clock()
            connection.execute(
                sa.update(prospect_target)
                .where(
                    prospect_target.c.target_id == claim.target["target_id"],
                    self._lease_matches(str(claim.request["request_id"]), claim.lease_id),
                )
                .values(
                    instantly_request_count=prospect_target.c.instantly_request_count + requests,
                    updated_at=now,
                )
            )
            self._set_result(claim, {"accounting": accounting}, now=now, connection=connection)
        claim.operations.ready_reads = ready
        if operation.key is not None:
            claim.operations.ready_mutations.add(operation.key)
        return None

    def _confirm_import(self, claim: _Claim, connection: sa.Connection) -> None:
        accounting = self._accounting(claim, connection)
        key = f"lead:{claim.target['target_id']}:import"
        intent = accounting.get(key)
        if (
            not isinstance(intent, dict)
            or not intent.get("zero_matches")
            or intent.get("confirmed")
        ):
            return
        # This covers a returned import or the unique scoped lead reconciled
        # after remote success/DB rollback. Existing leads without intent cost no credit.
        connection.execute(
            sa.update(prospect_target)
            .where(
                prospect_target.c.target_id == claim.target["target_id"],
                self._lease_matches(str(claim.request["request_id"]), claim.lease_id),
            )
            .values(instantly_credit_units=prospect_target.c.instantly_credit_units + 1)
        )
        accounting[key] = {**intent, "confirmed": True}
        self._set_result(
            claim, {"accounting": accounting}, now=claim.clock(), connection=connection
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
        activation_due = sent and self._activation_due(
            request["provider_campaign_id"], request["result"] or {}
        )
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
            if completed := self._check_target(claim, guarded_connection):
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
    ) -> WorkerOutcome:
        request_id = str(claim.request["request_id"])
        target_id = str(claim.target["target_id"])
        with self._mutation_guard(claim) as connection:
            if connection is None:
                return WorkerOutcome("lost", request_id, target_id)
            if completed := self._check_target(claim, connection):
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
                    delivery_error=None,
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
            if completed := self._check_target(claim, connection):
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
        # A sibling's pending/accepted transition must not hide the durable
        # recovery requirement of a previously exposed, cancelled target.
        if blocked := self._result(claim, connection=connection).get("activation_blocked"):
            error = self._blocked_error(blocked)
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
        claim.operations.phase_reads = []
        with self._mutation_guard(claim) as connection:
            if connection is None:
                return WorkerOutcome("lost", request_id, target_id)
            result = self._result(claim, connection=connection)
            if blocked := result.get("activation_blocked"):
                return self._wait(claim, error=self._blocked_error(blocked), connection=connection)
            if status in {"completed", "partial"}:
                activation = result.get("activation")
                activated = isinstance(activation, dict) and activation.get("state") == "active"
                if not activated and not campaign_id:
                    return self._wait(
                        claim, error="campaign id missing for activation", connection=connection
                    )
                try:
                    if not activated:
                        self._require_read(claim, "campaign:status")
                        activated = self._delivery.campaign_active(campaign_id)
                    if not activated:
                        if self._kill_switch_path.exists():
                            return self._wait(
                                claim, error="activation deferred", connection=connection
                            )
                        self._require_mutation(claim, "campaign:activate")
                        self._delivery.activate(campaign_id)
                except _DeclareOperation:
                    raise
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

    @staticmethod
    def _activation_due(campaign_id: object, result: dict) -> bool:
        activation = result.get("activation")
        activated = isinstance(activation, dict) and activation.get("state") == "active"
        return bool(campaign_id) and not activated

    @staticmethod
    def _blocked_error(code: object) -> str:
        return f"Activation blocked ({code}); reconcile imported lead before activation"[:1000]

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


class _SafeArgumentParser(argparse.ArgumentParser):
    """Keep process-boundary diagnostics structured and free of input echoes."""

    def error(self, _message: str) -> None:
        raise ValueError("invalid prospect send worker arguments")


def _batch_limit(value: str) -> int:
    try:
        limit = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("limit must be an integer") from error
    if not 1 <= limit <= MAX_BATCH_LIMIT:
        raise argparse.ArgumentTypeError(f"limit must be between 1 and {MAX_BATCH_LIMIT}")
    return limit


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        prog="python -m signals.prospection_actions.worker",
        add_help=False,
    )
    parser.add_argument("--limit", type=_batch_limit, default=DEFAULT_BATCH_LIMIT)
    return parser


def _run_batch(worker: ProspectSendWorker, *, limit: int, worker_ref: str) -> dict[str, int]:
    outcomes: dict[str, int] = {}
    for _ in range(limit):
        outcome = worker.run_once(worker_ref=worker_ref)
        status = outcome.status[:64]
        outcomes[status] = outcomes.get(status, 0) + 1
        if status == "idle":
            break
    return outcomes


def _run_production_batch(*, limit: int, worker_ref: str) -> dict[str, int]:
    """Build one short-lived production composition and always release its resources."""

    import httpx

    from signals.founder_api.actions_composition import build_prospect_send_worker
    from signals.founder_api.database import create_founder_write_database_engine

    engine: Engine | None = None
    client: httpx.Client | None = None
    try:
        engine = create_founder_write_database_engine()
        client = httpx.Client(timeout=60.0, follow_redirects=False)
        worker = build_prospect_send_worker(engine, client=client)
        return _run_batch(worker, limit=limit, worker_ref=worker_ref)
    finally:
        try:
            if client is not None:
                client.close()
        finally:
            if engine is not None:
                engine.dispose()


def _summary(*, status: str, limit: int | None, outcomes: dict[str, int]) -> str:
    payload: dict[str, object] = {"outcomes": outcomes, "status": status}
    if limit is not None:
        payload["limit"] = limit
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def main(
    argv: list[str] | None = None,
    *,
    worker_factory: Callable[[], ProspectSendWorker] | None = None,
) -> int:
    """Run a timer-invoked, bounded batch; item failures stay durable and non-fatal."""

    try:
        arguments = _parser().parse_args(argv)
    except (SystemExit, ValueError):
        print(_summary(status="configuration_invalid", limit=None, outcomes={}))
        return 2

    worker_ref = f"prospect-send:{os.getpid()}"
    try:
        if worker_factory is None:
            outcomes = _run_production_batch(limit=arguments.limit, worker_ref=worker_ref)
        else:
            outcomes = _run_batch(worker_factory(), limit=arguments.limit, worker_ref=worker_ref)
    except Exception:  # noqa: BLE001 - process boundary must not leak provider details
        print(_summary(status="operational_failure", limit=arguments.limit, outcomes={}))
        return 1
    print(_summary(status="ok", limit=arguments.limit, outcomes=outcomes))
    return 0


if __name__ == "__main__":  # pragma: no cover - module entrypoint
    raise SystemExit(main())


__all__ = [
    "DEFAULT_BATCH_LIMIT",
    "MAX_BATCH_LIMIT",
    "ProspectSendWorker",
    "WorkerOutcome",
    "main",
]
