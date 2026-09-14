"""Explicit private company membership; reads never create a follow."""

import datetime as dt

import sqlalchemy as sa

from signals.billing.service import aware_datetime
from signals.engagement.prospecting_schema import account_company_membership as membership
from signals.persistence.conflicts import insert_if_absent


def company_membership(connection, *, account_id: str, company_key: str) -> dict:
    row = (
        connection.execute(
            sa.select(membership).where(
                membership.c.account_id == account_id,
                membership.c.company_key == company_key,
            )
        )
        .mappings()
        .one_or_none()
    )
    return {
        "tracked": row is not None,
        "tracked_at": aware_datetime(row["created_at"]).isoformat() if row else None,
        "revision": row["revision"] if row else 0,
        "origin": row["origin"] if row else None,
    }


def follow_company(connection, *, account_id: str, company_key: str, now: dt.datetime) -> dict:
    insert_if_absent(
        connection,
        membership,
        {
            "account_id": account_id,
            "company_key": company_key,
            "origin": "user",
            "revision": 1,
            "created_at": now,
            "updated_at": now,
        },
    )
    return company_membership(connection, account_id=account_id, company_key=company_key)
