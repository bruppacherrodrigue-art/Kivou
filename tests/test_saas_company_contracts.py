from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from signals.companies.contracts import (
    MAX_OFFICIAL_IDENTIFIERS,
    MAX_RELATED_SIGNALS,
    CompanyCoverage,
    CompanyFit,
    CompanyOfficialIdentifier,
    CompanyOfficialIdentity,
    CompanyProfile,
    CompanyRelatedSignal,
    CompanySignalEvent,
)

UTC = dt.UTC


def _profile(**overrides: object) -> CompanyProfile:
    values: dict[str, object] = {
        "company_key": "cmp_0123456789abcdefghijklmnop",
        "official_identity": CompanyOfficialIdentity(
            name="Entreprise SA",
            country="CH",
            address="Rue de la Gare 1, 1000 Lausanne",
            identifiers=(
                CompanyOfficialIdentifier(scheme="CHE-UID", value="CHE-123.456.789"),
            ),
            website_url="https://entreprise.example",
            observed_at=dt.datetime(2026, 8, 23, 12, tzinfo=UTC),
        ),
        "related_signals": (
            CompanyRelatedSignal(
                signal_id="sig_1",
                contract_title="Services de maintenance",
                amount=None,
                event=CompanySignalEvent(
                    status="recent_award",
                    date=dt.date(2026, 8, 20),
                    headline="Entreprise SA a remporté un marché",
                    why_now="Attribution récente",
                    award_date_note=None,
                ),
                plausible_needs=(),
                fit=CompanyFit(label="Besoin ciblé", reasons=("Besoin : maintenance",)),
            ),
        ),
        "coverage": CompanyCoverage(
            related_signals_complete=True,
            unavailable_fields=("official_address",),
        ),
    }
    values.update(overrides)
    return CompanyProfile.model_validate(values)


def test_contracts_are_frozen_closed_and_client_safe() -> None:
    profile = _profile()

    with pytest.raises(ValidationError):
        CompanyProfile.model_validate({**profile.model_dump(), "apollo_id": "secret"})
    with pytest.raises(ValidationError):
        CompanyRelatedSignal.model_validate(
            {**profile.related_signals[0].model_dump(), "contact_ref": "contact_1"}
        )
    with pytest.raises(ValidationError):
        profile.company_key = "cmp_changed"  # type: ignore[misc]

    serialized = profile.model_dump(mode="json")
    forbidden = {
        "apollo",
        "acquisition",
        "contact_ref",
        "supplier_ref",
        "score",
        "person",
        "email",
        "phone",
    }
    assert not any(term in repr(serialized).lower() for term in forbidden)
    assert serialized["official_identity"]["source"] == "public_notice"


def test_contracts_bound_client_arrays() -> None:
    identifiers = tuple(
        CompanyOfficialIdentifier(scheme="REG", value=str(index))
        for index in range(MAX_OFFICIAL_IDENTIFIERS + 1)
    )
    with pytest.raises(ValidationError):
        CompanyOfficialIdentity(
            name="Entreprise SA",
            identifiers=identifiers,
            observed_at=dt.datetime(2026, 8, 23, tzinfo=UTC),
        )

    signal = _profile().related_signals[0]
    with pytest.raises(ValidationError):
        _profile(related_signals=tuple(signal for _ in range(MAX_RELATED_SIGNALS + 1)))


def test_observation_requires_timezone_and_website_requires_https() -> None:
    with pytest.raises(ValidationError):
        CompanyOfficialIdentity(
            name="Entreprise SA",
            observed_at=dt.datetime(2026, 8, 23, 12, tzinfo=UTC).replace(tzinfo=None),
        )

    for unsafe in (
        "http://entreprise.example",
        "javascript:alert(1)",
        "https://user:password@entreprise.example",
        "https://localhost",
    ):
        with pytest.raises(ValidationError):
            CompanyOfficialIdentity(
                name="Entreprise SA",
                website_url=unsafe,
                observed_at=dt.datetime(2026, 8, 23, tzinfo=UTC),
            )


def test_absent_official_fields_remain_absent() -> None:
    identity = CompanyOfficialIdentity(
        name="Entreprise SA",
        observed_at=dt.datetime(2026, 8, 23, tzinfo=UTC),
    )

    assert identity.country is None
    assert identity.address is None
    assert identity.website_url is None
    assert identity.identifiers == ()
