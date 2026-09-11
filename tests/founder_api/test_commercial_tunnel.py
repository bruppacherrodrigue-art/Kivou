from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.pool import StaticPool

from signals.accounts.schema import account_landing_signal
from signals.cockpit.contracts import completed_week
from signals.founder_api.commercial_tunnel import (
    FounderCommercialTunnelReadService,
    FounderMoneyTotal,
    FounderTunnelPeriod,
    FounderTunnelSlice,
    period_bounds,
)
from signals.persistence.schema import (
    METADATA,
    acquisition_campaign_member,
    acquisition_conversion_event,
    acquisition_conversion_journey,
    acquisition_provider_event,
    prospect_delivery_event,
    prospect_target,
)

NOW = dt.datetime(2026, 9, 12, 8, tzinfo=dt.UTC)


@pytest.fixture
def engine() -> sa.Engine:
    value = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    METADATA.create_all(value)
    return value


def _member(*, member_ref: str, sent_at: dt.datetime) -> dict[str, object]:
    return {
        "member_ref": member_ref,
        "campaign_ref": f"campaign-{member_ref}",
        "acquisition_opportunity_id": f"opportunity-{member_ref}",
        "supplier_ref": f"supplier-{member_ref}",
        "contact_ref": f"contact-{member_ref}",
        "personalization_artifact_id": f"artifact-{member_ref}",
        "personalization_artifact_fingerprint": f"artifact-fingerprint-{member_ref}",
        "compliance_assessment_id": f"compliance-{member_ref}",
        "compliance_assessment_fingerprint": f"compliance-fingerprint-{member_ref}",
        "policy_evaluation_id": f"policy-{member_ref}",
        "policy_provenance": {},
        "input_fingerprint": f"input-{member_ref}",
        "contact_provider_identity_binding": f"contact-binding-{member_ref}",
        "plan_fingerprint": f"plan-{member_ref}",
        "envelope_fingerprint": f"envelope-{member_ref}",
        "policy_action_fingerprint": f"policy-action-{member_ref}",
        "ruleset_fingerprint": f"ruleset-{member_ref}",
        "sender_config_fingerprint": f"sender-{member_ref}",
        "mailbox_ref": f"mailbox-{member_ref}",
        "mailbox_readiness_fingerprint": f"mailbox-readiness-{member_ref}",
        "step_1_execution_date": sent_at.date(),
        "step_1_authorization_deadline": sent_at + dt.timedelta(hours=1),
        "step_2_execution_date": sent_at.date() + dt.timedelta(days=2),
        "step_2_authorization_deadline": sent_at + dt.timedelta(days=2),
        "sequence_authorization_fingerprint": f"sequence-auth-{member_ref}",
        "step_1_sent_at": sent_at,
        "step_2_due_at": sent_at + dt.timedelta(days=2),
        "sequence_timing_fingerprint": f"sequence-timing-{member_ref}",
        "execution_state": "SENT",
        "sequence_state": "WAITING_STEP2",
        "created_at": sent_at,
        "updated_at": sent_at,
    }


def _target(
    *,
    target_id: str,
    sent_at: dt.datetime,
    opened_at: dt.datetime | None = None,
) -> dict[str, object]:
    return {
        "target_id": target_id,
        "version": 1,
        "cycle_ref": "cycle-tunnel",
        "opportunity_key": f"opportunity-{target_id}",
        "procedure_award_key": f"award-{target_id}",
        "acquisition_opportunity_id": f"acquisition-{target_id}",
        "siren": "123456789",
        "company_name": f"Company {target_id}",
        "company_city": "Lyon",
        "company_employees": 20,
        "vertical": "general_building",
        "family_key": "ready_mix_concrete",
        "family_label": "béton prêt à l'emploi",
        "email_address": f"{target_id}@example.test",
        "email_source": "site",
        "email_verification_status": "mx_verified",
        "signal_holder": "SAS Titulaire",
        "signal_subject": "Construction d'un groupe scolaire",
        "signal_amount_minor_units": 125_000_000,
        "signal_currency": "EUR",
        "signal_location": "Rhône",
        "signal_decision_date": sent_at.date(),
        "signal_source_url": "https://example.test/signal",
        "mail_subject": "Un signal commercial",
        "mail_text": "Bonjour, voici un signal commercial.",
        "mail_html": "<p>Bonjour, voici un signal commercial.</p>",
        "attribution_url": f"https://kivou.eu/a/{target_id}",
        "attribution_member_ref": f"member-{target_id}",
        "attribution_payload": {},
        "attribution_token_fingerprint": f"token-{target_id}",
        "unsubscribe_url": f"https://kivou.eu/unsubscribe/{target_id}",
        "mail_word_count": 5,
        "status": "sent",
        "delivery_status": "opened" if opened_at is not None else "sent",
        "sent_at": sent_at,
        "opened_at": opened_at,
        "created_at": sent_at,
        "updated_at": opened_at or sent_at,
    }


def _for_target(values: dict[str, object], *, target_id: str) -> dict[str, object]:
    return {
        **values,
        "prospect_target_id": target_id,
        "campaign_ref": None,
        "member_ref": None,
        "acquisition_opportunity_id": None,
    }


def _assisted_delivery_event(
    *,
    event_ref: str,
    target_id: str,
    occurred_at: dt.datetime,
    event_type: str = "email_opened",
) -> dict[str, object]:
    return {
        "event_fingerprint": event_ref,
        "target_id": target_id,
        "provider_campaign_id": f"provider-{target_id}",
        "provider_event_type": event_type,
        "occurred_at": occurred_at,
        "received_at": occurred_at,
    }


def _opening(
    *,
    event_ref: str,
    member_ref: str,
    occurred_at: dt.datetime,
    resolution_state: str = "PROCESSED",
) -> dict[str, object]:
    return {
        "provider_event_ref": event_ref,
        "canonical_event_fingerprint": event_ref,
        "fingerprint_version": "provider-event-v1",
        "fingerprint_key_version": "provider-key-v1",
        "provider_event_type": "email_opened",
        "provider_workspace_ref": "workspace-tunnel",
        "provider_campaign_id": f"provider-{member_ref}",
        "campaign_ref": f"campaign-{member_ref}",
        "member_ref": member_ref,
        "acquisition_opportunity_id": f"opportunity-{member_ref}",
        "contact_ref": f"contact-{member_ref}",
        "occurred_at": occurred_at,
        "received_at": occurred_at,
        "resolution_state": resolution_state,
    }


def _click(*, event_ref: str, member_ref: str, occurred_at: dt.datetime) -> dict[str, object]:
    return {
        "conversion_event_ref": event_ref,
        "journey_ref": None,
        "milestone": "CLICK",
        "event_version": "conversion-event-v1",
        "event_fingerprint": event_ref,
        "token_fingerprint": f"token-{event_ref}",
        "trigger_ref_type": None,
        "trigger_ref": None,
        "account_id": None,
        "campaign_ref": f"campaign-{member_ref}",
        "member_ref": member_ref,
        "acquisition_opportunity_id": f"opportunity-{member_ref}",
        "mrr_known": None,
        "mrr_minor_units": None,
        "currency": None,
        "reason_code": None,
        "occurred_at": occurred_at,
        "observed_at": occurred_at,
        "recorded_at": occurred_at,
    }


def _journey(
    *, journey_ref: str, account_id: str, member_ref: str, at: dt.datetime
) -> dict[str, object]:
    return {
        "journey_ref": journey_ref,
        "account_id": account_id,
        "source_click_event_ref": f"source-click-{journey_ref}",
        "campaign_ref": f"campaign-{member_ref}",
        "member_ref": member_ref,
        "acquisition_opportunity_id": f"opportunity-{member_ref}",
        "token_fingerprint": f"token-{journey_ref}",
        "token_version": "attribution-token-v1",
        "token_key_version": "key-v1",
        "country": "CH",
        "sector_ref": "sector-tunnel",
        "sector_version": "sector-v1",
        "need_ref": "need-tunnel",
        "need_version": "need-v1",
        "wedge": "wedge-tunnel",
        "wedge_version": "wedge-v1",
        "attribution_policy_version": "attribution-v1",
        "source_fingerprint": f"source-{journey_ref}",
        "clicked_at": at,
        "attribution_expires_at": at + dt.timedelta(days=30),
        "signed_up_at": at,
        "created_at": at,
    }


def _commercial_event(
    *,
    event_ref: str,
    journey_ref: str,
    account_id: str,
    member_ref: str,
    milestone: str,
    occurred_at: dt.datetime,
    mrr_known: bool | None = None,
    mrr_minor_units: int | None = None,
    currency: str | None = None,
) -> dict[str, object]:
    reason_code = "MRR_UNKNOWN" if milestone == "MRR_CHANGED" and mrr_known is False else None
    return {
        "conversion_event_ref": event_ref,
        "journey_ref": journey_ref,
        "milestone": milestone,
        "event_version": "conversion-event-v1",
        "event_fingerprint": event_ref,
        "token_fingerprint": None,
        "trigger_ref_type": "SYNTHETIC",
        "trigger_ref": event_ref,
        "account_id": account_id,
        "campaign_ref": f"campaign-{member_ref}",
        "member_ref": member_ref,
        "acquisition_opportunity_id": f"opportunity-{member_ref}",
        "mrr_known": mrr_known if milestone == "MRR_CHANGED" else None,
        "mrr_minor_units": mrr_minor_units if milestone == "MRR_CHANGED" else None,
        "currency": currency if milestone == "MRR_CHANGED" else None,
        "reason_code": reason_code,
        "occurred_at": occurred_at,
        "observed_at": occurred_at,
        "recorded_at": occurred_at,
    }


def _insert_current_journey(
    connection: sa.Connection,
    *,
    suffix: str,
    events: tuple[tuple[str, dt.datetime, bool | None, int | None, str | None], ...],
) -> None:
    member_ref = f"member-current-{suffix}"
    journey_ref = f"journey-current-{suffix}"
    account_id = f"account-current-{suffix}"
    connection.execute(
        sa.insert(acquisition_conversion_event),
        [
            _commercial_event(
                event_ref=f"{suffix}-{index}",
                journey_ref=journey_ref,
                account_id=account_id,
                member_ref=member_ref,
                milestone=milestone,
                occurred_at=occurred_at,
                mrr_known=mrr_known,
                mrr_minor_units=minor_units,
                currency=currency,
            )
            for index, (milestone, occurred_at, mrr_known, minor_units, currency) in enumerate(
                events
            )
        ],
    )


@pytest.mark.parametrize(
    ("period", "expected_start"),
    [
        (FounderTunnelPeriod.TODAY, dt.datetime(2026, 9, 11, 22, tzinfo=dt.UTC)),
        (
            FounderTunnelPeriod.LAST_7_DAYS,
            dt.datetime(2026, 9, 5, 22, tzinfo=dt.UTC),
        ),
    ],
)
def test_period_bounds_use_zurich_midnight(
    period: FounderTunnelPeriod, expected_start: dt.datetime
) -> None:
    bounds = period_bounds(NOW, period)

    assert bounds.start == expected_start
    assert bounds.end == NOW


def test_last_seven_days_keeps_local_midnight_across_dst() -> None:
    now = dt.datetime(2026, 10, 26, 12, tzinfo=dt.UTC)

    bounds = period_bounds(now, FounderTunnelPeriod.LAST_7_DAYS)

    assert bounds.start == dt.datetime(2026, 10, 19, 22, tzinfo=dt.UTC)
    assert bounds.end == now


def test_contracts_require_utc_aware_times_uppercase_money_and_non_negative_counts() -> None:
    with pytest.raises(ValidationError):
        FounderMoneyTotal(currency="chf", minor_units=100)
    with pytest.raises(ValidationError):
        FounderMoneyTotal(currency="CHF", minor_units=-1)
    with pytest.raises(ValidationError):
        FounderTunnelSlice(
            start_at=NOW.replace(tzinfo=None),
            end_at=NOW,
            sent_count=0,
            opened_count=0,
            click_count=0,
            landing_count=0,
            confirmed_profile_count=0,
            paid_count=0,
        )


def test_period_counts_each_stage_at_its_own_date_and_deduplicates_entities(
    engine: sa.Engine,
) -> None:
    member_ref = "member-period"
    sent_at = NOW - dt.timedelta(days=20)
    account_id = "account-period"
    journey_ref = "journey-period"
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_campaign_member), _member(member_ref=member_ref, sent_at=sent_at)
        )
        connection.execute(
            sa.insert(acquisition_provider_event),
            [
                _opening(
                    event_ref="open-period-1",
                    member_ref=member_ref,
                    occurred_at=NOW - dt.timedelta(days=2),
                    resolution_state="ACCEPTED",
                ),
                _opening(
                    event_ref="open-period-2",
                    member_ref=member_ref,
                    occurred_at=NOW - dt.timedelta(days=1),
                ),
                _opening(
                    event_ref="open-period-quarantined",
                    member_ref="member-quarantined",
                    occurred_at=NOW - dt.timedelta(hours=6),
                    resolution_state="QUARANTINED",
                ),
            ],
        )
        connection.execute(
            sa.insert(acquisition_conversion_journey),
            _journey(
                journey_ref=journey_ref,
                account_id=account_id,
                member_ref=member_ref,
                at=sent_at,
            ),
        )
        connection.execute(
            sa.insert(acquisition_conversion_event),
            [
                _click(
                    event_ref="click-period",
                    member_ref=member_ref,
                    occurred_at=NOW - dt.timedelta(days=1),
                ),
                _commercial_event(
                    event_ref="paid-period-1",
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref=member_ref,
                    milestone="PAID",
                    occurred_at=NOW - dt.timedelta(hours=2),
                ),
                _commercial_event(
                    event_ref="paid-period-2",
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref=member_ref,
                    milestone="PAID",
                    occurred_at=NOW - dt.timedelta(hours=1),
                ),
            ],
        )
        connection.execute(
            sa.insert(account_landing_signal),
            [
                {
                    "account_id": account_id,
                    "created_at": NOW - dt.timedelta(hours=20),
                    "profile_confirmed_at": NOW - dt.timedelta(hours=12),
                    "qa": False,
                },
                {
                    "account_id": "account-period-qa",
                    "created_at": NOW - dt.timedelta(hours=10),
                    "profile_confirmed_at": NOW - dt.timedelta(hours=8),
                    "qa": True,
                },
            ],
        )

    tunnel = FounderCommercialTunnelReadService(engine).read(
        now=NOW,
        period=FounderTunnelPeriod.LAST_7_DAYS,
        week_offset=0,
    )

    assert tunnel.period.sent_count == 0
    assert tunnel.period.opened_count == 1
    assert tunnel.period.click_count == 1
    assert tunnel.period.landing_count == 1
    assert tunnel.period.confirmed_profile_count == 1
    assert tunnel.period.paid_count == 1


def test_period_includes_both_bounds_and_excludes_events_outside_them(
    engine: sa.Engine,
) -> None:
    bounds = period_bounds(NOW, FounderTunnelPeriod.LAST_7_DAYS)
    rows = [
        _member(member_ref="member-at-start", sent_at=bounds.start),
        _member(member_ref="member-at-now", sent_at=NOW),
        _member(
            member_ref="member-before-start",
            sent_at=bounds.start - dt.timedelta(microseconds=1),
        ),
        _member(
            member_ref="member-after-now",
            sent_at=NOW + dt.timedelta(microseconds=1),
        ),
    ]
    with engine.begin() as connection:
        connection.execute(sa.insert(acquisition_campaign_member), rows)
        connection.execute(
            sa.insert(acquisition_conversion_event),
            [
                _click(
                    event_ref="click-at-now",
                    member_ref="member-at-now",
                    occurred_at=NOW,
                ),
                _click(
                    event_ref="click-after-now",
                    member_ref="member-after-now",
                    occurred_at=NOW + dt.timedelta(microseconds=1),
                ),
            ],
        )

    period = (
        FounderCommercialTunnelReadService(engine)
        .read(
            now=NOW,
            period=FounderTunnelPeriod.LAST_7_DAYS,
            week_offset=0,
        )
        .period
    )

    assert period.sent_count == 2
    assert period.click_count == 1


def test_period_uses_assisted_open_ledger_without_recounting_shared_stages(
    engine: sa.Engine,
) -> None:
    bounds = period_bounds(NOW, FounderTunnelPeriod.TODAY)
    target_id = "target-period-opened"
    sent_at = bounds.start - dt.timedelta(days=1)
    first_open_at = bounds.start - dt.timedelta(hours=1)
    account_id = "account-assisted-period"
    journey_ref = "journey-assisted-period"
    with engine.begin() as connection:
        connection.execute(
            sa.insert(prospect_target),
            [
                _target(
                    target_id="target-period-sent",
                    sent_at=NOW - dt.timedelta(hours=6),
                ),
                _target(
                    target_id=target_id,
                    sent_at=sent_at,
                    opened_at=first_open_at,
                ),
            ],
        )
        connection.execute(
            sa.insert(prospect_delivery_event),
            [
                _assisted_delivery_event(
                    event_ref="open-assisted-period-first",
                    target_id=target_id,
                    occurred_at=first_open_at,
                ),
                _assisted_delivery_event(
                    event_ref="open-assisted-period-second",
                    target_id=target_id,
                    occurred_at=NOW - dt.timedelta(hours=5),
                ),
            ],
        )
        connection.execute(
            sa.insert(acquisition_conversion_event),
            _for_target(
                _click(
                    event_ref="click-assisted-period",
                    member_ref="unused-assisted-period",
                    occurred_at=NOW - dt.timedelta(hours=4),
                ),
                target_id=target_id,
            ),
        )
        connection.execute(
            sa.insert(acquisition_conversion_journey),
            _for_target(
                _journey(
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref="unused-assisted-period",
                    at=sent_at,
                ),
                target_id=target_id,
            ),
        )
        connection.execute(
            sa.insert(acquisition_conversion_event),
            _for_target(
                _commercial_event(
                    event_ref="paid-assisted-period",
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref="unused-assisted-period",
                    milestone="PAID",
                    occurred_at=NOW - dt.timedelta(hours=1),
                ),
                target_id=target_id,
            ),
        )
        connection.execute(
            sa.insert(account_landing_signal),
            {
                "account_id": account_id,
                "created_at": NOW - dt.timedelta(hours=3),
                "profile_confirmed_at": NOW - dt.timedelta(hours=2),
                "qa": False,
            },
        )

    period = (
        FounderCommercialTunnelReadService(engine)
        .read(
            now=NOW,
            period=FounderTunnelPeriod.TODAY,
            week_offset=0,
        )
        .period
    )

    assert period.sent_count == 1
    assert period.opened_count == 1
    assert period.click_count == 1
    assert period.landing_count == 1
    assert period.confirmed_profile_count == 1
    assert period.paid_count == 1


def test_cohort_includes_later_stages_through_now_but_not_before_send_or_in_future(
    engine: sa.Engine,
) -> None:
    week = completed_week(NOW)
    sent_at = week.week_start.astimezone(dt.UTC) + dt.timedelta(hours=4)
    member_ref = "member-cohort"
    journey_ref = "journey-cohort"
    account_id = "account-cohort"
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_campaign_member), _member(member_ref=member_ref, sent_at=sent_at)
        )
        connection.execute(
            sa.insert(acquisition_provider_event),
            [
                _opening(
                    event_ref="open-before-send",
                    member_ref=member_ref,
                    occurred_at=sent_at - dt.timedelta(seconds=1),
                ),
                _opening(
                    event_ref="open-cohort-1",
                    member_ref=member_ref,
                    occurred_at=sent_at + dt.timedelta(days=2),
                ),
                _opening(
                    event_ref="open-cohort-2",
                    member_ref=member_ref,
                    occurred_at=sent_at + dt.timedelta(days=3),
                ),
                _opening(
                    event_ref="open-after-now",
                    member_ref=member_ref,
                    occurred_at=NOW + dt.timedelta(seconds=1),
                ),
            ],
        )
        connection.execute(
            sa.insert(acquisition_conversion_journey),
            _journey(
                journey_ref=journey_ref,
                account_id=account_id,
                member_ref=member_ref,
                at=sent_at,
            ),
        )
        connection.execute(
            sa.insert(acquisition_conversion_event),
            [
                _click(
                    event_ref="click-before-send",
                    member_ref=member_ref,
                    occurred_at=sent_at - dt.timedelta(seconds=1),
                ),
                _click(
                    event_ref="click-day-ten",
                    member_ref=member_ref,
                    occurred_at=sent_at + dt.timedelta(days=10),
                ),
                _click(
                    event_ref="click-after-now-cohort",
                    member_ref=member_ref,
                    occurred_at=NOW + dt.timedelta(seconds=1),
                ),
                _commercial_event(
                    event_ref="paid-cohort",
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref=member_ref,
                    milestone="PAID",
                    occurred_at=sent_at + dt.timedelta(days=12),
                ),
                _commercial_event(
                    event_ref="mrr-cohort",
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref=member_ref,
                    milestone="MRR_CHANGED",
                    occurred_at=sent_at + dt.timedelta(days=12, minutes=1),
                    mrr_known=True,
                    mrr_minor_units=19_900,
                    currency="chf",
                ),
            ],
        )
        connection.execute(
            sa.insert(account_landing_signal),
            {
                "account_id": account_id,
                "created_at": sent_at + dt.timedelta(days=10, minutes=1),
                "profile_confirmed_at": sent_at + dt.timedelta(days=11),
                "qa": False,
            },
        )

    result = FounderCommercialTunnelReadService(engine).read(
        now=NOW,
        period=FounderTunnelPeriod.TODAY,
        week_offset=0,
    )

    assert result.cohort.start_at == week.week_start.astimezone(dt.UTC)
    assert result.cohort.end_at == week.week_end.astimezone(dt.UTC)
    assert result.cohort.sent_count == 1
    assert result.cohort.opened_count == 1
    assert result.cohort.click_count == 1
    assert result.cohort.landing_count == 1
    assert result.cohort.confirmed_profile_count == 1
    assert result.cohort.paid_count == 1


def test_cohort_uses_assisted_open_ledger_and_relates_later_stages_by_target(
    engine: sa.Engine,
) -> None:
    week = completed_week(NOW)
    sent_at = week.week_start.astimezone(dt.UTC) + dt.timedelta(hours=4)
    other_sent_at = week.week_start.astimezone(dt.UTC) - dt.timedelta(days=1)
    target_id = "target-assisted-cohort"
    other_target_id = "target-assisted-other"
    account_id = "account-assisted-cohort"
    other_account_id = "account-assisted-other"
    journey_ref = "journey-assisted-cohort"
    other_journey_ref = "journey-assisted-other"
    with engine.begin() as connection:
        connection.execute(
            sa.insert(prospect_target),
            [
                _target(
                    target_id=target_id,
                    sent_at=sent_at,
                ),
                _target(
                    target_id=other_target_id,
                    sent_at=other_sent_at,
                    opened_at=NOW - dt.timedelta(hours=3),
                ),
            ],
        )
        connection.execute(
            sa.insert(prospect_delivery_event),
            [
                _assisted_delivery_event(
                    event_ref="open-assisted-before-send",
                    target_id=target_id,
                    occurred_at=sent_at - dt.timedelta(seconds=1),
                ),
                _assisted_delivery_event(
                    event_ref="open-assisted-cohort-1",
                    target_id=target_id,
                    occurred_at=sent_at + dt.timedelta(days=2),
                ),
                _assisted_delivery_event(
                    event_ref="open-assisted-cohort-2",
                    target_id=target_id,
                    occurred_at=sent_at + dt.timedelta(days=3),
                ),
                _assisted_delivery_event(
                    event_ref="open-assisted-wrong-type",
                    target_id=target_id,
                    occurred_at=sent_at + dt.timedelta(days=4),
                    event_type="email_sent",
                ),
                _assisted_delivery_event(
                    event_ref="open-assisted-future",
                    target_id=target_id,
                    occurred_at=NOW + dt.timedelta(seconds=1),
                ),
                _assisted_delivery_event(
                    event_ref="open-assisted-other",
                    target_id=other_target_id,
                    occurred_at=NOW - dt.timedelta(hours=3),
                ),
            ],
        )
        connection.execute(
            sa.insert(acquisition_conversion_event),
            [
                _for_target(
                    _click(
                        event_ref="click-assisted-before-send",
                        member_ref="unused-assisted-before",
                        occurred_at=sent_at - dt.timedelta(seconds=1),
                    ),
                    target_id=target_id,
                ),
                _for_target(
                    _click(
                        event_ref="click-assisted-cohort",
                        member_ref="unused-assisted-selected",
                        occurred_at=sent_at + dt.timedelta(days=10),
                    ),
                    target_id=target_id,
                ),
                _for_target(
                    _click(
                        event_ref="click-assisted-future",
                        member_ref="unused-assisted-future",
                        occurred_at=NOW + dt.timedelta(seconds=1),
                    ),
                    target_id=target_id,
                ),
                _for_target(
                    _click(
                        event_ref="click-assisted-other",
                        member_ref="unused-assisted-other",
                        occurred_at=NOW - dt.timedelta(hours=2),
                    ),
                    target_id=other_target_id,
                ),
            ],
        )
        connection.execute(
            sa.insert(acquisition_conversion_journey),
            [
                _for_target(
                    _journey(
                        journey_ref=journey_ref,
                        account_id=account_id,
                        member_ref="unused-assisted-selected",
                        at=sent_at + dt.timedelta(days=10),
                    ),
                    target_id=target_id,
                ),
                _for_target(
                    _journey(
                        journey_ref=other_journey_ref,
                        account_id=other_account_id,
                        member_ref="unused-assisted-other",
                        at=NOW - dt.timedelta(hours=3),
                    ),
                    target_id=other_target_id,
                ),
            ],
        )
        connection.execute(
            sa.insert(acquisition_conversion_event),
            [
                _for_target(
                    _commercial_event(
                        event_ref="paid-assisted-cohort",
                        journey_ref=journey_ref,
                        account_id=account_id,
                        member_ref="unused-assisted-selected",
                        milestone="PAID",
                        occurred_at=sent_at + dt.timedelta(days=12),
                    ),
                    target_id=target_id,
                ),
                _for_target(
                    _commercial_event(
                        event_ref="paid-assisted-other",
                        journey_ref=other_journey_ref,
                        account_id=other_account_id,
                        member_ref="unused-assisted-other",
                        milestone="PAID",
                        occurred_at=NOW - dt.timedelta(hours=1),
                    ),
                    target_id=other_target_id,
                ),
            ],
        )
        connection.execute(
            sa.insert(account_landing_signal),
            [
                {
                    "account_id": account_id,
                    "created_at": sent_at + dt.timedelta(days=10, minutes=1),
                    "profile_confirmed_at": sent_at + dt.timedelta(days=11),
                    "qa": False,
                },
                {
                    "account_id": other_account_id,
                    "created_at": NOW - dt.timedelta(hours=2),
                    "profile_confirmed_at": NOW - dt.timedelta(hours=1),
                    "qa": False,
                },
            ],
        )

    cohort = (
        FounderCommercialTunnelReadService(engine)
        .read(
            now=NOW,
            period=FounderTunnelPeriod.TODAY,
            week_offset=0,
        )
        .cohort
    )

    assert cohort.sent_count == 1
    assert cohort.opened_count == 1
    assert cohort.click_count == 1
    assert cohort.landing_count == 1
    assert cohort.confirmed_profile_count == 1
    assert cohort.paid_count == 1


def test_cohort_relates_accounts_through_journeys_and_excludes_qa_landings(
    engine: sa.Engine,
) -> None:
    week = completed_week(NOW)
    sent_at = week.week_start.astimezone(dt.UTC) + dt.timedelta(hours=1)
    other_sent_at = week.week_start.astimezone(dt.UTC) - dt.timedelta(days=1)
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_campaign_member),
            [
                _member(member_ref="member-selected", sent_at=sent_at),
                _member(member_ref="member-other", sent_at=other_sent_at),
            ],
        )
        connection.execute(
            sa.insert(acquisition_conversion_journey),
            [
                _journey(
                    journey_ref="journey-selected",
                    account_id="account-selected-qa",
                    member_ref="member-selected",
                    at=sent_at,
                ),
                _journey(
                    journey_ref="journey-other",
                    account_id="account-other",
                    member_ref="member-other",
                    at=other_sent_at,
                ),
            ],
        )
        connection.execute(
            sa.insert(account_landing_signal),
            [
                {
                    "account_id": "account-selected-qa",
                    "created_at": sent_at + dt.timedelta(hours=1),
                    "profile_confirmed_at": sent_at + dt.timedelta(hours=2),
                    "qa": True,
                },
                {
                    "account_id": "account-other",
                    "created_at": sent_at + dt.timedelta(hours=1),
                    "profile_confirmed_at": sent_at + dt.timedelta(hours=2),
                    "qa": False,
                },
            ],
        )

    cohort = (
        FounderCommercialTunnelReadService(engine)
        .read(
            now=NOW,
            period=FounderTunnelPeriod.TODAY,
            week_offset=0,
        )
        .cohort
    )

    assert cohort.sent_count == 1
    assert cohort.landing_count == 0
    assert cohort.confirmed_profile_count == 0


def test_current_uses_latest_state_latest_known_mrr_and_ignores_future(
    engine: sa.Engine,
) -> None:
    with engine.begin() as connection:
        _insert_current_journey(
            connection,
            suffix="active-chf",
            events=(
                ("PAID", NOW - dt.timedelta(days=5), None, None, None),
                ("MRR_CHANGED", NOW - dt.timedelta(days=4), True, 19_900, "chf"),
                ("CHURNED", NOW + dt.timedelta(seconds=1), None, None, None),
            ),
        )
        _insert_current_journey(
            connection,
            suffix="churned-eur",
            events=(
                ("PAID", NOW - dt.timedelta(days=5), None, None, None),
                ("MRR_CHANGED", NOW - dt.timedelta(days=4), True, 8_000, "eur"),
                ("CHURNED", NOW - dt.timedelta(days=3), None, None, None),
                ("RETAINED_M2", NOW - dt.timedelta(days=1), None, None, None),
            ),
        )
        _insert_current_journey(
            connection,
            suffix="reactivated-eur",
            events=(
                ("PAID", NOW - dt.timedelta(days=7), None, None, None),
                ("MRR_CHANGED", NOW - dt.timedelta(days=6), True, 4_000, "eur"),
                ("CHURNED", NOW - dt.timedelta(days=5), None, None, None),
                ("MRR_CHANGED", NOW - dt.timedelta(days=4), True, 0, "eur"),
                ("PAID", NOW - dt.timedelta(days=3), None, None, None),
                ("MRR_CHANGED", NOW - dt.timedelta(days=2), True, 4_900, "eur"),
            ),
        )
        _insert_current_journey(
            connection,
            suffix="unknown",
            events=(
                ("PAID", NOW - dt.timedelta(days=4), None, None, None),
                ("MRR_CHANGED", NOW - dt.timedelta(days=3), True, 1_000, "chf"),
                ("MRR_CHANGED", NOW - dt.timedelta(days=2), False, None, None),
            ),
        )
        _insert_current_journey(
            connection,
            suffix="not-paid",
            events=(("MRR_CHANGED", NOW - dt.timedelta(days=1), True, 99_999, "chf"),),
        )

    service = FounderCommercialTunnelReadService(engine)
    today = service.read(
        now=NOW,
        period=FounderTunnelPeriod.TODAY,
        week_offset=0,
    )
    another_view = service.read(
        now=NOW,
        period=FounderTunnelPeriod.LAST_7_DAYS,
        week_offset=1,
    )

    assert today.current == another_view.current
    assert today.current.observed_at == NOW
    assert today.current.churn_count == 1
    assert [item.model_dump() for item in today.current.mrr_by_currency] == [
        {"currency": "CHF", "minor_units": 20_900},
        {"currency": "EUR", "minor_units": 4_900},
    ]


def test_current_preserves_churn_after_cancellation_writes_zero_mrr(
    engine: sa.Engine,
) -> None:
    with engine.begin() as connection:
        _insert_current_journey(
            connection,
            suffix="cancellation",
            events=(
                ("PAID", NOW - dt.timedelta(days=3), None, None, None),
                ("MRR_CHANGED", NOW - dt.timedelta(days=2), True, 9_900, "chf"),
                ("CHURNED", NOW - dt.timedelta(hours=2), None, None, None),
                ("MRR_CHANGED", NOW - dt.timedelta(hours=1), True, 0, "chf"),
            ),
        )

    current = (
        FounderCommercialTunnelReadService(engine)
        .read(
            now=NOW,
            period=FounderTunnelPeriod.TODAY,
            week_offset=0,
        )
        .current
    )

    assert current.churn_count == 1
    assert current.mrr_by_currency == ()


def test_current_requires_known_mrr_after_latest_paid_transition(
    engine: sa.Engine,
) -> None:
    with engine.begin() as connection:
        _insert_current_journey(
            connection,
            suffix="reactivated-without-new-mrr",
            events=(
                ("PAID", NOW - dt.timedelta(days=5), None, None, None),
                ("MRR_CHANGED", NOW - dt.timedelta(days=4), True, 7_900, "chf"),
                ("CHURNED", NOW - dt.timedelta(days=3), None, None, None),
                ("MRR_CHANGED", NOW - dt.timedelta(days=2), True, 0, "chf"),
                ("PAID", NOW - dt.timedelta(days=1), None, None, None),
            ),
        )

    current = (
        FounderCommercialTunnelReadService(engine)
        .read(
            now=NOW,
            period=FounderTunnelPeriod.TODAY,
            week_offset=0,
        )
        .current
    )

    assert current.churn_count == 0
    assert current.mrr_by_currency == ()


def test_current_keeps_mrr_at_same_time_when_its_ref_sorts_before_paid(
    engine: sa.Engine,
) -> None:
    occurred_at = NOW - dt.timedelta(hours=1)
    member_ref = "member-same-time"
    journey_ref = "journey-same-time"
    account_id = "account-same-time"
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_conversion_event),
            [
                _commercial_event(
                    event_ref="z-paid-same-time",
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref=member_ref,
                    milestone="PAID",
                    occurred_at=occurred_at,
                ),
                _commercial_event(
                    event_ref="a-mrr-same-time",
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref=member_ref,
                    milestone="MRR_CHANGED",
                    occurred_at=occurred_at,
                    mrr_known=True,
                    mrr_minor_units=12_900,
                    currency="chf",
                ),
            ],
        )

    current = (
        FounderCommercialTunnelReadService(engine)
        .read(
            now=NOW,
            period=FounderTunnelPeriod.TODAY,
            week_offset=0,
        )
        .current
    )

    assert current.churn_count == 0
    assert [item.model_dump() for item in current.mrr_by_currency] == [
        {"currency": "CHF", "minor_units": 12_900}
    ]


@pytest.mark.parametrize(
    ("paid_ref", "churned_ref"),
    [
        ("a-paid-same-time", "z-churned-same-time"),
        ("z-paid-same-time", "a-churned-same-time"),
    ],
)
def test_current_prefers_churn_when_paid_and_churn_have_equal_times(
    engine: sa.Engine,
    paid_ref: str,
    churned_ref: str,
) -> None:
    occurred_at = NOW - dt.timedelta(hours=1)
    member_ref = "member-transition-tie"
    journey_ref = "journey-transition-tie"
    account_id = "account-transition-tie"
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_conversion_event),
            [
                _commercial_event(
                    event_ref=paid_ref,
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref=member_ref,
                    milestone="PAID",
                    occurred_at=occurred_at,
                ),
                _commercial_event(
                    event_ref=churned_ref,
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref=member_ref,
                    milestone="CHURNED",
                    occurred_at=occurred_at,
                ),
            ],
        )

    current = (
        FounderCommercialTunnelReadService(engine)
        .read(
            now=NOW,
            period=FounderTunnelPeriod.TODAY,
            week_offset=0,
        )
        .current
    )

    assert current.churn_count == 1
    assert current.mrr_by_currency == ()


@pytest.mark.parametrize(
    ("known_ref", "unknown_ref"),
    [
        ("a-known-same-time", "z-unknown-same-time"),
        ("z-known-same-time", "a-unknown-same-time"),
    ],
)
def test_current_ignores_unknown_mrr_when_known_mrr_has_equal_times(
    engine: sa.Engine,
    known_ref: str,
    unknown_ref: str,
) -> None:
    paid_at = NOW - dt.timedelta(hours=2)
    mrr_at = NOW - dt.timedelta(hours=1)
    member_ref = "member-mrr-unknown-tie"
    journey_ref = "journey-mrr-unknown-tie"
    account_id = "account-mrr-unknown-tie"
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_conversion_event),
            [
                _commercial_event(
                    event_ref="paid-before-mrr-tie",
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref=member_ref,
                    milestone="PAID",
                    occurred_at=paid_at,
                ),
                _commercial_event(
                    event_ref=known_ref,
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref=member_ref,
                    milestone="MRR_CHANGED",
                    occurred_at=mrr_at,
                    mrr_known=True,
                    mrr_minor_units=13_900,
                    currency="chf",
                ),
                _commercial_event(
                    event_ref=unknown_ref,
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref=member_ref,
                    milestone="MRR_CHANGED",
                    occurred_at=mrr_at,
                    mrr_known=False,
                ),
            ],
        )

    current = (
        FounderCommercialTunnelReadService(engine)
        .read(
            now=NOW,
            period=FounderTunnelPeriod.TODAY,
            week_offset=0,
        )
        .current
    )

    assert current.churn_count == 0
    assert [item.model_dump() for item in current.mrr_by_currency] == [
        {"currency": "CHF", "minor_units": 13_900}
    ]


def test_current_uses_descending_ref_for_known_mrr_at_equal_times(
    engine: sa.Engine,
) -> None:
    paid_at = NOW - dt.timedelta(hours=2)
    mrr_at = NOW - dt.timedelta(hours=1)
    member_ref = "member-known-mrr-tie"
    journey_ref = "journey-known-mrr-tie"
    account_id = "account-known-mrr-tie"
    with engine.begin() as connection:
        connection.execute(
            sa.insert(acquisition_conversion_event),
            [
                _commercial_event(
                    event_ref="paid-before-known-mrr-tie",
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref=member_ref,
                    milestone="PAID",
                    occurred_at=paid_at,
                ),
                _commercial_event(
                    event_ref="a-known-mrr-tie",
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref=member_ref,
                    milestone="MRR_CHANGED",
                    occurred_at=mrr_at,
                    mrr_known=True,
                    mrr_minor_units=11_900,
                    currency="chf",
                ),
                _commercial_event(
                    event_ref="z-known-mrr-tie",
                    journey_ref=journey_ref,
                    account_id=account_id,
                    member_ref=member_ref,
                    milestone="MRR_CHANGED",
                    occurred_at=mrr_at,
                    mrr_known=True,
                    mrr_minor_units=15_900,
                    currency="chf",
                ),
            ],
        )

    current = (
        FounderCommercialTunnelReadService(engine)
        .read(
            now=NOW,
            period=FounderTunnelPeriod.TODAY,
            week_offset=0,
        )
        .current
    )

    assert current.churn_count == 0
    assert [item.model_dump() for item in current.mrr_by_currency] == [
        {"currency": "CHF", "minor_units": 15_900}
    ]


def test_current_projection_uses_filtered_sql_windows_for_postgresql() -> None:
    from signals.founder_api.commercial_tunnel import _current_projection_statement

    statement = _current_projection_statement(observed_at=NOW)
    sql = " ".join(
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    )

    assert sql.count("row_number() OVER") == 2
    assert "milestone IN ('PAID', 'CHURNED')" in sql
    assert "milestone = 'MRR_CHANGED'" in sql
    assert "mrr_known IS true" in sql
    assert "mrr_minor_units IS NOT NULL" in sql
    assert "currency IS NOT NULL" in sql
    assert "mrr_known IS false" not in sql
    assert "RETAINED_M2" not in sql
