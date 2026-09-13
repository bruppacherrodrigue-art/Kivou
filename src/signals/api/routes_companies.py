"""Authenticated SaaS company profiles, scoped through current unlocked signals."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from signals.accounts import service as accounts
from signals.accounts.schema import target_icp
from signals.api.cards import presentation_bindings_for_items, render_unlocked_card
from signals.api.dependencies import current_session, enforce_origin, request_now
from signals.api.errors import api_error
from signals.billing import service as billing
from signals.billing.access import FeedAccess, feed_access
from signals.card_intelligence.store import published_for_signals
from signals.client_value import user_contacts
from signals.client_value.capabilities import company_capabilities, project_directory
from signals.client_value.company_identity import (
    exact_french_siren,
    register_alias,
    resolve_subject,
)
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
from signals.client_value.prospecting import company_membership, follow_company
from signals.companies.contracts import (
    CompanyContactLookupView,
    CompanyCoverage,
    CompanyProfile,
    DirectoryCompanyProfileView,
)
from signals.companies.enrichment import (
    requeue_winner_enrichments,
    winner_enrichments_for_signals,
)
from signals.companies.listing import InvalidCompanyCursor, list_companies
from signals.companies.schema import saas_company
from signals.companies.service import company_profile_with_items
from signals.companies.store import get_company_by_key
from signals.engagement import analytics, feedback, notes
from signals.engagement import company as company_engagement
from signals.engagement.prospecting_schema import (
    account_company_alias_override,
    account_company_membership,
    company_subject_alias,
)
from signals.engagement.schema import (
    COMPANY_CONTACT_STATUSES,
    MAXIMUM_COMPANY_NOTE_LENGTH,
    product_event,
)
from signals.engagement.status import status_resolver, workflow_by_signal
from signals.feed import query as feed_query
from signals.feed.history import history_sort_key
from signals.persistence.schema import materialized_signal, supplier_directory

router = APIRouter()
logger = logging.getLogger(__name__)

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
    expected_revision: int | None = Field(default=None, strict=True, ge=0)


class FollowCompanyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _subject(connection, *, account_id, company_key, now, profile=None):
    siren = _directory_siren_for_company_key(company_key)
    if siren is None and profile is not None:
        siren = exact_french_siren(
            profile.official_identity.identifiers, country=profile.official_identity.country
        )
    if siren is None:
        row = (
            connection.execute(
                sa.select(saas_company).where(
                    saas_company.c.company_key == company_key,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row:
            siren = exact_french_siren(row["official_identifiers"], country=row["official_country"])
    if siren:
        register_alias(connection, company_key=company_key, siren=siren, now=now)
    return resolve_subject(connection, account_id=account_id, company_key=company_key, now=now)


def _private_context(connection, *, subject, account_id, access, request):
    private_key = subject.private_subject_key
    note = company_engagement.get_note(connection, account_id=account_id, company_key=private_key)
    contact = company_engagement.get_contact(
        connection, account_id=account_id, company_key=private_key
    )
    return {
        "canonical_company_key": subject.canonical_company_key,
        "private_subject_key": private_key,
        "identity_resolution": subject.resolution,
        "note": note.body if note else None,
        "note_revision": note.revision if note else 0,
        "note_updated_at": note.updated_at if note else None,
        "contact_status": contact.status if contact else "to_contact",
        "contacted_at": contact.contacted_at if contact else None,
        "manual_contact": user_contacts.get_contact(
            connection, account_id=account_id, company_key=private_key
        ),
        "membership": company_membership(
            connection, account_id=account_id, company_key=private_key
        ),
        "capabilities": company_capabilities(
            access.entitlements,
            lookup_available=request.app.state.company_contact_lookup_service is not None,
        ),
    }


def _has_directory_company(connection, siren):
    return siren is not None and connection.scalar(
        sa.select(sa.exists().where(supplier_directory.c.siren == siren))
    )


def _accessible_subject(connection, session, company_key, now):
    directory_siren = _directory_siren_for_company_key(company_key)
    profile = None
    if _has_directory_company(connection, directory_siren):
        _require_directory_company(connection, directory_siren)
    else:
        profile, _, _, _ = _accessible_company(connection, session, company_key, now)
    return _subject(
        connection, account_id=session.account_id, company_key=company_key, now=now, profile=profile
    )


def _company_candidates(connection, *, account_id, company_key):
    """Exact canonical aliases only; account-owned history is an identity hint,
    never an access grant. Every returned candidate is authorized separately.
    """
    siren = _directory_siren_for_company_key(company_key)
    if siren is None:
        return (company_key,)
    registered = sa.select(company_subject_alias.c.alias_company_key).where(
        company_subject_alias.c.canonical_company_key == company_key,
        company_subject_alias.c.resolution_status == "exact",
    )
    owned_fingerprints = (
        sa.select(materialized_signal.c.company_identity_fingerprint)
        .select_from(
            materialized_signal.join(
                target_icp, target_icp.c.target_icp_id == materialized_signal.c.target_icp_id
            )
        )
        .where(target_icp.c.account_id == account_id)
    )
    rows = connection.execute(
        sa.select(saas_company)
        .where(
            ~sa.exists(
                sa.select(company_subject_alias.c.alias_company_key).where(
                    company_subject_alias.c.alias_company_key == saas_company.c.company_key,
                    sa.or_(
                        company_subject_alias.c.resolution_status != "exact",
                        company_subject_alias.c.canonical_company_key != company_key,
                    ),
                )
            ),
            sa.or_(
                saas_company.c.company_key.in_(registered),
                saas_company.c.identity_fingerprint.in_(owned_fingerprints),
            ),
        )
        .order_by(saas_company.c.company_key)
    ).mappings()
    return tuple(
        row["company_key"]
        for row in rows
        if exact_french_siren(
            row["official_identifiers"],
            country=row["official_country"],
        )
        == siren
    )


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
    candidates = _company_candidates(
        connection, account_id=session.account_id, company_key=company_key
    )
    for candidate in candidates:
        result = company_profile_with_items(
            connection,
            company_key=candidate,
            account_id=session.account_id,
            as_of=as_of,
            allowed_target_icp_ids=allowed,
            access=access,
            lang=lang,
        )
        if result is not None:
            profile, items = result
            return profile.model_copy(update={"company_key": company_key}), items, access, lang
    private_key = (
        connection.scalar(
            sa.select(account_company_alias_override.c.private_subject_key).where(
                account_company_alias_override.c.account_id == session.account_id,
                account_company_alias_override.c.alias_company_key == company_key,
                sa.exists(
                    sa.select(company_subject_alias.c.alias_company_key).where(
                        company_subject_alias.c.alias_company_key == company_key,
                        company_subject_alias.c.resolution_status == "exact",
                    )
                ),
            )
        )
        or company_key
    )
    membership = connection.scalar(
        sa.select(account_company_membership.c.company_key).where(
            account_company_membership.c.account_id == session.account_id,
            account_company_membership.c.company_key == private_key,
        )
    )
    if membership is not None:
        for candidate in candidates:
            stored = get_company_by_key(connection, company_key=candidate)
            if stored is not None:
                return (
                    CompanyProfile(
                        company_key=company_key,
                        official_identity=stored.official_identity,
                        related_signals=(),
                        coverage=CompanyCoverage(
                            related_signals_complete=False,
                            unavailable_fields=("current_unlocked_signals",),
                        ),
                    ),
                    [],
                    access,
                    lang,
                )
    raise api_error(404, "company_not_found", "entreprise introuvable")


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
    workflows = workflow_by_signal(connection, account_id=account_id)
    resolve_status = status_resolver(
        feedback.feedback_by_signal(connection, account_id=account_id), workflows
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
        {
            **render_unlocked_card(
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
            ),
            "status_revision": workflows[item.signal.signal_key].revision
            if item.signal.signal_key in workflows
            else 0,
        }
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


def _siren_from_identifiers(identifiers) -> str | None:
    for identifier in identifiers or ():
        value = identifier.value if hasattr(identifier, "value") else identifier.get("value", "")
        raw_scheme = (
            identifier.scheme if hasattr(identifier, "scheme") else identifier.get("scheme", "")
        )
        digits = "".join(character for character in str(value) if character.isdigit())
        scheme = str(raw_scheme).casefold()
        if scheme == "siren" and len(digits) == 9:
            return digits
        source_formatted_siret = scheme == "boamp-company-id" and bool(
            re.fullmatch(r"[\d\s]+", str(value).strip())
        )
        if (scheme == "siret" or source_formatted_siret) and len(digits) == 14:
            return digits[:9]
    return None


def _siren_for_profile(profile: CompanyProfile) -> str | None:
    return _siren_from_identifiers(profile.official_identity.identifiers)


def _directory_cities_for_companies(
    connection: sa.Connection, company_keys: tuple[str, ...]
) -> dict[str, str]:
    if not company_keys:
        return {}
    identities = connection.execute(
        sa.select(saas_company.c.company_key, saas_company.c.official_identifiers).where(
            saas_company.c.company_key.in_(company_keys)
        )
    ).mappings()
    siren_by_company = {
        row["company_key"]: siren
        for row in identities
        if (siren := _siren_from_identifiers(row["official_identifiers"])) is not None
    }
    if not siren_by_company:
        return {}
    city_by_siren = dict(
        connection.execute(
            sa.select(supplier_directory.c.siren, supplier_directory.c.city).where(
                supplier_directory.c.siren.in_(tuple(siren_by_company.values())),
                supplier_directory.c.city.is_not(None),
                supplier_directory.c.suppressed_at.is_(None),
            )
        ).all()
    )
    return {
        company_key: city_by_siren[siren]
        for company_key, siren in siren_by_company.items()
        if siren in city_by_siren
    }


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
    target_icp_id: str | None = None,
    offer_category: str | None = None,
    subdivision_code: str | None = None,
    amount_currency: Literal["EUR", "CHF"] | None = None,
    min_amount: str | None = None,
    sort: Literal["recent", "amount"] = "recent",
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
    from signals.client_value.targeting import context_fingerprint, resolve_scope

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
                limit=access.entitlements.max_active_icps if target_icp_id is not None else None,
            )
        )
        consultation = resolve_scope(
            connection,
            account_id=session.account_id,
            entitlements=access.entitlements,
            allowed_target_icp_ids=allowed,
            target_icp_id=target_icp_id,
            offer_category=offer_category,
            subdivision_code=subdivision_code,
            min_amount=min_amount,
            amount_currency=amount_currency,
            query_parameters=request.query_params,
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
                consultation_scope=consultation,
                sort=sort,
                context_tag=context_fingerprint(
                    {
                        "scope": consultation.context_tag,
                        "q": q,
                        "contact_statuses": sorted(statuses) if statuses is not None else None,
                        "sort": sort,
                    }
                ),
            )
        except InvalidCompanyCursor as error:
            raise api_error(422, "invalid_company_cursor", "curseur invalide") from error
        directory_cities = _directory_cities_for_companies(
            connection, tuple(row.company_key for row in page.rows)
        )
    return {
        "scope": consultation.payload(),
        "counts": page.counts,
        "total": page.total,
        "counts_available": True,
        "counts_truncated": page.scan_truncated,
        "items": [
            {
                "company_key": row.company_key,
                "name": row.name,
                "city": directory_cities.get(row.company_key) or row.city,
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
                "tracked": row.tracked,
                "origin": row.origin,
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


@router.get("/companies/{company_key}", response_model=CompanyProfile | DirectoryCompanyProfileView)
def get_company(company_key: str, request: Request) -> CompanyProfile | DirectoryCompanyProfileView:
    """Return a company only while this account retains one unlocked current signal."""
    now = request_now(request)
    directory_siren = _directory_siren_for_company_key(company_key)
    if directory_siren:
        with request.app.state.engine.connect() as connection:
            cached_directory = _has_directory_company(connection, directory_siren)
        if cached_directory:
            return get_directory_company(directory_siren, request)
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
        most_recent = min(items, key=lambda item: history_sort_key(item.signal), default=None)
        client_place = (
            (
                most_recent.signal.award.client_location
                or most_recent.signal.award.place_of_performance
            )
            if most_recent is not None
            else None
        )
        place = client_place or {}
        history = _company_history(
            connection,
            account_id=session.account_id,
            company_key=company_key,
            items=items,
        )
        holder_history = (
            history_for_company(
                connection,
                company_key=company_key,
                winner_name=profile.official_identity.name,
                department=department_for_place(client_place),
                as_of=now.date(),
            )
            if items
            else None
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
            department=department_for_place(client_place),
            include_public_contact=True,
        )
        directory = project_directory(directory, entitlements=access.entitlements)
        subject = _subject(
            connection,
            account_id=session.account_id,
            company_key=company_key,
            now=now,
            profile=profile,
        )
        private_context = _private_context(
            connection,
            subject=subject,
            account_id=session.account_id,
            access=access,
            request=request,
        )
        available_fields = set(directory.get("available_fields", ())) if directory else set()
        if profile.official_identity.website_url:
            available_fields.add("website")
        if not access.entitlements.is_paid:
            profile = profile.model_copy(
                update={
                    "official_identity": profile.official_identity.model_copy(
                        update={"website_url": None}
                    )
                }
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
        "plan_code": access.plan_code,
        "available_fields": sorted(available_fields),
        **private_context,
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
            include_public_contact=True,
        )
        if directory is None:
            raise api_error(404, "company_not_found", "entreprise introuvable")
        company_key = f"cmp_directory_{siren}"
        directory = project_directory(directory, entitlements=access.entitlements)
        subject = _subject(
            connection, account_id=session.account_id, company_key=company_key, now=now
        )
        private_context = _private_context(
            connection,
            subject=subject,
            account_id=session.account_id,
            access=access,
            request=request,
        )
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
        "plan_code": access.plan_code,
        "directory": directory,
        "markets": list(markets),
        "contact_status": contact.status if contact is not None else "to_contact",
        "contacted_at": contact.contacted_at.isoformat()
        if contact is not None and contact.contacted_at
        else None,
        "note": note.body if note is not None else None,
        "history": list(history),
        **private_context,
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
        subject = _accessible_subject(connection, session, company_key, now)
        # `payload.status` is already restricted by the pydantic `Literal` —
        # `InvalidContactStatus` in `engagement/company.py` exists for direct
        # (non-HTTP) callers, and can never fire from here.
        stored = company_engagement.set_contact(
            connection,
            account_id=session.account_id,
            company_key=subject.private_subject_key,
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
    "/companies/{company_key}/directory-enrichment",
)
def queue_company_directory_enrichment(company_key: str, request: Request) -> dict[str, Any]:
    """Queue the shared directory enrichment without calling Apollo here."""

    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        access = feed_access(connection, account_id=session.account_id, as_of=now.date())
        _accessible_subject(connection, session, company_key, now)
        if not access.entitlements.is_paid:
            raise api_error(
                403, "company_enrichment_locked", "l’enrichissement nécessite une formule payante"
            )
        directory_siren = _directory_siren_for_company_key(company_key)
        if _has_directory_company(connection, directory_siren):
            _require_directory_company(connection, directory_siren)
            return {"queued": False, "state": "ready"}
        profile, items, _access, _lang = _accessible_company(connection, session, company_key, now)
        siren = _siren_for_profile(profile)
        if (
            siren is not None
            and directory_company(
                connection,
                siren=siren,
                legal_name=profile.official_identity.name,
                department=None,
                include_public_contact=False,
            )
            is not None
        ):
            return {"queued": False, "state": "ready"}
        queued = requeue_winner_enrichments(
            connection,
            signal_keys=tuple(item.signal.signal_key for item in items),
            now=now,
        )
        logger.info(
            "company_directory_enrichment_queued",
            extra={
                "account_id": session.account_id,
                "company_key": company_key,
                "queued_signal_count": queued,
            },
        )
    return {
        "queued": queued > 0,
        "state": "queued" if queued > 0 else "already_queued",
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
        if _has_directory_company(connection, directory_siren):
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
            most_recent = min(items, key=lambda item: history_sort_key(item.signal), default=None)
            client_place = (
                (
                    most_recent.signal.award.client_location
                    or most_recent.signal.award.place_of_performance
                )
                if most_recent is not None
                else None
            )
            department = department_for_place(client_place)
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
        if not access.entitlements.is_paid:
            raise api_error(
                403,
                "contact_lookup_locked",
                "la recherche de contact nécessite une formule payante",
            )

    lookup_service = request.app.state.company_contact_lookup_service
    if lookup_service is None:
        logger.warning(
            "company_contact_lookup_unavailable",
            extra={
                "account_id": account_id,
                "company_key": company_key,
                "contact_lookup_error_code": "provider_not_configured",
            },
        )
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
        logger.warning(
            "company_contact_lookup_unavailable",
            extra={
                "account_id": account_id,
                "company_key": company_key,
                "contact_lookup_error_code": "provider_failure",
            },
        )
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
        subject = _accessible_subject(connection, session, company_key, now)
        try:
            stored = company_engagement.put_note(
                connection,
                account_id=session.account_id,
                company_key=subject.private_subject_key,
                body=payload.body,
                expected_revision=payload.expected_revision,
                now=now,
            )
        except notes.NoteRevisionError as error:
            raise api_error(
                409,
                error.code,
                "la note a changé ; comparez la version enregistrée",
                note=error.note,
                revision=error.revision,
                updated_at=error.updated_at.isoformat() if error.updated_at else None,
            ) from error
        analytics.record(
            connection,
            account_id=session.account_id,
            user_id=session.user_id,
            signal_key=None,
            target_icp_id=None,
            event_type="company_note_updated",
            occurred_at=now,
            properties={"company_key": company_key, "deleted": not stored.body},
        )
    return {
        "company_key": company_key,
        "note": stored.body if stored is not None else None,
        "updated_at": (stored.updated_at if stored is not None else now).isoformat(),
        "revision": stored.revision if stored is not None else 0,
    }


@router.put("/companies/{company_key}/prospection")
def follow_company_route(
    company_key: str, payload: FollowCompanyRequest, request: Request
) -> dict[str, Any]:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        subject = _accessible_subject(connection, session, company_key, now)
        return {
            "company_key": company_key,
            **follow_company(
                connection,
                account_id=session.account_id,
                company_key=subject.private_subject_key,
                now=now,
            ),
        }


@router.get("/companies/{company_key}/manual-contact")
def get_manual_contact(company_key: str, request: Request) -> dict[str, Any]:
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        subject = _accessible_subject(connection, session, company_key, now)
        return user_contacts.get_contact(
            connection, account_id=session.account_id, company_key=subject.private_subject_key
        )


@router.put("/companies/{company_key}/manual-contact")
def put_manual_contact(
    company_key: str, payload: user_contacts.ManualContactWrite, request: Request
) -> dict[str, Any]:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        subject = _accessible_subject(connection, session, company_key, now)
        try:
            return user_contacts.put_contact(
                connection,
                account_id=session.account_id,
                company_key=subject.private_subject_key,
                payload=payload,
                now=now,
            )
        except user_contacts.ContactConflict as error:
            raise api_error(
                409,
                "manual_contact_conflict",
                "ce contact a changé ; rechargez sa version enregistrée",
                **error.current,
            ) from error


@router.delete("/companies/{company_key}/manual-contact")
def delete_manual_contact(
    company_key: str, request: Request, if_match: Annotated[str, Header(pattern=r'^"?\d+"?$')]
) -> dict[str, Any]:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        subject = _accessible_subject(connection, session, company_key, now)
        try:
            return user_contacts.delete_contact(
                connection,
                account_id=session.account_id,
                company_key=subject.private_subject_key,
                expected_revision=int(if_match.strip('"')),
                now=now,
            )
        except user_contacts.ContactConflict as error:
            raise api_error(
                409,
                "manual_contact_conflict",
                "ce contact a changé ; rechargez sa version enregistrée",
                **error.current,
            ) from error
