from __future__ import annotations

from pathlib import Path

import pytest

from signals.documents.portals.atexo import AtexoAdapter
from signals.documents.portals.base import PortalDownloadResult, PortalIdentity

FIXTURES = Path(__file__).parent / "fixtures" / "documents" / "portals"
IDENTITY = PortalIdentity("Kivou", "contact@kivou.ch")


@pytest.mark.parametrize(
    "fixture",
    [
        "atexo-place.html",
        "atexo-maximilien.html",
        "atexo-megalis.html",
        "atexo-ampa.html",
    ],
)
def test_atexo_is_detected_from_page_fingerprint_not_domain(fixture: str) -> None:
    html = (FIXTURES / fixture).read_text(encoding="utf-8")

    assert AtexoAdapter.matches(html)
    assert AtexoAdapter.matches(html.replace("www.marches-publics.gouv.fr", "new.example"))


def test_atexo_anonymous_withdrawal_sends_kivou_identity_and_downloads_zip() -> None:
    landing = (FIXTURES / "atexo-place.html").read_text(encoding="utf-8")
    calls = []

    class Browser:
        def download(self, url, identity):
            calls.append((url, identity))
            return PortalDownloadResult("available", content=b"PK\x03\x04archive")

        def close(self):
            pass

    result = AtexoAdapter(browser=Browser(), identity=IDENTITY).download(
        "https://new-atexo.example/consultation/3054794", landing
    )

    assert result.access_status == "available"
    assert result.content == b"PK\x03\x04archive"
    assert calls == [("https://new-atexo.example/consultation/3054794", IDENTITY)]


def test_atexo_never_downloads_an_executable() -> None:
    html = (
        '<script src="/app/js/atexo.common.js"></script>'
        '<a id="linkDownloadDce" href="/assistant.exe">DCE</a>'
    )
    class Browser:
        def download(self, url, identity):
            return PortalDownloadResult("unsupported", detail="executable_refused")

        def close(self):
            pass

    result = AtexoAdapter(browser=Browser(), identity=IDENTITY).download(
        "https://atexo.example/consultation/1", html
    )

    assert result.access_status == "unsupported"
    assert result.detail == "executable_refused"
