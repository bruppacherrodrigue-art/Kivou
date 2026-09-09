"""Persistence and review projection for PR7 shadow messages."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.persistence.schema import acquisition_shadow_mail


def mask_email(value: str) -> str:
    local, _, domain = value.partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain}"


@dataclass(frozen=True)
class ShadowMailRecord:
    shadow_mail_id: str
    opportunity_key: str
    company_name: str
    contact_role: str
    masked_email: str
    signal_snapshot: dict[str, object]
    subject: str
    body: str
    apollo_query: dict[str, object]
    created_at: dt.datetime


def write_shadow_mail(
    engine: Engine,
    *,
    cycle_ref: str,
    opportunity_key: str,
    procedure_award_key: str,
    supplier_ref: str | None,
    contact_ref: str | None,
    company_name: str,
    contact_role: str,
    email: str,
    signal_snapshot: dict[str, object],
    subject: str,
    body: str,
    apollo_query: dict[str, object],
    created_at: dt.datetime,
) -> str | None:
    """Insert once per procedure/day; return None when already represented."""
    mail_id = hashlib.sha256(
        f"pr7-shadow\0{cycle_ref}\0{opportunity_key}\0{email}".encode()
    ).hexdigest()
    values = {
        "shadow_mail_id": mail_id,
        "cycle_ref": cycle_ref,
        "opportunity_key": opportunity_key,
        "procedure_award_key": procedure_award_key,
        "supplier_ref": supplier_ref,
        "contact_ref": contact_ref,
        "company_name": company_name,
        "contact_role": contact_role,
        "masked_email": mask_email(email),
        "signal_snapshot": signal_snapshot,
        "subject": subject,
        "body": body,
        "apollo_query": apollo_query,
        "status": "SHADOW",
        "created_day": created_at.date(),
        "created_at": created_at,
    }
    with engine.begin() as connection:
        try:
            connection.execute(sa.insert(acquisition_shadow_mail).values(values))
        except sa.exc.IntegrityError:
            return None
    return mail_id


def latest_shadow_mails(engine: Engine, *, limit: int = 20) -> tuple[ShadowMailRecord, ...]:
    with engine.connect() as connection:
        rows = connection.execute(
            sa.select(acquisition_shadow_mail)
            .where(acquisition_shadow_mail.c.status == "SHADOW")
            .order_by(acquisition_shadow_mail.c.created_at.desc())
            .limit(limit)
        ).mappings()
        return tuple(
            ShadowMailRecord(
                shadow_mail_id=row["shadow_mail_id"],
                opportunity_key=row["opportunity_key"],
                company_name=row["company_name"],
                contact_role=row["contact_role"],
                masked_email=row["masked_email"],
                signal_snapshot=row["signal_snapshot"],
                subject=row["subject"],
                body=row["body"],
                apollo_query=row["apollo_query"],
                created_at=row["created_at"],
            )
            for row in rows
        )


__all__ = ["ShadowMailRecord", "latest_shadow_mails", "mask_email", "write_shadow_mail"]
