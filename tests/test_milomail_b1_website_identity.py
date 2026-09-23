"""A public site can corroborate operational identity without a SIRENE match."""

import datetime as dt

import httpx
import sqlalchemy as sa
from test_milomail_a1_plan import _a0

from signals.acquisition_programs.legal_pages import LegalPageResolver
from signals.acquisition_programs.website_identity import (
    load_website_proofs,
    proof_from_legal_page,
    refresh_website_identity,
)
from signals.persistence.schema import (
    acquisition_census_b0_entry,
    acquisition_census_b0_plan,
    acquisition_census_candidate,
)

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


def test_home_title_provides_dated_identity_without_legal_identifier(monkeypatch) -> None:
    engine, _ = _a0()
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/":
            return httpx.Response(200, text="<title>Cabinet Atlas | Conseil</title>",
                                  headers={"content-type": "text/html"})
        return httpx.Response(404)

    resolver = LegalPageResolver(engine, client=httpx.Client(
        transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(resolver, "_public", lambda _: True)
    legal = resolver.resolve("atlas.fr", at=NOW)
    proof = proof_from_legal_page("Cabinet Atlas", "atlas.fr", legal)
    assert proof is not None
    assert proof.accessible and proof.identity_matches
    assert proof.source_url == "https://atlas.fr/"
    assert proof.observed_at == NOW
    assert resolver.resolve("atlas.fr", at=NOW) == legal
    assert calls.count("/") == 1


def test_unrelated_or_generic_title_cannot_prove_identity() -> None:
    base = {"home_title": "Another Company | Conseil", "home_source_url": "https://atlas.fr/",
            "observed_at": NOW.isoformat()}
    assert proof_from_legal_page("Cabinet Atlas", "atlas.fr", base) is None
    assert proof_from_legal_page("Conseil", "atlas.fr", {
        **base, "home_title": "Conseil et services",
    }) is None
    assert proof_from_legal_page("Cabinet Atlas", "atlas.fr", {
        **base, "home_source_url": "https://elsewhere.fr/",
    }) is None


def test_website_refresh_is_bounded_and_does_not_call_apollo() -> None:
    engine, _ = _a0()
    resolver = LegalPageResolver(engine)
    assert refresh_website_identity(engine, census_id="missing", resolver=resolver,
                                    max_companies=1, at=NOW) == {
        "checked": 0, "confirmed": 0, "unknown": 0,
        "apollo_calls": 0, "instantly_mutations": 0, "emails_sent": 0,
    }


def test_refresh_persists_independent_proof_and_reuses_cache(monkeypatch) -> None:
    engine, census_id = _a0()
    candidate_id = "a" * 64
    with engine.begin() as connection:
        connection.execute(sa.insert(acquisition_census_b0_plan).values(
            plan_id="synthetic-b0", census_id=census_id,
            plan_hash="a" * 64, baseline_hash="b" * 64, seed="public-seed",
            pool_before=2000, credit_cap=1, minimum_pool_balance=500,
            status="COMPLETE", created_at=NOW, updated_at=NOW,
        ))
        connection.execute(sa.insert(acquisition_census_candidate).values(
            candidate_id=candidate_id, census_id=census_id,
            provider_organization_id="org-atlas", primary_domain="atlas.fr",
            snapshot={"display_name": "Cabinet Atlas", "primary_domain": "atlas.fr"},
            sector="consulting", provider="GOOGLE_WORKSPACE",
            provider_confidence="CONFIRMED", contact_found=True,
            leader_identified=True, email_verified=True,
            status="PENDING", reason_codes=[], created_at=NOW, updated_at=NOW,
        ))
        connection.execute(sa.insert(acquisition_census_b0_entry).values(
            plan_id="synthetic-b0", candidate_id=candidate_id, selection_rank=1,
            stratum={"sector": "consulting"}, status="COMPLETE",
            result={"verified_email": True}, completed_at=NOW,
        ))
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/":
            return httpx.Response(200, text="<title>Cabinet Atlas | Conseil</title>",
                                  headers={"content-type": "text/html"})
        return httpx.Response(404)

    resolver = LegalPageResolver(engine, client=httpx.Client(
        transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(resolver, "_public", lambda _: True)
    first = refresh_website_identity(engine, census_id=census_id, resolver=resolver,
                                     max_companies=1, at=NOW)
    assert first["confirmed"] == 1 and first["apollo_calls"] == 0
    assert candidate_id in load_website_proofs(engine, census_id, at=NOW)
    assert refresh_website_identity(engine, census_id=census_id, resolver=resolver,
                                    max_companies=1, at=NOW)["checked"] == 0
    assert calls.count("/") == 1
