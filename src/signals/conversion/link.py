"""Kivou-owned CTA links; callers cannot supply a redirect destination."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from signals.conversion.contracts import AttributionTokenPayload
from signals.conversion.token import AttributionTokenKeyring


@dataclass(frozen=True)
class AttributionLink:
    url: str
    token_fingerprint: str


class AttributionLinkBuilder:
    def __init__(self, *, public_site_url: str, keyring: AttributionTokenKeyring) -> None:
        parsed = urlsplit(public_site_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("attribution public site must be an HTTPS origin")
        self._origin = public_site_url.rstrip("/")
        self._keyring = keyring

    def build(self, payload: AttributionTokenPayload) -> AttributionLink:
        issued = self._keyring.issue(payload)
        return AttributionLink(
            url=f"{self._origin}/a/{issued.raw_token}",
            token_fingerprint=issued.token_fingerprint,
        )


__all__ = ["AttributionLink", "AttributionLinkBuilder"]
