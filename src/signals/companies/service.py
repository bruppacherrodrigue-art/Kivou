"""Account-scoped assembly of official SaaS company profiles."""

from __future__ import annotations

import datetime as dt
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
from signals.companies.identity import IdentityMethod, official_company_identity
from signals.companies.store import StoredCompany, get_company_by_key, get_or_create_company
from signals.feed import query as feed_query
from signals.feed import view as feed_view
from signals.persistence.repository import SIGNAL_SELECT, signal_from_row
from signals.persistence.schema import contract_award, materialized_signal, source_event

_SCAN_CAP = 500


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
    if item.display is None:
        return None
    source = _award_sources(connection, {item.display.from_award_key}).get(
        item.display.from_award_key
    )
    if source is None:
        return None
    parties, observed_at = source
    resolved = official_company_identity(
        awardee_parties=parties,
        display=item.display,
        opportunity_key=item.signal.opportunity_key,
        observed_at=observed_at,
    )
    if resolved is None:
        return None
    stored = get_or_create_company(
        connection,
        resolved=resolved,
        source_award_key=item.display.from_award_key,
        origin_signal_key=item.signal.signal_key,
        now=now,
    )
    return stored.company_key


def _candidate_query(
    *,
    account_id: str,
    stored: StoredCompany,
    allowed_target_icp_ids: frozenset[str],
) -> sa.Select:
    scoped = SIGNAL_SELECT.join(
        target_icp, materialized_signal.c.target_icp_id == target_icp.c.target_icp_id
    ).where(
        target_icp.c.account_id == account_id,
        target_icp.c.status == feed_query.FEEDING_ICP_STATUS,
        target_icp.c.plan_limit_code.is_(None),
        materialized_signal.c.invalidated_at.is_(None),
        materialized_signal.c.target_icp_revision == target_icp.c.matching_revision,
        materialized_signal.c.target_icp_id.in_(sorted(allowed_target_icp_ids)),
    )

    if stored.identity_method is IdentityMethod.OPPORTUNITY:
        identity_scope = materialized_signal.c.opportunity_key == stored.identity_validation[
            "opportunity_key"
        ]
    else:
        probes: list[sa.ColumnElement[bool]] = [
            materialized_signal.c.winner_name == stored.official_identity.name
        ]
        if stored.official_identity.identifiers:
            probes.append(
                materialized_signal.c.winner_identifier_value
                == stored.official_identity.identifiers[0].value
            )
        identity_scope = sa.or_(*probes)

    return (
        scoped.where(identity_scope)
        .order_by(None)
        .order_by(materialized_signal.c.materialized_at.desc(), materialized_signal.c.signal_key)
        .limit(_SCAN_CAP + 1)
    )


def _matching_items(
    connection: sa.Connection,
    *,
    stored: StoredCompany,
    account_id: str,
    as_of: dt.date,
    allowed_target_icp_ids: frozenset[str],
) -> tuple[list[feed_query.FeedSignal], bool]:
    if not allowed_target_icp_ids:
        return [], True
    rows = connection.execute(
        _candidate_query(
            account_id=account_id,
            stored=stored,
            allowed_target_icp_ids=allowed_target_icp_ids,
        )
    ).all()
    scan_complete = len(rows) <= _SCAN_CAP
    rows = rows[:_SCAN_CAP]
    owned = feed_query.owned_target_icps(connection, account_id=account_id)
    signals = [signal_from_row(row) for row in rows]
    displays = feed_query.resolve_display_identity(connection, signals)
    display_awards = {display.from_award_key for display in displays.values()}
    sources = _award_sources(connection, display_awards)

    matches: list[feed_query.FeedSignal] = []
    for signal in signals:
        display = displays.get(signal.signal_key)
        if display is None:
            continue
        source = sources.get(display.from_award_key)
        if source is None:
            continue
        parties, observed_at = source
        resolved = official_company_identity(
            awardee_parties=parties,
            display=display,
            opportunity_key=signal.opportunity_key,
            observed_at=observed_at,
        )
        if resolved is None or resolved.identity_fingerprint != stored.identity_fingerprint:
            continue
        profile = owned.get(signal.target_icp_id)
        if profile is None:
            continue
        matches.append(
            feed_query.FeedSignal(
                signal=signal,
                recency=signal.current_recency(as_of=as_of),
                account_id=account_id,
                target_icp_label=profile.label,
                display=display,
            )
        )
    matches.sort(key=lambda item: item.sort_key)
    response_complete = scan_complete and len(matches) <= MAX_RELATED_SIGNALS
    return matches[:MAX_RELATED_SIGNALS], response_complete


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
    candidates, complete = _matching_items(
        connection,
        stored=stored,
        account_id=account_id,
        as_of=as_of,
        allowed_target_icp_ids=allowed_target_icp_ids,
    )
    unlocked = [item for item in candidates if access.is_unlocked(item)]
    if not unlocked:
        return None
    return CompanyProfile(
        company_key=stored.company_key,
        official_identity=stored.official_identity,
        related_signals=tuple(_related_signal(item, lang=lang) for item in unlocked),
        coverage=_coverage(stored.official_identity, complete=complete),
    )
