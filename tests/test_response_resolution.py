from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from signals.campaigns.instantly import InstantlyErrorCode, InstantlyProviderError
from signals.responses.contracts import ContentFingerprintKeyring, ResponseReasonCode
from signals.responses.instantly_email import (
    InstantlyEmail,
    InstantlyEmailPage,
    ListEmailsQuery,
)
from signals.responses.service import (
    EmailResolutionContext,
    EmailResolutionStatus,
    EmailResponseResolver,
)

FIXTURE = Path(__file__).parent / "fixtures" / "instantly_v2_email_response_2026-08-22.json"
VALUES = json.loads(FIXTURE.read_text())
EVENT_AT = dt.datetime(2026, 8, 22, 9, 59, tzinfo=dt.UTC)


class FakeReader:
    def __init__(self, items=(), *, full=None, error=None):
        self.items = tuple(items)
        self.full = full
        self.error = error
        self.list_queries: list[ListEmailsQuery] = []
        self.get_ids: list[str] = []

    def list_emails(self, query):
        self.list_queries.append(query)
        if self.error is not None:
            raise self.error
        return InstantlyEmailPage(items=self.items, next_starting_after=None)

    def get_email(self, provider_email_id):
        self.get_ids.append(provider_email_id)
        if self.full is None:
            raise AssertionError("unexpected Email GET")
        return self.full


def _email(**updates) -> InstantlyEmail:
    values = dict(VALUES["get"])
    values.update(updates)
    return InstantlyEmail.model_validate(values)


def _context(**updates) -> EmailResolutionContext:
    values = {
        "provider_workspace_ref": "01a028e4-5069-7b56-ae56-b7e52c2329d7",
        "provider_campaign_id": "01a028e4-5069-7b56-ae56-b7e622c7fbf1",
        "provider_lead_id": "01a028e4-5069-7b56-ae56-b7e9cb32ae4c",
        "lead_email_transient": "buyer@example.invalid",
        "email_account_transient": "sender@example.invalid",
        "provider_event_type": "reply_received",
        "provider_event_timestamp": EVENT_AT,
        "webhook_email_id_transport_only": "reply-to-uuid-must-not-be-used",
    }
    values.update(updates)
    return EmailResolutionContext.model_validate(values)


def _resolver(reader) -> EmailResponseResolver:
    return EmailResponseResolver(
        reader,
        source_keyring=ContentFingerprintKeyring(
            current_key_version="response-source-key-v1",
            keys={"response-source-key-v1": b"synthetic-response-source-key"},
        ),
    )


def test_zero_candidates_retry_then_exhaust_to_ambiguous_review() -> None:
    reader = FakeReader()
    resolver = _resolver(reader)

    first = resolver.resolve(_context(), attempt=1, now=EVENT_AT)
    exhausted = resolver.resolve(
        _context(), attempt=3, now=EVENT_AT + dt.timedelta(minutes=15)
    )

    assert first.status is EmailResolutionStatus.RETRYABLE
    assert first.retry_at == EVENT_AT + dt.timedelta(minutes=5)
    assert exhausted.status is EmailResolutionStatus.UNAVAILABLE
    assert exhausted.reason_code is ResponseReasonCode.RESPONSE_CONTENT_UNAVAILABLE
    assert exhausted.review_required is True
    assert len(reader.list_queries) == 2


def test_one_exact_candidate_is_read_and_fully_revalidated() -> None:
    candidate = _email()
    assert candidate.lead == "buyer@example.invalid"
    assert candidate.eaccount == "sender@example.invalid"
    assert candidate.from_address_email == "sender@example.invalid"
    assert candidate.from_address_email != candidate.lead
    reader = FakeReader((candidate,), full=candidate)
    result = _resolver(reader).resolve(_context(), attempt=1, now=EVENT_AT)

    assert result.status is EmailResolutionStatus.RESOLVED
    assert result.email is not None
    assert result.email.id == candidate.id
    assert result.source_fingerprint is not None
    assert len(result.source_fingerprint) == 64
    assert reader.get_ids == [candidate.id]
    assert reader.list_queries[0].min_timestamp_created == EVENT_AT - dt.timedelta(minutes=5)
    assert reader.list_queries[0].max_timestamp_created == EVENT_AT + dt.timedelta(minutes=15)
    assert "reply-to-uuid-must-not-be-used" not in reader.get_ids


def test_multiple_candidates_fail_closed_without_nearest_timestamp_selection() -> None:
    first = _email()
    second = _email(
        id="01a028e4-5069-7b56-ae56-b7e4352c53fb",
        timestamp_created="2026-08-22T09:54:07.000Z",
    )
    reader = FakeReader((first, second), full=first)

    result = _resolver(reader).resolve(_context(), attempt=1, now=EVENT_AT)

    assert result.status is EmailResolutionStatus.AMBIGUOUS
    assert result.reason_code is ResponseReasonCode.RESPONSE_IDENTITY_AMBIGUOUS
    assert result.review_required is True
    assert reader.get_ids == []


@pytest.mark.parametrize(
    "updates",
    [
        {"organization_id": "01a028e4-5069-7b56-ae56-b7e52c2329d8"},
        {"campaign_id": "01a028e4-5069-7b56-ae56-b7e622c7fbf2"},
        {"lead_id": "01a028e4-5069-7b56-ae56-b7e9cb32ae4d"},
        {"lead": "other@example.invalid"},
        {"eaccount": "other-sender@example.invalid"},
        {"timestamp_created": "2026-08-22T10:20:00Z"},
        {"is_auto_reply": 1},
    ],
)
def test_candidate_binding_mismatch_fails_closed(updates) -> None:
    candidate = _email(**updates)
    reader = FakeReader((candidate,), full=candidate)

    result = _resolver(reader).resolve(_context(), attempt=1, now=EVENT_AT)

    assert result.status is EmailResolutionStatus.AMBIGUOUS
    assert result.reason_code is ResponseReasonCode.RESPONSE_IDENTITY_AMBIGUOUS


def test_from_address_email_is_ignored_for_prospect_candidate_selection() -> None:
    candidate = _email(from_address_email="alternate-sender@example.invalid")
    reader = FakeReader((candidate,), full=candidate)

    result = _resolver(reader).resolve(_context(), attempt=1, now=EVENT_AT)

    assert result.status is EmailResolutionStatus.RESOLVED
    assert result.email is not None
    assert result.email.lead == "buyer@example.invalid"


def test_from_address_email_is_ignored_during_exact_get_revalidation() -> None:
    candidate = _email(from_address_email="sender@example.invalid")
    readback = _email(from_address_email="provider-enriched-sender@example.invalid")
    reader = FakeReader((candidate,), full=readback)

    result = _resolver(reader).resolve(_context(), attempt=1, now=EVENT_AT)

    assert result.status is EmailResolutionStatus.RESOLVED
    assert result.email == readback


def test_auto_reply_event_requires_auto_reply_candidate() -> None:
    auto = _email(is_auto_reply=1)
    reader = FakeReader((auto,), full=auto)

    result = _resolver(reader).resolve(
        _context(provider_event_type="auto_reply_received"), attempt=1, now=EVENT_AT
    )
    assert result.status is EmailResolutionStatus.RESOLVED


def test_timestamp_email_is_not_selection_authority() -> None:
    manipulated = _email(timestamp_email="2030-01-01T00:00:00Z")
    reader = FakeReader((manipulated,), full=manipulated)

    result = _resolver(reader).resolve(_context(), attempt=1, now=EVENT_AT)

    assert result.status is EmailResolutionStatus.RESOLVED


def test_provider_429_is_bounded_retry_not_an_uncontrolled_loop() -> None:
    reader = FakeReader(
        error=InstantlyProviderError(
            InstantlyErrorCode.RATE_LIMITED,
            retry_after_seconds=17,
        )
    )

    result = _resolver(reader).resolve(_context(), attempt=1, now=EVENT_AT)

    assert result.status is EmailResolutionStatus.RETRYABLE
    assert result.reason_code is ResponseReasonCode.PROVIDER_RATE_LIMITED
    assert result.retry_at == EVENT_AT + dt.timedelta(seconds=17)
    assert len(reader.list_queries) == 1


def test_full_get_record_is_revalidated_not_only_list_candidate() -> None:
    candidate = _email()
    conflicting_full = _email(eaccount="other-sender@example.invalid")
    reader = FakeReader((candidate,), full=conflicting_full)

    result = _resolver(reader).resolve(_context(), attempt=1, now=EVENT_AT)

    assert result.status is EmailResolutionStatus.AMBIGUOUS
    assert result.reason_code is ResponseReasonCode.RESPONSE_IDENTITY_AMBIGUOUS


def test_resolution_never_exposes_or_fetches_attachment_and_unibox_urls() -> None:
    candidate = _email()
    reader = FakeReader((candidate,), full=candidate)

    result = _resolver(reader).resolve(_context(), attempt=1, now=EVENT_AT)

    assert result.status is EmailResolutionStatus.RESOLVED
    assert "attachments.example.invalid" not in repr(result)
    assert "unibox" not in repr(result).lower()
