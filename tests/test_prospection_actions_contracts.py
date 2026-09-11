from __future__ import annotations

import datetime as dt
from uuid import UUID

import pytest
from pydantic import ValidationError

from signals.prospection_actions.contracts import (
    CorrectionChanges,
    EmailVerificationStatus,
    ProspectTarget,
    RejectCommand,
    RejectionReason,
)

NOW = dt.datetime(2026, 9, 11, 8, tzinfo=dt.UTC)


def target_payload() -> dict[str, object]:
    return {
        "target_id": "51d144ca-d697-47e4-a4dc-ee86d0a9c8ac",
        "version": 1,
        "status": "pending_review",
        "company": {
            "siren": "123456789",
            "name": "Béton du Bourbonnais",
            "city": "Saint-Victor",
            "employees": 35,
            "family": "béton prêt à l'emploi",
        },
        "director": None,
        "email": {
            "address": "contact@beton-bourbonnais.fr",
            "source": "site",
            "verification_status": "mx_verified",
        },
        "signal": {
            "opportunity_key": "boamp-2026-42",
            "holder": "SAS Exemple",
            "subject": "Construction d'un groupe scolaire",
            "amount_minor_units": 1_250_000_00,
            "currency": "eur",
            "location": "Allier",
            "decision_date": "2026-09-10",
        },
        "mail": {
            "subject": "Construction d'un groupe scolaire",
            "text": "Bonjour,\n\nVous fournissez du béton prêt à l'emploi ?",
            "html": "<p>Bonjour,</p><p>Vous fournissez du béton prêt à l'emploi ?</p>",
            "attribution_url": "https://kivou.eu/a/kat1.key.token.signature",
            "unsubscribe_url": "https://kivou.eu/unsubscribe/token",
            "word_count": 8,
        },
        "delivery": {
            "status": "not_sent",
            "instantly_id": None,
            "sent_at": None,
            "opened_at": None,
            "clicked_at": None,
            "replied_at": None,
            "bounced_at": None,
            "unsubscribed_at": None,
            "instantly_credit_units": 0,
            "instantly_request_count": 0,
        },
        "created_at": NOW,
        "updated_at": NOW,
        "approved_at": None,
        "approved_by": None,
    }


def test_target_contract_contains_final_greeting_when_director_is_absent() -> None:
    target = ProspectTarget.model_validate(target_payload())

    assert isinstance(target.target_id, UUID)
    assert target.director is None
    assert target.mail.text.startswith("Bonjour,")
    assert target.email.verification_status is EmailVerificationStatus.MX_VERIFIED


def test_target_contract_rejects_mail_that_still_needs_console_assembly() -> None:
    payload = target_payload()
    payload["mail"] = {**payload["mail"], "text": "Vous fournissez du béton ?"}

    with pytest.raises(ValidationError, match="Bonjour"):
        ProspectTarget.model_validate(payload)


@pytest.mark.parametrize(
    "reason",
    ["wrong_company", "wrong_address", "off_topic", "other"],
)
def test_rejection_reason_is_closed(reason: str) -> None:
    command = RejectCommand(
        target_id="51d144ca-d697-47e4-a4dc-ee86d0a9c8ac",
        expected_version=1,
        reason=reason,
        comment="précision" if reason == "other" else None,
    )

    assert command.reason is RejectionReason(reason)


def test_other_rejection_requires_comment_and_unknown_reason_is_refused() -> None:
    with pytest.raises(ValidationError, match="comment"):
        RejectCommand(
            target_id="51d144ca-d697-47e4-a4dc-ee86d0a9c8ac",
            expected_version=1,
            reason="other",
        )
    with pytest.raises(ValidationError):
        RejectCommand(
            target_id="51d144ca-d697-47e4-a4dc-ee86d0a9c8ac",
            expected_version=1,
            reason="duplicate",
        )


def test_correction_requires_at_least_one_supported_change() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        CorrectionChanges()
