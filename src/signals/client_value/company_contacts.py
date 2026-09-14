"""Exact, source-attributed public holder contacts shared by company views.

Candidate awards come from stored public identities, never name searches or
private contact caches. Only latest typed facts are read, in a bounded batch.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

import sqlalchemy as sa
from pydantic import EmailStr, TypeAdapter, ValidationError

from signals.billing.catalogue import PlanEntitlements
from signals.client_value.capabilities import usable_phone
from signals.client_value.company_identity import exact_french_siren
from signals.client_value.company_name import normalize_holder_name
from signals.client_value.history import _siren_history_fingerprints
from signals.client_value.notice_facts import NoticeAwardFacts
from signals.companies.contracts import CompanyPublicContact, safe_https_url
from signals.companies.schema import saas_company
from signals.engagement.prospecting_schema import company_subject_alias
from signals.persistence.notice_schema import notice_award_facts
from signals.persistence.schema import materialized_signal, supplier_directory

_EMAIL = TypeAdapter(EmailStr)
MAX_CONTACT_AWARDS = 250
MAX_CONTACTS = 100


def _identifier_pairs(identifiers: Iterable) -> set[tuple[str, str]]:
    pairs = set()
    for item in identifiers:
        scheme = item.get("scheme", "") if isinstance(item, Mapping) else item.scheme
        value = item.get("value", "") if isinstance(item, Mapping) else item.value
        kind, text = str(scheme).strip().casefold(), str(value).strip()
        if kind in {"siret", "boamp-company-id", "siren"}:
            compact = re.sub(r"\s", "", text)
            if re.fullmatch(r"[0-9]{14}", compact) and kind != "siren":
                kind, text = "siret", compact
            elif kind == "siren" and re.fullmatch(r"[0-9]{9}", compact):
                text = compact
        if kind and text:
            pairs.add((kind, text))
    return pairs


def _matches(identifiers: Iterable, wanted: Iterable | None, siren: str | None) -> bool:
    if siren is not None:
        return exact_french_siren(identifiers, country="FR") == siren
    if wanted is None:
        return True  # A signal displays each published winner, with attribution.
    expected, actual = _identifier_pairs(wanted), _identifier_pairs(identifiers)
    for pairs in (expected, actual):
        legal_entities = {
            value[:9] for kind, value in pairs if kind in {"siren", "siret"} and value.isdigit()
        }
        if len(legal_entities) > 1:
            return False
    expected_sirets = {value for kind, value in expected if kind == "siret"}
    if expected_sirets:
        return len(expected_sirets) == 1 and expected_sirets == {
            value for kind, value in actual if kind == "siret"
        }
    return bool(expected & actual)


def _safe_url(value: str | None) -> str | None:
    try:
        return safe_https_url(value)
    except ValueError:
        return None


def notice_contacts(
    facts: NoticeAwardFacts,
    *,
    identifiers: Iterable | None = None,
    siren: str | None = None,
    suppressed_sirens: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Keep organizations distinct, even when a legal entity has many agencies."""
    suppressed = set(suppressed_sirens)
    result = []
    for party in facts.winning_parties:
        for holder in party.members:
            holder_siren = exact_french_siren(holder.identifiers, country="FR")
            if holder_siren in suppressed or not _matches(holder.identifiers, identifiers, siren):
                continue
            try:
                email = str(_EMAIL.validate_python(holder.email.value)) if holder.email else None
            except ValidationError:
                email = None
            phone = usable_phone(holder.phone.value if holder.phone else None)
            website = _safe_url(holder.website.value if holder.website else None)
            if not any((email, phone, website)):
                continue
            try:
                contact = CompanyPublicContact(
                    organization_name=holder.name.value,
                    organization_ref=holder.organization_ref,
                    identifiers=tuple(
                        {
                            "scheme": kind.upper() if kind in {"siret", "siren"} else kind,
                            "value": value,
                        }
                        for kind, value in sorted(_identifier_pairs(holder.identifiers))
                    ),
                    source_notice_id=facts.source.source_notice_id,
                    source_url=_safe_url(facts.source.source_url),
                    observed_at=facts.source.collected_at,
                    email=email,
                    phone=phone,
                    website=website,
                    contact_name=holder.contact_name.value if holder.contact_name else None,
                )
            except ValidationError:
                continue
            rendered = contact.model_dump(mode="json")
            rendered["organization_name"] = normalize_holder_name(
                rendered["organization_name"]
            )
            result.append(rendered)
    return result


def suppressed_notice_sirens(
    connection: sa.Connection, facts: Iterable[NoticeAwardFacts]
) -> set[str]:
    sirens = {
        value
        for fact in facts
        for party in fact.winning_parties
        for holder in party.members
        if (value := exact_french_siren(holder.identifiers, country="FR"))
    }
    if not sirens:
        return set()
    return set(
        connection.scalars(
            sa.select(supplier_directory.c.siren).where(
                supplier_directory.c.siren.in_(sorted(sirens)),
                supplier_directory.c.suppressed_at.is_not(None),
            )
        )
    )


def project_contacts(contacts: Iterable[dict[str, Any]], *, entitlements: PlanEntitlements) -> dict:
    contacts = list(contacts)[:MAX_CONTACTS]
    available = [
        field
        for field in ("phone", "email", "website")
        if any(contact.get(field) for contact in contacts)
    ]
    return {
        "public_contacts": contacts if entitlements.is_paid else [],
        "available_contact_fields": available,
        "contacts_locked": not entitlements.is_paid,
    }


def company_public_contacts(
    connection: sa.Connection,
    *,
    company_key: str,
    entitlements: PlanEntitlements,
    identifiers: Iterable = (),
    award_keys: Iterable[str] = (),
) -> dict[str, Any]:
    """Read company contacts after the caller has authorized the company dossier."""
    canonical = re.fullmatch(r"cmp_directory_([0-9]{9})", company_key)
    siren = canonical.group(1) if canonical else None
    candidates = set(award_keys)
    fingerprints = ()
    if siren:
        fingerprints = _siren_history_fingerprints(connection, siren) or ()
        # An empty exact group never falls back to a name or another holder.
        if not fingerprints:
            return project_contacts([], entitlements=entitlements)
        source_awards = connection.scalars(
            sa.select(saas_company.c.source_award_key)
            .where(
                saas_company.c.identity_fingerprint.in_(fingerprints),
            )
            .limit(MAX_CONTACT_AWARDS)
        )
        candidates.update(source_awards)
    else:
        stored = connection.execute(
            sa.select(saas_company.c.source_award_key, saas_company.c.identity_fingerprint).where(
                saas_company.c.company_key == company_key,
            )
        ).one_or_none()
        if stored:
            candidates.add(stored.source_award_key)
            fingerprints = (stored.identity_fingerprint,)
    if fingerprints:
        candidates.update(
            connection.scalars(
                sa.select(materialized_signal.c.materialization_award_key)
                .where(materialized_signal.c.company_identity_fingerprint.in_(fingerprints))
                .distinct()
                .order_by(materialized_signal.c.materialization_award_key)
                .limit(MAX_CONTACT_AWARDS)
            )
        )
    if not candidates:
        return project_contacts([], entitlements=entitlements)
    rejected_identifiers = set()
    if siren:
        # A valid winner can share an award with an alias subsequently
        # quarantined. Authorizing the award must not re-authorize that member.
        rejected_rows = connection.scalars(
            sa.select(saas_company.c.official_identifiers)
            .select_from(
                saas_company.join(
                    company_subject_alias,
                    company_subject_alias.c.alias_company_key == saas_company.c.company_key,
                )
            )
            .where(
                sa.or_(
                    company_subject_alias.c.canonical_company_key == company_key,
                    saas_company.c.source_award_key.in_(sorted(candidates)),
                ),
                sa.or_(
                    company_subject_alias.c.resolution_status != "exact",
                    company_subject_alias.c.canonical_company_key != company_key,
                ),
            )
        )
        for rejected in rejected_rows:
            rejected_identifiers.update(_identifier_pairs(rejected))
    ranked = (
        sa.select(
            notice_award_facts.c.facts,
            notice_award_facts.c.collected_at,
            sa.func.row_number()
            .over(
                partition_by=notice_award_facts.c.award_key,
                order_by=(
                    notice_award_facts.c.collected_at.desc(),
                    notice_award_facts.c.created_at.desc(),
                    notice_award_facts.c.needs_related_enrichment.asc(),
                    notice_award_facts.c.facts_key.desc(),
                ),
            )
            .label("version_rank"),
        )
        .where(
            notice_award_facts.c.award_key.in_(sorted(candidates)),
        )
        .subquery("latest_company_contact_facts")
    )
    facts = []
    for payload in connection.scalars(
        sa.select(ranked.c.facts)
        .where(ranked.c.version_rank == 1)
        .order_by(ranked.c.collected_at.desc())
        .limit(MAX_CONTACT_AWARDS)
    ):
        try:
            facts.append(NoticeAwardFacts.model_validate(payload))
        except ValidationError:
            continue
    suppressed = suppressed_notice_sirens(connection, facts)
    contacts, seen = [], set()
    for fact in facts:
        for contact in notice_contacts(
            fact, identifiers=identifiers, siren=siren, suppressed_sirens=suppressed
        ):
            if _identifier_pairs(contact["identifiers"]) & rejected_identifiers:
                continue
            key = (
                tuple((item["scheme"], item["value"]) for item in contact["identifiers"]),
                contact["organization_name"],
                contact.get("email"),
                contact.get("phone"),
                contact.get("website"),
                contact.get("contact_name"),
            )
            if key not in seen:
                seen.add(key)
                contacts.append(contact)
    return project_contacts(contacts, entitlements=entitlements)
