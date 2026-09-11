"""Email-bound first-party links for assisted prospect targets."""

from __future__ import annotations

import datetime as dt

from signals.conversion.contracts import AttributionTokenPayload
from signals.conversion.link import AttributionLinkBuilder
from signals.conversion.token import AttributionTokenKeyring
from signals.decision_engine.policy import semantic_fingerprint
from signals.prospection_actions.service import IssuedProspectLink


class AttributionProspectLinkIssuer:
    def __init__(
        self,
        *,
        public_site_url: str,
        keyring: AttributionTokenKeyring,
    ) -> None:
        self._origin = public_site_url.rstrip("/")
        self._builder = AttributionLinkBuilder(
            public_site_url=public_site_url,
            keyring=keyring,
        )

    def issue(
        self, *, row: dict[str, object], email: str, at: dt.datetime
    ) -> IssuedProspectLink:
        member_ref = semantic_fingerprint(
            {
                "kind": "assisted-prospect-member-v1",
                "target_id": str(row["target_id"]),
                "email": email.strip().casefold(),
            }
        )
        campaign_ref = semantic_fingerprint(
            {
                "kind": "assisted-prospect-campaign-v1",
                "date": at.astimezone(dt.UTC).date().isoformat(),
            }
        )
        family_key = str(row["family_key"])
        payload = AttributionTokenPayload(
            campaign_ref=campaign_ref,
            member_ref=member_ref,
            acquisition_opportunity_id=str(row["acquisition_opportunity_id"]),
            wedge=str(row["vertical"]),
            wedge_version="supplier-families-v1",
            country="FR",
            sector_ref=semantic_fingerprint(
                {"kind": "assisted-prospect-sector-v1", "family": family_key}
            ),
            need_ref=family_key,
            need_version="supplier-families-v1",
            opportunity_key=str(row["opportunity_key"]),
            issued_at=at,
            expires_at=at + dt.timedelta(days=30),
        )
        link = self._builder.build(payload)
        raw_token = link.url.rpartition("/")[2]
        return IssuedProspectLink(
            url=link.url,
            member_ref=member_ref,
            token_fingerprint=link.token_fingerprint,
            payload=payload.model_dump(mode="json"),
            unsubscribe_url=f"{self._origin}/unsubscribe/{raw_token}",
        )


__all__ = ["AttributionProspectLinkIssuer"]
