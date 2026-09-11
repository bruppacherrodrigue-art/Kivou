"""Transactional Founder review actions for assisted prospecting."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.persistence.schema import (
    prospect_send_request,
    prospect_target,
    prospect_target_history,
    supplier_directory,
)
from signals.prospection_actions.contracts import (
    ApproveCommand,
    CompanySnapshot,
    CorrectCommand,
    DailyCounts,
    DeliverySnapshot,
    DirectorSnapshot,
    EmailSnapshot,
    ListResponse,
    MailSnapshot,
    Pagination,
    ProspectStatus,
    ProspectTarget,
    RejectCommand,
    RejectionReason,
    SignalSnapshot,
)
from signals.prospection_actions.mail import render_assisted_mail


class EmailVerifier(Protocol):
    def verify(self, email: str) -> bool: ...


@dataclass(frozen=True)
class IssuedProspectLink:
    url: str
    member_ref: str
    token_fingerprint: str
    payload: dict[str, object]


class ProspectLinkIssuer(Protocol):
    def issue(
        self, *, row: dict[str, object], email: str, at: dt.datetime
    ) -> IssuedProspectLink: ...


class SuppressionChecker(Protocol):
    def is_suppressed(self, connection: sa.Connection, *, email: str, at: dt.datetime) -> bool: ...


@dataclass(frozen=True)
class DeliveryPermit:
    request_id: str
    target_ids: frozenset[str]
    issued_at: dt.datetime


@dataclass(frozen=True)
class DeliveryTarget:
    target_id: str
    email: str
    company_name: str
    director_name: str | None
    subject: str
    text: str
    html: str


@dataclass(frozen=True)
class DeliveryAttempt:
    target_id: str
    status: str
    instantly_id: str | None
    provider_campaign_id: str | None
    instantly_credit_units: int
    instantly_request_count: int
    error: str | None = None


class DeliveryProvider(Protocol):
    def deliver(
        self,
        *,
        permit: DeliveryPermit,
        targets: tuple[DeliveryTarget, ...],
        at: dt.datetime,
    ) -> tuple[DeliveryAttempt, ...]: ...


class ProspectionActionError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        target_ids: tuple[str, ...] = (),
        status_code: int = 409,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.target_ids = target_ids
        self.status_code = status_code


@dataclass(frozen=True)
class CorrectResult:
    target: ProspectTarget
    token_reissued: bool
    email_reverified: bool
    directory_updated: bool


@dataclass(frozen=True)
class RejectResult:
    target: ProspectTarget
    directory_effect: str


@dataclass(frozen=True)
class SendItemResult:
    target_id: str
    status: str
    instantly_id: str | None


@dataclass(frozen=True)
class SendResult:
    request_id: str
    results: tuple[SendItemResult, ...]
    daily_sent_count: int
    daily_remaining: int


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.UTC)


def _target(row: dict[str, object]) -> ProspectTarget:
    director = None
    if row.get("director_name"):
        director = DirectorSnapshot(
            name=str(row["director_name"]),
            title=str(row.get("director_title") or "dirigeant"),
            source=str(row.get("director_source") or "registry"),
        )
    return ProspectTarget(
        target_id=UUID(str(row["target_id"])),
        version=int(row["version"]),
        status=str(row["status"]),
        company=CompanySnapshot(
            siren=str(row["siren"]),
            name=str(row["company_name"]),
            city=str(row["company_city"]),
            employees=int(row["company_employees"]),
            family=str(row["family_label"]),
        ),
        director=director,
        email=EmailSnapshot(
            address=str(row["email_address"]),
            source=str(row["email_source"]),
            verification_status=str(row["email_verification_status"]),
        ),
        signal=SignalSnapshot(
            opportunity_key=str(row["opportunity_key"]),
            holder=str(row["signal_holder"]),
            subject=str(row["signal_subject"]),
            amount_minor_units=int(row["signal_amount_minor_units"]),
            currency=str(row["signal_currency"]),
            location=str(row["signal_location"]),
            decision_date=row["signal_decision_date"],
        ),
        mail=MailSnapshot(
            subject=str(row["mail_subject"]),
            text=str(row["mail_text"]),
            html=str(row["mail_html"]),
            attribution_url=str(row["attribution_url"]),
            unsubscribe_url=str(row["unsubscribe_url"]),
            word_count=int(row["mail_word_count"]),
        ),
        delivery=DeliverySnapshot(
            status=str(row["delivery_status"]),
            instantly_id=row.get("instantly_id"),
            sent_at=_aware(row.get("sent_at")),
            opened_at=_aware(row.get("opened_at")),
            clicked_at=_aware(row.get("clicked_at")),
            replied_at=_aware(row.get("replied_at")),
            bounced_at=_aware(row.get("bounced_at")),
            unsubscribed_at=_aware(row.get("unsubscribed_at")),
            instantly_credit_units=int(row.get("instantly_credit_units") or 0),
            instantly_request_count=int(row.get("instantly_request_count") or 0),
        ),
        created_at=_aware(row["created_at"]),
        updated_at=_aware(row["updated_at"]),
        approved_at=_aware(row.get("approved_at")),
        approved_by=row.get("approved_by"),
    )


def _history_id(target_id: str, version: int, event_type: str) -> str:
    return hashlib.sha256(
        f"prospect-history\0{target_id}\0{version}\0{event_type}".encode()
    ).hexdigest()


class ProspectionActions:
    def __init__(
        self,
        engine: Engine,
        *,
        email_verifier: EmailVerifier,
        link_issuer: ProspectLinkIssuer,
        suppression_checker: SuppressionChecker | None = None,
        delivery_provider: DeliveryProvider | None = None,
        kill_switch_path: Path = Path("/etc/kivou/acquisition.disabled"),
        clock=lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._engine = engine
        self._email_verifier = email_verifier
        self._link_issuer = link_issuer
        self._suppression_checker = suppression_checker
        self._delivery_provider = delivery_provider
        self._kill_switch_path = kill_switch_path
        self._clock = clock

    def list(
        self,
        *,
        status: ProspectStatus | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> ListResponse:
        at = self._clock()
        start = dt.datetime.combine(at.astimezone(dt.UTC).date(), dt.time(), tzinfo=dt.UTC)
        end = start + dt.timedelta(days=1)
        with self._engine.connect() as connection:
            daily_rows = connection.execute(
                sa.select(prospect_target.c.status, sa.func.count())
                .where(prospect_target.c.created_at >= start, prospect_target.c.created_at < end)
                .group_by(prospect_target.c.status)
            ).all()
            status_counts = {str(name): int(count) for name, count in daily_rows}
            predicate = sa.true()
            if status is not None:
                predicate = prospect_target.c.status == status.value
            total = int(
                connection.scalar(
                    sa.select(sa.func.count()).select_from(prospect_target).where(predicate)
                )
                or 0
            )
            rows = tuple(
                dict(row)
                for row in connection.execute(
                    sa.select(prospect_target)
                    .where(predicate)
                    .order_by(prospect_target.c.created_at.desc(), prospect_target.c.target_id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                ).mappings()
            )
        return ListResponse(
            generated_at=at,
            daily_counts=DailyCounts(
                prepared=sum(status_counts.values()),
                approved=status_counts.get("approved", 0),
                rejected=status_counts.get("rejected", 0),
                sent=status_counts.get("sent", 0),
            ),
            kill_switch_active=self._kill_switch_path.exists(),
            items=tuple(_target(row) for row in rows),
            pagination=Pagination(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=(total + page_size - 1) // page_size,
            ),
        )

    @staticmethod
    def _load(
        connection: sa.Connection, target_id: UUID, expected_version: int
    ) -> dict[str, object]:
        row = (
            connection.execute(
                sa.select(prospect_target)
                .where(prospect_target.c.target_id == str(target_id))
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ProspectionActionError(
                "TARGET_NOT_FOUND",
                "cible introuvable",
                target_ids=(str(target_id),),
                status_code=404,
            )
        if int(row["version"]) != expected_version:
            raise ProspectionActionError(
                "TARGET_VERSION_CONFLICT",
                "la cible a été modifiée",
                target_ids=(str(target_id),),
            )
        return dict(row)

    @staticmethod
    def _history(
        connection: sa.Connection,
        *,
        row: dict[str, object],
        event_type: str,
        actor: str,
        previous: dict[str, object],
        new: dict[str, object],
        at: dt.datetime,
        reason: str | None = None,
        comment: str | None = None,
    ) -> None:
        connection.execute(
            sa.insert(prospect_target_history).values(
                history_id=_history_id(str(row["target_id"]), int(row["version"]) + 1, event_type),
                target_id=row["target_id"],
                event_type=event_type,
                actor=actor,
                previous_values=previous,
                new_values=new,
                reason=reason,
                comment=comment,
                created_at=at,
            )
        )

    @staticmethod
    def _updated_row(connection: sa.Connection, target_id: str) -> dict[str, object]:
        return dict(
            connection.execute(
                sa.select(prospect_target).where(prospect_target.c.target_id == target_id)
            )
            .mappings()
            .one()
        )

    def approve(self, command: ApproveCommand, *, actor: str) -> ProspectTarget:
        at = self._clock()
        with self._engine.begin() as connection:
            row = self._load(connection, command.target_id, command.expected_version)
            if row["status"] != ProspectStatus.PENDING_REVIEW.value:
                raise ProspectionActionError(
                    "INVALID_TARGET_STATUS",
                    "seule une cible en attente peut être validée",
                    target_ids=(str(command.target_id),),
                )
            values = {
                "status": ProspectStatus.APPROVED.value,
                "approved_at": at,
                "approved_by": actor,
                "version": int(row["version"]) + 1,
                "updated_at": at,
            }
            connection.execute(
                sa.update(prospect_target)
                .where(prospect_target.c.target_id == row["target_id"])
                .values(**values)
            )
            self._history(
                connection,
                row=row,
                event_type="approved",
                actor=actor,
                previous={"status": row["status"]},
                new={"status": values["status"]},
                at=at,
            )
            result = self._updated_row(connection, str(row["target_id"]))
        return _target(result)

    def correct(self, command: CorrectCommand, *, actor: str) -> CorrectResult:
        at = self._clock()
        changes = command.changes.model_dump(exclude_none=True, mode="json")
        email_changed = "email_address" in changes
        verified = False
        if email_changed:
            verified = self._email_verifier.verify(str(changes["email_address"]))
        with self._engine.begin() as connection:
            row = self._load(connection, command.target_id, command.expected_version)
            if row["status"] == ProspectStatus.SENT.value:
                raise ProspectionActionError(
                    "INVALID_TARGET_STATUS",
                    "une cible envoyée ne peut plus être corrigée",
                    target_ids=(str(command.target_id),),
                )
            values: dict[str, object] = {}
            previous: dict[str, object] = {}
            if "company_name" in changes:
                previous["company_name"] = row["company_name"]
                values["company_name"] = changes["company_name"]
                connection.execute(
                    sa.update(supplier_directory)
                    .where(supplier_directory.c.siren == row["siren"])
                    .values(
                        legal_name=changes["company_name"], legal_name_observed_at=at, updated_at=at
                    )
                )
            if "director_name" in changes:
                previous["director_name"] = row["director_name"]
                values.update(director_name=changes["director_name"], director_source="manual")
                director_title = str(row.get("director_title") or "dirigeant")
                values["director_title"] = director_title
                connection.execute(
                    sa.update(supplier_directory)
                    .where(supplier_directory.c.siren == row["siren"])
                    .values(
                        directors=[
                            {
                                "name": changes["director_name"],
                                "title": director_title,
                                "entity_type": "personne physique",
                            }
                        ],
                        directors_observed_at=at,
                        updated_at=at,
                    )
                )
            token_reissued = False
            if email_changed:
                email = str(changes["email_address"]).casefold()
                previous.update(
                    email_address=row["email_address"],
                    email_source=row["email_source"],
                    email_verification_status=row["email_verification_status"],
                )
                link = self._link_issuer.issue(row={**row, **values}, email=email, at=at)
                values.update(
                    email_address=email,
                    email_source="manual",
                    email_verification_status="mx_verified" if verified else "mx_failed",
                    attribution_url=link.url,
                    attribution_member_ref=link.member_ref,
                    attribution_payload=link.payload,
                    attribution_token_fingerprint=link.token_fingerprint,
                )
                connection.execute(
                    sa.update(supplier_directory)
                    .where(supplier_directory.c.siren == row["siren"])
                    .values(
                        professional_email=email,
                        email_source="manual",
                        email_verification_status=values["email_verification_status"],
                        email_observed_at=at,
                        updated_at=at,
                    )
                )
                token_reissued = True
            rendered = render_assisted_mail({**row, **values})
            values.update(
                mail_subject=rendered.subject,
                mail_text=rendered.text,
                mail_html=rendered.html,
                mail_word_count=rendered.word_count,
                version=int(row["version"]) + 1,
                updated_at=at,
            )
            connection.execute(
                sa.update(prospect_target)
                .where(prospect_target.c.target_id == row["target_id"])
                .values(**values)
            )
            self._history(
                connection,
                row=row,
                event_type="corrected",
                actor=actor,
                previous=previous,
                new={key: values[key] for key in changes},
                at=at,
            )
            result = self._updated_row(connection, str(row["target_id"]))
        return CorrectResult(
            target=_target(result),
            token_reissued=token_reissued,
            email_reverified=email_changed,
            directory_updated=True,
        )

    def reject(self, command: RejectCommand, *, actor: str) -> RejectResult:
        at = self._clock()
        with self._engine.begin() as connection:
            row = self._load(connection, command.target_id, command.expected_version)
            if row["status"] not in {
                ProspectStatus.PENDING_REVIEW.value,
                ProspectStatus.APPROVED.value,
            }:
                raise ProspectionActionError(
                    "INVALID_TARGET_STATUS",
                    "cette cible ne peut pas être écartée",
                    target_ids=(str(command.target_id),),
                )
            directory_effect = "none"
            if command.reason is RejectionReason.WRONG_ADDRESS:
                connection.execute(
                    sa.update(supplier_directory)
                    .where(supplier_directory.c.siren == row["siren"])
                    .values(
                        email_verification_status="mx_failed",
                        reverification_required_at=at,
                        reverification_reason="founder_wrong_address",
                        updated_at=at,
                    )
                )
                directory_effect = "email_invalidated"
            elif command.reason is RejectionReason.WRONG_COMPANY:
                directory = connection.execute(
                    sa.select(supplier_directory.c.family_review_keys)
                    .where(supplier_directory.c.siren == row["siren"])
                    .with_for_update()
                ).scalar_one()
                review_keys = sorted(set(directory or ()) | {str(row["family_key"])})
                connection.execute(
                    sa.update(supplier_directory)
                    .where(supplier_directory.c.siren == row["siren"])
                    .values(family_review_keys=review_keys, updated_at=at)
                )
                directory_effect = "family_review_required"
            values = {
                "status": ProspectStatus.REJECTED.value,
                "rejection_reason": command.reason.value,
                "rejection_comment": command.comment,
                "rejected_at": at,
                "rejected_by": actor,
                "version": int(row["version"]) + 1,
                "updated_at": at,
            }
            connection.execute(
                sa.update(prospect_target)
                .where(prospect_target.c.target_id == row["target_id"])
                .values(**values)
            )
            self._history(
                connection,
                row=row,
                event_type="rejected",
                actor=actor,
                previous={"status": row["status"]},
                new={"status": values["status"]},
                at=at,
                reason=command.reason.value,
                comment=command.comment,
            )
            result = self._updated_row(connection, str(row["target_id"]))
        return RejectResult(target=_target(result), directory_effect=directory_effect)

    @staticmethod
    def _send_fingerprint(command) -> str:
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

    @staticmethod
    def _send_result(value: dict[str, object]) -> SendResult:
        return SendResult(
            request_id=str(value["request_id"]),
            results=tuple(
                SendItemResult(
                    target_id=str(item["target_id"]),
                    status=str(item["status"]),
                    instantly_id=item.get("instantly_id"),
                )
                for item in value["results"]
            ),
            daily_sent_count=int(value["daily_sent_count"]),
            daily_remaining=int(value["daily_remaining"]),
        )

    def send(self, command, *, actor: str) -> SendResult:
        """Reserve a fully valid batch, then expose one scoped provider permit."""

        at = self._clock()
        if self._kill_switch_path.exists():
            raise ProspectionActionError(
                "KILL_SWITCH_ACTIVE", "l'arrêt d'urgence de l'acquisition est actif"
            )
        if self._suppression_checker is None or self._delivery_provider is None:
            raise RuntimeError("prospection delivery dependencies are not configured")
        request_id = str(command.request_id)
        fingerprint = self._send_fingerprint(command)
        request_day = at.astimezone(dt.UTC).date()
        target_rows: list[dict[str, object]] = []
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    sa.select(prospect_send_request).where(
                        prospect_send_request.c.request_id == request_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if existing["payload_fingerprint"] != fingerprint:
                    raise ProspectionActionError(
                        "REQUEST_ID_CONFLICT", "request_id a déjà un autre contenu"
                    )
                if existing["status"] in {"completed", "partial", "failed"}:
                    if existing["result"] is None:
                        raise ProspectionActionError(
                            "INSTANTLY_SEND_FAILED",
                            "le fournisseur n'a accepté aucune cible",
                            status_code=502,
                        )
                    return self._send_result(dict(existing["result"]))
                raise ProspectionActionError("REQUEST_ID_CONFLICT", "cet envoi est déjà en cours")

            reserved_today = connection.scalar(
                sa.select(
                    sa.func.coalesce(
                        sa.func.sum(
                            sa.case(
                                (
                                    prospect_send_request.c.status == "started",
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
                raise ProspectionActionError(
                    "DAILY_SEND_CAP_EXCEEDED",
                    "le plafond quotidien de 25 envois est atteint",
                    target_ids=tuple(str(item.target_id) for item in command.targets),
                )

            for item in command.targets:
                row = self._load(connection, item.target_id, item.expected_version)
                target_id = str(item.target_id)
                if row["status"] != ProspectStatus.APPROVED.value or row.get("send_request_id"):
                    raise ProspectionActionError(
                        "INVALID_TARGET_STATUS",
                        "toutes les cibles doivent être validées",
                        target_ids=(target_id,),
                    )
                if row["email_verification_status"] != "mx_verified":
                    raise ProspectionActionError(
                        "EMAIL_NOT_MX_VERIFIED",
                        "l'adresse doit être vérifiée MX",
                        target_ids=(target_id,),
                        status_code=422,
                    )
                if self._suppression_checker.is_suppressed(
                    connection, email=str(row["email_address"]), at=at
                ):
                    raise ProspectionActionError(
                        "EMAIL_SUPPRESSED",
                        "l'adresse est dans la liste de suppression",
                        target_ids=(target_id,),
                        status_code=422,
                    )
                target_rows.append(row)

            connection.execute(
                sa.insert(prospect_send_request).values(
                    request_id=request_id,
                    payload_fingerprint=fingerprint,
                    target_ids=[str(item.target_id) for item in command.targets],
                    request_day=request_day,
                    reserved_count=len(command.targets),
                    sent_count=0,
                    status="started",
                    created_by=actor,
                    created_at=at,
                )
            )
            connection.execute(
                sa.update(prospect_target)
                .where(prospect_target.c.target_id.in_([row["target_id"] for row in target_rows]))
                .values(send_request_id=request_id, updated_at=at)
            )

        delivery_targets = tuple(
            DeliveryTarget(
                target_id=str(row["target_id"]),
                email=str(row["email_address"]),
                company_name=str(row["company_name"]),
                director_name=row.get("director_name"),
                subject=str(row["mail_subject"]),
                text=str(row["mail_text"]),
                html=str(row["mail_html"]),
            )
            for row in target_rows
        )
        permit = DeliveryPermit(
            request_id=request_id,
            target_ids=frozenset(item.target_id for item in delivery_targets),
            issued_at=at,
        )
        try:
            attempts = self._delivery_provider.deliver(
                permit=permit, targets=delivery_targets, at=at
            )
        except Exception as error:  # noqa: BLE001 - provider boundary becomes audited failure
            attempts = tuple(
                DeliveryAttempt(
                    target_id=item.target_id,
                    status="failed",
                    instantly_id=None,
                    provider_campaign_id=None,
                    instantly_credit_units=0,
                    instantly_request_count=0,
                    error=str(error)[:1000],
                )
                for item in delivery_targets
            )
        attempts_by_id = {item.target_id: item for item in attempts}
        if set(attempts_by_id) != set(permit.target_ids):
            missing = set(permit.target_ids) - set(attempts_by_id)
            for target_id in missing:
                attempts_by_id[target_id] = DeliveryAttempt(
                    target_id=target_id,
                    status="failed",
                    instantly_id=None,
                    provider_campaign_id=None,
                    instantly_credit_units=0,
                    instantly_request_count=0,
                    error="provider result missing",
                )
        sent_count = sum(item.status == "sent" for item in attempts_by_id.values())
        with self._engine.begin() as connection:
            for row in target_rows:
                attempt = attempts_by_id[str(row["target_id"])]
                sent = attempt.status == "sent"
                values = {
                    "status": "sent" if sent else "approved",
                    "delivery_status": "sent" if sent else "not_sent",
                    "provider_campaign_id": attempt.provider_campaign_id,
                    "instantly_id": attempt.instantly_id,
                    "send_request_id": request_id if sent else None,
                    "sent_at": at if sent else None,
                    "instantly_credit_units": attempt.instantly_credit_units,
                    "instantly_request_count": attempt.instantly_request_count,
                    "delivery_error": attempt.error,
                    "version": int(row["version"]) + 1,
                    "updated_at": at,
                }
                connection.execute(
                    sa.update(prospect_target)
                    .where(
                        prospect_target.c.target_id == row["target_id"],
                        prospect_target.c.send_request_id == request_id,
                    )
                    .values(**values)
                )
                self._history(
                    connection,
                    row=row,
                    event_type="sent" if sent else "send_failed",
                    actor=actor,
                    previous={"status": row["status"]},
                    new={"status": values["status"], "instantly_id": attempt.instantly_id},
                    at=at,
                )
            daily_sent = (
                int(
                    connection.scalar(
                        sa.select(
                            sa.func.coalesce(sa.func.sum(prospect_send_request.c.sent_count), 0)
                        ).where(prospect_send_request.c.request_day == request_day)
                    )
                    or 0
                )
                + sent_count
            )
            result = SendResult(
                request_id=request_id,
                results=tuple(
                    SendItemResult(
                        target_id=item.target_id,
                        status=item.status,
                        instantly_id=item.instantly_id,
                    )
                    for item in attempts_by_id.values()
                ),
                daily_sent_count=daily_sent,
                daily_remaining=max(0, 25 - daily_sent),
            )
            result_json = {
                "request_id": result.request_id,
                "results": [item.__dict__ for item in result.results],
                "daily_sent_count": result.daily_sent_count,
                "daily_remaining": result.daily_remaining,
            }
            request_status = (
                "completed"
                if sent_count == len(target_rows)
                else ("partial" if sent_count else "failed")
            )
            connection.execute(
                sa.update(prospect_send_request)
                .where(prospect_send_request.c.request_id == request_id)
                .values(
                    status=request_status,
                    sent_count=sent_count,
                    result=result_json if sent_count else None,
                    error=None if sent_count else "provider rejected every target",
                    completed_at=at,
                )
            )
        if sent_count == 0:
            raise ProspectionActionError(
                "INSTANTLY_SEND_FAILED",
                "le fournisseur n'a accepté aucune cible",
                target_ids=tuple(permit.target_ids),
                status_code=502,
            )
        return result


__all__ = [
    "CorrectResult",
    "DeliveryAttempt",
    "DeliveryPermit",
    "DeliveryProvider",
    "DeliveryTarget",
    "EmailVerifier",
    "IssuedProspectLink",
    "ProspectLinkIssuer",
    "ProspectionActionError",
    "ProspectionActions",
    "RejectResult",
    "SendItemResult",
    "SendResult",
    "SuppressionChecker",
]
