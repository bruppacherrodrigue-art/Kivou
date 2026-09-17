"""Durable reservation and progress helpers for prospect-send requests."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.persistence.schema import (
    prospect_send_item,
    prospect_send_request,
    prospect_target,
    supplier_directory,
)
from signals.prospection_actions.contracts import (
    ProspectStatus,
    SendItemProgress,
    SendRequestProgress,
)
from signals.supplier_directory.email_quality import (
    is_consumer_mailbox,
    is_placeholder_email,
)

ErrorFactory = Callable[..., Exception]
LockedRows = Callable[..., tuple[sa.RowMapping, ...]]
DirectoryValidator = Callable[[dict[str, object], sa.RowMapping | None], None]
SuppressionCheck = Callable[[sa.Connection, str, dt.datetime], bool]

_POSTGRES_QUOTA_LOCK_NAMESPACE = 61_408


@dataclass(frozen=True)
class SendReservation:
    request_id: str
    fingerprint: str
    target_rows: tuple[dict[str, object], ...]
    existing: dict[str, object] | None = None


def _existing_request(connection: sa.Connection, request_id: str) -> dict[str, object] | None:
    row = (
        connection.execute(
            sa.select(prospect_send_request).where(prospect_send_request.c.request_id == request_id)
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else dict(row)


def _is_request_id_conflict(error: sa.exc.IntegrityError) -> bool:
    original = error.orig
    diagnostic = getattr(original, "diag", None)
    constraint = getattr(diagnostic, "constraint_name", None)
    if constraint == "prospect_send_request_pkey":
        return True
    return "UNIQUE constraint failed: prospect_send_request.request_id" in str(original)


def _existing_reservation(
    *, request_id: str, fingerprint: str, existing: dict[str, object]
) -> SendReservation:
    return SendReservation(
        request_id=request_id,
        fingerprint=fingerprint,
        target_rows=(),
        existing=existing,
    )


@contextmanager
def _reservation_transaction(engine: Engine, request_day: dt.date) -> Iterator[sa.Connection]:
    """Serialize daily quota allocation without relying on process-local state."""
    connection = engine.connect()
    transaction: sa.Transaction | None = None
    try:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            transaction = connection.begin()
            if connection.dialect.name == "postgresql":
                connection.execute(
                    sa.text("SELECT pg_advisory_xact_lock(:namespace, :day_key)"),
                    {
                        "namespace": _POSTGRES_QUOTA_LOCK_NAMESPACE,
                        "day_key": request_day.toordinal(),
                    },
                )
        yield connection
        if transaction is None:
            connection.commit()
        else:
            transaction.commit()
    except Exception:
        if transaction is None:
            connection.rollback()
        else:
            transaction.rollback()
        raise
    finally:
        connection.close()


def send_fingerprint(command) -> str:
    body = {
        "request_id": str(command.request_id),
        "targets": [
            {"target_id": str(item.target_id), "expected_version": item.expected_version}
            for item in command.targets
        ],
    }
    return hashlib.sha256(
        json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def reserve_send(
    *,
    engine: Engine,
    command,
    actor: str,
    at: dt.datetime,
    status: Literal["queued", "started"],
    create_items: bool,
    suppression_check: SuppressionCheck,
    locked_rows: LockedRows,
    validate_live_directory_contact: DirectoryValidator,
    action_error: ErrorFactory,
    before_reservation: Callable[[], None] | None = None,
) -> SendReservation:
    """Atomically validate and reserve a complete batch, or return its existing request."""
    request_id = str(command.request_id)
    fingerprint = send_fingerprint(command)
    request_day = at.astimezone(dt.UTC).date()
    requested_target_ids = tuple(str(item.target_id) for item in command.targets)

    with _reservation_transaction(engine, request_day) as connection:
        existing = _existing_request(connection, request_id)
        if existing is not None:
            return _existing_reservation(
                request_id=request_id, fingerprint=fingerprint, existing=existing
            )
        if before_reservation is not None:
            before_reservation()

        reserved_today = connection.scalar(
            sa.select(
                sa.func.coalesce(
                    sa.func.sum(
                        sa.case(
                            (
                                prospect_send_request.c.status.in_(
                                    ("started", "queued", "running", "waiting")
                                ),
                                prospect_send_request.c.reserved_count,
                            ),
                            else_=prospect_send_request.c.sent_count,
                        )
                    ),
                    0,
                )
            ).where(prospect_send_request.c.request_day == request_day)
        )
        if int(reserved_today or 0) + len(command.targets) > 25:
            existing = _existing_request(connection, request_id)
            if existing is not None:
                return _existing_reservation(
                    request_id=request_id, fingerprint=fingerprint, existing=existing
                )
            raise action_error(
                "DAILY_SEND_CAP_EXCEEDED",
                "le plafond quotidien de 25 envois est atteint",
                target_ids=requested_target_ids,
            )

        locked_target_rows = locked_rows(
            connection,
            sa.select(prospect_target)
            .where(prospect_target.c.target_id.in_(tuple(sorted(requested_target_ids))))
            .order_by(prospect_target.c.target_id)
            .with_for_update(nowait=True),
            target_ids=requested_target_ids,
        )
        existing = _existing_request(connection, request_id)
        if existing is not None:
            return _existing_reservation(
                request_id=request_id, fingerprint=fingerprint, existing=existing
            )
        targets_by_id = {str(row["target_id"]): row for row in locked_target_rows}
        target_rows: list[dict[str, object]] = []
        for item in command.targets:
            target_id = str(item.target_id)
            row = targets_by_id.get(target_id)
            if row is None:
                raise action_error(
                    "TARGET_NOT_FOUND",
                    "cible introuvable",
                    target_ids=(target_id,),
                    status_code=404,
                )
            if int(row["version"]) != item.expected_version:
                raise action_error(
                    "TARGET_VERSION_CONFLICT",
                    "la cible a été modifiée",
                    target_ids=(target_id,),
                )
            if row["status"] != ProspectStatus.APPROVED.value or row.get("send_request_id"):
                raise action_error(
                    "INVALID_TARGET_STATUS",
                    "toutes les cibles doivent être validées",
                    target_ids=(target_id,),
                )
            if row["mail_contract_status"] != "passed":
                raise action_error(
                    "MAIL_CONTRACT_FAILED",
                    "le mail ne respecte pas le contrat de rendu",
                    target_ids=(target_id,),
                    status_code=422,
                )
            target_rows.append(dict(row))

        requested_sirens = tuple(sorted({str(row["siren"]) for row in target_rows}))
        locked_directory_rows = locked_rows(
            connection,
            sa.select(
                supplier_directory.c.siren,
                supplier_directory.c.domain,
                supplier_directory.c.domain_validation_method,
                supplier_directory.c.professional_email,
                supplier_directory.c.reverification_required_at,
                supplier_directory.c.suppressed_at,
            )
            .where(supplier_directory.c.siren.in_(requested_sirens))
            .order_by(supplier_directory.c.siren)
            .with_for_update(nowait=True),
            target_ids=requested_target_ids,
        )
        directories_by_siren = {str(row["siren"]): row for row in locked_directory_rows}
        for row in target_rows:
            target_id = str(row["target_id"])
            validate_live_directory_contact(row, directories_by_siren.get(str(row["siren"])))
            if is_placeholder_email(row["email_address"]):
                raise action_error(
                    "PLACEHOLDER_EMAIL",
                    "l'adresse est une valeur de démonstration",
                    target_ids=(target_id,),
                    status_code=422,
                )
            if is_consumer_mailbox(row["email_address"]):
                raise action_error(
                    "CONSUMER_MAILBOX_HELD",
                    "les boîtes grand public restent en attente",
                    target_ids=(target_id,),
                    status_code=422,
                )
            if row["email_verification_status"] != "mx_verified":
                raise action_error(
                    "EMAIL_NOT_MX_VERIFIED",
                    "l'adresse doit être vérifiée MX",
                    target_ids=(target_id,),
                    status_code=422,
                )
            if suppression_check(connection, str(row["email_address"]), at):
                raise action_error(
                    "EMAIL_SUPPRESSED",
                    "l'adresse est dans la liste de suppression",
                    target_ids=(target_id,),
                    status_code=422,
                )

        request_values: dict[str, object] = {
            "request_id": request_id,
            "payload_fingerprint": fingerprint,
            "target_ids": list(requested_target_ids),
            "request_day": request_day,
            "reserved_count": len(command.targets),
            "sent_count": 0,
            "processed_count": 0,
            "failed_count": 0,
            "status": status,
            "created_by": actor,
            "created_at": at,
            "updated_at": at,
        }
        if create_items:
            request_values["next_attempt_at"] = at
        try:
            with connection.begin_nested():
                connection.execute(sa.insert(prospect_send_request).values(**request_values))
                if create_items:
                    connection.execute(
                        sa.insert(prospect_send_item),
                        [
                            {
                                "request_id": request_id,
                                "target_id": str(item.target_id),
                                "position": position,
                                "expected_version": item.expected_version,
                                "status": "queued",
                                "next_attempt_at": at,
                                "created_at": at,
                                "updated_at": at,
                            }
                            for position, item in enumerate(command.targets)
                        ],
                    )
                for item in command.targets:
                    updated = connection.execute(
                        sa.update(prospect_target)
                        .where(
                            prospect_target.c.target_id == str(item.target_id),
                            prospect_target.c.version == item.expected_version,
                            prospect_target.c.status == ProspectStatus.APPROVED.value,
                            prospect_target.c.send_request_id.is_(None),
                            prospect_target.c.mail_contract_status == "passed",
                            prospect_target.c.email_verification_status == "mx_verified",
                        )
                        .values(send_request_id=request_id, updated_at=at)
                    )
                    if updated.rowcount != 1:
                        raise action_error(
                            "INVALID_TARGET_STATUS",
                            "une cible a déjà été réservée ou modifiée",
                            target_ids=(str(item.target_id),),
                        )
        except sa.exc.IntegrityError as error:
            if not _is_request_id_conflict(error):
                raise
            existing = _existing_request(connection, request_id)
            if existing is None:
                raise
            return _existing_reservation(
                request_id=request_id, fingerprint=fingerprint, existing=existing
            )

    return SendReservation(
        request_id=request_id,
        fingerprint=fingerprint,
        target_rows=tuple(target_rows),
    )


def send_progress(
    engine: Engine, request_id: UUID | str, *, action_error: ErrorFactory
) -> SendRequestProgress:
    """Load the durable request view, including queue item status in payload order."""
    with engine.connect() as connection:
        rows = tuple(
            connection.execute(
                sa.select(
                    prospect_send_request.c.request_id,
                    prospect_send_request.c.status.label("request_status"),
                    prospect_send_request.c.reserved_count,
                    prospect_send_request.c.processed_count,
                    prospect_send_request.c.sent_count,
                    prospect_send_request.c.failed_count,
                    prospect_send_item.c.target_id,
                    prospect_send_item.c.status.label("item_status"),
                    prospect_send_item.c.instantly_id,
                    prospect_send_item.c.verification_status,
                    prospect_send_item.c.error_code,
                    prospect_send_item.c.error_message,
                    prospect_target.c.email_address,
                )
                .select_from(
                    prospect_send_request.outerjoin(
                        prospect_send_item,
                        prospect_send_item.c.request_id == prospect_send_request.c.request_id,
                    ).outerjoin(
                        prospect_target,
                        prospect_target.c.target_id == prospect_send_item.c.target_id,
                    )
                )
                .where(prospect_send_request.c.request_id == str(request_id))
                .order_by(prospect_send_item.c.position)
            ).mappings()
        )
        if not rows:
            raise action_error(
                "SEND_REQUEST_NOT_FOUND",
                "demande d'envoi introuvable",
                status_code=404,
            )
        request = rows[0]
        items = tuple(
            SendItemProgress(
                target_id=UUID(str(row["target_id"])),
                email_address=str(row["email_address"]),
                status=str(row["item_status"]),
                instantly_id=row["instantly_id"],
                verification_status=row["verification_status"],
                error_code=row["error_code"],
                error_message=row["error_message"],
            )
            for row in rows
            if row["target_id"] is not None
        )
    return SendRequestProgress(
        request_id=UUID(str(request["request_id"])),
        status=str(request["request_status"]),
        total_count=int(request["reserved_count"]),
        processed_count=int(request["processed_count"]),
        sent_count=int(request["sent_count"]),
        failed_count=int(request["failed_count"]),
        items=items,
    )


__all__ = ["SendReservation", "reserve_send", "send_fingerprint", "send_progress"]
