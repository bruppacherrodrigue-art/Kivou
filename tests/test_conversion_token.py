from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from signals.conversion.contracts import AttributionTokenPayload, ConversionMilestone
from signals.conversion.token import (
    AttributionTokenExpired,
    AttributionTokenInvalid,
    AttributionTokenKeyring,
)

NOW = dt.datetime(2026, 8, 22, 9, tzinfo=dt.UTC)


def payload(**changes: object) -> AttributionTokenPayload:
    values: dict[str, object] = {
        "campaign_ref": "a" * 64,
        "member_ref": "b" * 64,
        "acquisition_opportunity_id": "c" * 64,
        "wedge": "construction-ch",
        "wedge_version": "wedge-v1",
        "country": "CH",
        "sector_ref": "sector-construction-v1",
        "need_ref": "energy-monitoring",
        "need_version": "need-graph-v1",
        "issued_at": NOW,
        "expires_at": NOW + dt.timedelta(days=34),
    }
    values.update(changes)
    return AttributionTokenPayload(**values)


def keyring() -> AttributionTokenKeyring:
    return AttributionTokenKeyring(
        current_key_version="attribution-key-v2",
        keys={
            "attribution-key-v1": b"old-synthetic-attribution-key",
            "attribution-key-v2": b"current-synthetic-attribution-key",
        },
    )


def test_token_round_trip_is_deterministic_and_contains_no_pii() -> None:
    first = keyring().issue(payload())
    second = keyring().issue(payload())

    assert first.raw_token == second.raw_token
    assert first.token_fingerprint == second.token_fingerprint
    assert first.token_version == "conversion-attribution-token-v1"
    assert first.key_version == "attribution-key-v2"
    assert "buyer@example" not in first.raw_token
    assert keyring().verify(first.raw_token, at=NOW).payload == payload().model_copy(
        update={"key_version": "attribution-key-v2"}
    )


def test_retained_key_version_verifies_an_old_token() -> None:
    old = AttributionTokenKeyring(
        current_key_version="attribution-key-v1",
        keys={"attribution-key-v1": b"old-synthetic-attribution-key"},
    ).issue(payload())

    verified = keyring().verify(old.raw_token, at=NOW)

    assert verified.key_version == "attribution-key-v1"
    assert verified.token_fingerprint == old.token_fingerprint


def test_tampered_and_expired_tokens_fail_closed() -> None:
    token = keyring().issue(payload())
    replacement = "A" if token.raw_token[-1] != "A" else "B"

    with pytest.raises(AttributionTokenInvalid):
        keyring().verify(token.raw_token[:-1] + replacement, at=NOW)
    with pytest.raises(AttributionTokenExpired):
        keyring().verify(token.raw_token, at=payload().expires_at)


def test_token_contract_rejects_naive_time_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        payload(issued_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        AttributionTokenPayload(**payload().model_dump(), email="buyer@example.invalid")


def test_conversion_milestone_vocabulary_is_closed() -> None:
    assert {item.value for item in ConversionMilestone} == {
        "CLICK",
        "SIGNUP",
        "ACTIVATED",
        "PAID",
        "MRR_CHANGED",
        "RETAINED_M1",
        "RETAINED_M2",
        "CHURNED",
    }
