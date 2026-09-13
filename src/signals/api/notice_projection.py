"""Commercial facts for V11; reads only persisted sources and applies field rights."""

from __future__ import annotations

from typing import Any

from pydantic import EmailStr, TypeAdapter, ValidationError

from signals.billing.catalogue import PlanEntitlements
from signals.client_value.capabilities import usable_phone
from signals.client_value.notice_facts import NoticeAwardFacts
from signals.companies.contracts import safe_https_url

_EMAIL = TypeAdapter(EmailStr)


def _text(fact) -> str | None:
    return fact.value if fact else None


def _duration(fact):
    if fact is None:
        return None
    return {
        "value": fact.value,
        "unit": fact.unit,
        "scope": fact.scope,
        "period_kind": fact.period_kind,
        "source_path": fact.source_path,
        "source_notice_id": fact.source_notice_id,
        "source_url": fact.source_url,
        "notice_kind": fact.notice_kind,
    }


def _money(fact):
    return {"value": fact.value, "currency": fact.currency} if fact else None


def project_notice_facts(
    facts: NoticeAwardFacts, *, entitlements: PlanEntitlements
) -> dict[str, Any]:
    contacts = []
    for party in facts.winning_parties:
        for holder in party.members:
            email = None
            website = None
            try:
                email = str(_EMAIL.validate_python(_text(holder.email))) if holder.email else None
            except ValidationError:
                pass
            try:
                website = safe_https_url(_text(holder.website))
            except ValueError:
                pass
            phone = usable_phone(_text(holder.phone))
            if not any((phone, email, website)):
                continue
            contact = {
                "organization_name": holder.name.value,
                "organization_ref": holder.organization_ref,
                "source": "boamp",
                "observed_at": facts.source.collected_at.isoformat(),
            }
            contact.update(
                {
                    key: value
                    for key, value in {
                        "phone": phone,
                        "email": email,
                        "website": website,
                        "contact_name": _text(holder.contact_name),
                    }.items()
                    if value
                }
            )
            contacts.append(contact)
    available = [
        field
        for field in ("phone", "email", "website")
        if any(field in contact for contact in contacts)
    ]
    duration = _duration(facts.duration)
    initial = _duration(getattr(facts, "initial_duration", None))
    maximum = _duration(getattr(facts, "maximum_duration", None))
    calendar = None
    if duration or initial or maximum or facts.maximum_renewals is not None:
        calendar = {
            "duration": duration,
            "initial_duration": initial,
            "maximum_duration": maximum,
            "renewals": int(facts.maximum_renewals.value) if facts.maximum_renewals else None,
        }
    # Do not return source snapshots, content hashes, raw descriptions or buyer
    # personal data. The single source link is sufficient in the commercial UI.
    return {
        "source_system": facts.source.source_system,
        "source_notice_id": facts.source.source_notice_id,
        "source_url": facts.source.source_url,
        "collected_at": facts.source.collected_at.isoformat(),
        "publication_date": facts.published_on.value.isoformat() if facts.published_on else None,
        "lot_identifier": facts.lot_identifier,
        "title": _text(facts.lot_title) or _text(facts.title),
        "description": (_text(facts.lot_description) or "")[:4000] or None,
        "awarded_amount": _money(facts.awarded_value),
        "minimum_amount": _money(facts.minimum_value),
        "maximum_amount": _money(facts.maximum_value),
        "calendar": calendar,
        "buyers": [{"name": buyer.name.value} for buyer in facts.buyers],
        "contacts": contacts if entitlements.is_paid else [],
        "available_contact_fields": available,
        "contacts_locked": not entitlements.is_paid,
        "notice_status": facts.notice_status,
    }
