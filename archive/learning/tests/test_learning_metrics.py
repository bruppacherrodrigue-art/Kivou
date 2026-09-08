from __future__ import annotations

import datetime as dt

import sqlalchemy as sa
from test_conversion_attribution import NOW, create_account, prepared

from signals.learning.contracts import make_learning_window
from signals.learning.metrics import RepositoryLearningMetricsSource
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_conversion_event,
    acquisition_conversion_journey,
    acquisition_provider_event,
    acquisition_response_evaluation,
    policy_evaluation,
)


def _provider_event(
    *,
    ref: str,
    campaign: dict,
    member: dict,
    event_type: str,
    occurred_at: dt.datetime,
    step: int | None,
) -> dict:
    return {
        "provider_event_ref": ref,
        "canonical_event_fingerprint": ref,
        "fingerprint_version": "provider-event-fingerprint-v2",
        "fingerprint_key_version": "synthetic-v1",
        "provider_event_type": event_type,
        "provider_workspace_ref": campaign["provider_workspace_ref"],
        "provider_campaign_id": "campaign-synthetic",
        "provider_lead_id": member["provider_lead_id"],
        "campaign_ref": campaign["campaign_ref"],
        "member_ref": member["member_ref"],
        "acquisition_opportunity_id": member["acquisition_opportunity_id"],
        "contact_ref": member["contact_ref"],
        "step": step,
        "occurred_at": occurred_at,
        "received_at": occurred_at,
        "mailbox_ref": member["mailbox_ref"],
        "transport_status": "sent",
        "resolution_state": "PROCESSED",
    }


def _conversion_event(
    *,
    ref: str,
    milestone: str,
    journey: dict,
    occurred_at: dt.datetime,
    mrr: int | None = None,
) -> dict:
    return {
        "conversion_event_ref": ref,
        "journey_ref": journey["journey_ref"],
        "milestone": milestone,
        "event_version": "conversion-event-v1",
        "event_fingerprint": ref,
        "trigger_ref_type": "SYNTHETIC",
        "trigger_ref": ref,
        "account_id": journey["account_id"],
        "campaign_ref": journey["campaign_ref"],
        "member_ref": journey["member_ref"],
        "acquisition_opportunity_id": journey["acquisition_opportunity_id"],
        "mrr_known": mrr is not None if milestone == "MRR_CHANGED" else None,
        "mrr_minor_units": mrr,
        "currency": "chf" if mrr is not None else None,
        "occurred_at": occurred_at,
        "observed_at": occurred_at,
        "recorded_at": occurred_at,
    }


def test_repository_metrics_use_authoritative_sources_without_double_counting(tmp_path) -> None:
    engine, attribution, token, _ = prepared(tmp_path)
    sent_at = NOW + dt.timedelta(hours=1)
    attribution.record_click(token.raw_token, at=sent_at + dt.timedelta(hours=1))
    with engine.begin() as connection:
        campaign = dict(connection.execute(sa.select(acquisition_campaign)).mappings().one())
        member = dict(connection.execute(sa.select(acquisition_campaign_member)).mappings().one())
        connection.execute(
            sa.update(policy_evaluation)
            .where(policy_evaluation.c.evaluation_id == member["policy_evaluation_id"])
            .values(estimated_cost="1.25", currency="CHF")
        )
        connection.execute(
            sa.insert(acquisition_provider_event),
            [
                _provider_event(
                    ref="1" * 64,
                    campaign=campaign,
                    member=member,
                    event_type="email_sent",
                    occurred_at=sent_at,
                    step=1,
                ),
                _provider_event(
                    ref="2" * 64,
                    campaign=campaign,
                    member=member,
                    event_type="email_sent",
                    occurred_at=sent_at + dt.timedelta(days=4),
                    step=2,
                ),
                _provider_event(
                    ref="3" * 64,
                    campaign=campaign,
                    member=member,
                    event_type="email_bounced",
                    occurred_at=sent_at + dt.timedelta(minutes=1),
                    step=1,
                ),
                _provider_event(
                    ref="4" * 64,
                    campaign=campaign,
                    member=member,
                    event_type="lead_interested",
                    occurred_at=sent_at + dt.timedelta(minutes=2),
                    step=None,
                ),
                _provider_event(
                    ref="5" * 64,
                    campaign=campaign,
                    member=member,
                    event_type="reply_received",
                    occurred_at=sent_at + dt.timedelta(minutes=3),
                    step=1,
                ),
            ],
        )
        connection.execute(
            sa.insert(acquisition_response_evaluation).values(
                response_evaluation_id="6" * 64,
                response_ref="7" * 64,
                provider_event_ref="5" * 64,
                campaign_ref=campaign["campaign_ref"],
                member_ref=member["member_ref"],
                acquisition_opportunity_id=member["acquisition_opportunity_id"],
                contact_ref=member["contact_ref"],
                input_source="WEBHOOK_V2",
                source_fingerprint="8" * 64,
                resolver_version="response-email-resolution-v1",
                normalizer_version="response-content-normalizer-v1",
                safety_version="response-safety-rules-v1",
                taxonomy_version="response-taxonomy-v1",
                classifier_version="synthetic-v1",
                human_response_confirmed=True,
                classification="POSITIVE",
                confidence="0.9000",
                reason_codes=["EXPLICIT_COMMERCIAL_INTEREST"],
                hot_lead=True,
                review_required=True,
                next_action="request_human_review",
                policy_evaluation_id=member["policy_evaluation_id"],
                estimated_cost="0",
                actual_cost="0.25",
                processing_state="FINALIZED",
                attempt=1,
                disposition="CLASSIFIED",
                received_at=sent_at,
                evaluated_at=sent_at,
                finalized_at=sent_at,
                created_at=sent_at,
                updated_at=sent_at,
            )
        )
        account_a = create_account(connection, suffix="learning-a", now=sent_at)
        account_b = create_account(connection, suffix="learning-b", now=sent_at)
        assert attribution.bind_signup_in_transaction(
            connection,
            account_id=account_a,
            raw_token=token.raw_token,
            at=sent_at + dt.timedelta(days=1),
        )
        assert attribution.bind_signup_in_transaction(
            connection,
            account_id=account_b,
            raw_token=token.raw_token,
            at=sent_at + dt.timedelta(days=2),
        )

    window = make_learning_window(
        window_end=sent_at + dt.timedelta(days=60),
        captured_at=sent_at + dt.timedelta(days=60),
    )
    metrics = RepositoryLearningMetricsSource(engine).capture(window=window)

    assert len(metrics) == 1
    cell = metrics[0]
    assert cell.contacted_count == 1
    assert cell.bounce_count == 1
    assert cell.delivery_proxy_count == 0
    assert cell.positive_reply_count == 1
    assert cell.signup_count == 2
    assert cell.known_variable_cost_minor_units == 150
    assert cell.cost_currency == "CHF"
    assert cell.cost_complete is False
    assert "PROVIDER_COST_UNAVAILABLE" in cell.missing_cost_reason_codes


def test_churn_removes_retained_mrr_and_m1_m2_use_paid_age(tmp_path) -> None:
    engine, attribution, token, _ = prepared(tmp_path)
    sent_at = NOW + dt.timedelta(hours=1)
    attribution.record_click(token.raw_token, at=sent_at)
    with engine.begin() as connection:
        campaign = dict(connection.execute(sa.select(acquisition_campaign)).mappings().one())
        member = dict(connection.execute(sa.select(acquisition_campaign_member)).mappings().one())
        connection.execute(
            sa.insert(acquisition_provider_event).values(
                **_provider_event(
                    ref="a" * 64,
                    campaign=campaign,
                    member=member,
                    event_type="email_sent",
                    occurred_at=sent_at,
                    step=1,
                )
            )
        )
        account_id = create_account(connection, suffix="learning-mrr", now=sent_at)
        attribution.bind_signup_in_transaction(
            connection,
            account_id=account_id,
            raw_token=token.raw_token,
            at=sent_at,
        )
        journey = dict(
            connection.execute(sa.select(acquisition_conversion_journey)).mappings().one()
        )
        connection.execute(
            sa.insert(acquisition_conversion_event),
            [
                _conversion_event(
                    ref="b" * 64,
                    milestone="PAID",
                    journey=journey,
                    occurred_at=sent_at,
                ),
                _conversion_event(
                    ref="c" * 64,
                    milestone="MRR_CHANGED",
                    journey=journey,
                    occurred_at=sent_at,
                    mrr=9_900,
                ),
                _conversion_event(
                    ref="d" * 64,
                    milestone="RETAINED_M1",
                    journey=journey,
                    occurred_at=sent_at + dt.timedelta(days=32),
                ),
                _conversion_event(
                    ref="e" * 64,
                    milestone="RETAINED_M2",
                    journey=journey,
                    occurred_at=sent_at + dt.timedelta(days=60, seconds=-2),
                ),
                _conversion_event(
                    ref="f" * 64,
                    milestone="CHURNED",
                    journey=journey,
                    occurred_at=sent_at + dt.timedelta(days=60, seconds=-1),
                ),
            ],
        )

    window = make_learning_window(
        window_end=sent_at + dt.timedelta(days=60),
        captured_at=sent_at + dt.timedelta(days=60),
    )
    cell = RepositoryLearningMetricsSource(engine).capture(window=window)[0]

    assert cell.paid_count == 1
    assert cell.m1_eligible_count == 1
    assert cell.retained_m1_count == 1
    assert cell.m2_eligible_count == 1
    assert cell.retained_m2_count == 1
    assert cell.churn_count == 1
    assert cell.known_mrr_minor_units == 0
    assert cell.retained_mrr_minor_units == 0
    assert cell.mrr_complete is False
