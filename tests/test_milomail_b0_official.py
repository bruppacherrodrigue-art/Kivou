"""An exact public identifier still requires an official identity corroboration."""

import datetime as dt

import httpx
from test_milomail_a1_plan import _a0

from signals.acquisition_programs.legal_pages import LegalPageResolver
from signals.acquisition_programs.official_company import (
    OfficialCompanyMatcher,
    OfficialSourceConfig,
)
from signals.supplier_discovery.contracts import ApolloOrganizationCandidate

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


def _candidate(name: str = "EDF") -> ApolloOrganizationCandidate:
    return ApolloOrganizationCandidate(
        provider_organization_id="synthetic-apollo-org", display_name=name,
        normalized_name=name.casefold(), primary_domain="edf.fr", country_code="FR",
        provider_observed_at=NOW, source_fingerprint="a" * 64,
    )


def _source(*, legal_name: str = "EDF", status: str = "A", legal_ids: str = "SIREN 552 100 554"):
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.host == "edf.fr":
            if request.url.path == "/robots.txt":
                return httpx.Response(200, text="User-agent: *\nAllow: /",
                                      headers={"content-type": "text/plain"})
            if request.url.path == "/":
                return httpx.Response(200, text='<a href="/mentions-legales">Legal</a>',
                                      headers={"content-type": "text/html"})
            return httpx.Response(200, text=f"<p>{legal_ids}</p>",
                                  headers={"content-type": "text/html"})
        assert request.url.path == "/search"
        return httpx.Response(200, json={"total_results": 1, "results": [{
            "siren": "552100554", "nom_raison_sociale": legal_name,
            "etat_administratif": status, "siege": {
                "siret": "55210055400013", "nom_commercial": None,
                "libelle_commune": "PARIS", "code_postal": "75000",
            },
        }]})

    return httpx.Client(transport=httpx.MockTransport(respond)), requests


def _match(monkeypatch, *, name: str = "EDF", legal_name: str = "EDF", status: str = "A",
           legal_ids: str = "SIREN 552 100 554"):
    engine, _ = _a0()
    client, requests = _source(legal_name=legal_name, status=status, legal_ids=legal_ids)
    pages = LegalPageResolver(engine, client=client)
    monkeypatch.setattr(pages, "_public", lambda _: True)
    matcher = OfficialCompanyMatcher(
        engine, OfficialSourceConfig(enabled=True, max_requests=10), client=client,
    )
    result = matcher.assess_with_legal_page(_candidate(name), resolver=pages, at=NOW)
    return result, requests


def test_exact_legal_identifier_and_official_identity_confirm_active(monkeypatch) -> None:
    result, requests = _match(monkeypatch)
    assert result.match_confidence == "CONFIRMED_MATCH"
    assert result.legal_status == "ACTIVE"
    assert result.siren == "552100554"
    assert result.legal_page_source_url == "https://edf.fr/mentions-legales"
    assert len(requests) == 4  # robots, home, legal page, official lookup


def test_official_cessation_is_real_exclusion(monkeypatch) -> None:
    result, _ = _match(monkeypatch, status="C")
    assert result.match_confidence == "CONFIRMED_MATCH"
    assert result.activity().status == "INACTIVE"


def test_site_owner_with_unrelated_official_name_stays_probable(monkeypatch) -> None:
    result, _ = _match(monkeypatch, name="Other Agency", legal_name="EDF")
    assert result.match_confidence == "PROBABLE_MATCH"
    assert "APOLLO_NAME_NOT_CORROBORATED" in result.match_reasons
    assert result.activity().status == "UNKNOWN"


def test_multiple_site_identifiers_do_not_force_match(monkeypatch) -> None:
    result, _ = _match(monkeypatch,
                       legal_ids="SIREN 552 100 554 SIREN 732 829 320")
    assert result.match_confidence != "CONFIRMED_MATCH"


def test_missing_robots_file_permits_bounded_access_but_server_error_blocks(monkeypatch) -> None:
    engine, _ = _a0()

    def response_for(status: int, calls: list[str]):
        def respond(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == "/robots.txt":
                return httpx.Response(status)
            if request.url.path == "/":
                return httpx.Response(200, text='<a href="/mentions-legales">Legal</a>',
                                      headers={"content-type": "text/html"})
            return httpx.Response(200, text="SIREN 552 100 554",
                                  headers={"content-type": "text/html"})

        return respond

    for robot_status, expected_pages in ((404, 3), (503, 1)):
        calls = []
        resolver = LegalPageResolver(engine, client=httpx.Client(
            transport=httpx.MockTransport(response_for(robot_status, calls))))
        monkeypatch.setattr(resolver, "_public", lambda _: True)
        evidence = resolver.resolve(f"robot-{robot_status}.fr", at=NOW)
        assert evidence["pages_fetched"] == expected_pages
        assert len(calls) == expected_pages
        assert evidence["siren"] == ("552100554" if robot_status == 404 else None)


def test_single_homepage_identifier_uses_only_home_and_robots(monkeypatch) -> None:
    engine, _ = _a0()
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="<footer>SIREN 552 100 554</footer>",
                              headers={"content-type": "text/html"})

    resolver = LegalPageResolver(engine, client=httpx.Client(
        transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(resolver, "_public", lambda _: True)
    result = resolver.resolve("example.fr", at=NOW)
    assert result["siren"] == "552100554"
    assert result["source_url"] == "https://example.fr/"
    assert calls == ["/robots.txt", "/"]
