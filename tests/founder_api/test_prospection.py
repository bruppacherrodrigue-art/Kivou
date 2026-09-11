from __future__ import annotations

import datetime as dt
import subprocess
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from signals.accounts.schema import account_landing_signal
from signals.founder_api.prospection import (
    FounderAcquisitionTimer,
    FounderDirectoryStatus,
    SystemdAcquisitionTimerReader,
)
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
    source_event,
    supplier_directory,
    supplier_discovery_run,
)

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


def test_systemd_timer_reader_reports_when_the_timer_stopped() -> None:
    output = (
        "LoadState=loaded\n"
        "ActiveState=inactive\n"
        "SubState=dead\n"
        "UnitFileState=enabled\n"
        "InactiveEnterTimestamp=Thu 2026-09-10 07:48:16 UTC\n"
        "LastTriggerUSec=Thu 2026-09-10 07:34:23 UTC\n"
        "NextElapseUSecRealtime=\n"
    )

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        return subprocess.CompletedProcess([], 0, stdout=output, stderr="")

    timer = SystemdAcquisitionTimerReader(run=run)(NOW)

    assert timer.state == "STOPPED"
    assert timer.inactive_since == dt.datetime(2026, 9, 10, 7, 48, 16, tzinfo=dt.UTC)
    assert timer.last_triggered_at == dt.datetime(2026, 9, 10, 7, 34, 23, tzinfo=dt.UTC)
    assert timer.next_trigger_at is None


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
