"""One-item, lease-protected worker for durable prospect-send requests."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.persistence.schema import prospect_send_item, prospect_send_request, prospect_target
from signals.prospection_actions.delivery import (
    AssistedInstantlyDelivery,
    AssistedInstantlyProvider,
)
from signals.prospection_actions.service import DeliveryTarget

LEASE = dt.timedelta(minutes=5)
MUTATION_HORIZON = dt.timedelta(minutes=15)
# Instantly clients used here must have a bounded timeout below this horizon;
# composition owns that transport invariant.  A lease is never held in a DB
# transaction while the network call is in flight.
MAX_PROVIDER_TIMEOUT = dt.timedelta(minutes=5)
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


class ProspectSendWorker:
    def __init__(
        self,
        engine: Engine,
        *,
        provider: AssistedInstantlyProvider,
        provider_account_id: str,
        kill_switch_path: Path = Path("/etc/kivou/acquisition.disabled"),
    ) -> None:
        timeout_seconds = getattr(
            provider, "mutation_timeout_seconds", MAX_PROVIDER_TIMEOUT.total_seconds()
        )
        if (
            not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
            or timeout_seconds >= MUTATION_HORIZON.total_seconds()
        ):
            raise ValueError("provider timeout must be bounded below the mutation lease horizon")
        self._engine = engine
        self._delivery = AssistedInstantlyDelivery(
            provider=provider, provider_account_id=provider_account_id
        )
        self._kill_switch_path = kill_switch_path

    def run_once(self, *, worker_ref: str, now: dt.datetime) -> WorkerOutcome:
        if now.tzinfo is None or not worker_ref or len(worker_ref) > 320:
            raise ValueError("worker_ref and now must be bounded and timezone-aware")
        claim = self._claim(worker_ref=worker_ref, now=now)
        if claim is None:
            return WorkerOutcome("idle")
        try:
            return self._process(claim, now=now)
        except Exception as error:  # noqa: BLE001 - provider boundary is made durable
            return self._retry(claim, now=now, error=error)

    def _claim(self, *, worker_ref: str, now: dt.datetime) -> _Claim | None:
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
        with self._engine.begin() as connection:
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
            item = dict(
                connection.execute(
                    sa.select(prospect_send_item).where(
                        prospect_send_item.c.request_id == row["request_id"],
                        prospect_send_item.c.target_id == row["target_id"],
                    )
                )
                .mappings()
                .one()
            )
            target = dict(
                connection.execute(
                    sa.select(prospect_target).where(
                        prospect_target.c.target_id == row["target_id"]
                    )
                )
                .mappings()
                .one()
            )
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
            return _Claim(request=request, item=item, target=target, lease_id=lease_id)

    @staticmethod
    def _lease_matches(request_id: str, lease_id: str):
        return sa.exists(
            sa.select(sa.literal(1)).where(
                prospect_send_request.c.request_id == request_id,
                prospect_send_request.c.lease_id == lease_id,
                prospect_send_request.c.status == "running",
            )
        )

    def _process(self, claim: _Claim, *, now: dt.datetime) -> WorkerOutcome:
        request_id = str(claim.request["request_id"])
        target_id = str(claim.target["target_id"])
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
                now=now,
                campaign_id=str(campaign_id or ""),
                status=final_status,
            )
        campaign_id = claim.request.get("provider_campaign_id") or claim.target.get(
            "provider_campaign_id"
        )
        if not campaign_id:
            result = self._result(claim)
            if result is None:
                return WorkerOutcome("lost", request_id, target_id)
            if result.get("reconcile") == "campaign":
                campaign_id = self._delivery.find_campaign(claim.request, at=now)
                if campaign_id and not self._persist_campaign(claim, campaign_id, now=now):
                    return WorkerOutcome("lost", request_id, target_id)
            if campaign_id:
                claim = _Claim(
                    request={**claim.request, "provider_campaign_id": campaign_id},
                    item=claim.item,
                    target={**claim.target, "provider_campaign_id": campaign_id},
                    lease_id=claim.lease_id,
                )
            else:
                if not self._extend_mutation_lease(claim, now):
                    return WorkerOutcome("lost", request_id, target_id)
                if not self._set_result(claim, {"reconcile": "campaign"}, now):
                    return WorkerOutcome("lost", request_id, target_id)
                if self._kill_switch_path.exists():
                    return self._wait(claim, now=now, error="kill switch active")
                campaign_id = self._delivery.ensure_campaign(claim.request, at=now)
                if not self._persist_campaign(claim, campaign_id, now=now):
                    return WorkerOutcome("lost", request_id, target_id)

        instantly_id = claim.item.get("instantly_id") or claim.target.get("instantly_id")
        imported = False
        if not instantly_id:
            result = self._result(claim)
            if result is None:
                return WorkerOutcome("lost", request_id, target_id)
            if result.get("reconcile") == "lead":
                instantly_id = self._delivery.find_lead(
                    str(campaign_id), str(claim.target["email_address"])
                )
                if instantly_id and not self._persist_lead(
                    claim, str(campaign_id), instantly_id, now=now
                ):
                    return WorkerOutcome("lost", request_id, target_id)
            if not instantly_id:
                if not self._extend_mutation_lease(claim, now):
                    return WorkerOutcome("lost", request_id, target_id)
                if not self._set_result(claim, {"reconcile": "lead"}, now):
                    return WorkerOutcome("lost", request_id, target_id)
                if self._kill_switch_path.exists():
                    return self._wait(claim, now=now, error="kill switch active")
                instantly_id = self._delivery.import_target(
                    str(campaign_id), self._delivery_target(claim.target)
                )
                imported = True
                if not self._persist_lead(claim, str(campaign_id), instantly_id, now=now):
                    return WorkerOutcome("lost", request_id, target_id)

        verification = self._delivery.verification(str(instantly_id))
        if verification.status == "pending":
            return self._wait(
                claim,
                now=now,
                verification_status=verification.verification_status,
                instantly_id=str(instantly_id),
            )
        if verification.status == "failed":
            return self._failed(
                claim,
                now=now,
                campaign_id=str(campaign_id),
                instantly_id=str(instantly_id),
                verification_status=verification.verification_status,
                error_code=str(verification.error_code),
            )
        return self._accepted(
            claim,
            now=now,
            campaign_id=str(campaign_id),
            instantly_id=str(instantly_id),
            imported=imported,
        )

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

    def _persist_campaign(self, claim: _Claim, campaign_id: str, *, now: dt.datetime) -> bool:
        request_id = str(claim.request["request_id"])
        with self._engine.begin() as connection:
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
        self, claim: _Claim, campaign_id: str, instantly_id: str, *, now: dt.datetime
    ) -> bool:
        request_id = str(claim.request["request_id"])
        with self._engine.begin() as connection:
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
        now: dt.datetime,
        verification_status: int | None = None,
        instantly_id: str | None = None,
        error: str | None = None,
    ) -> WorkerOutcome:
        request_id = str(claim.request["request_id"])
        next_attempt = now + RETRY_DELAY
        with self._engine.begin() as connection:
            current_status = connection.scalar(
                sa.select(prospect_send_item.c.status).where(
                    prospect_send_item.c.request_id == request_id,
                    prospect_send_item.c.target_id == claim.target["target_id"],
                    self._lease_matches(request_id, claim.lease_id),
                )
            )
            if current_status is None:
                return WorkerOutcome("lost", request_id, str(claim.target["target_id"]))
            terminal = current_status in _TERMINAL
            item = connection.execute(
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
                connection,
                claim,
                now=now,
                status="waiting",
                next_attempt=next_attempt,
                error=error[:1000] if error else None,
            )
        return WorkerOutcome("waiting", request_id, str(claim.target["target_id"]))

    def _retry(self, claim: _Claim, *, now: dt.datetime, error: Exception) -> WorkerOutcome:
        return self._wait(claim, now=now, error=str(error))

    def _accepted(
        self,
        claim: _Claim,
        *,
        now: dt.datetime,
        campaign_id: str,
        instantly_id: str,
        imported: bool,
    ) -> WorkerOutcome:
        request_id = str(claim.request["request_id"])
        target_id = str(claim.target["target_id"])
        with self._engine.begin() as connection:
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
        return self._finalize(claim, now=now, campaign_id=campaign_id, status=final_status)

    def _failed(
        self,
        claim: _Claim,
        *,
        now: dt.datetime,
        campaign_id: str,
        instantly_id: str,
        verification_status: int | None,
        error_code: str,
    ) -> WorkerOutcome:
        request_id = str(claim.request["request_id"])
        target_id = str(claim.target["target_id"])
        with self._engine.begin() as connection:
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
        return self._finalize(claim, now=now, campaign_id=campaign_id, status=final_status)

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

    def _finalize(
        self, claim: _Claim, *, now: dt.datetime, campaign_id: str, status: str
    ) -> WorkerOutcome:
        request_id = str(claim.request["request_id"])
        target_id = str(claim.target["target_id"])
        activated = False
        if status in {"completed", "partial"}:
            result = self._result(claim)
            if result is None:
                return WorkerOutcome("lost", request_id, target_id)
            activation = result.get("activation") if isinstance(result, dict) else None
            activated = isinstance(activation, dict) and activation.get("state") == "active"
            if not activated and not campaign_id:
                return self._wait(claim, now=now, error="campaign id missing for activation")
            try:
                # Reconciliation is the durable ambiguity fence: an interrupted
                # activate is always read back before another mutation is allowed.
                if not activated and self._delivery.campaign_active(campaign_id):
                    if not self._set_result(claim, {"activation": {"state": "active"}}, now):
                        return WorkerOutcome("lost", request_id, target_id)
                    activated = True
                if not activated:
                    if not self._extend_mutation_lease(claim, now):
                        return WorkerOutcome("lost", request_id, target_id)
                    if not self._set_result(claim, {"activation": {"state": "activating"}}, now):
                        return WorkerOutcome("lost", request_id, target_id)
                    if not self._lease_current(claim):
                        return WorkerOutcome("lost", request_id, target_id)
                    if self._kill_switch_path.exists():
                        return self._wait(claim, now=now, error="activation deferred")
                    self._delivery.activate(campaign_id)
                    if not self._set_result(claim, {"activation": {"state": "active"}}, now):
                        return WorkerOutcome("lost", request_id, target_id)
            except Exception:  # noqa: BLE001 - terminal item remains terminal on retry
                return self._wait(claim, now=now, error="Instantly activation failed")
        with self._engine.begin() as connection:
            if not self._release_with_counts(
                connection, claim, now=now, status=status, next_attempt=None, completed=True
            ):
                return WorkerOutcome("lost", request_id, target_id)
        return WorkerOutcome(status, request_id, target_id)

    def _result(self, claim: _Claim) -> dict[str, object] | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(prospect_send_request.c.result).where(
                        prospect_send_request.c.request_id == claim.request["request_id"],
                        prospect_send_request.c.lease_id == claim.lease_id,
                        prospect_send_request.c.status == "running",
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return dict(row["result"] or {}) if isinstance(row["result"], dict) else {}

    def _set_result(self, claim: _Claim, values: dict[str, object], now: dt.datetime) -> bool:
        current = self._result(claim)
        if current is None:
            return False
        with self._engine.begin() as connection:
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

    def _lease_current(self, claim: _Claim) -> bool:
        return self._result(claim) is not None

    def _extend_mutation_lease(self, claim: _Claim, now: dt.datetime) -> bool:
        if MAX_PROVIDER_TIMEOUT >= MUTATION_HORIZON:
            raise RuntimeError("provider timeout exceeds mutation lease horizon")
        with self._engine.begin() as connection:
            return (
                connection.execute(
                    sa.update(prospect_send_request)
                    .where(
                        prospect_send_request.c.request_id == claim.request["request_id"],
                        prospect_send_request.c.lease_id == claim.lease_id,
                        prospect_send_request.c.status == "running",
                    )
                    .values(lease_expires_at=now + MUTATION_HORIZON, updated_at=now)
                ).rowcount
                == 1
            )


__all__ = ["ProspectSendWorker", "WorkerOutcome"]
