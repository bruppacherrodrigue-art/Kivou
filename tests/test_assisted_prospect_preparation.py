from __future__ import annotations

import datetime as dt
import hashlib

import sqlalchemy as sa

from signals.persistence.schema import prospect_target, supplier_directory
from signals.prospection_actions.preparation import (
    AssistedSignal,
    ProspectPreparationService,
)
from signals.prospection_actions.service import IssuedProspectLink

NOW = dt.datetime(2026, 9, 11, 7, tzinfo=dt.UTC)


class Links:
    def issue(self, *, row, email: str, at: dt.datetime) -> IssuedProspectLink:
        digest = hashlib.sha256(f"{row['target_id']}\0{email}".encode()).hexdigest()
        return IssuedProspectLink(
            url=f"https://kivou.eu/a/kat1.key.{digest}.signature",
            member_ref=digest,
            token_fingerprint=hashlib.sha256(digest.encode()).hexdigest(),
            payload={"member_ref": digest, "issued_at": at.isoformat()},
            unsubscribe_url=f"https://kivou.eu/unsubscribe/{digest}",
        )


def signal(**changes) -> AssistedSignal:
    values = {
        "opportunity_key": "boamp-2026-42",
        "acquisition_opportunity_id": "a" * 64,
        "procedure_key": "boamp-notice-2026-42",
        "holder": "SAS Bâtiment Exemple",
        "subject": "Construction d'un groupe scolaire",
        "amount_minor_units": 125_000_000,
        "currency": "eur",
        "location": "Allier",
        "department": "03",
        "decision_date": dt.date(2026, 9, 10),
        "source_url": "https://www.boamp.fr/avis/42",
        "vertical": "general_building",
        "families": (
            ("ready_mix_concrete", "Béton prêt à l'emploi"),
            ("reinforcement_steel", "Armatures et ferraillage"),
        ),
    }
    values.update(changes)
    return AssistedSignal(**values)


def seed_directory(engine, count: int = 30, *, eligible_department_count: int = 26) -> None:
    rows = []
    for index in range(count):
        family = "ready_mix_concrete" if index % 2 == 0 else "reinforcement_steel"
        rows.append(
            {
                "siren": f"{100_000_000 + index:09d}",
                "legal_name": f"FOURNISSEUR {index:02d}",
                "legal_name_observed_at": NOW,
                "naf_code": "23.63Z",
                "naf_observed_at": NOW,
                "family_keys": [family],
                "families_observed_at": NOW,
                "department": "03" if index < eligible_department_count else "75",
                "department_observed_at": NOW,
                "city": "MOULINS",
                "city_observed_at": NOW,
                "employees": 100 - index if index != 0 else 9,
                "employees_observed_at": NOW,
                "domain": f"fournisseur-{index}.fr",
                "domain_validation_method": "name_word",
                "domain_observed_at": NOW,
                "directors": (
                    [{"name": f"Alice Martin {index}", "title": "Gérante", "entity_type": "personne physique"}]
                    if index != 1
                    else []
                ),
                "directors_observed_at": NOW,
                "professional_email": f"contact{index}@fournisseur-{index}.fr",
                "email_source": "site",
                "email_verification_status": "mx_failed" if index == 2 else "mx_verified",
                "email_observed_at": NOW,
                "suppressed_at": NOW if index == 3 else None,
                "created_at": NOW,
                "updated_at": NOW,
            }
        )
    with engine.begin() as connection:
        connection.execute(sa.insert(supplier_directory), rows)


def test_assisted_preparation_builds_up_to_twenty_five_final_pending_targets(
    migrated_sqlite_engine,
) -> None:
    seed_directory(migrated_sqlite_engine, 35)
    service = ProspectPreparationService(
        migrated_sqlite_engine, link_issuer=Links(), clock=lambda: NOW
    )

    result = service.prepare(signal(), cycle_ref="cycle-1")

    assert result.prepared == 23
    assert result.status == "pending_review"
    with migrated_sqlite_engine.connect() as connection:
        rows = tuple(
            connection.execute(
                sa.select(prospect_target).order_by(prospect_target.c.company_employees.desc())
            ).mappings()
        )
    assert len(rows) == 23
    assert all(row["status"] == "pending_review" for row in rows)
    assert all(row["company_employees"] >= 10 for row in rows)
    assert all(row["email_verification_status"] == "mx_verified" for row in rows)
    no_director = next(row for row in rows if row["siren"] == "100000001")
    assert no_director["mail_text"].startswith("Bonjour,")
    assert "Béton prêt à l'emploi" in "\n".join(row["mail_text"] for row in rows)


def test_assisted_preparation_caps_daily_queue_at_twenty_five(migrated_sqlite_engine) -> None:
    seed_directory(migrated_sqlite_engine, 40, eligible_department_count=40)
    service = ProspectPreparationService(
        migrated_sqlite_engine, link_issuer=Links(), clock=lambda: NOW
    )

    first = service.prepare(signal(), cycle_ref="cycle-1")
    second = service.prepare(
        signal(
            opportunity_key="boamp-2026-43",
            acquisition_opportunity_id="b" * 64,
            procedure_key="boamp-notice-2026-43",
        ),
        cycle_ref="cycle-2",
    )

    assert first.prepared == 25
    assert second.prepared == 0


def test_assisted_preparation_never_uses_two_lots_of_same_notice_same_day(
    migrated_sqlite_engine,
) -> None:
    seed_directory(migrated_sqlite_engine, 3)
    service = ProspectPreparationService(
        migrated_sqlite_engine, link_issuer=Links(), clock=lambda: NOW
    )
    service.prepare(signal(), cycle_ref="cycle-1")

    second = service.prepare(
        signal(
            opportunity_key="boamp-2026-42-lot-2",
            acquisition_opportunity_id="b" * 64,
        ),
        cycle_ref="cycle-2",
    )

    assert second.prepared == 0
    assert second.reason == "PROCEDURE_ALREADY_PREPARED_TODAY"


def test_assisted_preparation_skips_contacted_in_last_ninety_days(
    migrated_sqlite_engine,
) -> None:
    seed_directory(migrated_sqlite_engine, 5)
    service = ProspectPreparationService(
        migrated_sqlite_engine, link_issuer=Links(), clock=lambda: NOW
    )
    service.prepare(signal(), cycle_ref="cycle-1")
    with migrated_sqlite_engine.begin() as connection:
        connection.execute(
            sa.update(prospect_target)
            .where(prospect_target.c.siren == "100000001")
            .values(status="sent", delivery_status="sent", sent_at=NOW)
        )
        connection.execute(
            sa.delete(prospect_target).where(prospect_target.c.siren != "100000001")
        )

    replay = service.prepare(
        signal(
            opportunity_key="boamp-2026-44",
            acquisition_opportunity_id="c" * 64,
            procedure_key="boamp-notice-2026-44",
        ),
        cycle_ref="cycle-3",
    )

    assert replay.prepared == 1
    with migrated_sqlite_engine.connect() as connection:
        assert connection.scalar(
            sa.select(sa.func.count())
            .select_from(prospect_target)
            .where(prospect_target.c.siren == "100000001")
        ) == 1
