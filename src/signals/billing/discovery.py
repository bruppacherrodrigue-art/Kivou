"""Account-locked lifetime grants; a token bait consumes one of three places."""
from __future__ import annotations

import dataclasses
import datetime as dt
import uuid

import sqlalchemy as sa
from pydantic import ValidationError

from signals.accounts.schema import account
from signals.billing.catalogue import DISCOVERY_GRANT_LIMIT
from signals.billing.schema import discovery_signal_grant


@dataclasses.dataclass(frozen=True)
class Grant:
    account_id: str
    signal_key: str
    opportunity_key: str
    granted_at: dt.datetime


def lock_account(connection: sa.Connection, *, account_id: str) -> None:
    connection.execute(sa.select(account.c.account_id).where(
        account.c.account_id == account_id
    ).with_for_update()).scalar_one()


def granted_signal_keys(connection: sa.Connection, *, account_id: str) -> frozenset[str]:
    return frozenset(connection.scalars(sa.select(discovery_signal_grant.c.signal_key).where(
        discovery_signal_grant.c.account_id == account_id
    )))


def grants(connection: sa.Connection, *, account_id: str) -> tuple[Grant, ...]:
    rows = connection.execute(sa.select(discovery_signal_grant).where(
        discovery_signal_grant.c.account_id == account_id
    ).order_by(discovery_signal_grant.c.granted_at, discovery_signal_grant.c.signal_key))
    return tuple(Grant(row.account_id, row.signal_key, row.opportunity_key,
                       _aware(row.granted_at)) for row in rows)


def remaining_slots(connection: sa.Connection, *, account_id: str) -> int:
    # No calendar boundary: Discovery is a lifetime gift, never a monthly reset.
    return max(0, DISCOVERY_GRANT_LIMIT - len(granted_signal_keys(connection, account_id=account_id)))


def _aware(value: dt.datetime) -> dt.datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)


def procedure_aliases(*, source: str, country: str, procedure: str | None,
                      notice: str | None) -> frozenset[str]:
    """Global UUIDs cross sources; local IDs and notice fallbacks are namespaced.

    Notice aliases prevent separate lots sharing a notice. Missing references
    fail closed: opportunity, award and lot keys are never procedure fallbacks.
    """
    aliases = set()
    namespace = f"{country.upper()}:{source.casefold()}"
    if procedure and procedure.strip():
        value = procedure.strip()
        try:
            canonical = str(uuid.UUID(value.removeprefix("urn:uuid:")))
        except ValueError:
            aliases.add(f"procedure:{namespace}:{value}")
        else:
            aliases.add(f"procedure:uuid:{canonical}")
    if notice and notice.strip():
        aliases.add(f"notice:{namespace}:{notice.strip()}")
    return frozenset(aliases)


def opportunity_facts(connection: sa.Connection, opportunity_keys, *, as_of: dt.date) -> dict:
    """Check ALL stored representations, without provider calls or writes."""
    from signals.domain.prospect import prospect_refusal_codes
    from signals.ingestion.persisted import canonical_award, canonical_event
    from signals.persistence.schema import contract_award, opportunity_representation, source_event

    keys = tuple(set(opportunity_keys))
    if not keys:
        return {}
    rows = connection.execute(sa.select(
        opportunity_representation.c.opportunity_key, source_event, contract_award
    ).select_from(opportunity_representation.join(
        contract_award, opportunity_representation.c.award_key == contract_award.c.award_key
    ).join(source_event, contract_award.c.event_key == source_event.c.event_key)).where(
        opportunity_representation.c.opportunity_key.in_(keys)
    ).order_by(opportunity_representation.c.opportunity_key, contract_award.c.award_key))
    facts = {}
    for row in rows:
        entry = facts.setdefault(row.opportunity_key, {
            "aliases": set(), "eligible": [], "named": False, "refusal_codes": set(),
        })
        entry["aliases"].update(procedure_aliases(
            source=row._mapping[source_event.c.source_system],
            country=row._mapping[source_event.c.source_country],
            procedure=row._mapping[source_event.c.source_procedure_id],
            notice=row._mapping[source_event.c.source_notice_id],
        ))
        try:
            event = canonical_event(row)
            award = canonical_award(row, event)
        except ValidationError as error:
            # Legacy facts can predate canonical validation. Reject this
            # representation, not the whole account or its named alternatives.
            title_only = all(tuple(item["loc"]) in {("title",), ("lot", "title")}
                             for item in error.errors())
            entry["refusal_codes"].add(
                "SIGNAL_OBJECT_UNRESOLVED" if title_only else "SOURCE_REPRESENTATION_INVALID"
            )
            continue
        codes = set(prospect_refusal_codes(award, event, as_of=as_of))
        # prospect_refusal_codes owns object eligibility, including its
        # existing CPV-label fallback. Do not add a stricter parallel policy.
        if not codes.intersection({"WINNER_NAME_UNRESOLVED", "SIGNAL_OBJECT_UNRESOLVED"}):
            entry["named"] = True
        if not codes:
            entry["eligible"].append((event, award))
        entry["refusal_codes"].update(codes)
    for entry in facts.values():
        if entry["eligible"]:
            entry["refusal_codes"] = set()
        if not entry["aliases"]:
            entry["refusal_codes"].add("PROCEDURE_REFERENCE_UNRESOLVED")
            entry["eligible"] = []
    return facts


def fit_sort_key(item):
    from signals.dashboard.service import _top3_sort_key
    return (*(-part for part in _top3_sort_key(item)), item.signal.signal_key)


def is_token_discovery(connection: sa.Connection, *, account_id: str, as_of: dt.date) -> bool:
    from signals.accounts import service as accounts
    from signals.billing.access import feed_access
    return (accounts.landing_signal(connection, account_id=account_id) is not None
            and not feed_access(connection, account_id=account_id, as_of=as_of).is_paid)


def grant_up_to_limit(connection: sa.Connection, *, account_id: str,
                      candidates: list, now: dt.datetime) -> tuple[str, ...]:
    from signals.accounts import service as accounts

    lock_account(connection, account_id=account_id)
    existing = grants(connection, account_id=account_id)
    slots = max(0, DISCOVERY_GRANT_LIMIT - len(existing))
    if not slots:
        return ()
    already = {row.signal_key for row in existing}
    landing = accounts.landing_signal(connection, account_id=account_id)
    facts, used = {}, set()
    if landing is not None:
        facts = opportunity_facts(connection,
            [item.signal.opportunity_key for item in candidates]
            + [row.opportunity_key for row in existing], as_of=now.date())
        for row in existing:
            aliases = facts.get(row.opportunity_key, {}).get("aliases", set())
            if not aliases:
                return ()
            used.update(aliases)
        candidates = sorted(candidates, key=lambda item: (
            item.signal.signal_key != landing.signal_key, fit_sort_key(item)))
        if landing.signal_key not in already:
            bait = next((item for item in candidates
                         if item.signal.signal_key == landing.signal_key), None)
            evidence = facts.get(bait.signal.opportunity_key, {}) if bait else {}
            if not evidence.get("eligible") or used.intersection(evidence.get("aliases", ())):
                return ()
    newly = []
    for item in candidates:
        if not slots:
            break
        key = item.signal.signal_key
        if key in already or item.account_id != account_id:
            continue
        if landing is not None:
            evidence = facts.get(item.signal.opportunity_key, {})
            aliases = evidence.get("aliases", set())
            if not evidence.get("eligible") or not aliases or used.intersection(aliases):
                continue
            if key != landing.signal_key and (
                item.signal.icp_match_decision != "show" or item.model_fit == "none"
            ):
                continue
            used.update(aliases)
        connection.execute(sa.insert(discovery_signal_grant).values(
            account_id=account_id, signal_key=key, opportunity_key=item.signal.opportunity_key,
            granted_at=now, created_at=now,
        ))
        newly.append(key)
        already.add(key)
        slots -= 1
    return tuple(newly)


def fill_token_cohort(connection: sa.Connection, *, account_id: str,
                      now: dt.datetime) -> tuple[str, ...]:
    from signals.accounts import service as accounts
    from signals.billing import service as billing
    from signals.billing.access import feed_access
    from signals.feed import query

    landing = accounts.landing_signal(connection, account_id=account_id)
    if landing is None or landing.signal_key is None:
        return ()
    access = feed_access(connection, account_id=account_id, as_of=now.date())
    if access.is_paid:
        return ()
    lock_account(connection, account_id=account_id)
    if remaining_slots(connection, account_id=account_id) == 0:
        return ()
    allowed = frozenset(billing.feedable_target_icps(
        connection, account_id=account_id, limit=access.entitlements.max_active_icps))
    page = query.feed_page(connection, account_id=account_id, as_of=now.date(), freshness="all",
                           allowed_target_icp_ids=allowed, limit=1)
    candidates = list(page.matched)
    if landing.signal_key not in {item.signal.signal_key for item in candidates}:
        bait = query.owned_signal(connection, account_id=account_id, signal_key=landing.signal_key,
                                  as_of=now.date(), allowed_target_icp_ids=allowed)
        if bait is not None:
            candidates.append(bait)
    return grant_up_to_limit(connection, account_id=account_id, candidates=candidates, now=now)


def cohort_audit(connection: sa.Connection, *, account_id: str, now: dt.datetime) -> dict:
    from signals.accounts import service as accounts

    landing = accounts.landing_signal(connection, account_id=account_id)
    rows = grants(connection, account_id=account_id)
    facts = opportunity_facts(connection, [row.opportunity_key for row in rows], as_of=now.date())
    keys = {row.signal_key for row in rows}
    return {
        "account_id": account_id, "quota": DISCOVERY_GRANT_LIMIT,
        "used": len(rows), "remaining": max(0, DISCOVERY_GRANT_LIMIT - len(rows)),
        "bait_signal_key": landing.signal_key if landing else None,
        "legacy_bait_conflict": bool(rows and landing and landing.signal_key
                                     and landing.signal_key not in keys),
        "grants": [{"signal_key": row.signal_key, "opportunity_key": row.opportunity_key,
                    "granted_at": row.granted_at.isoformat(),
                    "procedure_references": sorted(facts.get(row.opportunity_key, {}).get("aliases", ()))}
                   for row in rows],
    }
