"""Atomic staging-only reconciliation of source-owned public company facts."""

from __future__ import annotations

import datetime as dt
import hashlib

import sqlalchemy as sa

from signals.client_value.directory import published_email_evidence
from signals.persistence.schema import supplier_directory
from signals.supplier_directory.catalogue_publication import (
    CatalogueSnapshot,
    _encoded,
    aware,
    validated_record,
)
from signals.supplier_directory.catalogue_schema import (
    catalogue_mirror_entry,
    catalogue_mirror_state,
)

_FACT_GROUPS = {
    "legal_name_observed_at": ("legal_name",),
    "naf_observed_at": ("naf_code",),
    "naf_label_observed_at": ("naf_label",),
    "families_observed_at": (
        "family_keys",
        "family_review_keys",
        "family_source",
        "family_confidence",
        "family_confirmation_status",
    ),
    "department_observed_at": ("department",),
    "city_observed_at": ("city",),
    "employees_observed_at": ("employees",),
    "domain_observed_at": (
        "domain",
        "website_url",
        "domain_source",
        "domain_validation_method",
        "domain_validation_evidence_url",
    ),
    "directors_observed_at": ("directors",),
    "director_observed_at": ("director_display_name", "director_source"),
    "email_observed_at": ("professional_email", "email_source", "email_evidence_url"),
    "phone_observed_at": ("phone", "phone_source"),
    "contact_form_observed_at": ("contact_form_url",),
    "enrichment_observed_at": (),
}


def _fact_hashes(record):
    # Fingerprints distinguish source withdrawals from facts never published by
    # the source. No duplicate contact values are stored in mirror metadata.
    return {
        observed_at: hashlib.sha256(_encoded([record[field] for field in fields])).hexdigest()
        for observed_at, fields in _FACT_GROUPS.items()
        if fields
    }


def _merge_facts(existing, incoming, ownership):
    updates = {}
    previous_hashes = ownership["source_fact_hashes"] if ownership else {}
    current_hashes = _fact_hashes(existing)
    for observed_at, fields in _FACT_GROUPS.items():
        old, new = existing[observed_at], incoming[observed_at]
        if observed_at == "email_observed_at" and existing["email_source"] in {"manual", "apollo"}:
            continue
        withdrawn = (
            old is not None
            and new is None
            and fields
            and not incoming[fields[0]]
            and previous_hashes.get(observed_at) == current_hashes.get(observed_at)
            and aware(old) <= aware(incoming["updated_at"])
        )
        if withdrawn:
            updates.update({field: incoming[field] for field in (*fields, observed_at)})
            continue
        if old is not None and (new is None or aware(old) > aware(new)):
            continue
        updates.update({field: incoming[field] for field in (*fields, observed_at)})
    # Publication eligibility must remain true after merging independent fact clocks.
    combined = {**dict(existing), **updates, "suppressed_at": None}
    if combined["email_source"] == "site" and published_email_evidence(combined) is None:
        updates.update(
            professional_email=None,
            email_source=None,
            email_evidence_url=None,
            email_observed_at=None,
        )
    normalize_domain = lambda value: str(value or "").casefold().removeprefix("www.").rstrip(".")
    if normalize_domain(combined["domain"]) != normalize_domain(existing["domain"]):
        # Never import provider identifiers. Revoke only a local binding made
        # against the previous website identity; its existing DB trigger clears
        # obsolete licensed lookup results, not notes or manually entered contacts.
        updates.update(apollo_organization_id=None, apollo_status=None, apollo_observed_at=None)
    updates["updated_at"] = max(aware(existing["updated_at"]), aware(incoming["updated_at"]))
    return updates


def apply_snapshot(
    connection: sa.Connection,
    snapshot: CatalogueSnapshot,
    *,
    destination_environment: str,
    now: dt.datetime,
) -> dict[str, int]:
    """Caller owns the transaction; validate everything before its first write."""
    if destination_environment != "STAGING":
        raise ValueError("catalogue destination must be staging")
    if connection.dialect.name == "postgresql":
        if connection.scalar(sa.text("SELECT current_database()")) != "kivou_staging":
            raise ValueError("catalogue database must be staging")
        # Serializes the entire import, including the initial empty checkpoint.
        connection.execute(sa.text("SELECT pg_advisory_xact_lock(4918632871163)"))
    snapshot = CatalogueSnapshot.model_validate(snapshot.model_dump(mode="json"))
    now = aware(now)
    if snapshot.generated_at > now + dt.timedelta(minutes=5):
        raise ValueError("catalogue future snapshot")
    records = {row["siren"]: validated_record(row) for row in snapshot.rows}
    checkpoint = (
        connection.execute(
            sa.select(catalogue_mirror_state).where(catalogue_mirror_state.c.source == "production")
        )
        .mappings()
        .first()
    )
    counts = {
        "inserted": 0,
        "updated": 0,
        "withdrawn": 0,
        "unchanged": 0,
        "source_total": snapshot.total,
    }
    if checkpoint:
        previous_at = aware(checkpoint["generated_at"])
        if snapshot.generated_at < previous_at:
            raise ValueError("catalogue stale snapshot")
        if snapshot.generated_at == previous_at:
            if checkpoint["digest"] != snapshot.digest:
                raise ValueError("catalogue conflicting snapshot")
            counts["unchanged"] = snapshot.total
            return counts
    owned = {
        row["siren"]: row
        for row in connection.execute(sa.select(catalogue_mirror_entry)).mappings()
    }
    for siren, values in records.items():
        existing = (
            connection.execute(
                sa.select(supplier_directory)
                .where(supplier_directory.c.siren == siren)
                .with_for_update()
            )
            .mappings()
            .first()
        )
        source_updated = aware(values["updated_at"])
        ownership = owned.get(siren)
        withdrawal = ownership["withdrawn_at"] if ownership else None
        mirror_suppressed = bool(
            existing
            and withdrawal
            and existing["suppressed_at"]
            and aware(existing["suppressed_at"]) == aware(withdrawal)
        )
        if existing is None:
            connection.execute(supplier_directory.insert().values(**values))
            counts["inserted"] += 1
        elif existing["suppressed_at"] is not None and not mirror_suppressed:
            counts["unchanged"] += 1
        elif (
            mirror_suppressed
            or ownership is None
            or source_updated > aware(ownership["source_updated_at"])
        ):
            updates = _merge_facts(existing, values, ownership)
            if mirror_suppressed:
                updates["suppressed_at"] = None
            # No source account/private values, provider IDs, journals or costs are imported.
            changed = connection.execute(
                supplier_directory.update()
                .where(
                    supplier_directory.c.siren == siren,
                    supplier_directory.c.suppressed_at == withdrawal
                    if mirror_suppressed
                    else supplier_directory.c.suppressed_at.is_(None),
                )
                .values(**updates)
            )
            counts["updated" if changed.rowcount else "unchanged"] += 1
        else:
            counts["unchanged"] += 1
        metadata = {
            "source_updated_at": source_updated,
            "source_fact_hashes": _fact_hashes(values),
            "mirrored_at": now,
            "withdrawn_at": None,
        }
        if ownership:
            connection.execute(
                catalogue_mirror_entry.update()
                .where(catalogue_mirror_entry.c.siren == siren)
                .values(**metadata)
            )
        else:
            connection.execute(catalogue_mirror_entry.insert().values(siren=siren, **metadata))
    for siren, ownership in owned.items():
        if siren in records or ownership["withdrawn_at"] is not None:
            continue
        updated = connection.execute(
            supplier_directory.update()
            .where(
                supplier_directory.c.siren == siren, supplier_directory.c.suppressed_at.is_(None)
            )
            .values(suppressed_at=now)
        )
        if updated.rowcount:
            connection.execute(
                catalogue_mirror_entry.update()
                .where(catalogue_mirror_entry.c.siren == siren)
                .values(withdrawn_at=now, mirrored_at=now)
            )
            counts["withdrawn"] += 1
    state = {"generated_at": snapshot.generated_at, "digest": snapshot.digest, "mirrored_at": now}
    if checkpoint:
        connection.execute(
            catalogue_mirror_state.update()
            .where(catalogue_mirror_state.c.source == "production")
            .values(**state)
        )
    else:
        connection.execute(catalogue_mirror_state.insert().values(source="production", **state))
    return counts
