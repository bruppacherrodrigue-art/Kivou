"""Sélection d'un adaptateur d'après le contenu observé de la page."""

from __future__ import annotations

import httpx

from signals.documents.portals.atexo import AtexoAdapter, PlaywrightAtexoBrowser
from signals.documents.portals.base import AtexoBrowser, PortalDownloadResult, PortalIdentity
from signals.documents.portals.policy import PortalPolicy
from signals.documents.portals.xmarches import XMarchesAdapter


class PortalRegistry:
    def __init__(
        self,
        *,
        client: httpx.Client,
        identity: PortalIdentity,
        policy: PortalPolicy,
        atexo_browser: AtexoBrowser | None = None,
    ) -> None:
        self.policy = policy
        self.adapters = (
            AtexoAdapter(
                browser=atexo_browser or PlaywrightAtexoBrowser(), identity=identity
            ),
            XMarchesAdapter(client=client),
        )

    def preflight(self, url: str) -> PortalDownloadResult | None:
        decision = self.policy.decision(url)
        if decision is None:
            return None
        return PortalDownloadResult(decision.status, detail=decision.reason)

    def supports(self, html: str) -> bool:
        return any(adapter.matches(html) for adapter in self.adapters)

    def download(self, url: str, html: str) -> PortalDownloadResult:
        if decision := self.preflight(url):
            return decision
        for adapter in self.adapters:
            if adapter.matches(html):
                try:
                    return adapter.download(url, html)
                except ValueError as error:
                    if str(error) == "identity_missing":
                        return PortalDownloadResult(
                            "portal_blocked", detail="identity_missing"
                        )
                    raise
        return PortalDownloadResult("external", detail="portal_not_supported")

    def close(self) -> None:
        for adapter in self.adapters:
            close = getattr(adapter, "close", None)
            if close is not None:
                close()
