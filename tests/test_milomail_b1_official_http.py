"""Official company API requests are durably counted without response bodies."""

import datetime as dt

import httpx
import sqlalchemy as sa
from test_milomail_a1_plan import _a0
from test_milomail_census import _candidate

from signals.acquisition_programs.http_accounting_store import LegalHttpAttemptStore
from signals.acquisition_programs.official_company import (
    OfficialCompanyMatcher,
    OfficialSourceConfig,
)
from signals.persistence.schema import (
    acquisition_census_candidate,
    acquisition_census_legal_http_attempt,
)


def test_official_api_request_and_cache_hit_are_persisted_without_payload() -> None:
    engine, census_id = _a0()
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    candidate = _candidate()
    with engine.begin() as connection:
        connection.execute(sa.insert(acquisition_census_candidate).values(
            candidate_id="a" * 64, census_id=census_id,
            provider_organization_id=candidate.provider_organization_id,
            primary_domain=candidate.primary_domain,
            snapshot=candidate.model_dump(mode="json"), sector="consulting",
            provider="UNKNOWN", provider_confidence="UNKNOWN",
            contact_found=False, leader_identified=False, email_verified=False,
            status="PENDING", reason_codes=[], created_at=now, updated_at=now,
        ))
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={
            "results": [{"siren": "123456789", "nom_raison_sociale": "Agence Exemple",
                         "etat_administratif": "A", "private_email": "hidden@example.fr",
                         "siege": {"libelle_commune": "Paris", "code_postal": "75001"}}],
            "total_results": 1,
        })

    matcher = OfficialCompanyMatcher(
        engine, OfficialSourceConfig(enabled=True, max_requests=2),
        client=httpx.Client(transport=httpx.MockTransport(respond)),
        census_id=census_id, attempt_sink=LegalHttpAttemptStore(engine).record,
    )
    matcher.assess_search_candidate(candidate, at=now)
    matcher.assess_search_candidate(candidate, at=now)
    assert calls == ["/search"]
    assert LegalHttpAttemptStore(engine).summary(census_id) == {
        "OFFICIAL_API:HTTP_OK": 1, "OFFICIAL_API:CACHE_HIT": 1,
    }
    with engine.connect() as connection:
        rows = connection.execute(sa.select(acquisition_census_legal_http_attempt)).mappings().all()
    assert {row["candidate_id"] for row in rows} == {"a" * 64}
    assert {row["proof_type"] for row in rows} == {"OFFICIAL_STATUS"}
    assert "hidden@example.fr" not in repr(rows)
