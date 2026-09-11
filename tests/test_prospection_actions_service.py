from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa

from signals.persistence.schema import (
    prospect_target,
    prospect_target_history,
    supplier_directory,
)
from signals.prospection_actions.contracts import (
    ApproveCommand,
    CorrectCommand,
    CorrectionChanges,
    RejectCommand,
)
from signals.prospection_actions.service import (
    IssuedProspectLink,
    ProspectionActionError,
    ProspectionActions,
)

NOW = dt.datetime(2026, 9, 11, 9, tzinfo=dt.UTC)
TARGET_ID = "51d144ca-d697-47e4-a4dc-ee86d0a9c8ac"


class MxVerifier:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.calls: list[str] = []

    def verify(self, email: str) -> bool:
        self.calls.append(email)
        return self.accepted


class LinkIssuer:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def issue(self, *, row, email: str, at: dt.datetime) -> IssuedProspectLink:
        self.calls.append(email)
        return IssuedProspectLink(
            url="https://kivou.eu/a/kat1.key.reissued.signature",
            member_ref="b" * 64,
            token_fingerprint="c" * 64,
            payload={"member_ref": "b" * 64, "email_nonce": email, "issued_at": at.isoformat()},
        )


def seed(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.insert(supplier_directory).values(
                siren="123456789",
                legal_name="Béton du Bourbonnais",
                legal_name_observed_at=NOW,
                family_keys=["ready_mixed_concrete"],
                families_observed_at=NOW,
                department="03",
                department_observed_at=NOW,
                city="Saint-Victor",
                city_observed_at=NOW,
                employees=35,
                employees_observed_at=NOW,
                domain="beton-bourbonnais.fr",
                domain_validation_method="name_word",
                domain_observed_at=NOW,
                directors=[],
                professional_email="contact@beton-bourbonnais.fr",
                email_source="site",
                email_verification_status="mx_verified",
                email_contact_name="",
                email_contact_title="",
                email_observed_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            sa.insert(prospect_target).values(
                target_id=TARGET_ID,
                version=1,
                cycle_ref="cycle-1",
                opportunity_key="boamp-2026-42",
                procedure_award_key="notice-1:lot-1",
                acquisition_opportunity_id="a" * 64,
                siren="123456789",
                company_name="Béton du Bourbonnais",
                company_city="Saint-Victor",
                company_employees=35,
                family_key="ready_mixed_concrete",
                family_label="béton prêt à l'emploi",
                director_name=None,
                director_title=None,
                director_source=None,
                email_address="contact@beton-bourbonnais.fr",
                email_source="site",
                email_verification_status="mx_verified",
                signal_holder="SAS Exemple",
                signal_subject="Construction d'un groupe scolaire",
                signal_amount_minor_units=125_000_000,
                signal_currency="eur",
                signal_location="Allier",
                signal_decision_date=dt.date(2026, 9, 10),
                signal_source_url="https://www.boamp.fr/avis/42",
                mail_subject="Construction d'un groupe scolaire",
                mail_text="Bonjour,\n\nVous fournissez du béton prêt à l'emploi ?",
                mail_html="<p>Bonjour,</p><p>Vous fournissez du béton prêt à l'emploi ?</p>",
                attribution_url="https://kivou.eu/a/kat1.key.old.signature",
                attribution_member_ref="a" * 64,
                attribution_payload={"member_ref": "a" * 64},
                attribution_token_fingerprint="d" * 64,
                unsubscribe_url="https://kivou.eu/unsubscribe/token",
                mail_word_count=8,
                status="pending_review",
                delivery_status="not_sent",
                created_at=NOW,
                updated_at=NOW,
            )
        )


@pytest.fixture
def service(migrated_sqlite_engine):
    seed(migrated_sqlite_engine)
    verifier = MxVerifier()
    issuer = LinkIssuer()
    return (
        ProspectionActions(
            migrated_sqlite_engine,
            email_verifier=verifier,
            link_issuer=issuer,
            clock=lambda: NOW + dt.timedelta(hours=1),
        ),
        verifier,
        issuer,
        migrated_sqlite_engine,
    )


def test_approve_is_versioned_and_records_actor(service) -> None:
    actions, _verifier, _issuer, _engine = service

    target = actions.approve(
        ApproveCommand(target_id=TARGET_ID, expected_version=1), actor="rodrigue@kivou.eu"
    )

    assert target.status == "approved"
    assert target.version == 2
    assert target.approved_by == "rodrigue@kivou.eu"
    with pytest.raises(ProspectionActionError) as stale:
        actions.approve(
            ApproveCommand(target_id=TARGET_ID, expected_version=1),
            actor="rodrigue@kivou.eu",
        )
    assert stale.value.code == "TARGET_VERSION_CONFLICT"


def test_correct_email_rechecks_mx_reissues_token_and_keeps_status(service) -> None:
    actions, verifier, issuer, engine = service

    result = actions.correct(
        CorrectCommand(
            target_id=TARGET_ID,
            expected_version=1,
            changes=CorrectionChanges(email_address="direction@altrad.com"),
        ),
        actor="rodrigue@kivou.eu",
    )

    assert result.target.status == "pending_review"
    assert result.target.email.address == "direction@altrad.com"
    assert result.target.email.source == "manual"
    assert result.target.mail.attribution_url.endswith("reissued.signature")
    assert result.token_reissued is True
    assert result.email_reverified is True
    assert verifier.calls == ["direction@altrad.com"]
    assert issuer.calls == ["direction@altrad.com"]
    with engine.connect() as connection:
        history = connection.execute(sa.select(prospect_target_history)).mappings().one()
        directory = connection.execute(sa.select(supplier_directory)).mappings().one()
    assert history["previous_values"]["email_address"] == "contact@beton-bourbonnais.fr"
    assert directory["professional_email"] == "direction@altrad.com"
    assert directory["email_source"] == "manual"


@pytest.mark.parametrize(
    ("reason", "expected_effect"),
    [("wrong_address", "email_invalidated"), ("wrong_company", "family_review_required")],
)
def test_reject_propagates_closed_reason_to_directory(service, reason, expected_effect) -> None:
    actions, _verifier, _issuer, engine = service

    result = actions.reject(
        RejectCommand(target_id=TARGET_ID, expected_version=1, reason=reason),
        actor="rodrigue@kivou.eu",
    )

    assert result.target.status == "rejected"
    assert result.directory_effect == expected_effect
    with engine.connect() as connection:
        directory = connection.execute(sa.select(supplier_directory)).mappings().one()
    if reason == "wrong_address":
        assert directory["email_verification_status"] == "mx_failed"
    else:
        assert directory["family_review_keys"] == ["ready_mixed_concrete"]
