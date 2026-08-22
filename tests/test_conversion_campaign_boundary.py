from __future__ import annotations

import datetime as dt

import pytest

from signals.campaigns.contracts import FooterCatalog, FooterCatalogEntry
from signals.campaigns.envelope import EnvelopeInput, build_envelope
from signals.conversion.contracts import AttributionTokenPayload
from signals.conversion.link import AttributionLinkBuilder
from signals.conversion.token import AttributionTokenKeyring

NOW = dt.datetime(2026, 8, 24, 9, tzinfo=dt.UTC)


def footer() -> FooterCatalog:
    return FooterCatalog(
        catalog_version="footer-synthetic-v1",
        entries=(
            FooterCatalogEntry(
                language="fr",
                sender_profile_ref="sender:synthetic",
                sender_identity="Kivou Synthetic",
                source_notice="Source publique synthétique",
                privacy_route="https://example.invalid/privacy",
                visible_opt_out="Répondez STOP pour ne plus être contacté.",
            ),
        ),
    )


def payload() -> AttributionTokenPayload:
    return AttributionTokenPayload(
        campaign_ref="a" * 64,
        member_ref="b" * 64,
        acquisition_opportunity_id="c" * 64,
        wedge="construction",
        wedge_version="wedge-v1",
        country="CH",
        sector_ref="sector-construction-v1",
        need_ref="materials",
        need_version="need-v1",
        issued_at=NOW,
        expires_at=NOW + dt.timedelta(days=34),
    )


def test_kivou_link_is_fixed_https_and_envelope_keeps_approved_cta_prose() -> None:
    builder = AttributionLinkBuilder(
        public_site_url="https://kivou.example.invalid",
        keyring=AttributionTokenKeyring(
            current_key_version="attribution-test-v1",
            keys={"attribution-test-v1": b"synthetic-attribution-secret"},
        ),
    )
    link = builder.build(payload())
    envelope = build_envelope(
        EnvelopeInput(
            language="fr",
            sender_profile_ref="sender:synthetic",
            subject="Sujet synthétique",
            greeting="Bonjour,",
            body="Corps approuvé.",
            cta="CTA approuvé inchangé.",
            attribution_url=link.url,
            catalog=footer(),
        )
    )

    assert link.url.startswith("https://kivou.example.invalid/a/kat1.")
    assert "CTA approuvé inchangé.\n\nhttps://kivou.example.invalid/a/" in envelope.initial_envelope
    assert link.url in envelope.follow_up_body
    assert envelope.custom_variables["kivou_attribution_url"] == link.url
    assert envelope.steps[0].body == envelope.initial_envelope
    assert envelope.steps[1].body == envelope.follow_up_body


def test_link_builder_and_envelope_reject_non_https_or_arbitrary_url_shapes() -> None:
    keyring = AttributionTokenKeyring(
        current_key_version="attribution-test-v1",
        keys={"attribution-test-v1": b"synthetic-attribution-secret"},
    )
    with pytest.raises(ValueError):
        AttributionLinkBuilder(public_site_url="http://kivou.invalid", keyring=keyring)
    with pytest.raises(ValueError):
        build_envelope(
            EnvelopeInput(
                language="fr",
                sender_profile_ref="sender:synthetic",
                subject="Sujet synthétique",
                greeting="Bonjour,",
                body="Corps approuvé.",
                cta="CTA approuvé inchangé.",
                attribution_url="https://evil.example.invalid/redirect?to=elsewhere",
                catalog=footer(),
            )
        )


def test_existing_envelope_without_attribution_remains_byte_compatible() -> None:
    envelope = build_envelope(
        EnvelopeInput(
            language="fr",
            sender_profile_ref="sender:synthetic",
            subject="Sujet synthétique",
            greeting="Bonjour,",
            body="Corps approuvé.",
            cta="CTA approuvé inchangé.",
            catalog=footer(),
        )
    )
    assert envelope.initial_envelope.startswith(
        "Bonjour,\n\nCorps approuvé.\n\nCTA approuvé inchangé.\n\nKivou Synthetic"
    )
    assert "kivou_attribution_url" not in envelope.custom_variables
