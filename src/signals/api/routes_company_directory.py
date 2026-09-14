"""Bounded authenticated directory search; no account grant or provider call."""

import base64
import binascii
import hashlib
import json
from typing import Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Query, Request

from signals.api.dependencies import current_session, request_now
from signals.api.errors import api_error
from signals.billing.access import feed_access
from signals.client_value.capabilities import company_capabilities, project_directory
from signals.client_value.directory import _company_view
from signals.domain.french_departments import DEPARTMENTS
from signals.engagement.prospecting_schema import (
    account_company_alias_override,
    account_company_membership,
    company_subject_alias,
)
from signals.persistence.schema import supplier_directory
from signals.supplier_discovery.families import load_supplier_family_catalog

router = APIRouter()


@router.get("/companies/directory/options")
def directory_options(request: Request) -> dict[str, Any]:
    """Use the versioned directory taxonomy; never require customers to enter keys."""
    if "account_id" in request.query_params:
        raise api_error(422, "invalid_input", "le compte est déterminé par votre session")
    with request.app.state.engine.connect() as connection:
        current_session(request, connection, request_now(request))
    families = {
        family.key: family.label_fr
        for values in load_supplier_family_catalog().values()
        for family in values
    }
    return {
        "families": [
            {"key": key, "label": label}
            for key, label in sorted(families.items(), key=lambda item: item[1])
        ],
        "departments": [
            {"code": code, "label": label} for code, label in sorted(DEPARTMENTS.items())
        ],
    }


def _offset(cursor, fingerprint):
    if cursor is None:
        return 0
    try:
        payload = json.loads(
            base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        )
        if (
            not isinstance(payload, dict)
            or set(payload) != {"v", "f", "o"}
            or payload["v"] != 1
            or payload["f"] != fingerprint
            or type(payload["o"]) is not int
            or not 0 <= payload["o"] <= 1_000_000
        ):
            raise ValueError("invalid directory cursor")
        return payload["o"]
    except (ValueError, TypeError, binascii.Error, UnicodeError) as error:
        raise api_error(
            422, "invalid_directory_cursor", "ce curseur ne correspond pas à la recherche"
        ) from error


@router.get("/companies/directory")
def list_directory(
    request: Request,
    q: str = Query(default="", max_length=120),
    department: str | None = Query(
        default=None, min_length=2, max_length=3, pattern=r"^[0-9A-Z]+$"
    ),
    family: str | None = Query(default=None, max_length=80, pattern=r"^[a-z0-9_]+$"),
    sort: Literal["name", "city"] = "name",
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=512),
) -> dict[str, Any]:
    if "account_id" in request.query_params:
        raise api_error(422, "invalid_input", "le compte est déterminé par votre session")
    now = request_now(request)
    q = q.strip().casefold()
    fingerprint = hashlib.sha256(
        json.dumps([q, department, family, sort], separators=(",", ":")).encode()
    ).hexdigest()
    offset = _offset(cursor, fingerprint)
    conditions = [supplier_directory.c.suppressed_at.is_(None)]
    if q:
        conditions.append(
            sa.or_(
                sa.func.lower(supplier_directory.c.legal_name).contains(q, autoescape=True),
                sa.func.lower(supplier_directory.c.city).contains(q, autoescape=True),
                sa.func.lower(supplier_directory.c.naf_label).contains(q, autoescape=True),
                sa.func.lower(supplier_directory.c.naf_code).contains(q, autoescape=True),
                supplier_directory.c.siren.contains(q, autoescape=True),
            )
        )
    if department:
        conditions.append(supplier_directory.c.department == department)
    if family:
        # JSON string token matching works on both supported database dialects;
        # quoted tokens cannot match a longer family name accidentally.
        conditions.append(
            sa.cast(supplier_directory.c.family_keys, sa.Text).contains(
                json.dumps(family), autoescape=True
            )
        )
    order = sa.func.lower(
        sa.func.coalesce(
            supplier_directory.c.legal_name if sort == "name" else supplier_directory.c.city,
            "",
        )
    )
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        access = feed_access(connection, account_id=session.account_id, as_of=now.date())
        total = connection.execute(
            sa.select(sa.func.count()).select_from(supplier_directory).where(*conditions)
        ).scalar_one()
        rows = (
            connection.execute(
                sa.select(supplier_directory)
                .where(*conditions)
                .order_by(order, supplier_directory.c.siren)
                .limit(limit)
                .offset(offset)
            )
            .mappings()
            .all()
        )
        keys = tuple(f"cmp_directory_{row['siren']}" for row in rows)
        exceptions = dict(
            connection.execute(
                sa.select(
                    account_company_alias_override.c.alias_company_key,
                    account_company_alias_override.c.private_subject_key,
                ).where(
                    account_company_alias_override.c.account_id == session.account_id,
                    account_company_alias_override.c.alias_company_key.in_(keys),
                    sa.exists(
                        sa.select(1).where(
                            company_subject_alias.c.alias_company_key
                            == account_company_alias_override.c.alias_company_key,
                            company_subject_alias.c.resolution_status == "exact",
                            company_subject_alias.c.canonical_company_key
                            == account_company_alias_override.c.alias_company_key,
                        )
                    ),
                )
            ).all()
        )
        private_keys = tuple(exceptions.get(key, key) for key in keys)
        tracked = set(
            connection.execute(
                sa.select(account_company_membership.c.company_key).where(
                    account_company_membership.c.account_id == session.account_id,
                    account_company_membership.c.company_key.in_(private_keys),
                )
            ).scalars()
        )
        items = []
        for row, key in zip(rows, keys, strict=True):
            directory = project_directory(
                _company_view(row, matched_by_name=False, include_public_contact=True),
                entitlements=access.entitlements,
            )
            items.append(
                {
                    "company_key": key,
                    "canonical_company_key": key,
                    "private_subject_key": exceptions.get(key, key),
                    "name": row["legal_name"],
                    "city": row["city"],
                    "country": "FR",
                    "directory": directory,
                    "tracked": exceptions.get(key, key) in tracked,
                    "capabilities": company_capabilities(
                        access.entitlements,
                        enrichment_available=request.app.state.config.company_directory_enrichment_enabled,
                        lookup_available=request.app.state.company_contact_lookup_service
                        is not None,
                    ),
                }
            )
    has_more = offset + len(rows) < total
    next_cursor = (
        base64.urlsafe_b64encode(
            json.dumps(
                {"v": 1, "f": fingerprint, "o": offset + len(rows)}, separators=(",", ":")
            ).encode()
        )
        .decode()
        .rstrip("=")
        if has_more
        else None
    )
    return {
        "items": items,
        "page": {
            "limit": limit,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "scan_truncated": False,
        },
        "counts": {"total": total, "exact": True},
        "scope": None,
        "read_at": now.isoformat(),
    }
