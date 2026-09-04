from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from signals.documents.portals.base import PortalIdentity
from signals.documents.portals.policy import PortalPolicy
from signals.documents.portals.registry import PortalRegistry
from signals.documents.portals.xmarches import XMarchesAdapter

FIXTURES = Path(__file__).parent / "fixtures" / "documents" / "portals"
IDENTITY = PortalIdentity("Kivou", "contact@kivou.ch")


def test_xmarches_is_detected_from_real_page_fingerprint() -> None:
    html = (FIXTURES / "xmarches-consultation.html").read_text(encoding="utf-8")

    assert XMarchesAdapter.matches(html)


def test_xmarches_downloads_the_complete_dce_anonymously() -> None:
    html = (FIXTURES / "xmarches-consultation.html").read_text(encoding="utf-8")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.params["telequoi"] == "DCE"
        assert request.url.params.get("filesDCE") is None
        return httpx.Response(
            200,
            content=b"PK\x03\x04xmarches",
            headers={"content-type": "application/zip"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = XMarchesAdapter(client=client).download(
        "https://www.xmarches.fr/entreprise/detailConsultation.php?key=41085", html
    )

    assert result.access_status == "available"
    assert result.content == b"PK\x03\x04xmarches"
    assert len(seen) == 1


def test_xmarches_stops_when_the_withdrawal_redirects_to_a_captcha() -> None:
    html = (FIXTURES / "xmarches-consultation.html").read_text(encoding="utf-8")
    captcha = (FIXTURES / "xmarches-captcha.html").read_text(encoding="utf-8")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                text=captcha,
                headers={"content-type": "text/html; charset=UTF-8"},
            )
        )
    )

    result = XMarchesAdapter(client=client).download(
        "https://www.xmarches.fr/entreprise/detailConsultation.php?key=41085", html
    )

    assert (result.access_status, result.detail) == ("portal_blocked", "captcha")


@pytest.mark.parametrize(
    ("url", "status", "reason"),
    [
        ("https://www.marches-publics.info/dce", "portal_blocked", "captcha"),
        (
            "https://www.marches-securises.fr/dce",
            "cgu_restricted",
            "cgu_automation",
        ),
        (
            "https://www.achatpublic.com/dce",
            "portal_blocked",
            "robots_disallowed",
        ),
    ],
)
def test_reviewed_policy_never_attempts_withdrawal(
    tmp_path, url: str, status: str, reason: str
) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(AssertionError(request))
        )
    )
    registry = PortalRegistry(
        client=client,
        identity=IDENTITY,
        policy=PortalPolicy(tmp_path / "missing.json"),
    )

    result = registry.download(url, "<html>external portal</html>")

    assert (result.access_status, result.detail) == (status, reason)
