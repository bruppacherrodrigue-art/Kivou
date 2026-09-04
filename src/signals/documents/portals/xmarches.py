"""Retrait anonyme du dossier complet sur XMarchés."""

from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urljoin

import httpx

from signals.documents.portals.base import PortalDownloadResult
from signals.documents.portals.html import parse_html

_EXECUTABLE_SUFFIXES = {".exe", ".msi", ".dmg", ".app", ".bat", ".cmd", ".ps1"}


class XMarchesAdapter:
    def __init__(self, *, client: httpx.Client) -> None:
        self.client = client

    @staticmethod
    def matches(html: str) -> bool:
        folded = html.casefold().replace("&amp;", "&")
        return (
            "data-confirm-download-dce" in folded
            and "telequoi=dce" in folded
            and "prov=xmar" in folded
        )

    def download(self, landing_url: str, landing_html: str) -> PortalDownloadResult:
        download_url = None
        for element in parse_html(landing_html).elements:
            value = element.attrs.get("data-url", "")
            if (
                element.tag == "a"
                and element.attrs.get("data-no-login") == "1"
                and "telequoi=DCE" in value
            ):
                download_url = urljoin(landing_url, value)
                break
        if download_url is None:
            return PortalDownloadResult("download_failed", detail="anonymous_dce_link_not_found")
        suffix = PurePosixPath(download_url.split("?", 1)[0]).suffix.casefold()
        if suffix in _EXECUTABLE_SUFFIXES:
            return PortalDownloadResult("unsupported", detail="executable_refused")
        response = self.client.get(download_url)
        if response.status_code >= 400:
            status = (
                "auth_required" if response.status_code in {401, 403} else "download_failed"
            )
            return PortalDownloadResult(status, detail=f"HTTP {response.status_code}")
        media_type = response.headers.get("content-type", "").split(";", 1)[0]
        if media_type in {"text/html", "application/xhtml+xml"}:
            folded = response.text.casefold()
            if "captcha" in folded or "saisir-captcha" in str(response.url).casefold():
                return PortalDownloadResult("portal_blocked", detail="captcha")
            return PortalDownloadResult("download_failed", detail="unexpected_html")
        if not response.content.startswith((b"PK\x03\x04", b"%PDF")):
            return PortalDownloadResult("download_failed", detail="invalid_document_signature")
        return PortalDownloadResult(
            "available",
            response.content,
            media_type or None,
            final_url=str(response.url),
        )
