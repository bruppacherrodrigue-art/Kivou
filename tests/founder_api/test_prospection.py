from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from signals.accounts.schema import account_landing_signal
from signals.founder_api.access import FOUNDER_USER_HEADER, ORIGIN_SECRET_HEADER
from signals.founder_api.acquisition_status import FounderAcquisitionActivity
from signals.founder_api.app import create_founder_app
from signals.founder_api.config import FounderApiConfig
from signals.founder_api.prospection import FounderDirectoryStatus
from signals.founder_api.read_models import FounderReadService
from signals.persistence.schema import (
    METADATA,
    acquisition_campaign_member,
    acquisition_contact,
    acquisition_conversion_event,
    acquisition_opportunity,
    acquisition_provider_event,
    acquisition_runtime_cycle,
    acquisition_runtime_stage,
    acquisition_supplier,
    contact_discovery_run,
    contract_award,
    opportunity_representation,
    prospect_target,
    source_event,
    supplier_directory,
    supplier_discovery_run,
)

NOW = dt.datetime(2026, 9, 11, 8, 0, tzinfo=dt.UTC)
ALLOWED_EMAIL = "rodrigue.bruppacher@gmail.com"
ALLOWED_USER = "rodrigue"
ORIGIN_SECRET = "s" * 40


def _engine() -> sa.Engine:
    engine = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    METADATA.create_all(engine)
    return engine


def _stopped_timer(_: dt.datetime) -> FounderAcquisitionActivity:
    return FounderAcquisitionActivity(
        activity="STOPPED",
        activity_since=NOW - dt.timedelta(hours=2),
    )


def _headers() -> dict[str, str]:
    return {
        FOUNDER_USER_HEADER: ALLOWED_USER,
        ORIGIN_SECRET_HEADER: ORIGIN_SECRET,
    }


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
        "family_keys": ["ready_mix_concrete" if index % 2 == 0 else "reinforcement_steel"],
        "families_observed_at": observed_at,
        "department": "69" if index % 2 == 0 else "38",
        "department_observed_at": observed_at,
        "city": "LYON" if index % 2 == 0 else "GRENOBLE",
        "city_observed_at": observed_at,
        "employees": 10 + index,
        "employees_observed_at": observed_at,
        "domain": f"entreprise-{index}.example" if confirmed_domain else None,
        "website_url": (f"https://entreprise-{index}.example" if confirmed_domain else None),
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
        "reverification_reason": ("legacy_domain_not_validated" if needs_reverification else None),
        "website_search_queries_completed": 0,
        "website_search_results_examined": 0,
        "suppressed_at": observed_at if suppressed else None,
        "created_at": observed_at,
        "updated_at": observed_at,
    }


def test_directory_returns_real_global_counts_and_twenty_five_rows() -> None:
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(
            sa.insert(supplier_directory),
            [_directory_row(index) for index in range(27)] + [_directory_row(99, suppressed=True)],
        )

    result = FounderReadService(engine, timer_reader=_stopped_timer).prospection(
        now=NOW,
        page=1,
        page_size=25,
    )

    assert result.version == "founder-prospection-v1"
    assert result.read_only is True
    assert result.acquisition_status.activity == "STOPPED"
    assert result.acquisition_status.activity_since == NOW - dt.timedelta(hours=2)
    assert "timer" not in result.model_dump()
    assert result.directory.summary.company_count == 27
    assert result.directory.summary.confirmed_domain_count == 9
    assert result.directory.summary.verified_email_count == 7
    assert result.directory.summary.reverification_required_count == 6
    assert result.directory.pagination.total_items == 27
    assert result.directory.pagination.total_pages == 2
    assert len(result.directory.rows) == 25
    assert result.directory.rows[0].legal_name == "BÉTON ENTREPRISE 00"
    assert result.directory.rows[-1].legal_name == "BÉTON ENTREPRISE 24"

    second_page = FounderReadService(engine, timer_reader=_stopped_timer).prospection(
        now=NOW,
        page=2,
        page_size=25,
    )
    assert second_page.directory.pagination.page == 2
    assert [row.legal_name for row in second_page.directory.rows] == [
        "BÉTON ENTREPRISE 25",
        "BÉTON ENTREPRISE 26",
    ]


def test_directory_reports_enrichment_and_filters_clickable_review_reasons() -> None:
    engine = _engine()
    today = _directory_row(0)
    today.update(
        enrichment_model_id="anthropic/claude-sonnet-4.6",
        enrichment_cost_usd=Decimal("0.003000"),
        enrichment_observed_at=NOW - dt.timedelta(hours=1),
        reverification_required_at=NOW - dt.timedelta(hours=1),
        reverification_reason="email_below_threshold",
    )
    this_week = _directory_row(1)
    this_week.update(
        enrichment_model_id="anthropic/claude-sonnet-4.6",
        enrichment_cost_usd=Decimal("0.002000"),
        enrichment_observed_at=dt.datetime(2026, 9, 7, 8, tzinfo=dt.UTC),
        reverification_required_at=NOW - dt.timedelta(days=1),
        reverification_reason="email_below_threshold",
    )
    older = _directory_row(2)
    older.update(
        enrichment_model_id="legacy/model",
        enrichment_cost_usd=Decimal("0.001000"),
        enrichment_observed_at=NOW - dt.timedelta(days=10),
        reverification_required_at=NOW - dt.timedelta(days=2),
        reverification_reason="website_below_threshold",
    )
    with engine.begin() as connection:
        connection.execute(sa.insert(supplier_directory), [today, this_week, older])

    service = FounderReadService(engine, timer_reader=_stopped_timer)
    result = service.prospection(now=NOW)

    assert result.directory.enrichment.enriched_today_count == 1
    assert result.directory.enrichment.enriched_week_count == 2
    assert result.directory.enrichment.model == "anthropic/claude-sonnet-4.6"
    assert result.directory.enrichment.cumulative_cost_usd == Decimal("0.006000")
    assert [item.model_dump() for item in result.directory.reverification_reason_counts] == [
        {"key": "email_below_threshold", "label": "email_below_threshold", "count": 2},
        {"key": "website_below_threshold", "label": "website_below_threshold", "count": 1},
    ]

    filtered = service.prospection(
        now=NOW,
        directory_status=FounderDirectoryStatus.REVERIFICATION_REQUIRED,
        reverification_reason="website_below_threshold",
    )
    assert [row.siren for row in filtered.directory.rows] == [older["siren"]]


def test_directory_hides_unconfirmed_domain_and_names_departments() -> None:
    engine = _engine()
    record = _directory_row(1)
    record.update(
        department="69",
        domain="candidate.example",
        website_url="https://candidate.example",
        domain_validation_method=None,
    )
    with engine.begin() as connection:
        connection.execute(sa.insert(supplier_directory), record)

    result = FounderReadService(engine, timer_reader=_stopped_timer).prospection(now=NOW)

    row = result.directory.rows[0]
    assert row.confirmed_domain is False
    assert row.domain is None
    assert row.website_url is None
    assert row.department == "69"
    assert row.department_name == "Rhône"
    assert result.directory.department_counts[0].label == "Rhône (69)"
    assert result.directory.family_counts[0].label == "reinforcement_steel"


def test_without_website_excludes_an_unconfirmed_raw_domain() -> None:
    engine = _engine()
    record = _directory_row(0)
    record.update(
        domain="candidate.example",
        website_url="https://candidate.example",
        domain_validation_method=None,
        reverification_required_at=None,
        reverification_reason=None,
    )
    with engine.begin() as connection:
        connection.execute(sa.insert(supplier_directory), record)

    unfiltered = FounderReadService(engine, timer_reader=_stopped_timer).prospection(now=NOW)

    assert len(unfiltered.directory.rows) == 1
    assert unfiltered.directory.rows[0].domain is None
    assert unfiltered.directory.rows[0].website_url is None
    assert unfiltered.directory.rows[0].professional_email == "contact0@example.test"
    assert unfiltered.directory.rows[0].qualification_status == "to_qualify"

    without_website = FounderReadService(
        engine, timer_reader=_stopped_timer
    ).prospection(
        now=NOW,
        directory_status=FounderDirectoryStatus.WITHOUT_WEBSITE,
    )

    assert without_website.directory.rows == ()
    assert without_website.directory.pagination.total_items == 0


def test_directory_qualification_uses_durable_verdicts_and_priority() -> None:
    engine = _engine()
    reverification = _directory_row(0)
    durable_without_website = _directory_row(1)
    durable_without_website.update(
        domain_source="no_website",
        reverification_reason="no_website",
        website_search_queries_completed=3,
        website_search_results_examined=30,
    )
    never_searched = _directory_row(2)
    confirmed = _directory_row(3)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(supplier_directory),
            [reverification, durable_without_website, never_searched, confirmed],
        )

    service = FounderReadService(engine, timer_reader=_stopped_timer)
    unfiltered = service.prospection(now=NOW)

    assert {row.siren: row.qualification_status for row in unfiltered.directory.rows} == {
        "100000000": "reverification_required",
        "100000001": "without_website",
        "100000002": "to_qualify",
        "100000003": "confirmed_domain",
    }

    expected_by_filter = {
        FounderDirectoryStatus.CONFIRMED_DOMAIN: "100000003",
        FounderDirectoryStatus.WITHOUT_WEBSITE: "100000001",
        FounderDirectoryStatus.REVERIFICATION_REQUIRED: "100000000",
    }
    for status, expected_siren in expected_by_filter.items():
        filtered = service.prospection(
            now=NOW,
            page=1,
            page_size=1,
            directory_status=status,
        )
        assert [row.siren for row in filtered.directory.rows] == [expected_siren]
        assert filtered.directory.pagination.total_items == 1
        assert filtered.directory.pagination.total_pages == 1


def test_directory_uses_department_code_as_label_when_name_is_unknown() -> None:
    engine = _engine()
    record = _directory_row(1)
    record["department"] = "XX"
    with engine.begin() as connection:
        connection.execute(sa.insert(supplier_directory), record)

    result = FounderReadService(engine, timer_reader=_stopped_timer).prospection(now=NOW)

    assert result.directory.rows[0].department == "XX"
    assert result.directory.rows[0].department_name is None
    assert result.directory.department_counts[0].label == "XX"


def test_queue_reads_only_pending_review_targets_as_ready_mail() -> None:
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(sa.insert(supplier_directory), _directory_row(0))
        base = {
            "version": 1,
            "opportunity_key": "boamp-2026-assisted",
            "procedure_award_key": "notice-assisted:lot-1",
            "siren": "100000000",
            "company_name": "BÉTON ENTREPRISE 00",
            "company_city": "LYON",
            "company_employees": 20,
            "vertical": "general_building",
            "family_key": "ready_mix_concrete",
            "family_label": "béton prêt à l'emploi",
            "director_name": "Camille Martin",
            "director_title": "Gérante",
            "director_source": "registry",
            "email_source": "site",
            "email_verification_status": "mx_verified",
            "signal_holder": "SAS TITULAIRE",
            "signal_subject": "Construction d'un groupe scolaire",
            "signal_amount_minor_units": 125_000_000,
            "signal_currency": "EUR",
            "signal_location": "Rhône",
            "signal_decision_date": NOW.date(),
            "signal_source_url": "https://example.test/signal",
            "mail_subject": "Un signal pour BÉTON ENTREPRISE 00",
            "mail_text": "Bonjour Camille Martin,\n\nVous fournissez du béton prêt à l'emploi ?",
            "mail_html": "<p>Bonjour Camille Martin,</p>",
            "attribution_url": "https://kivou.eu/a/token",
            "attribution_member_ref": "a" * 64,
            "attribution_payload": {},
            "attribution_token_fingerprint": "b" * 64,
            "unsubscribe_url": "https://kivou.eu/unsubscribe/token",
            "mail_word_count": 10,
            "delivery_status": "not_sent",
            "sent_at": None,
            "created_at": NOW,
            "updated_at": NOW,
        }
        connection.execute(
            sa.insert(prospect_target),
            [
                {
                    **base,
                    "target_id": "51d144ca-d697-47e4-a4dc-ee86d0a9c8ac",
                    "email_address": "camille@example.test",
                    "status": "pending_review",
                },
                {
                    **base,
                    "target_id": "6b4ce58f-2537-4aac-9952-363430532477",
                    "email_address": "sent@example.test",
                    "attribution_member_ref": "c" * 64,
                    "status": "sent",
                    "delivery_status": "sent",
                    "sent_at": NOW,
                },
            ],
        )

    result = FounderReadService(engine, timer_reader=_stopped_timer).prospection(now=NOW)

    assert result.queue.available is True
    assert len(result.queue.items) == 1
    item = result.queue.items[0]
    assert item.target_ref == "51d144ca-d697-47e4-a4dc-ee86d0a9c8ac"
    assert item.company_name == "BÉTON ENTREPRISE 00"
    assert item.family_key == "ready_mix_concrete"
    assert item.email_address == "camille@example.test"
    assert item.bait_holder == "SAS TITULAIRE"
    assert item.mail_body.startswith("Bonjour Camille Martin,")
    assert item.mail_html == "<p>Bonjour Camille Martin,</p>"
    assert result.results.sent_count == 1
    assert result.results.no_sends_yet is False


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


@pytest.mark.parametrize(
    ("directory_status", "expected_count"),
    (
        (FounderDirectoryStatus.CONFIRMED_DOMAIN, 7),
        (FounderDirectoryStatus.WITHOUT_WEBSITE, 0),
        (FounderDirectoryStatus.REVERIFICATION_REQUIRED, 6),
    ),
)
def test_directory_supports_each_status_filter(
    directory_status: FounderDirectoryStatus,
    expected_count: int,
) -> None:
    engine = _engine()
    with engine.begin() as connection:
        connection.execute(
            sa.insert(supplier_directory),
            [_directory_row(index) for index in range(27)],
        )

    result = FounderReadService(engine, timer_reader=_stopped_timer).prospection(
        now=NOW,
        directory_status=directory_status,
    )

    assert result.directory.pagination.total_items == expected_count


def test_targeting_uses_the_latest_cycle_and_its_existing_journals() -> None:
    engine = _engine()
    cycle_started_at = NOW - dt.timedelta(hours=3)
    cycle_completed_at = NOW - dt.timedelta(hours=2, minutes=55)
    signal_ref = "procurement-opportunity:opp-prospection"
    with engine.begin() as connection:
        connection.execute(
            sa.insert(source_event),
            {
                "event_key": "boamp:notice-prospection:v1",
                "source_system": "boamp",
                "source_notice_id": "notice-prospection",
                "source_country": "FR",
                "event_type": "award",
                "published_on": NOW.date() - dt.timedelta(days=2),
                "procedure_buyers": [],
                "created_at": cycle_started_at,
            },
        )
        connection.execute(
            sa.insert(contract_award),
            {
                "award_key": "award-prospection",
                "event_key": "boamp:notice-prospection:v1",
                "title": "INSTALLATION CHANTIER - GROS-OEUVRE",
                "cpv_additional": [],
                "amount": Decimal("466865.90"),
                "currency": "EUR",
                "winner_status": "identified",
                "awardee_parties": [],
                "contract_signatories": [],
                "place_country": "FR",
                "created_at": cycle_started_at,
            },
        )
        connection.execute(
            sa.insert(opportunity_representation),
            {
                "award_key": "award-prospection",
                "opportunity_key": "opp-prospection",
                "created_at": cycle_started_at,
            },
        )
        connection.execute(
            sa.insert(acquisition_runtime_cycle),
            {
                "cycle_ref": "cycle-prospection",
                "opportunity_key": "opp-prospection",
                "config_fingerprint": "config-prospection",
                "status": "SUPPRESSED",
                "next_stage": None,
                "spent_cost": Decimal("8"),
                "last_reason_code": "VERIFIED_CONTACT_NOT_FOUND",
                "started_at": cycle_started_at,
                "updated_at": cycle_completed_at,
                "completed_at": cycle_completed_at,
            },
        )
        connection.execute(
            sa.insert(acquisition_runtime_stage),
            {
                "cycle_ref": "cycle-prospection",
                "stage": "CONTACT_DISCOVERY",
                "status": "SUPPRESSED",
                "attempt_count": 1,
                "plan_ref": "plan-prospection",
                "command": "find_decision_makers",
                "argument_fingerprint": "argument-prospection",
                "result_refs": [],
                "reserved_cost": Decimal("6"),
                "observed_cost": Decimal("6"),
                "reason_codes": ["VERIFIED_CONTACT_NOT_FOUND"],
                "retry_at": None,
                "replay_same_attempt": False,
                "started_at": cycle_started_at + dt.timedelta(minutes=3),
                "completed_at": cycle_completed_at,
                "updated_at": cycle_completed_at,
            },
        )
        connection.execute(
            sa.insert(supplier_discovery_run),
            {
                "discovery_run_id": "run-prospection",
                "signal_ref": signal_ref,
                "policy_evaluation_id": "policy-prospection",
                "provider": "sirene",
                "search_profile_version": "supplier-search-v1",
                "search_profile_fingerprint": "search-profile-prospection",
                "search_profile": {
                    "supplier_family_keys": [
                        "ready_mix_concrete",
                        "reinforcement_steel",
                        "subcontracted_structural_work",
                    ]
                },
                "provider_request_fingerprint": "provider-request-prospection",
                "requested_max_pages": 1,
                "per_page": 1,
                "candidate_cap": 1,
                "planned_provider_credit_units": 0,
                "pages_requested": 1,
                "recovery_provider_calls": 0,
                "provider_credit_units_observed": 0,
                "provider_total_entries": 75,
                "partial_results_only": False,
                "records_returned": 75,
                "records_accepted": 1,
                "records_rejected": 5,
                "rejection_reason_counts": {"contact_identity_unresolved": 5},
                "family_result_counts": {
                    "ready_mix_concrete": 25,
                    "reinforcement_steel": 25,
                    "subcontracted_structural_work": 25,
                },
                "family_target_counts": {"ready_mix_concrete": 1},
                "duplicates": 0,
                "opportunities_created": 1,
                "started_at": cycle_started_at + dt.timedelta(minutes=1),
                "completed_at": cycle_started_at + dt.timedelta(minutes=2),
                "status": "SUCCESS",
                "correlation_id": "correlation-prospection",
            },
        )
        connection.execute(sa.insert(supplier_directory), _directory_row(30))
        connection.execute(
            sa.insert(acquisition_supplier),
            {
                "supplier_ref": "supplier-prospection",
                "provider": "sirene",
                "provider_organization_id": "100000030",
                "display_name": "BÉTON ENTREPRISE 30",
                "normalized_name": "beton entreprise 30",
                "primary_domain": "entreprise-30.example",
                "country_code": "FR",
                "identity_status": "SIRENE_IDENTIFIED",
                "provider_observed_at": cycle_started_at,
                "source_fingerprint": "supplier-source-prospection",
                "created_at": cycle_started_at + dt.timedelta(minutes=1),
                "updated_at": cycle_started_at + dt.timedelta(minutes=1),
            },
        )
        connection.execute(
            sa.insert(acquisition_contact),
            {
                "contact_ref": "contact-prospection",
                "supplier_ref": "supplier-prospection",
                "provider": "apollo",
                "provider_person_id": "person-prospection",
                "provider_organization_id": "100000030",
                "first_name": "Camille",
                "last_name": "Martin",
                "display_name": "Camille Martin",
                "title": "Directrice commerciale",
                "normalized_title": "directrice commerciale",
                "role_profile_version": "decision-maker-v1",
                "role_tier": 2,
                "business_email": "camille@example.test",
                "provider_email_status": "verified",
                "verification_state": "PROVIDER_VERIFIED",
                "verification_provider": "apollo",
                "provider_observed_at": cycle_started_at,
                "email_observed_at": cycle_started_at,
                "source_fingerprint": "contact-source-prospection",
                "created_at": cycle_started_at + dt.timedelta(minutes=2),
                "updated_at": cycle_started_at + dt.timedelta(minutes=2),
            },
        )
        connection.execute(
            sa.insert(acquisition_opportunity),
            {
                "acquisition_opportunity_id": "acquisition-prospection",
                "identity_key": "acquisition-prospection-identity",
                "state": "CONTACT_VERIFIED",
                "stream_version": 1,
                "state_machine_version": "acquisition-v1",
                "signal_ref": signal_ref,
                "supplier_ref": "supplier-prospection",
                "contact_ref": "contact-prospection",
                "reason_codes": [],
                "evidence_refs": [],
                "retry_count": 0,
                "last_event_id": "event-prospection",
                "created_at": cycle_started_at + dt.timedelta(minutes=1),
                "updated_at": cycle_started_at + dt.timedelta(minutes=4),
            },
        )
        connection.execute(
            sa.insert(contact_discovery_run),
            {
                "contact_discovery_run_id": "contact-run-prospection",
                "acquisition_opportunity_id": "acquisition-prospection",
                "supplier_ref": "supplier-prospection",
                "policy_evaluation_id": "contact-policy-prospection",
                "provider": "apollo",
                "search_profile_version": "decision-maker-v1",
                "search_profile_fingerprint": "contact-profile-prospection",
                "search_profile": {},
                "provider_request_fingerprint": "contact-request-prospection",
                "expected_post_policy_version": 2,
                "requested_max_pages": 1,
                "per_page": 25,
                "max_enrichment_attempts": 3,
                "people_search_requests": 1,
                "recovery_provider_calls": 0,
                "provider_total_entries": 1,
                "search_results_returned": 1,
                "search_results_truncated": False,
                "candidates_eligible": 1,
                "candidates_rejected": 0,
                "enrichment_attempts": 1,
                "planned_provider_credit_units": 1,
                "observed_provider_credit_units": 1,
                "attempted_contact_refs": ["contact-prospection"],
                "selected_contact_ref": "contact-prospection",
                "started_at": cycle_started_at + dt.timedelta(minutes=3),
                "completed_at": cycle_started_at + dt.timedelta(minutes=4),
                "status": "SUCCESS",
                "correlation_id": "contact-correlation-prospection",
            },
        )

    result = FounderReadService(engine, timer_reader=_stopped_timer).prospection(
        now=NOW,
    )

    assert result.queue.last_cycle_at == cycle_completed_at
    assert result.targeting is not None
    assert result.targeting.cycle_ref == "cycle-prospection"
    assert result.targeting.status == "SUPPRESSED"
    assert result.targeting.recent is True
    assert result.targeting.signal.title == "INSTALLATION CHANTIER - GROS-OEUVRE"
    assert result.targeting.signal.amount_minor_units == 46_686_590
    assert result.targeting.signal.currency == "EUR"
    assert result.targeting.family_keys == (
        "ready_mix_concrete",
        "reinforcement_steel",
        "subcontracted_structural_work",
    )
    assert result.targeting.sirene_account_count == 75
    assert result.targeting.confirmed_domain_count == 1
    assert [item.count for item in result.targeting.email_counts_by_level] == [0, 1, 0, 0]
    assert {item.reason_code: item.count for item in result.targeting.deviation_counts} == {
        "contact_identity_unresolved": 5,
        "VERIFIED_CONTACT_NOT_FOUND": 1,
    }

    stale = FounderReadService(engine, timer_reader=_stopped_timer).prospection(
        now=NOW + dt.timedelta(days=3),
    )
    assert stale.targeting is not None
    assert stale.targeting.updated_at == cycle_completed_at
    assert stale.targeting.recent is False


def test_empty_prospection_keeps_numeric_results_and_no_cycle() -> None:
    result = FounderReadService(
        _engine(),
        timer_reader=_stopped_timer,
    ).prospection(now=NOW)

    assert result.targeting is None
    assert result.queue.last_cycle_at is None
    assert result.results.sent_count == 0
    assert result.results.opened_count == 0
    assert result.results.attribution_click_count == 0
    assert result.results.landing_count == 0
    assert result.results.confirmed_profile_count == 0
    assert result.results.paid_account_count == 0
    assert result.results.mrr_by_currency == ()
    assert result.results.no_sends_yet is True


def test_results_exclude_every_conversion_from_qa_tokens_and_accounts() -> None:
    engine = _engine()
    occurred_at = NOW - dt.timedelta(hours=1)

    def event(
        ref: str,
        milestone: str,
        *,
        token: str | None = None,
        journey: str | None = None,
        account_id: str | None = None,
        amount: int | None = None,
    ) -> dict[str, object]:
        return {
            "conversion_event_ref": ref,
            "event_fingerprint": ref,
            "event_version": "conversion-event-v1",
            "journey_ref": journey,
            "milestone": milestone,
            "token_fingerprint": token,
            "account_id": account_id,
            "mrr_known": True if milestone == "MRR_CHANGED" else None,
            "mrr_minor_units": amount,
            "currency": "eur" if amount is not None else None,
            "occurred_at": occurred_at,
            "observed_at": occurred_at,
            "recorded_at": occurred_at,
        }

    with engine.begin() as connection:
        connection.execute(
            sa.insert(account_landing_signal),
            [
                {
                    "account_id": "account-real",
                    "token_fingerprint": "token-real",
                    "profile_confirmed_at": occurred_at,
                    "created_at": occurred_at,
                    "qa": False,
                },
                {
                    "account_id": "account-qa",
                    "token_fingerprint": "token-qa",
                    "profile_confirmed_at": occurred_at,
                    "created_at": occurred_at,
                    "qa": True,
                },
            ],
        )
        connection.execute(
            sa.insert(acquisition_conversion_event),
            [
                event("click-real", "CLICK", token="token-real"),
                event("click-qa", "CLICK", token="token-qa"),
                event("paid-real", "PAID", journey="journey-real", account_id="account-real"),
                event(
                    "mrr-real",
                    "MRR_CHANGED",
                    journey="journey-real",
                    account_id="account-real",
                    amount=12_900,
                ),
                event("paid-qa", "PAID", journey="journey-qa", account_id="account-qa"),
                event(
                    "mrr-qa",
                    "MRR_CHANGED",
                    journey="journey-qa",
                    account_id="account-qa",
                    amount=99_900,
                ),
            ],
        )

    result = FounderReadService(engine, timer_reader=_stopped_timer).prospection(now=NOW)

    assert result.results.attribution_click_count == 1
    assert result.results.landing_count == 1
    assert result.results.confirmed_profile_count == 1
    assert result.results.paid_account_count == 1
    assert [(item.currency, item.minor_units) for item in result.results.mrr_by_currency] == [
        ("EUR", 12_900)
    ]


def test_results_read_persisted_events_and_keep_zero_capable_metrics() -> None:
    engine = _engine()
    sent_at = NOW - dt.timedelta(days=1)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_campaign_member),
            {
                "member_ref": "member-results",
                "campaign_ref": "campaign-results",
                "acquisition_opportunity_id": "opportunity-results",
                "supplier_ref": "supplier-results",
                "contact_ref": "contact-results",
                "personalization_artifact_id": "artifact-results",
                "personalization_artifact_fingerprint": "artifact-fingerprint-results",
                "compliance_assessment_id": "compliance-results",
                "compliance_assessment_fingerprint": "compliance-fingerprint-results",
                "policy_evaluation_id": "policy-results",
                "policy_provenance": {},
                "input_fingerprint": "input-results",
                "contact_provider_identity_binding": "contact-binding-results",
                "plan_fingerprint": "plan-results",
                "envelope_fingerprint": "envelope-results",
                "policy_action_fingerprint": "policy-action-results",
                "ruleset_fingerprint": "ruleset-results",
                "sender_config_fingerprint": "sender-results",
                "mailbox_ref": "mailbox-results",
                "mailbox_readiness_fingerprint": "mailbox-readiness-results",
                "step_1_execution_date": sent_at.date(),
                "step_1_authorization_deadline": sent_at + dt.timedelta(hours=1),
                "step_2_execution_date": sent_at.date() + dt.timedelta(days=2),
                "step_2_authorization_deadline": sent_at + dt.timedelta(days=2),
                "sequence_authorization_fingerprint": "sequence-auth-results",
                "step_1_sent_at": sent_at,
                "step_2_due_at": sent_at + dt.timedelta(days=2),
                "sequence_timing_fingerprint": "sequence-timing-results",
                "execution_state": "SENT",
                "sequence_state": "WAITING_STEP2",
                "created_at": sent_at,
                "updated_at": sent_at,
            },
        )
        provider_base = {
            "fingerprint_version": "provider-event-v1",
            "fingerprint_key_version": "provider-key-v1",
            "provider_workspace_ref": "workspace-results",
            "provider_campaign_id": "provider-campaign-results",
            "campaign_ref": "campaign-results",
            "member_ref": "member-results",
            "acquisition_opportunity_id": "opportunity-results",
            "contact_ref": "contact-results",
            "occurred_at": sent_at,
            "received_at": sent_at,
        }
        connection.execute(
            sa.insert(acquisition_provider_event),
            [
                {
                    **provider_base,
                    "provider_event_ref": "opening-results",
                    "canonical_event_fingerprint": "opening-results",
                    "provider_event_type": "email_opened",
                    "resolution_state": "PROCESSED",
                },
                {
                    **provider_base,
                    "provider_event_ref": "opening-quarantined-results",
                    "canonical_event_fingerprint": "opening-quarantined-results",
                    "provider_event_type": "email_opened",
                    "resolution_state": "QUARANTINED",
                },
            ],
        )
        connection.execute(
            sa.insert(account_landing_signal),
            [
                {
                    "account_id": "account-landing-one",
                    "profile_confirmed_at": sent_at,
                    "created_at": sent_at,
                    "qa": False,
                },
                {
                    "account_id": "account-landing-two",
                    "profile_confirmed_at": None,
                    "created_at": sent_at,
                    "qa": False,
                },
                {
                    "account_id": "account-landing-qa",
                    "profile_confirmed_at": sent_at,
                    "created_at": sent_at,
                    "qa": True,
                },
            ],
        )
        event_base = {
            "event_version": "conversion-event-v1",
            "campaign_ref": "campaign-results",
            "member_ref": "member-results",
            "acquisition_opportunity_id": "opportunity-results",
            "occurred_at": sent_at,
            "observed_at": sent_at,
            "recorded_at": sent_at,
        }
        for event in (
            {
                **event_base,
                "conversion_event_ref": "click-results",
                "event_fingerprint": "click-results",
                "journey_ref": None,
                "milestone": "CLICK",
                "token_fingerprint": "token-results",
                "account_id": None,
            },
            {
                **event_base,
                "conversion_event_ref": "paid-one-results",
                "event_fingerprint": "paid-one-results",
                "journey_ref": "journey-one-results",
                "milestone": "PAID",
                "account_id": "account-paid-one",
            },
            {
                **event_base,
                "conversion_event_ref": "mrr-one-results",
                "event_fingerprint": "mrr-one-results",
                "journey_ref": "journey-one-results",
                "milestone": "MRR_CHANGED",
                "account_id": "account-paid-one",
                "mrr_known": True,
                "mrr_minor_units": 9_900,
                "currency": "chf",
            },
            {
                **event_base,
                "conversion_event_ref": "paid-two-results",
                "event_fingerprint": "paid-two-results",
                "journey_ref": "journey-two-results",
                "milestone": "PAID",
                "account_id": "account-paid-two",
            },
            {
                **event_base,
                "conversion_event_ref": "mrr-two-results",
                "event_fingerprint": "mrr-two-results",
                "journey_ref": "journey-two-results",
                "milestone": "MRR_CHANGED",
                "account_id": "account-paid-two",
                "mrr_known": True,
                "mrr_minor_units": 4_900,
                "currency": "eur",
            },
            {
                **event_base,
                "conversion_event_ref": "churn-two-results",
                "event_fingerprint": "churn-two-results",
                "journey_ref": "journey-two-results",
                "milestone": "CHURNED",
                "account_id": "account-paid-two",
                "occurred_at": sent_at + dt.timedelta(hours=1),
                "observed_at": sent_at + dt.timedelta(hours=1),
                "recorded_at": sent_at + dt.timedelta(hours=1),
            },
        ):
            connection.execute(sa.insert(acquisition_conversion_event), event)

    result = FounderReadService(engine, timer_reader=_stopped_timer).prospection(
        now=NOW,
    )

    assert result.results.sent_count == 1
    assert result.results.opened_count == 1
    assert result.results.attribution_click_count == 1
    assert result.results.landing_count == 2
    assert result.results.confirmed_profile_count == 1
    assert result.results.paid_account_count == 2
    assert result.results.no_sends_yet is False
    assert [(item.currency, item.minor_units) for item in result.results.mrr_by_currency] == [
        ("CHF", 9_900)
    ]


def test_prospection_route_is_authenticated_and_returns_the_versioned_contract() -> None:
    engine = _engine()
    app = create_founder_app(
        FounderApiConfig(
            allowed_email=ALLOWED_EMAIL,
            allowed_user=ALLOWED_USER,
            origin_secret=ORIGIN_SECRET,
        ),
        now_override=lambda: NOW,
        read_service=FounderReadService(engine, timer_reader=_stopped_timer),
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/founder/prospection?page=1&page_size=25",
            headers=_headers(),
        )
        unauthenticated = client.get("/api/founder/prospection")

    assert response.status_code == 200
    assert response.json()["version"] == "founder-prospection-v1"
    assert response.json()["read_only"] is True
    assert response.json()["acquisition_status"]["activity"] == "STOPPED"
    assert "timer" not in response.json()
    assert unauthenticated.status_code == 403


@pytest.mark.parametrize(
    "query",
    (
        "page=0",
        "page_size=26",
        f"q={'x' * 101}",
        "status=not-a-directory-status",
    ),
)
def test_prospection_route_rejects_unbounded_queries(query: str) -> None:
    engine = _engine()
    app = create_founder_app(
        FounderApiConfig(
            allowed_email=ALLOWED_EMAIL,
            allowed_user=ALLOWED_USER,
            origin_secret=ORIGIN_SECRET,
        ),
        now_override=lambda: NOW,
        read_service=FounderReadService(engine, timer_reader=_stopped_timer),
    )

    with TestClient(app) as client:
        response = client.get(f"/api/founder/prospection?{query}", headers=_headers())

    assert response.status_code == 422


def test_prospection_route_fails_closed_without_reads_or_actions() -> None:
    app = create_founder_app(
        FounderApiConfig(
            allowed_email=ALLOWED_EMAIL,
            allowed_user=ALLOWED_USER,
            origin_secret=ORIGIN_SECRET,
        ),
        now_override=lambda: NOW,
    )

    with TestClient(app) as client:
        unavailable = client.get("/api/founder/prospection", headers=_headers())
        action = client.post(
            "/api/founder/actions/validate",
            headers=_headers(),
        )

    assert unavailable.status_code == 503
    assert action.status_code == 404
