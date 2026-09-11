from __future__ import annotations

import datetime as dt
from urllib.parse import urlsplit

import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_assisted_prospect_preparation import NOW, seed_directory, signal

from signals.api.app import create_app
from signals.api.config import ApiConfig
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.conversion.service import ConversionAttributionService
from signals.conversion.source import AttributionSourceResolver
from signals.conversion.token import AttributionTokenKeyring
from signals.persistence.schema import (
    acquisition_contact_suppression,
    acquisition_conversion_event,
    prospect_target,
    supplier_directory,
)
from signals.prospection_actions.attribution import AttributionProspectLinkIssuer
from signals.prospection_actions.preparation import ProspectPreparationService
from signals.prospection_actions.unsubscribe import ProspectUnsubscribeService


def test_assisted_link_is_email_bound_and_reconstructed_from_target(
    migrated_sqlite_engine,
) -> None:
    seed_directory(migrated_sqlite_engine, 2)
    keyring = AttributionTokenKeyring(
        current_key_version="current",
        keys={"current": b"0123456789abcdef0123456789abcdef"},
    )
    issuer = AttributionProspectLinkIssuer(
        public_site_url="https://kivou.eu",
        keyring=keyring,
    )
    prepared = ProspectPreparationService(
        migrated_sqlite_engine, link_issuer=issuer, clock=lambda: NOW
    ).prepare(signal(), cycle_ref="cycle-1")
    with migrated_sqlite_engine.connect() as connection:
        row = connection.execute(sa.select(prospect_target)).mappings().one()
        payload = AttributionSourceResolver(migrated_sqlite_engine).for_member(
            connection, row["attribution_member_ref"]
        )

    raw_token = urlsplit(row["attribution_url"]).path.removeprefix("/a/")
    verified = keyring.verify(raw_token, payload=payload, at=NOW + dt.timedelta(hours=1))
    assert prepared.prepared == 1
    assert verified.payload.opportunity_key == "boamp-2026-42"
    assert verified.payload.member_ref == row["attribution_member_ref"]
    assert row["email_address"] not in row["attribution_url"]
    assert row["unsubscribe_url"].endswith(raw_token)

    click = ConversionAttributionService(migrated_sqlite_engine, keyring).record_click(
        raw_token, at=NOW + dt.timedelta(hours=1)
    )
    with migrated_sqlite_engine.connect() as connection:
        event = connection.execute(sa.select(acquisition_conversion_event)).mappings().one()
        updated = connection.execute(sa.select(prospect_target)).mappings().one()
    assert not click.replayed
    assert event["prospect_target_id"] == row["target_id"]
    assert event["campaign_ref"] is None
    assert updated["clicked_at"].replace(tzinfo=dt.UTC) == NOW + dt.timedelta(hours=1)


def test_visible_unsubscribe_requires_confirmation_and_suppresses_target(
    migrated_sqlite_engine,
) -> None:
    seed_directory(migrated_sqlite_engine, 2)
    attribution = AttributionTokenKeyring(
        current_key_version="current",
        keys={"current": b"0123456789abcdef0123456789abcdef"},
    )
    issuer = AttributionProspectLinkIssuer(
        public_site_url="https://kivou.eu",
        keyring=attribution,
    )
    ProspectPreparationService(
        migrated_sqlite_engine, link_issuer=issuer, clock=lambda: NOW
    ).prepare(signal(), cycle_ref="cycle-1")
    with migrated_sqlite_engine.connect() as connection:
        row = connection.execute(sa.select(prospect_target)).mappings().one()
    token = urlsplit(row["unsubscribe_url"]).path.removeprefix("/unsubscribe/")
    service = ProspectUnsubscribeService(
        migrated_sqlite_engine,
        attribution_keyring=attribution,
        suppression_keyring=SuppressionIdentityKeyring(
            current_key_version="v1", keys={"v1": b"s" * 32}
        ),
    )
    client = TestClient(
        create_app(
            migrated_sqlite_engine,
            ApiConfig(cookie_secure=False),
            now_override=lambda: NOW + dt.timedelta(hours=1),
            prospect_unsubscribe_service=service,
        )
    )

    confirmation = client.get(f"/unsubscribe/{token}")
    with migrated_sqlite_engine.connect() as connection:
        before = connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_contact_suppression)
        )

    completed = client.post(f"/unsubscribe/{token}")
    with migrated_sqlite_engine.connect() as connection:
        after = connection.scalar(
            sa.select(sa.func.count()).select_from(acquisition_contact_suppression)
        )
        target = connection.execute(sa.select(prospect_target)).mappings().one()
        directory = connection.execute(
            sa.select(supplier_directory).where(supplier_directory.c.siren == row["siren"])
        ).mappings().one()

    assert confirmation.status_code == 200
    assert "Confirmer" in confirmation.text
    assert before == 0
    assert completed.status_code == 200
    assert "confirmée" in completed.text
    assert after == 1
    assert target["delivery_status"] == "unsubscribed"
    assert target["unsubscribed_at"] is not None
    assert directory["suppressed_at"] is not None
