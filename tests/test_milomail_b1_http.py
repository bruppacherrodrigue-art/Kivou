"""Public legal-page HTTP accounting stays bounded and contains no page data."""

import datetime as dt
import socket
import ssl

import httpx
import pytest
import sqlalchemy as sa

from signals.acquisition_programs.legal_pages import LegalPageResolver
from signals.persistence.schema import acquisition_census_legal_page_cache

NOW = dt.datetime(2026, 9, 22, 9, tzinfo=dt.UTC)


@pytest.fixture
def engine():
    database = sa.create_engine("sqlite:///:memory:")
    acquisition_census_legal_page_cache.create(database)
    return database


def _resolver(engine, monkeypatch, respond, events):
    resolver = LegalPageResolver(
        engine, client=httpx.Client(transport=httpx.MockTransport(respond)),
        attempt_sink=events.append if isinstance(events, list) else events,
    )
    monkeypatch.setattr(resolver, "_public", lambda _domain: True)
    return resolver


def test_http_attempt_lifecycle_and_cache_hit_are_minimal(engine, monkeypatch) -> None:
    events = []
    paths = []

    def respond(request):
        paths.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /",
                                  headers={"content-type": "text/plain"})
        if request.url.path == "/":
            return httpx.Response(200, text='<a href="/mentions-legales">Legal</a>',
                                  headers={"content-type": "text/html"})
        return httpx.Response(200, text="SIREN 552 100 554 secret-person@example.fr",
                              headers={"content-type": "text/html"})

    resolver = _resolver(engine, monkeypatch, respond, events)
    first = resolver.resolve("example.fr", at=NOW, run_id="census-123", company_id="org-456")
    assert first["siren"] == "552100554"
    assert paths == ["/robots.txt", "/", "/mentions-legales"]
    starts = [item for item in events if item.outcome == "STARTED" and
              item.request_type in {"ROBOTS", "HOMEPAGE", "LEGAL_PAGE"}]
    assert [item.request_type for item in starts] == ["ROBOTS", "HOMEPAGE", "LEGAL_PAGE"]
    for start in starts:
        terminal = [item for item in events if item.attempt_id == start.attempt_id
                    and item.outcome != "STARTED"]
        assert len(terminal) == 1
        assert terminal[0].outcome == "HTTP_OK"
        assert terminal[0].http_status == 200
        assert start.run_id == "census-123"
        assert start.company_id == "org-456"
        assert start.domain == "example.fr"
        assert start.occurred_at.tzinfo is not None
    assert resolver.resolve("example.fr", at=NOW, run_id="census-123",
                            company_id="org-456") == first
    assert len(paths) == 3
    assert events[-1].request_type == "CACHE"
    assert events[-1].outcome == "CACHE_HIT"
    serialized = repr(events)
    assert "secret-person@example.fr" not in serialized
    assert "SIREN 552" not in serialized
    assert "/mentions-legales" not in serialized


@pytest.mark.parametrize("kind,reply,expected", [
    ("timeout", None, "TIMEOUT"),
    ("tls", None, "TLS_ERROR"),
    ("tls-direct", None, "TLS_ERROR"),
    ("redirect", 302, "REDIRECT_BLOCKED"),
    ("status", 503, "HTTP_STATUS"),
    ("size", 200, "SIZE_LIMIT"),
])
def test_robots_request_failure_is_accounted_and_cannot_open_homepage(
    engine, monkeypatch, kind, reply, expected,
) -> None:
    events = []
    paths = []

    def respond(request):
        paths.append(request.url.path)
        if kind == "timeout":
            raise httpx.ReadTimeout("private timeout payload", request=request)
        if kind == "tls":
            try:
                raise ssl.SSLError("private TLS payload")
            except ssl.SSLError as error:
                raise httpx.ConnectError("private transport payload", request=request) from error
        if kind == "tls-direct":
            raise ssl.SSLError("private TLS payload")
        if kind == "size":
            return httpx.Response(200, content=b"x" * 262_145)
        return httpx.Response(reply, headers={"location": "https://other.example/private"})

    resolver = _resolver(engine, monkeypatch, respond, events)
    result = resolver.resolve("example.fr", at=NOW, run_id="census-123", company_id="org-456")
    assert result["siren"] is None
    assert paths == ["/robots.txt"]
    assert [item.outcome for item in events if item.request_type == "ROBOTS"] == [
        "STARTED", expected,
    ]
    assert "private" not in repr(events)


def test_dns_rejection_and_robots_disallow_are_accounted_without_followup(
    engine, monkeypatch,
) -> None:
    events = []
    paths = []

    def respond(request):
        paths.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nDisallow: /",
                              headers={"content-type": "text/plain"})

    resolver = _resolver(engine, monkeypatch, respond, events)
    monkeypatch.setattr(resolver, "_public", lambda _domain: False)
    assert resolver.resolve("private.fr", at=NOW, run_id="census", company_id="org")[
        "reason"
    ] == "DOMAIN_NOT_PUBLICLY_RESOLVABLE"
    assert paths == []
    dns = [item for item in events if item.request_type == "DNS"]
    assert [item.outcome for item in dns] == ["STARTED", "DNS_REJECTED"]
    assert dns[0].attempt_id == dns[1].attempt_id
    monkeypatch.setattr(resolver, "_public", lambda _domain: True)
    assert resolver.resolve("public.fr", at=NOW, run_id="census", company_id="org")[
        "siren"
    ] is None
    assert paths == ["/robots.txt"]
    assert any(item.request_type == "ROBOTS_POLICY" and item.outcome == "ROBOTS_BLOCKED"
               for item in events)


def test_dns_lookup_error_is_distinct_from_private_address(engine, monkeypatch) -> None:
    events = []
    paths = []

    def fail_lookup(*_args, **_kwargs):
        raise socket.gaierror("private DNS detail")

    monkeypatch.setattr(socket, "getaddrinfo", fail_lookup)
    resolver = LegalPageResolver(engine, client=httpx.Client(transport=httpx.MockTransport(
        lambda request: paths.append(request.url.path) or httpx.Response(200),
    )), attempt_sink=events.append)
    result = resolver.resolve("unresolvable.fr", at=NOW, run_id="census", company_id="org")
    assert result["reason"] == "DOMAIN_NOT_PUBLICLY_RESOLVABLE"
    assert paths == []
    dns = [item for item in events if item.request_type == "DNS"]
    assert [item.outcome for item in dns] == ["STARTED", "DNS_ERROR"]
    assert dns[0].attempt_id == dns[1].attempt_id
    assert "private DNS detail" not in repr(events)


def test_accounting_failure_prevents_http_and_cache_write(engine, monkeypatch) -> None:
    from signals.acquisition_programs.http_accounting import AttemptAccountingError

    paths = []

    def sink(item):
        if item.outcome == "STARTED":
            raise RuntimeError("private storage error")

    def respond(request):
        paths.append(request.url.path)
        return httpx.Response(200)

    resolver = _resolver(engine, monkeypatch, respond, sink)
    with pytest.raises(AttemptAccountingError):
        resolver.resolve("example.fr", at=NOW, run_id="census", company_id="org")
    assert paths == []
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(
            acquisition_census_legal_page_cache,
        )) == 0


def test_terminal_accounting_failure_prevents_followup_request(engine, monkeypatch) -> None:
    from signals.acquisition_programs.http_accounting import AttemptAccountingError

    paths = []

    def sink(item):
        if item.request_type == "ROBOTS" and item.outcome == "HTTP_OK":
            raise RuntimeError("private storage error")

    def respond(request):
        paths.append(request.url.path)
        return httpx.Response(200, text="User-agent: *\nAllow: /")

    resolver = _resolver(engine, monkeypatch, respond, sink)
    with pytest.raises(AttemptAccountingError):
        resolver.resolve("example.fr", at=NOW, run_id="census", company_id="org")
    assert paths == ["/robots.txt"]


def test_accounting_context_rejects_email_instead_of_opaque_company_id(
    engine, monkeypatch,
) -> None:
    events = []
    paths = []
    resolver = _resolver(engine, monkeypatch, lambda request: (
        paths.append(request.url.path) or httpx.Response(200)
    ), events)
    with pytest.raises(ValueError, match="opaque"):
        resolver.resolve("example.fr", at=NOW, run_id="census-123",
                         company_id="alice@example.fr")
    assert paths == []
    assert events == []


def test_four_page_cap_and_no_script_execution(engine, monkeypatch) -> None:
    events = []
    paths = []

    def respond(request):
        paths.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/":
            links = "".join(f'<a href="/legal-{n}">Legal</a>' for n in range(6))
            return httpx.Response(200, text=links + "<script>sendEmail()</script>",
                                  headers={"content-type": "text/html"})
        return httpx.Response(200, text="No identifier", headers={"content-type": "text/html"})

    resolver = _resolver(engine, monkeypatch, respond, events)
    result = resolver.resolve("example.fr", at=NOW, run_id="census", company_id="org")
    assert result["pages_fetched"] == 4
    assert len(paths) == 4
    assert len([item for item in events if item.outcome == "STARTED" and
                item.request_type in {"ROBOTS", "HOMEPAGE", "LEGAL_PAGE"}]) == 4
    assert all(item.request_type in {"DNS", "ROBOTS", "HOMEPAGE", "LEGAL_PAGE"}
               for item in events if item.outcome == "STARTED")
