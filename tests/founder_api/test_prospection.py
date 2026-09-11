from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from signals.founder_api.prospection import FounderAcquisitionTimer, FounderDirectoryStatus
from signals.founder_api.read_models import FounderReadService
from signals.persistence.schema import METADATA, supplier_directory

NOW = dt.datetime(2026, 9, 11, 8, 0, tzinfo=dt.UTC)


def _engine() -> sa.Engine:
    engine = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    METADATA.create_all(engine)
    return engine


def _stopped_timer(_: dt.datetime) -> FounderAcquisitionTimer:
    return FounderAcquisitionTimer(
        state="STOPPED",
        unit="kivou-acquisition-production.timer",
        inactive_since=NOW - dt.timedelta(hours=2),
        last_triggered_at=NOW - dt.timedelta(hours=3),
        next_trigger_at=None,
    )


def _directory_row(index: int, *, suppressed: bool = False) -> dict[str, object]:
    observed_at = NOW - dt.timedelta(days=index % 4)
    confirmed_domain = index % 3 == 0
    verified_email = index % 4 == 0
    needs_reverification = index % 5 == 0
    return {
        "siren": f"{index + 100_000_000:09d}",
        "legal_name": f"BÉTON ENTREPRISE {index:02d}",
        "legal_name_observed_at": observed_at,
        "naf_code": "23.63Z",
        "naf_observed_at": observed_at,
        "family_keys": [
            "ready_mix_concrete" if index % 2 == 0 else "reinforcement_steel"
        ],
        "families_observed_at": observed_at,
        "department": "69" if index % 2 == 0 else "38",
        "department_observed_at": observed_at,
        "city": "LYON" if index % 2 == 0 else "GRENOBLE",
        "city_observed_at": observed_at,
        "employees": 10 + index,
        "employees_observed_at": observed_at,
        "domain": f"entreprise-{index}.example" if confirmed_domain else None,
        "website_url": (
            f"https://entreprise-{index}.example" if confirmed_domain else None
        ),
        "domain_source": "manual" if confirmed_domain else None,
        "domain_validation_method": "name_word" if confirmed_domain else None,
        "domain_validation_evidence_url": (
            f"https://entreprise-{index}.example/legal" if confirmed_domain else None
        ),
        "domain_observed_at": observed_at if confirmed_domain else None,
        "apollo_organization_id": None,
        "apollo_status": None,
        "apollo_observed_at": None,
        "directors": [],
        "directors_observed_at": observed_at,
        "professional_email": f"contact{index}@example.test" if verified_email else None,
        "email_source": "site" if verified_email else None,
        "email_verification_status": "mx_verified" if verified_email else None,
        "email_contact_name": "Camille Martin" if verified_email else None,
        "email_contact_title": "Gérant" if verified_email else None,
        "email_observed_at": observed_at if verified_email else None,
        "contact_form_url": None,
        "contact_form_observed_at": None,
        "reverification_required_at": observed_at if needs_reverification else None,
        "reverification_reason": (
            "legacy_domain_not_validated" if needs_reverification else None
        ),
        "suppressed_at": observed_at if suppressed else None,
        "created_at": observed_at,
        "updated_at": observed_at,
    }


def test_directory_returns_real_global_counts_and_twenty_five_rows() -> None:
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(
            sa.insert(supplier_directory),
            [_directory_row(index) for index in range(27)]
            + [_directory_row(99, suppressed=True)],
        )

    result = FounderReadService(engine, timer_reader=_stopped_timer).prospection(
        now=NOW,
        page=1,
        page_size=25,
    )

    assert result.version == "founder-prospection-v1"
    assert result.read_only is True
    assert result.directory.summary.company_count == 27
    assert result.directory.summary.confirmed_domain_count == 9
    assert result.directory.summary.verified_email_count == 7
    assert result.directory.summary.reverification_required_count == 6
    assert result.directory.pagination.total_items == 27
    assert result.directory.pagination.total_pages == 2
    assert len(result.directory.rows) == 25
    assert result.directory.rows[0].legal_name == "BÉTON ENTREPRISE 00"
    assert result.directory.rows[-1].legal_name == "BÉTON ENTREPRISE 24"


def test_directory_filters_before_pagination_without_changing_global_facets() -> None:
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(
            sa.insert(supplier_directory),
            [_directory_row(index) for index in range(27)],
        )

    result = FounderReadService(engine, timer_reader=_stopped_timer).prospection(
        now=NOW,
        page=1,
        page_size=25,
        q="  béton entreprise 06  ",
        family="ready_mix_concrete",
        department="69",
        directory_status=FounderDirectoryStatus.CONFIRMED_DOMAIN,
    )

    assert result.directory.summary.company_count == 27
    assert result.directory.family_counts[0].key == "ready_mix_concrete"
    assert result.directory.family_counts[0].count == 14
    assert result.directory.department_counts[0].key == "69"
    assert result.directory.pagination.total_items == 1
    assert [row.siren for row in result.directory.rows] == ["100000006"]
