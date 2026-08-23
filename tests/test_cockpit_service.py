from __future__ import annotations

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from test_conversion_attribution import NOW, create_account, prepared
from test_learning_metrics import _conversion_event, _provider_event

from signals.cockpit.contracts import CockpitWeek
from signals.cockpit.service import WeeklyCommercialCockpitService
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_conversion_event,
    acquisition_conversion_journey,
    acquisition_opportunity,
    acquisition_provider_event,
    acquisition_response_evaluation,
)


def _week(start: dt.datetime) -> CockpitWeek:
    local = start.astimezone(ZoneInfo("Europe/Zurich"))
    local_start = dt.datetime.combine(local.date(), dt.time(0), tzinfo=local.tzinfo)
    return CockpitWeek(week_start=local_start, week_end=local_start + dt.timedelta(days=7))


def _response(*, ref: str, response_ref: str, campaign: dict, member: dict, at: dt.datetime,
              classification: str, supersedes: str | None = None) -> dict:
    human = classification not in {"AUTO_REPLY", "OUT_OF_OFFICE"}
    hot = classification == "POSITIVE"
    return {
        "response_evaluation_id": ref,
        "response_ref": response_ref,
        "provider_event_ref": "5" * 64,
        "campaign_ref": campaign["campaign_ref"],
        "member_ref": member["member_ref"],
        "acquisition_opportunity_id": member["acquisition_opportunity_id"],
        "contact_ref": member["contact_ref"],
        "input_source": "WEBHOOK_V2",
        "source_fingerprint": "8" * 64,
        "resolver_version": "response-email-resolution-v1",
        "normalizer_version": "response-content-normalizer-v1",
        "safety_version": "response-safety-rules-v1",
        "taxonomy_version": "response-taxonomy-v1",
        "classifier_version": f"synthetic-{ref[:2]}",
        "human_response_confirmed": human,
        "classification": classification,
        "confidence": "0.9000",
        "reason_codes": [f"SYNTHETIC_{classification}"],
        "hot_lead": hot,
        "review_required": hot,
        "next_action": "request_human_review" if hot else None,
        "estimated_cost": "0",
        "processing_state": "FINALIZED",
        "attempt": 1,
        "disposition": "CLASSIFIED",
        "supersedes_response_evaluation_id": supersedes,
        "reclassification_reason": "NEW_CLASSIFIER" if supersedes else None,
        "received_at": at,
        "evaluated_at": at,
        "finalized_at": at,
        "created_at": at,
        "updated_at": at,
    }


def test_weekly_report_uses_one_step1_cohort_and_as_of_authoritative_truth(tmp_path) -> None:
    engine, attribution, token, _ = prepared(tmp_path)
    week = _week(dt.datetime(2026, 8, 24, tzinfo=dt.UTC))
    sent_at = week.week_start.astimezone(dt.UTC) + dt.timedelta(hours=10)
    click = attribution.record_click(token.raw_token, at=sent_at + dt.timedelta(hours=1))
    with engine.begin() as connection:
        campaign = dict(connection.execute(sa.select(acquisition_campaign)).mappings().one())
        member = dict(connection.execute(sa.select(acquisition_campaign_member)).mappings().one())
        connection.execute(
            sa.insert(acquisition_provider_event),
            [
                _provider_event(ref="1" * 64, campaign=campaign, member=member,
                                event_type="email_sent", occurred_at=sent_at, step=1),
                _provider_event(ref="2" * 64, campaign=campaign, member=member,
                                event_type="email_sent", occurred_at=sent_at, step=1),
                _provider_event(ref="3" * 64, campaign=campaign, member=member,
                                event_type="email_sent", occurred_at=sent_at, step=2),
                _provider_event(ref="4" * 64, campaign=campaign, member=member,
                                event_type="lead_interested", occurred_at=sent_at, step=None),
                _provider_event(ref="5" * 64, campaign=campaign, member=member,
                                event_type="reply_received", occurred_at=sent_at, step=1),
                _provider_event(ref="6" * 64, campaign=campaign, member=member,
                                event_type="email_bounced", occurred_at=week.week_end, step=1),
            ],
        )
        first_eval = "7" * 64
        connection.execute(
            sa.insert(acquisition_response_evaluation),
            [
                _response(ref=first_eval, response_ref="9" * 64, campaign=campaign,
                          member=member, at=sent_at, classification="NEGATIVE"),
                _response(ref="a" * 64, response_ref="9" * 64, campaign=campaign,
                          member=member, at=sent_at + dt.timedelta(minutes=1),
                          classification="POSITIVE", supersedes=first_eval),
            ],
        )
        account_specs = (
            ("a", "chf", 9_900, "b", "d", "f"),
            ("b", "eur", 4_900, "c", "e", "0"),
            ("c", None, None, "1", "2", "3"),
        )
        for suffix, currency, mrr, activated_ref, paid_ref, mrr_ref in account_specs:
            account_id = create_account(connection, suffix=f"cockpit-{suffix}", now=sent_at)
            attribution.bind_signup_in_transaction(
                connection, account_id=account_id, raw_token=token.raw_token,
                at=sent_at + dt.timedelta(hours=2),
            )
            journey = dict(
                connection.execute(
                    sa.select(acquisition_conversion_journey).where(
                        acquisition_conversion_journey.c.account_id == account_id
                    )
                ).mappings().one()
            )
            events = [
                _conversion_event(ref=activated_ref * 64,
                                  milestone="ACTIVATED", journey=journey,
                                  occurred_at=sent_at + dt.timedelta(days=1)),
                _conversion_event(ref=paid_ref * 64,
                                  milestone="PAID", journey=journey,
                                  occurred_at=sent_at + dt.timedelta(days=2)),
                _conversion_event(ref=mrr_ref * 64,
                                  milestone="MRR_CHANGED", journey=journey,
                                  occurred_at=sent_at + dt.timedelta(days=2), mrr=mrr),
            ]
            events[-1]["currency"] = currency
            if mrr is None:
                events[-1]["reason_code"] = "MRR_UNKNOWN_PLAN"
            for event in events:
                connection.execute(sa.insert(acquisition_conversion_event).values(**event))
        # A later churn must not restate this completed report.
        journey = dict(
            connection.execute(
                sa.select(acquisition_conversion_journey).order_by(
                    acquisition_conversion_journey.c.account_id
                )
            ).mappings().first()
        )
        connection.execute(
            sa.insert(acquisition_conversion_event).values(
                **_conversion_event(ref="8" * 64, milestone="CHURNED", journey=journey,
                                    occurred_at=week.week_end + dt.timedelta(seconds=1))
            )
        )
        before = {
            table.name: connection.scalar(sa.select(sa.func.count()).select_from(table))
            for table in (
                acquisition_campaign,
                acquisition_campaign_member,
                acquisition_provider_event,
                acquisition_response_evaluation,
                acquisition_conversion_journey,
                acquisition_conversion_event,
            )
        }

    report = WeeklyCommercialCockpitService(engine).generate(week=week)
    replay = WeeklyCommercialCockpitService(engine).generate(week=week)

    assert report == replay
    assert report.report_ref == replay.report_ref
    assert report.funnel.delivered_proxy_count == 1  # bounce exactly at cutoff is excluded
    assert report.funnel.positive_reply_count == 1
    assert report.funnel.click_count == 1
    assert report.funnel.activated_account_count == 3
    assert report.funnel.paid_account_count == 3
    assert [(money.currency, money.minor_units) for money in report.funnel.mrr_by_currency] == [
        ("CHF", 9_900),
        ("EUR", 4_900),
    ]
    assert report.funnel.churn_count == 0
    assert report.data_quality.unknown_mrr_journey_count == 1
    assert len(report.analytical_rows) == 1
    row = report.analytical_rows[0]
    assert row.click_count == 1
    assert row.activated_account_count == 3
    assert row.activation_rate == Decimal("3.000000")
    assert click.conversion_event_ref
    rendered = report.model_dump_json()
    for marker in (
        "conversion-cockpit-a@example.invalid",
        "conversion-cockpit-b@example.invalid",
        "Synthetic Account",
        "lead_interested",
    ):
        assert marker not in rendered
    with engine.connect() as connection:
        after = {
            table.name: connection.scalar(sa.select(sa.func.count()).select_from(table))
            for table in (
                acquisition_campaign,
                acquisition_campaign_member,
                acquisition_provider_event,
                acquisition_response_evaluation,
                acquisition_conversion_journey,
                acquisition_conversion_event,
            )
        }
    assert after == before


def test_bounce_proxy_unknown_mrr_and_empty_week_are_truthful(tmp_path) -> None:
    engine, _, _, _ = prepared(tmp_path)
    week = _week(dt.datetime(2026, 8, 24, tzinfo=dt.UTC))
    sent_at = week.week_start.astimezone(dt.UTC) + dt.timedelta(hours=10)
    with engine.begin() as connection:
        campaign = dict(connection.execute(sa.select(acquisition_campaign)).mappings().one())
        member = dict(connection.execute(sa.select(acquisition_campaign_member)).mappings().one())
        connection.execute(
            sa.insert(acquisition_provider_event),
            [
                _provider_event(ref="1" * 64, campaign=campaign, member=member,
                                event_type="email_sent", occurred_at=sent_at, step=1),
                _provider_event(ref="2" * 64, campaign=campaign, member=member,
                                event_type="email_bounced", occurred_at=sent_at, step=1),
            ],
        )
        connection.execute(
            sa.update(acquisition_opportunity).values(signal_ref="unresolved-source")
        )

    report = WeeklyCommercialCockpitService(engine).generate(week=week)
    assert report.funnel.delivered_proxy_count == 0
    assert report.analytical_rows[0].sector_ref == "UNRESOLVED"
    assert report.data_quality.unresolved_sector_count == 1
    assert report.analytical_rows[0].positive_reply_rate is None

    empty = WeeklyCommercialCockpitService(engine).generate(
        week=_week(dt.datetime(2026, 9, 7, tzinfo=dt.UTC))
    )
    assert empty.funnel.delivered_proxy_count == 0
    assert empty.funnel.mrr_by_currency == ()
    assert empty.analytical_rows == ()


def test_m2_efficiency_uses_paid_age_known_mrr_and_excludes_churn(tmp_path) -> None:
    engine, attribution, token, _ = prepared(tmp_path)
    sent_at = NOW + dt.timedelta(hours=1)
    attribution.record_click(token.raw_token, at=sent_at)
    cutoff_week = _week(dt.datetime(2026, 11, 2, tzinfo=dt.UTC))
    with engine.begin() as connection:
        campaign = dict(connection.execute(sa.select(acquisition_campaign)).mappings().one())
        member = dict(connection.execute(sa.select(acquisition_campaign_member)).mappings().one())
        connection.execute(sa.insert(acquisition_provider_event).values(
            **_provider_event(ref="1" * 64, campaign=campaign, member=member,
                              event_type="email_sent", occurred_at=sent_at, step=1)
        ))
        account_id = create_account(connection, suffix="cockpit-m2", now=sent_at)
        attribution.bind_signup_in_transaction(
            connection, account_id=account_id, raw_token=token.raw_token, at=sent_at
        )
        journey = dict(connection.execute(sa.select(acquisition_conversion_journey)).mappings().one())
        events = [
            _conversion_event(ref="2" * 64, milestone="PAID", journey=journey,
                              occurred_at=sent_at),
            _conversion_event(ref="3" * 64, milestone="MRR_CHANGED", journey=journey,
                              occurred_at=sent_at, mrr=10_000),
            _conversion_event(ref="4" * 64, milestone="RETAINED_M2", journey=journey,
                              occurred_at=sent_at + dt.timedelta(days=60)),
        ]
        connection.execute(sa.insert(acquisition_conversion_event), events)

    immature = WeeklyCommercialCockpitService(engine).generate(
        week=_week(dt.datetime(2026, 9, 7, tzinfo=dt.UTC))
    )
    assert immature.wedge_m2_efficiency[0].data_status == "INSUFFICIENT_M2_EVIDENCE"

    ready = WeeklyCommercialCockpitService(engine).generate(week=cutoff_week)
    m2 = ready.wedge_m2_efficiency[0]
    assert m2.data_status == "READY"
    assert m2.m2_eligible_delivered_proxy_count == 1
    assert m2.retained_m2_accounts == 1
    assert m2.retained_m2_mrr_per_1000_delivered == Decimal("10000000.000000")

    with engine.begin() as connection:
        journey = dict(connection.execute(sa.select(acquisition_conversion_journey)).mappings().one())
        connection.execute(sa.insert(acquisition_conversion_event).values(
            **_conversion_event(ref="5" * 64, milestone="CHURNED", journey=journey,
                                occurred_at=cutoff_week.week_end - dt.timedelta(seconds=1))
        ))
    churned = WeeklyCommercialCockpitService(engine).generate(week=cutoff_week)
    m2 = churned.wedge_m2_efficiency[0]
    assert m2.retained_m2_accounts == 0
    assert m2.retained_m2_mrr_minor_units == 0
