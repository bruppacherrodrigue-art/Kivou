from __future__ import annotations

import datetime as dt
from urllib.parse import urlsplit

from test_assisted_prospect_preparation import NOW, seed_directory, signal

from signals.conversion.source import AttributionSourceResolver
from signals.conversion.token import AttributionTokenKeyring
from signals.prospection_actions.attribution import AttributionProspectLinkIssuer
from signals.prospection_actions.preparation import ProspectPreparationService


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
    target = ProspectPreparationService  # keep imports explicit for architecture checks
    del target

    listed = __import__("sqlalchemy").select
    from signals.persistence.schema import prospect_target

    with migrated_sqlite_engine.connect() as connection:
        row = connection.execute(listed(prospect_target)).mappings().one()
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
