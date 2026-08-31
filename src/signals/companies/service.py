"""Account-scoped assembly of official SaaS company profiles."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa

from signals.accounts.schema import target_icp
from signals.billing.access import FeedAccess
from signals.companies.contracts import (
    MAX_RELATED_SIGNALS,
    CompanyCoverage,
    CompanyFit,
    CompanyOfficialIdentity,
    CompanyPlausibleNeed,
    CompanyProfile,
    CompanyRelatedSignal,
    CompanySignalAmount,
    CompanySignalEvent,
)
from signals.companies.identity import ResolvedOfficialCompany, official_company_identity
from signals.companies.indexing import (
    index_signal_company_identities,
    index_signal_company_identity,
)
from signals.companies.store import StoredCompany, get_company_by_key, get_or_create_company
from signals.feed import query as feed_query
from signals.feed import view as feed_view
from signals.persistence.repository import SIGNAL_SELECT, signal_from_row
from signals.persistence.schema import contract_award, materialized_signal, source_event

_SCAN_BATCH = 250


@dataclass(frozen=True)
class _AccessibleCompanySignal:
    item: feed_query.FeedSignal
    resolved: ResolvedOfficialCompany


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def _award_sources(
    connection: sa.Connection, award_keys: set[str]
) -> dict[str, tuple[list[dict[str, Any]], dt.datetime]]:
    if not award_keys:
        return {}
    rows = connection.execute(
        sa.select(
            contract_award.c.award_key,
            contract_award.c.awardee_parties,
            source_event.c.discovered_at,
            contract_award.c.created_at.label("award_created_at"),
        )
        .select_from(
            contract_award.join(
                source_event, contract_award.c.event_key == source_event.c.event_key
            )
        )
        .where(contract_award.c.award_key.in_(sorted(award_keys)))
    ).all()
    return {
        row.award_key: (
            row.awardee_parties,
            _aware(row.discovered_at or row.award_created_at),
        )
        for row in rows
    }


def ensure_company_for_unlocked_signal(
    connection: sa.Connection,
    *,
    item: feed_query.FeedSignal,
    now: dt.datetime,
) -> str | None:
    """Persist the exact public winner after the caller has granted signal access."""
    indexed = index_signal_company_identity(
        connection, signal_key=item.signal.signal_key
    )
    if indexed is None:
        return None
    stored = get_or_create_company(
        connection,
        resolved=indexed.resolved,
        source_award_key=indexed.source_award_key,
        origin_signal_key=item.signal.signal_key,
        now=now,
    )
    return stored.company_key


def ensure_companies_for_unlocked_signals(
    connection: sa.Connection,
    *,
    items: tuple[feed_query.FeedSignal, ...],
    now: dt.datetime,
) -> dict[str, str]:
    """Resolve company keys for an authorised feed page in one identity batch."""
    if not items:
        return {}
    by_signal_key = {item.signal.signal_key: item for item in items}
    indexed = index_signal_company_identities(
        connection,
        signal_keys=tuple(by_signal_key),
    )
    company_key_by_fingerprint: dict[str, str] = {}
    resolved_keys: dict[str, str] = {}
    for signal_key, item in by_signal_key.items():
        identity = indexed.get(signal_key)
        if identity is None:
            continue
        known_key = company_key_by_fingerprint.get(identity.resolved.identity_fingerprint)
        if known_key is None:
            stored = get_or_create_company(
                connection,
                resolved=identity.resolved,
                source_award_key=identity.source_award_key,
                origin_signal_key=item.signal.signal_key,
                now=now,
            )
            known_key = stored.company_key
            company_key_by_fingerprint[identity.resolved.identity_fingerprint] = known_key
        resolved_keys[signal_key] = known_key
    return resolved_keys


def _current_signal_query(
    *,
    account_id: str,
    allowed_target_icp_ids: frozenset[str],
    identity_fingerprint: str,
    after_signal_key: str,
) -> sa.Select:
    return (
        SIGNAL_SELECT.join(
            target_icp, materialized_signal.c.target_icp_id == target_icp.c.target_icp_id
        )
        .where(
            target_icp.c.account_id == account_id,
            target_icp.c.status == feed_query.FEEDING_ICP_STATUS,
            target_icp.c.plan_limit_code.is_(None),
            materialized_signal.c.invalidated_at.is_(None),
            materialized_signal.c.target_icp_revision == target_icp.c.matching_revision,
            materialized_signal.c.target_icp_id.in_(sorted(allowed_target_icp_ids)),
            materialized_signal.c.company_identity_fingerprint == identity_fingerprint,
            materialized_signal.c.signal_key > after_signal_key,
        )
        .order_by(None)
        .order_by(materialized_signal.c.signal_key)
        .limit(_SCAN_BATCH)
    )


def _accessible_matching_items(
    connection: sa.Connection,
    *,
    stored: StoredCompany,
    account_id: str,
    as_of: dt.date,
    allowed_target_icp_ids: frozenset[str],
    access: FeedAccess,
) -> tuple[list[_AccessibleCompanySignal], CompanyOfficialIdentity | None, bool]:
    if not allowed_target_icp_ids:
        return [], None, True
    owned = feed_query.owned_target_icps(connection, account_id=account_id)
    selected: list[_AccessibleCompanySignal] = []
    accessible_count = 0
    latest_identity: CompanyOfficialIdentity | None = None
    latest_identity_rank: tuple[dt.datetime, str] | None = None
    cursor = ""

    while True:
        rows = connection.execute(
            _current_signal_query(
                account_id=account_id,
                allowed_target_icp_ids=allowed_target_icp_ids,
                identity_fingerprint=stored.identity_fingerprint,
                after_signal_key=cursor,
            )
        ).all()
        if not rows:
            break
        cursor = rows[-1].signal_key
        signals = [signal_from_row(row) for row in rows]
        displays = feed_query.resolve_display_identity(connection, signals)
        display_awards = {display.from_award_key for display in displays.values()}
        sources = _award_sources(connection, display_awards)

        for signal in signals:
            display = displays.get(signal.signal_key)
            if display is None:
                continue
            source = sources.get(display.from_award_key)
            if source is None:
                continue
            parties, observed_at = source
            try:
                resolved = official_company_identity(
                    awardee_parties=parties,
                    display=display,
                    opportunity_key=signal.opportunity_key,
                    observed_at=observed_at,
                )
            except (TypeError, ValueError):
                continue
            if resolved is None or resolved.identity_fingerprint != stored.identity_fingerprint:
                continue
            profile = owned.get(signal.target_icp_id)
            if profile is None:
                continue
            item = feed_query.FeedSignal(
                signal=signal,
                recency=signal.current_recency(as_of=as_of),
                account_id=account_id,
                target_icp_label=profile.label,
                display=display,
            )
            if not access.is_unlocked(item):
                continue
            accessible_count += 1
            match = _AccessibleCompanySignal(item=item, resolved=resolved)
            selected.append(match)
            selected.sort(key=lambda candidate: candidate.item.sort_key)
            del selected[MAX_RELATED_SIGNALS:]
            identity_rank = (resolved.official.observed_at, signal.signal_key)
            if latest_identity_rank is None or identity_rank > latest_identity_rank:
                latest_identity = resolved.official
                latest_identity_rank = identity_rank

        if len(rows) < _SCAN_BATCH:
            break

    return selected, latest_identity, accessible_count <= MAX_RELATED_SIGNALS


def _related_signal(item: feed_query.FeedSignal, *, lang: str) -> CompanyRelatedSignal:
    rendered = feed_view.signal_detail(item, lang=lang)
    contract = rendered["contract"]
    event = rendered["event"]
    analysis = rendered["analysis"]
    raw_amount = contract["amount"]
    amount = (
        None
        if raw_amount is None
        else CompanySignalAmount(value=raw_amount["value"], currency=raw_amount["currency"])
    )
    needs = tuple(
        CompanyPlausibleNeed(
            label=need["label"],
            statement=need.get("statement"),
            timing_label=need.get("timing_label"),
            reasoning=need.get("reasoning"),
        )
        for need in analysis["plausible_needs"]["items"]
        if need.get("label")
    )
    fit = analysis["fit"]
    return CompanyRelatedSignal(
        signal_id=item.signal.signal_key,
        contract_title=contract.get("title"),
        amount=amount,
        event=CompanySignalEvent(
            status=event["status"],
            date=event.get("date"),
            headline=event["headline"],
            why_now=event["why_now"],
            award_date_note=event.get("award_date_note"),
        ),
        plausible_needs=needs,
        fit=CompanyFit(label=fit["label"], reasons=tuple(fit["reasons"])),
    )


def _coverage(identity: CompanyOfficialIdentity, *, complete: bool) -> CompanyCoverage:
    unavailable: list[str] = []
    for field, value in (
        ("official_country", identity.country),
        ("official_address", identity.address),
        ("official_identifiers", identity.identifiers),
        ("official_website", identity.website_url),
    ):
        if not value:
            unavailable.append(field)
    return CompanyCoverage(
        related_signals_complete=complete,
        unavailable_fields=tuple(unavailable),
    )


def company_profile_for_account(
    connection: sa.Connection,
    *,
    company_key: str,
    account_id: str,
    as_of: dt.date,
    allowed_target_icp_ids: frozenset[str],
    access: FeedAccess,
    lang: str,
) -> CompanyProfile | None:
    """Return the profile only if this account still has one unlocked current signal."""
    stored = get_company_by_key(connection, company_key=company_key)
    if stored is None:
        return None
    accessible, official_identity, complete = _accessible_matching_items(
        connection,
        stored=stored,
        account_id=account_id,
        as_of=as_of,
        allowed_target_icp_ids=allowed_target_icp_ids,
        access=access,
    )
    if not accessible or official_identity is None:
        return None
    return CompanyProfile(
        company_key=stored.company_key,
        official_identity=official_identity,
        related_signals=tuple(_related_signal(match.item, lang=lang) for match in accessible),
        coverage=_coverage(official_identity, complete=complete),
    )
