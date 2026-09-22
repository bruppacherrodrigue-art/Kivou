"""Pure B1 export preview: no provider transport or personal report rows."""

import json

import pytest

from signals.acquisition_programs.export_preview import (
    ExportLead,
    build_export_preview,
    validate_ready_payload,
)

KEY = b"synthetic-preview-hmac-key-32-bytes"


def lead(email: str | None, *, sector: str = "Agences",
         status: str = "READY_THEORETICAL", domain: str | None = "agency.example") -> ExportLead:
    return ExportLead(status=status, email=email, company_domain=domain,
                      sector=sector, country_code="FR")


def test_preview_is_aggregate_deterministic_and_rechecks_suppression() -> None:
    records = [
        lead("  Alice@Agency.Example  "),
        lead("alice@agency.example", domain="AGENCY.EXAMPLE."),
        lead("bob@consulting.example", sector="Conseil", domain="consulting.example"),
        lead("carol@recruiting.example", sector="Recrutement", domain="recruiting.example"),
        lead(None, status="HOLD", domain=None),
        lead(None, status="NO_SEND", domain=None),
    ]
    checked: list[str] = []

    def suppressed(email: str) -> bool:
        checked.append(email)
        return email == "bob@consulting.example"

    first = build_export_preview(records, is_suppressed=suppressed, hmac_key=KEY,
                                 campaign_ref="milomail-france-b1")
    assert checked == ["alice@agency.example", "bob@consulting.example",
                       "carol@recruiting.example"]
    assert first.segment_counts == {
        "France Agences": 1, "France Conseil": 0, "France Recrutement": 1,
    }
    assert first.input_count == 6
    assert first.eligible_count == 2
    assert first.excluded_hold == 1
    assert first.excluded_no_send == 1
    assert first.suppressed_count == 1
    assert first.duplicates_dropped == 1
    assert first.diff.added == 2
    assert first.diff.removed == first.diff.unchanged == 0
    assert first.receipt.mode == "DRY_RUN"
    assert first.receipt.provider_calls == 0
    assert first.receipt.mutations_allowed is False
    second = build_export_preview(reversed(records), is_suppressed=suppressed,
                                  hmac_key=KEY, campaign_ref="milomail-france-b1")
    assert second.receipt.idempotency_hash == first.receipt.idempotency_hash
    assert second.diff == first.diff
    public = json.dumps(first.model_dump(mode="json"), sort_keys=True)
    assert not any(value in public for value in (
        "alice@", "bob@", "carol@", "agency.example", "consulting.example",
    ))


def test_diff_counts_add_remove_and_unchanged_without_exposing_members() -> None:
    previous = [lead("a@agency.example"),
                lead("b@consulting.example", sector="Conseil", domain="consulting.example")]
    current = [lead("a@agency.example"),
               lead("c@recruiting.example", sector="Recrutement", domain="recruiting.example")]
    result = build_export_preview(current, previous=previous,
                                  is_suppressed=lambda _: False, hmac_key=KEY,
                                  campaign_ref="milomail-france-b1")
    assert (result.diff.added, result.diff.removed, result.diff.unchanged) == (1, 1, 1)
    assert result.receipt.previous_hash is not None
    again = build_export_preview(current, previous=current,
                                 is_suppressed=lambda _: False, hmac_key=KEY,
                                 campaign_ref="milomail-france-b1")
    assert (again.diff.added, again.diff.removed, again.diff.unchanged) == (0, 0, 2)
    assert again.receipt.previous_hash == again.receipt.idempotency_hash


def test_email_domain_is_canonical_for_deduplication() -> None:
    result = build_export_preview(
        [lead("alice@agency.example."), lead("ALICE@AGENCY.EXAMPLE")],
        is_suppressed=lambda _: False, hmac_key=KEY,
        campaign_ref="milomail-france-b1",
    )
    assert result.eligible_count == 1
    assert result.duplicates_dropped == 1


@pytest.mark.parametrize("record", [
    lead("a@agency.example", status="HOLD"),
    lead("a@agency.example", status="NO_SEND"),
    lead("a@other.example"),
    lead("bad email"),
    lead("a@agency.example", sector="Other"),
    ExportLead(status="READY_THEORETICAL", email="a@agency.example",
               company_domain="agency.example", sector="Agences", country_code="CH"),
])
def test_payload_validation_fails_closed_with_generic_error(record: ExportLead) -> None:
    with pytest.raises(ValueError) as error:
        validate_ready_payload(record)
    assert "@" not in str(error.value)


def test_conflicting_duplicate_and_unavailable_suppression_fail_closed() -> None:
    with pytest.raises(ValueError, match="conflicting duplicate"):
        build_export_preview(
            [lead("same@agency.example"),
             lead("same@agency.example", sector="Conseil")],
            is_suppressed=lambda _: False, hmac_key=KEY,
            campaign_ref="milomail-france-b1",
        )
    with pytest.raises(ValueError, match="suppression recheck"):
        build_export_preview([lead("same@agency.example")],
                             is_suppressed=lambda _: None,  # type: ignore[return-value]
                             hmac_key=KEY, campaign_ref="milomail-france-b1")


def test_hmac_key_and_campaign_scope_are_required() -> None:
    record = [lead("a@agency.example")]
    with pytest.raises(ValueError, match="HMAC key"):
        build_export_preview(record, is_suppressed=lambda _: False,
                             hmac_key=b"short", campaign_ref="milomail-france-b1")
    first = build_export_preview(record, is_suppressed=lambda _: False, hmac_key=KEY,
                                 campaign_ref="milomail-france-b1")
    other = build_export_preview(record, is_suppressed=lambda _: False, hmac_key=KEY,
                                 campaign_ref="milomail-france-b2")
    assert first.receipt.idempotency_hash != other.receipt.idempotency_hash
