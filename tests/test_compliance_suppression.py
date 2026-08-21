from __future__ import annotations

import datetime as dt

import pytest

from signals.compliance.suppression import (
    SUPPRESSION_SCOPE,
    SuppressionIdentityKeyring,
    SuppressionIdentityUnavailable,
    minimum_retention_until,
    normalize_business_email,
)

NOW = dt.datetime(2026, 8, 21, 9, tzinfo=dt.UTC)


def test_email_identity_is_normalized_and_domain_separated_hmac() -> None:
    keyring = SuppressionIdentityKeyring(
        current_key_version="key-v2",
        keys={"key-v1": b"old-test-key", "key-v2": b"current-test-key"},
    )

    assert normalize_business_email(" Sales@Example.COM ") == "sales@example.com"
    identities = keyring.identities_for_email(" Sales@Example.COM ")
    assert tuple(identities) == ("key-v1", "key-v2")
    assert all(len(value) == 64 for value in identities.values())
    assert identities["key-v1"] != identities["key-v2"]
    assert "sales@example.com" not in repr(identities)
    assert SUPPRESSION_SCOPE == "KIVOU_ACQUISITION_EMAIL"
    assert "old-test-key" not in repr(keyring)
    assert "current-test-key" not in repr(keyring)


@pytest.mark.parametrize("email", ("", "not-an-email", "a@", "a b@example.com"))
def test_unusable_email_fails_closed(email: str) -> None:
    with pytest.raises(SuppressionIdentityUnavailable):
        normalize_business_email(email)


def test_key_rotation_retains_old_matching_identity() -> None:
    old = SuppressionIdentityKeyring(current_key_version="key-v1", keys={"key-v1": b"old-test-key"})
    rotated = SuppressionIdentityKeyring(
        current_key_version="key-v2",
        keys={"key-v1": b"old-test-key", "key-v2": b"new-test-key"},
    )

    old_identity = old.identities_for_email("person@example.com")["key-v1"]

    assert rotated.identities_for_email("PERSON@example.com")["key-v1"] == old_identity
    with pytest.raises(SuppressionIdentityUnavailable):
        rotated.require_versions_covered(("key-v1", "retired-without-key"))


def test_minimum_retention_is_three_calendar_years_without_auto_expiry() -> None:
    assert minimum_retention_until(NOW) == NOW.replace(year=2029)
    leap = dt.datetime(2024, 2, 29, 12, tzinfo=dt.UTC)
    assert minimum_retention_until(leap) == dt.datetime(2027, 2, 28, 12, tzinfo=dt.UTC)
