"""Authenticated SaaS company profiles, scoped through current unlocked signals."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from signals.accounts import service as accounts
from signals.api.cards import presentation_bindings_for_items, render_unlocked_card
from signals.api.dependencies import current_session, enforce_origin, request_now
from signals.api.errors import api_error
from signals.billing import service as billing
from signals.billing.access import FeedAccess, feed_access
from signals.card_intelligence.store import published_for_signals
from signals.companies.contracts import CompanyProfile
from signals.companies.enrichment import winner_enrichments_for_signals
from signals.companies.listing import InvalidCompanyCursor, list_companies
from signals.companies.service import company_profile_with_items
from signals.engagement import analytics, feedback
from signals.engagement import company as company_engagement
from signals.engagement.schema import (
    COMPANY_CONTACT_STATUSES,
    MAXIMUM_COMPANY_NOTE_LENGTH,
    product_event,
)
from signals.engagement.status import status_resolver
from signals.feed import query as feed_query
from signals.feed.history import history_sort_key

router = APIRouter()

_COMPANY_KEY = re.compile(r"^cmp_[A-Za-z0-9_-]{12,60}$")


class CompanyContactRequest(BaseModel):
    """PR1 §4 — `extra="forbid"` : un champ inconnu échoue plutôt que d'être ignoré."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["to_contact", "contacted", "replied"]


class CompanyNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(max_length=MAXIMUM_COMPANY_NOTE_LENGTH)


def _accessible_company(
    connection,
    session,
    company_key: str,
    now,
) -> tuple[CompanyProfile, list[feed_query.FeedSignal], FeedAccess, str]:
    """The profile and its accessible items, or the 404 this account must see.

    Factors the session/access/allowed resolution shared by the three
    `/companies/{key}` routes, so none of them can drift from `GET`'s notion
    of "this account still has one unlocked current signal for this company".
    """
    as_of = now.date()
    if _COMPANY_KEY.fullmatch(company_key) is None:
        raise api_error(404, "company_not_found", "entreprise introuvable")
    user = accounts.current_user(connection, user_id=session.user_id)
    lang = user.locale if user.locale in {"fr", "en"} else "fr"
    access = feed_access(connection, account_id=session.account_id, as_of=as_of)
    accounts.reconcile_territory_plan_limits(
        connection,
        account_id=session.account_id,
        max_territories=access.entitlements.max_territories_per_icp,
        now=now,
    )
    allowed = frozenset(
        billing.feedable_target_icps(
            connection,
            account_id=session.account_id,
            limit=None,
        )
    )
    result = company_profile_with_items(
        connection,
        company_key=company_key,
        account_id=session.account_id,
        as_of=as_of,
        allowed_target_icp_ids=allowed,
        access=access,
        lang=lang,
    )
    if result is None:
        raise api_error(404, "company_not_found", "entreprise introuvable")
    profile, items = result
    return profile, items, access, lang


def _company_signals(
    connection,
    *,
    items: list[feed_query.FeedSignal],
    company_key: str,
    account_id: str,
    lang: str,
) -> tuple[dict[str, Any], ...]:
    """The same card `GET /signals` would render for each item — same
    presentation, same winner enrichment — so this list can never drift from
    the feed's idea of what an unlocked card looks like (§4 F2)."""
    resolve_status = status_resolver(
        feedback.feedback_by_signal(connection, account_id=account_id)
    )
    ordered = sorted(items, key=lambda item: history_sort_key(item.signal))
    signal_keys = tuple(item.signal.signal_key for item in ordered)
    presentation_bindings = presentation_bindings_for_items(connection, ordered)
    presentations = published_for_signals(
        connection,
        account_id=account_id,
        bindings=presentation_bindings,
        language=lang,
    )
    enrichments = winner_enrichments_for_signals(connection, signal_keys=signal_keys)
    return tuple(
        render_unlocked_card(
            item,
            lang=lang,
            presentation=presentations.get(item.signal.signal_key),
            company_key=company_key,
            enrichment=enrichments.get(item.signal.signal_key),
            status=resolve_status(item.signal.signal_key),
        )
        for item in ordered
    )


def _company_history(connection, *, account_id: str, company_key: str, items) -> tuple[dict[str, Any], ...]:
    signal_keys = {item.signal.signal_key for item in items}
    rows = connection.execute(
        sa.select(product_event).where(product_event.c.account_id == account_id)
    ).mappings()
    events = []
    labels = {
        "company_contact_updated": "contact",
        "company_note_updated": "note",
        "signal_feedback_relevant": "signal_saved",
        "signal_contacted": "signal_contacted",
    }
    for row in rows:
        event_type = row["event_type"]
        properties = row["properties"] or {}
        belongs = (
            properties.get("company_key") == company_key
            if event_type.startswith("company_")
            else row["signal_key"] in signal_keys
        )
        if belongs and event_type in labels:
            events.append(
                {
                    "type": (
                        properties.get("status", labels[event_type])
                        if event_type == "company_contact_updated"
                        else labels[event_type]
                    ),
                    "occurred_at": row["occurred_at"].isoformat(),
                    "signal_key": row["signal_key"],
                }
            )
    return tuple(sorted(events, key=lambda event: event["occurred_at"], reverse=True))


@router.get("/companies")
def list_companies_route(
    request: Request,
    contact_status: Annotated[list[str] | None, Query()] = None,
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=512),
) -> dict[str, Any]:
    """PR1 §3 — l'agrégat par titulaire résolu, sur les signaux accessibles du compte.

    Même portée que `view=history` sans filtre de date : ce que ce compte ne
    peut pas voir n'existe pas ici non plus (§26 — jamais 403, une liste vide).
    """
    now = request_now(request)
    as_of = now.date()
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        access = feed_access(connection, account_id=session.account_id, as_of=as_of)
        accounts.reconcile_territory_plan_limits(
            connection,
            account_id=session.account_id,
            max_territories=access.entitlements.max_territories_per_icp,
            now=now,
        )
        allowed = frozenset(
            billing.feedable_target_icps(
                connection,
                account_id=session.account_id,
                limit=None,
            )
        )
        statuses: frozenset[str] | None = None
        if contact_status is not None:
            for value in contact_status:
                if value not in COMPANY_CONTACT_STATUSES:
                    raise api_error(
                        422, "invalid_contact_status", f"statut de contact inconnu : {value!r}"
                    )
            statuses = frozenset(contact_status)
        try:
            page = list_companies(
                connection,
                account_id=session.account_id,
                as_of=as_of,
                allowed_target_icp_ids=allowed,
                access=access,
                contact_statuses=statuses,
                contacted_before=None,
                query=q,
                limit=limit,
                cursor=cursor,
                now=now,
            )
        except InvalidCompanyCursor as error:
            raise api_error(422, "invalid_company_cursor", "curseur invalide") from error
    return {
        "items": [
            {
                "company_key": row.company_key,
                "name": row.name,
                "city": row.city,
                "country": row.country,
                "awards_count": row.awards_count,
                "total_amount": [
                    {"currency": currency, "value": str(value)}
                    for currency, value in row.total_amount
                ],
                "last_award_at": row.last_award_at.isoformat() if row.last_award_at else None,
                "contact_status": row.contact_status,
                "contacted_at": row.contacted_at.isoformat() if row.contacted_at else None,
                "top_fit": row.top_fit,
            }
            for row in page.rows
        ],
        "page": {
            "limit": page.limit,
            "cursor": page.cursor,
            "next_cursor": page.next_cursor,
            "has_more": page.has_more,
            "scan_truncated": page.scan_truncated,
        },
        "read_at": as_of.isoformat(),
        "plan_code": access.plan_code,
    }


@router.get("/companies/{company_key}", response_model=CompanyProfile)
def get_company(company_key: str, request: Request) -> CompanyProfile:
    """Return a company only while this account retains one unlocked current signal."""
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        profile, items, _access, lang = _accessible_company(connection, session, company_key, now)
        signals = _company_signals(
            connection,
            items=items,
            company_key=company_key,
            account_id=session.account_id,
            lang=lang,
        )
        contact = company_engagement.get_contact(
            connection, account_id=session.account_id, company_key=company_key
        )
        note = company_engagement.get_note(
            connection, account_id=session.account_id, company_key=company_key
        )
        most_recent = min(items, key=lambda item: history_sort_key(item.signal))
        place = most_recent.signal.award.place_of_performance or {}
        history = _company_history(
            connection,
            account_id=session.account_id,
            company_key=company_key,
            items=items,
        )
    return profile.model_copy(
        update={
            "city": place.get("locality"),
            "contact_status": contact.status if contact is not None else "to_contact",
            "contacted_at": contact.contacted_at if contact is not None else None,
            "note": note.body if note is not None else None,
            "signals": signals,
            "history": history,
        }
    )


@router.post("/companies/{company_key}/contact")
def set_company_contact(
    company_key: str, payload: CompanyContactRequest, request: Request
) -> dict[str, Any]:
    """PR1 §4 — le suivi commercial d'une entreprise, distinct du jugement d'un signal."""
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        _accessible_company(connection, session, company_key, now)
        # `payload.status` is already restricted by the pydantic `Literal` —
        # `InvalidContactStatus` in `engagement/company.py` exists for direct
        # (non-HTTP) callers, and can never fire from here.
        stored = company_engagement.set_contact(
            connection,
            account_id=session.account_id,
            company_key=company_key,
            status=payload.status,
            now=now,
        )
        analytics.record(
            connection,
            account_id=session.account_id,
            user_id=session.user_id,
            signal_key=None,
            target_icp_id=None,
            event_type="company_contact_updated",
            occurred_at=now,
            properties={"company_key": company_key, "status": stored.status},
        )
    return {
        "company_key": stored.company_key,
        "contact_status": stored.status,
        "contacted_at": stored.contacted_at.isoformat() if stored.contacted_at else None,
        "updated_at": stored.updated_at.isoformat(),
    }


@router.put("/companies/{company_key}/note")
def set_company_note(
    company_key: str, payload: CompanyNoteRequest, request: Request
) -> dict[str, Any]:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        _accessible_company(connection, session, company_key, now)
        stored = company_engagement.put_note(
            connection,
            account_id=session.account_id,
            company_key=company_key,
            body=payload.body,
            now=now,
        )
        analytics.record(
            connection,
            account_id=session.account_id,
            user_id=session.user_id,
            signal_key=None,
            target_icp_id=None,
            event_type="company_note_updated",
            occurred_at=now,
            properties={"company_key": company_key, "deleted": stored is None},
        )
    return {
        "company_key": company_key,
        "note": stored.body if stored is not None else None,
        "updated_at": (stored.updated_at if stored is not None else now).isoformat(),
    }
