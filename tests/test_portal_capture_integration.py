from __future__ import annotations

from pathlib import Path

import httpx

from signals.documents.fetch import DocumentFetcher, FetchLimits
from signals.documents.portals.base import PortalDownloadResult

FIXTURES = Path(__file__).parent / "fixtures" / "documents" / "portals"


def test_blocked_portal_is_not_requested_even_for_its_landing_page(tmp_path) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(AssertionError(request))
        )
    )
    fetcher = DocumentFetcher(client=client, portal_policy_path=tmp_path / "missing.json")

    result = fetcher.fetch("https://www.achatpublic.com/dce")

    assert (result.access_status, result.detail) == (
        "portal_blocked",
        "robots_disallowed",
    )
    assert fetcher.requests_sent == 0


def test_host_discipline_wraps_the_landing_request(tmp_path) -> None:
    calls: list[str] = []

    class Discipline:
        def acquire(self, url):
            calls.append(f"acquire:{url}")

        def record(self, url, result):
            calls.append(f"record:{result.access_status}:{result.detail}")

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"request:{request.url}")
        return httpx.Response(503)

    fetcher = DocumentFetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        portal_policy_path=tmp_path / "missing.json",
        portal_discipline=Discipline(),
    )

    result = fetcher.fetch("https://portal.example/dce/42")

    assert (result.access_status, result.detail) == ("download_failed", "HTTP 503")
    assert calls == [
        "acquire:https://portal.example/dce/42",
        "request:https://portal.example/dce/42",
        "record:download_failed:HTTP 503",
    ]


def test_atexo_archive_returns_through_existing_hash_and_size_guards(tmp_path) -> None:
    landing = (FIXTURES / "atexo-place.html").read_text(encoding="utf-8")
    archive = b"PK\x03\x04" + (b"x" * 400)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/consultation/3054794":
            return httpx.Response(200, text=landing, headers={"content-type": "text/html"})
        raise AssertionError(request)

    class Browser:
        def download(self, url, identity):
            return PortalDownloadResult("available", archive, "application/zip")

        def close(self):
            pass

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = DocumentFetcher(
        client=client,
        limits=FetchLimits(max_bytes=350),
        portal_policy_path=tmp_path / "missing.json",
        portal_company_name="Kivou",
        portal_contact_email="contact@kivou.ch",
        portal_atexo_browser=Browser(),
    )

    result = fetcher.fetch("https://new-atexo.example/consultation/3054794")

    assert result.access_status == "too_large"
    assert result.byte_size == len(archive)
    assert result.content is None
    assert result.content_hash is None


def test_atexo_identity_is_never_submitted_empty(tmp_path) -> None:
    landing = (FIXTURES / "atexo-place.html").read_text(encoding="utf-8")
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.url.path == "/consultation/3054794":
            return httpx.Response(200, text=landing, headers={"content-type": "text/html"})
        raise AssertionError("an incomplete identity must never reach the browser")

    class Browser:
        def download(self, url, identity):
            raise AssertionError("an incomplete identity must never reach the browser")

        def close(self):
            pass

    fetcher = DocumentFetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        portal_policy_path=tmp_path / "missing.json",
        portal_company_name="",
        portal_contact_email="",
        portal_atexo_browser=Browser(),
    )

    result = fetcher.fetch("https://new-atexo.example/consultation/3054794")

    assert (result.access_status, result.detail) == (
        "portal_blocked",
        "identity_missing",
    )
    assert methods == ["GET"]
