from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from signals.campaigns.contracts import (
    BATCH_SEAL_POLICY_VERSION,
    CAMPAIGN_FACTORY_VERSION,
    CAMPAIGN_SEQUENCE_POLICY_VERSION,
    PACING_POLICY_VERSION,
    SEND_WINDOW_POLICY_VERSION,
    SEQUENCE_WINDOW_POLICY_VERSION,
    TRACKING_POLICY_VERSION,
    CampaignFactoryInput,
    CampaignLifecycle,
    FooterCatalog,
    FooterCatalogEntry,
    MailboxCatalog,
    MemberExecutionState,
    MemberSequenceState,
    PacingPolicy,
    ProviderStopPolicy,
    TrackingPolicy,
    TransportContractProof,
    WebhookEntitlement,
)
from signals.campaigns.envelope import EnvelopeInput, build_envelope
from signals.campaigns.factory import CampaignFactory, sequence_window
from signals.campaigns.pacing import effective_capacity

FINGERPRINT = "a" * 64


def _factory_input(*, first_date: dt.date = dt.date(2026, 8, 24)) -> CampaignFactoryInput:
    return CampaignFactoryInput(
        wedge="public-procurement",
        wedge_version="wedge-v1",
        jurisdiction="FR",
        country="FR",
        language="fr",
        selected_need_category="RECENT_AWARD_GROWTH",
        selected_need_version="need-v1",
        personalization_catalog_version="personalization-catalog-v1",
        personalization_template_version="personalization-template-v1",
        language_policy_version="personalization-language-v1",
        envelope_catalog_version="footer-catalog-test-v1",
        sender_profile_ref="sender-profile:test",
        mailbox_pool_version="mailbox-pool-test-v1",
        compliance_ruleset_fingerprint=FINGERPRINT,
        step_1_execution_date=first_date,
    )


def test_factory_is_deterministic_and_contains_no_pii() -> None:
    plan = CampaignFactory().build(_factory_input(), batch_generation=2)
    replay = CampaignFactory().build(_factory_input(), batch_generation=2)

    assert plan == replay
    assert plan.factory_version == CAMPAIGN_FACTORY_VERSION
    assert plan.batch_policy_version == BATCH_SEAL_POLICY_VERSION
    assert plan.sequence_policy_version == CAMPAIGN_SEQUENCE_POLICY_VERSION
    assert plan.send_window_policy_version == SEND_WINDOW_POLICY_VERSION
    assert plan.sequence_window_policy_version == SEQUENCE_WINDOW_POLICY_VERSION
    assert plan.tracking_policy_version == TRACKING_POLICY_VERSION
    assert plan.pacing_policy_version == PACING_POLICY_VERSION
    assert plan.batch_generation == 2
    assert plan.provider_campaign_name.startswith(f"KIVOU-{plan.campaign_ref[:12]}-FR-fr-")
    assert len(plan.campaign_group_key) == 64
    assert len(plan.campaign_ref) == 64
    serialized = plan.model_dump_json()
    for forbidden in ("@", "first_name", "last_name", "business_email"):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("step_1", "step_2"),
    [
        (dt.date(2026, 8, 24), dt.date(2026, 8, 28)),  # Monday -> Friday
        (dt.date(2026, 8, 25), dt.date(2026, 8, 31)),  # Tuesday -> Monday
        (dt.date(2026, 8, 26), dt.date(2026, 8, 31)),
        (dt.date(2026, 8, 27), dt.date(2026, 8, 31)),
        (dt.date(2026, 8, 28), dt.date(2026, 9, 1)),
    ],
)
def test_two_window_dates_are_calendar_and_weekday_bounded(
    step_1: dt.date, step_2: dt.date
) -> None:
    window = sequence_window("FR", step_1)

    assert window.timezone == "Europe/Paris"
    assert window.step_2_execution_date == step_2
    assert window.step_1_authorization_deadline == dt.datetime.combine(
        step_1, dt.time(17), ZoneInfo("Europe/Paris")
    )
    assert window.step_2_authorization_deadline == dt.datetime.combine(
        step_2, dt.time(17), ZoneInfo("Europe/Paris")
    )


def test_sequence_window_is_dst_aware_and_rejects_non_workday() -> None:
    winter = sequence_window("CH", dt.date(2026, 10, 23))
    summer = sequence_window("CH", dt.date(2026, 8, 24))

    assert winter.step_2_authorization_deadline.utcoffset() == dt.timedelta(hours=1)
    assert summer.step_2_authorization_deadline.utcoffset() == dt.timedelta(hours=2)
    with pytest.raises(ValueError, match="weekday"):
        sequence_window("FR", dt.date(2026, 8, 22))


def test_envelope_preserves_exact_core_and_frozen_follow_up() -> None:
    catalog = FooterCatalog(
        catalog_version="footer-catalog-test-v1",
        entries=(
            FooterCatalogEntry(
                language="fr",
                sender_profile_ref="sender-profile:test",
                sender_identity="Kivou Test",
                source_notice="Coordonnees professionnelles issues de Test Source.",
                privacy_route="https://example.invalid/privacy",
                visible_opt_out="Repondez STOP pour ne plus etre contacte.",
            ),
        ),
    )
    envelope = build_envelope(
        EnvelopeInput(
            language="fr",
            sender_profile_ref="sender-profile:test",
            subject="Objet exact",
            greeting="Bonjour Camille,",
            body="Corps exact.",
            cta="Souhaitez-vous un exemple ?",
            catalog=catalog,
        )
    )

    assert envelope.provider_subject_template == "{{kivou_subject}}"
    assert envelope.provider_body_template == "{{kivou_envelope}}"
    assert envelope.custom_variables["kivou_subject"] == "Objet exact"
    assert envelope.initial_envelope.startswith(
        "Bonjour Camille,\n\nCorps exact.\n\nSouhaitez-vous un exemple ?\n\n"
    )
    assert envelope.follow_up_subject == ""
    assert envelope.follow_up_body.startswith(
        "Bonjour Camille,\n\nJe me permets de revenir sur mon precedent message."
    ) is False
    assert "Je me permets de revenir sur mon précédent message." in envelope.follow_up_body
    assert len(envelope.steps) == 2
    assert envelope.steps[1].delay_calendar_days == 4


def test_envelope_fails_closed_without_footer_or_with_template_syntax() -> None:
    empty = FooterCatalog(catalog_version="footer-catalog-empty-v1", entries=())
    with pytest.raises(ValueError, match="footer"):
        build_envelope(
            EnvelopeInput(
                language="fr",
                sender_profile_ref="sender-profile:test",
                subject="Objet",
                greeting="Bonjour,",
                body="Corps",
                cta="CTA",
                catalog=empty,
            )
        )
    with pytest.raises(ValueError, match="template syntax"):
        FooterCatalogEntry(
            language="en",
            sender_profile_ref="sender-profile:test",
            sender_identity="{{sender}}",
            source_notice="source",
            privacy_route="https://example.invalid/privacy",
            visible_opt_out="opt out",
        )


def test_defaults_are_fail_closed_and_pacing_only_decreases_capacity() -> None:
    assert MailboxCatalog().entries == ()
    assert MailboxCatalog().usable_entries == ()
    assert TransportContractProof.UNVERIFIED.value == "UNVERIFIED"
    assert WebhookEntitlement.UNVERIFIED.value == "UNVERIFIED"
    policy = PacingPolicy()
    assert policy.autonomous_live_cap == 0
    assert policy.global_daily_cap == 5
    assert policy.country_daily_cap == 5
    assert policy.wedge_daily_cap == 3
    assert policy.mailbox_daily_cap == 3
    assert policy.micro_campaign_member_cap == 10
    assert policy.company_rolling_30d_cap == 1
    assert effective_capacity(policy, provider_daily_limit=2) == 2
    assert effective_capacity(policy, provider_daily_limit=99) == 3


def test_closed_lifecycle_and_state_vocabularies_are_frozen() -> None:
    assert {item.value for item in CampaignLifecycle} == {
        "BUILDING",
        "SEALED",
        "ACTIVE",
        "PAUSED",
        "COMPLETED",
        "FAILED",
    }
    assert {item.value for item in MemberExecutionState} == {
        "RESERVED",
        "ENROLLED",
        "QUEUED",
        "STOPPED",
        "SENT",
        "FAILED",
    }
    assert {item.value for item in MemberSequenceState} == {
        "PENDING_STEP1",
        "WAITING_STEP2",
        "COMPLETED",
        "STOPPED",
        "FAILED",
    }
    assert TrackingPolicy().model_dump() == {
        "policy_version": TRACKING_POLICY_VERSION,
        "open_tracking": False,
        "link_tracking": False,
        "text_only": True,
        "first_email_text_only": True,
        "auto_variant_select": False,
        "ai_sdr": False,
        "spintax": False,
        "liquid": False,
        "allow_risky_contacts": False,
        "bounce_protection": True,
        "insert_unsubscribe_header": True,
    }
    assert ProviderStopPolicy().model_dump(exclude={"policy_version"}) == {
        "stop_on_reply": True,
        "stop_on_auto_reply": True,
        "stop_for_company": False,
    }
