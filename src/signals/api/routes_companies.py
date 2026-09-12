"""Authenticated SaaS company profiles, scoped through current unlocked signals."""

from __future__ import annotations

import re
from collections.abc import Mapping
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
from signals.client_value.contact_lookup import (
    CompanyLookupIdentity,
    ContactLookupIdentityUnavailable,
    ContactLookupProviderFailure,
    ContactLookupQuotaExceeded,
    ContactLookupSuppressed,
)
from signals.client_value.directory import directory_company
from signals.client_value.history import (
    department_for_place,
    directory_history_and_markets,
    history_for_company,
)
from signals.companies.contracts import (
    CompanyContactLookupView,
    CompanyProfile,
    DirectoryCompanyProfileView,
)
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
_SIREN = re.compile(r"^\d{9}$")
_DIRECTORY_COMPANY_KEY = re.compile(r"^cmp_directory_(?P<siren>\d{9})$")


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
    generated_for_you_enabled: bool,
    commercial_start_delay_months_by_cpv_prefix: Mapping[str, int],
) -> tuple[dict[str, Any], ...]:
    """The same card `GET /signals` would render for each item — same
    presentation, same winner enrichment — so this list can never drift from
    the feed's idea of what an unlocked card looks like (§4 F2)."""
    resolve_status = status_resolver(feedback.feedback_by_signal(connection, account_id=account_id))
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
            generated_for_you_enabled=generated_for_you_enabled,
            commercial_start_delay_months_by_cpv_prefix=(
                commercial_start_delay_months_by_cpv_prefix
            ),
        )
        for item in ordered
    )


def _company_history(
    connection, *, account_id: str, company_key: str, items
) -> tuple[dict[str, Any], ...]:
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


def _siren_for_profile(profile: CompanyProfile) -> str | None:
    for identifier in profile.official_identity.identifiers:
        digits = "".join(character for character in identifier.value if character.isdigit())
        scheme = identifier.scheme.casefold()
        if scheme == "siren" and len(digits) == 9:
            return digits
        if scheme == "siret" and len(digits) == 14:
            return digits[:9]
    return None


def _directory_siren_for_company_key(company_key: str) -> str | None:
    match = _DIRECTORY_COMPANY_KEY.fullmatch(company_key)
    return match.group("siren") if match is not None else None


def _require_directory_company(connection, siren: str) -> dict[str, Any]:
    directory = directory_company(
        connection,
        siren=siren,
        legal_name=None,
        department=None,
    )
    if directory is None:
        raise api_error(404, "company_not_found", "entreprise introuvable")
    return directory


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
        profile, items, access, lang = _accessible_company(connection, session, company_key, now)
        signals = _company_signals(
            connection,
            items=items,
            company_key=company_key,
            account_id=session.account_id,
            lang=lang,
            generated_for_you_enabled=request.app.state.config.generated_for_you_enabled,
            commercial_start_delay_months_by_cpv_prefix=(
                request.app.state.config.commercial_start_delay_months_by_cpv_prefix
            ),
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
        holder_history = history_for_company(
            connection,
            company_key=company_key,
            winner_name=profile.official_identity.name,
            department=department_for_place(most_recent.signal.award.place_of_performance),
            as_of=now.date(),
        )
        market_summary = None
        if holder_history is not None:
            market_summary = {
                **holder_history["summary"],
                "last_12_months": holder_history["last_12_months"],
                "resolution": holder_history["resolution"],
                "source": holder_history["source"],
            }
            if "resolution_note" in holder_history:
                market_summary["resolution_note"] = holder_history["resolution_note"]
        directory = directory_company(
            connection,
            siren=_siren_for_profile(profile),
            legal_name=profile.official_identity.name,
            department=department_for_place(most_recent.signal.award.place_of_performance),
            include_public_contact=(
                request.app.state.config.company_profile_v2_enabled
                and access.plan_code != "discovery"
            ),
        )
        account_id = session.account_id
    update = {
        "city": place.get("locality"),
        "contact_status": contact.status if contact is not None else "to_contact",
        "contacted_at": contact.contacted_at if contact is not None else None,
        "note": note.body if note is not None else None,
        "signals": signals,
        "history": history,
        "market_summary": market_summary,
        "directory": directory,
        "company_profile_v2_enabled": request.app.state.config.company_profile_v2_enabled,
        "plan_code": access.plan_code,
    }
    lookup_service = request.app.state.company_contact_lookup_service
    if lookup_service is not None:
        lookup = lookup_service.view(
            account_id=account_id,
            company_key=company_key,
            plan_code=access.plan_code,
            now=now,
            siren=_siren_for_profile(profile),
        )
        if lookup is not None:
            update["contact_lookup"] = lookup
    elif access.plan_code == "discovery":
        # L'invitation vers les offres est un droit produit, pas une donnée
        # Apollo : elle doit rester visible même si le fournisseur n'est pas
        # configuré sur cette instance. Aucun autre plan ne promet un état
        # exploitable sans service de recherche.
        update["contact_lookup"] = {
            "state": "locked",
            "remaining": 0,
            "monthly_quota": 0,
            "source": "apollo",
            "removal_path": "/contact",
        }
    # Re-validate the optional provider projection instead of letting
    # `model_copy(update=...)` bypass the closed response contract.
    return CompanyProfile.model_validate({**profile.model_dump(), **update})


@router.get("/companies/directory/{siren}", response_model=DirectoryCompanyProfileView)
def get_directory_company(siren: str, request: Request) -> DirectoryCompanyProfileView:
    """Read one public directory profile for an authenticated client."""

    now = request_now(request)
    if _SIREN.fullmatch(siren) is None:
        raise api_error(404, "company_not_found", "entreprise introuvable")
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        access = feed_access(connection, account_id=session.account_id, as_of=now.date())
        directory = directory_company(
            connection,
            siren=siren,
            legal_name=None,
            department=None,
            include_public_contact=(
                request.app.state.config.company_profile_v2_enabled
                and access.plan_code != "discovery"
            ),
        )
        if directory is None:
            raise api_error(404, "company_not_found", "entreprise introuvable")
        company_key = f"cmp_directory_{siren}"
        contact = company_engagement.get_contact(
            connection, account_id=session.account_id, company_key=company_key
        )
        note = company_engagement.get_note(
            connection, account_id=session.account_id, company_key=company_key
        )
        history = _company_history(
            connection,
            account_id=session.account_id,
            company_key=company_key,
            items=(),
        )
        holder_history, markets = directory_history_and_markets(
            connection,
            siren=siren,
            winner_name=directory["name"],
            department=directory.get("department", ""),
            as_of=now.date(),
        )
        account_id = session.account_id
    result: dict[str, Any] = {
        "company_key": company_key,
        "company_profile_v2_enabled": request.app.state.config.company_profile_v2_enabled,
        "plan_code": access.plan_code,
        "directory": directory,
        "markets": list(markets),
        "contact_status": contact.status if contact is not None else "to_contact",
        "contacted_at": contact.contacted_at.isoformat()
        if contact is not None and contact.contacted_at
        else None,
        "note": note.body if note is not None else None,
        "history": list(history),
    }
    if holder_history is not None:
        result["market_summary"] = {
            **holder_history["summary"],
            "last_12_months": holder_history["last_12_months"],
            "resolution": holder_history["resolution"],
            "source": holder_history["source"],
            **(
                {"resolution_note": holder_history["resolution_note"]}
                if "resolution_note" in holder_history
                else {}
            ),
        }
    lookup_service = request.app.state.company_contact_lookup_service
    if lookup_service is not None:
        lookup = lookup_service.view(
            account_id=account_id,
            company_key=company_key,
            plan_code=access.plan_code,
            now=now,
            siren=siren,
        )
        if lookup is not None:
            result["contact_lookup"] = lookup
    elif access.plan_code == "discovery":
        result["contact_lookup"] = {
            "state": "locked",
            "remaining": 0,
            "monthly_quota": 0,
            "source": "apollo",
            "removal_path": "/contact",
        }
    return DirectoryCompanyProfileView.model_validate(result)


@router.post("/companies/{company_key}/contact")
def set_company_contact(
    company_key: str, payload: CompanyContactRequest, request: Request
) -> dict[str, Any]:
    """PR1 §4 — le suivi commercial d'une entreprise, distinct du jugement d'un signal."""
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        directory_siren = _directory_siren_for_company_key(company_key)
        if directory_siren is None:
            _accessible_company(connection, session, company_key, now)
        else:
            _require_directory_company(connection, directory_siren)
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


@router.post(
    "/companies/{company_key}/contact-lookup",
    response_model=CompanyContactLookupView,
    response_model_exclude_none=True,
)
def find_company_decision_maker(company_key: str, request: Request) -> dict[str, Any]:
    """Run the bounded Apollo chain after an explicit, authenticated click."""
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        directory_siren = _directory_siren_for_company_key(company_key)
        if directory_siren is not None:
            access = feed_access(connection, account_id=session.account_id, as_of=now.date())
            directory = _require_directory_company(connection, directory_siren)
            identity = CompanyLookupIdentity(
                company_key=company_key,
                siren=directory_siren,
                name=directory["name"],
                city=directory.get("city"),
                website_url=directory.get("website_url"),
            )
        else:
            profile, items, access, _lang = _accessible_company(
                connection, session, company_key, now
            )
            most_recent = min(items, key=lambda item: history_sort_key(item.signal))
            department = department_for_place(most_recent.signal.award.place_of_performance)
            directory = directory_company(
                connection,
                siren=_siren_for_profile(profile),
                legal_name=profile.official_identity.name,
                department=department,
            )
            identity = CompanyLookupIdentity(
                company_key=company_key,
                siren=_siren_for_profile(profile),
                name=profile.official_identity.name,
                city=(directory or {}).get("city"),
                website_url=(directory or {}).get("website_url")
                or profile.official_identity.website_url,
            )
        account_id = session.account_id

    lookup_service = request.app.state.company_contact_lookup_service
    if lookup_service is None:
        raise api_error(
            503,
            "contact_lookup_unavailable",
            "la recherche de contact est temporairement indisponible",
        )
    try:
        return lookup_service.research(
            account_id=account_id,
            plan_code=access.plan_code,
            identity=identity,
            now=now,
        )
    except ContactLookupQuotaExceeded as error:
        if access.plan_code == "discovery":
            raise api_error(
                403,
                "contact_lookup_locked",
                "aucune recherche de contact disponible avec cette formule",
            ) from error
        raise api_error(
            403,
            "contact_lookup_quota_exhausted",
            "le quota mensuel de recherches de contact est épuisé",
        ) from error
    except ContactLookupProviderFailure as error:
        raise api_error(
            503,
            "contact_lookup_failed",
            "la recherche de contact n'a pas abouti",
        ) from error
    except ContactLookupIdentityUnavailable as error:
        raise api_error(
            409,
            "contact_lookup_identity_unavailable",
            "l'identité annuaire de cette entreprise ne permet pas la recherche",
        ) from error
    except ContactLookupSuppressed as error:
        raise api_error(
            409,
            "contact_lookup_suppressed",
            "la recherche de contact n'est pas disponible pour cette entreprise",
        ) from error


@router.put("/companies/{company_key}/note")
def set_company_note(
    company_key: str, payload: CompanyNoteRequest, request: Request
) -> dict[str, Any]:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        directory_siren = _directory_siren_for_company_key(company_key)
        if directory_siren is None:
            _accessible_company(connection, session, company_key, now)
        else:
            _require_directory_company(connection, directory_siren)
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
