"""Public legal status is never inferred from Apollo alone."""

import datetime as dt

import httpx
import pytest
import sqlalchemy as sa
from test_milomail_census import _candidate
from test_milomail_policy import ready_config

from signals.acquisition_programs.census import CensusStore, build_partitions
from signals.acquisition_programs.official_company import (
    OfficialCompanyMatcher,
    OfficialSourceConfig,
    OfficialSourceRetryLater,
    match_official_results,
)
from signals.acquisition_programs.store import AcquisitionProgramStore
from signals.company_research.contracts import ApolloOrganizationObservation
from signals.persistence.database import migrate_to_latest
from signals.persistence.schema import (
    acquisition_census_company_match,
    acquisition_census_official_cache,
    sirene_apollo_binding,
)

NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


def _company(name="Agence Exemple"):
    return ApolloOrganizationObservation(
        provider_organization_id="org-1", provider_company_name=name,
        provider_primary_domain="agence.fr", provider_observed_at=NOW,
        provider_source_fingerprint="a" * 64,
    )


def _official(status="A", *, siren="123456789", name="Agence Exemple", city="Paris"):
    return {"siren": siren, "nom_raison_sociale": name, "etat_administratif": status,
            "siege": {"siret": siren + "00001", "libelle_commune": city,
                      "code_postal": "75001", "etat_administratif": "A"}}


def test_siren_binding_confirms_active_and_ceased() -> None:
    candidate = _candidate()
    for status, expected in (("A", "ACTIVE"), ("C", "INACTIVE")):
        matched = match_official_results(
            _company(), candidate, [_official(status)], observed_at=NOW,
            trusted_siren="123456789",
        )
        assert matched.match_confidence == "CONFIRMED_MATCH"
        assert matched.activity().status == expected
        assert matched.source_reference.endswith("123456789")


def test_name_city_is_only_probable_and_homonyms_are_ambiguous() -> None:
    candidate = _candidate()
    probable = match_official_results(_company(), candidate, [_official()], observed_at=NOW)
    assert probable.match_confidence == "PROBABLE_MATCH"
    assert probable.activity().status == "UNKNOWN"
    ambiguous = match_official_results(
        _company(), candidate, [_official(), _official(siren="987654321")],
        observed_at=NOW,
    )
    assert ambiguous.match_confidence == "AMBIGUOUS_MATCH"
    assert ambiguous.activity().status == "UNKNOWN"
    assert match_official_results(_company(), candidate, [], observed_at=NOW).legal_status == "UNKNOWN"
    assert match_official_results(
        _company(), candidate, [_official(name="Autre")], observed_at=NOW,
    ).match_confidence == "NO_MATCH"


def test_unique_exact_name_city_postal_and_consistent_apollo_domain_confirm() -> None:
    candidate = _candidate().model_copy(update={"postal_code": "75001"})
    matched = match_official_results(_company(), candidate, [_official()], observed_at=NOW)
    assert matched.match_confidence == "CONFIRMED_MATCH"
    assert matched.activity().status == "ACTIVE"
    mismatch = candidate.model_copy(update={"postal_code": "75002"})
    assert match_official_results(
        _company(), mismatch, [_official()], observed_at=NOW,
    ).match_confidence == "PROBABLE_MATCH"


def test_a1_matches_search_candidate_without_apollo_company_enrichment() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    calls = []

    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"results": [_official()], "total_results": 1})

    matcher = OfficialCompanyMatcher(
        engine, OfficialSourceConfig(enabled=True, max_requests=1, rate_limit_per_minute=60),
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    candidate = _candidate().model_copy(update={"postal_code": "75001"})
    result = matcher.assess_search_candidate(candidate, at=NOW)
    assert result.match_confidence == "CONFIRMED_MATCH"
    assert result.legal_status == "ACTIVE"
    assert calls == ["/search"]


def test_source_is_disabled_by_default_and_cache_expires() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"results": [_official()], "total_results": 1})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    disabled = OfficialCompanyMatcher(engine, OfficialSourceConfig(), client=client)
    assert disabled.assess(_company(), _candidate(), at=NOW).legal_status == "UNKNOWN"
    assert not calls
    matcher = OfficialCompanyMatcher(
        engine, OfficialSourceConfig(enabled=True, max_requests=2, cache_ttl_days=1), client=client,
    )
    assert matcher.assess(_company(), _candidate(), at=NOW).match_confidence == "PROBABLE_MATCH"
    assert matcher.assess(_company(), _candidate(), at=NOW).match_confidence == "PROBABLE_MATCH"
    assert len(calls) == 1
    assert matcher.assess(_company(), _candidate(), at=NOW + dt.timedelta(days=2)).legal_status == "ACTIVE"
    assert len(calls) == 2


def test_timeout_and_rate_limit_never_prove_activity() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    for response in (httpx.Response(429), httpx.ConnectTimeout("synthetic")):
        def handle(_request, result=response):
            if isinstance(result, Exception):
                raise result
            return result
        matcher = OfficialCompanyMatcher(
            engine, OfficialSourceConfig(enabled=True, max_requests=1),
            client=httpx.Client(transport=httpx.MockTransport(handle)),
        )
        with pytest.raises(OfficialSourceRetryLater):
            matcher.assess(_company(), _candidate(), at=NOW)


def test_recent_domain_binding_proves_siren_and_persists_minimal_evidence() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    config = ready_config()
    program_id = AcquisitionProgramStore(engine).register(config, at=NOW)
    store = CensusStore(engine)
    census_id = store.plan(program_id=program_id, partitions=build_partitions(config), at=NOW)
    with engine.begin() as connection:
        connection.execute(sa.insert(sirene_apollo_binding).values(
            siren="123456789", apollo_organization_id="org-1", resolved_at=NOW,
            resolution_method="domain", confidence_score="0.95", domain="agence.fr",
            status="resolved", created_at=NOW, updated_at=NOW,
        ))
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(
        200, json={"results": [{**_official(), "private_director": "must-not-cache"}]},
    )))
    matcher = OfficialCompanyMatcher(
        engine, OfficialSourceConfig(enabled=True, max_requests=1),
        client=client, census_id=census_id,
    )
    assessment = matcher.assess(_company(), _candidate(), at=NOW)
    assert assessment.match_confidence == "CONFIRMED_MATCH"
    assert assessment.activity().status == "ACTIVE"
    with engine.connect() as connection:
        cache = connection.execute(sa.select(acquisition_census_official_cache)).mappings().one()
        saved = connection.execute(sa.select(acquisition_census_company_match)).mappings().one()
    assert "private_director" not in str(cache["evidence"])
    assert saved["match_evidence"]["siren"] == "123456789"
    assert store.report(census_id)["official_legal_status"] == {"ACTIVE": 1}


def test_stale_binding_never_confirms_match() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    with engine.begin() as connection:
        connection.execute(sa.insert(sirene_apollo_binding).values(
            siren="123456789", apollo_organization_id="org-1",
            resolved_at=NOW - dt.timedelta(days=100),
            resolution_method="domain", confidence_score="0.95", domain="agence.fr",
            status="resolved", created_at=NOW, updated_at=NOW,
        ))
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(
        200, json={"results": [_official()], "total_results": 1},
    )))
    matcher = OfficialCompanyMatcher(engine, OfficialSourceConfig(enabled=True, max_requests=1),
                                     client=client)
    assert matcher.assess(_company(), _candidate(), at=NOW).match_confidence == "PROBABLE_MATCH"


def test_truncated_official_search_cannot_confirm_unique_postal_match() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(
        200, json={"results": [_official()], "total_results": 2},
    )))
    candidate = _candidate().model_copy(update={"postal_code": "75001"})
    matcher = OfficialCompanyMatcher(engine, OfficialSourceConfig(enabled=True, max_requests=1),
                                     client=client)
    result = matcher.assess(_company(), candidate, at=NOW)
    assert result.match_confidence == "AMBIGUOUS_MATCH"
    assert result.activity().status == "UNKNOWN"


@pytest.mark.parametrize("total", [None, "1", -1, 2])
def test_missing_or_invalid_total_cannot_confirm_name_match(total) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    client = httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(
        200, json={"results": [_official()], "total_results": total},
    )))
    matcher = OfficialCompanyMatcher(engine, OfficialSourceConfig(enabled=True, max_requests=1),
                                     client=client)
    result = matcher.assess(
        _company(), _candidate().model_copy(update={"postal_code": "75001"}), at=NOW,
    )
    assert result.match_confidence == "AMBIGUOUS_MATCH"
    assert result.activity().status == "UNKNOWN"


def test_trusted_siren_cannot_resolve_to_different_legal_unit() -> None:
    result = match_official_results(
        _company(), _candidate().model_copy(update={"postal_code": "75001"}),
        [_official(siren="987654321")], observed_at=NOW, trusted_siren="123456789",
    )
    assert result.match_confidence == "NO_MATCH"


def test_official_request_cap_is_durable_across_resume() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    config = ready_config()
    program_id = AcquisitionProgramStore(engine).register(config, at=NOW)
    census_id = CensusStore(engine).plan(
        program_id=program_id, partitions=build_partitions(config), at=NOW,
    )
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"results": [_official()], "total_results": 1})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    source_config = OfficialSourceConfig(enabled=True, max_requests=1)
    first = OfficialCompanyMatcher(engine, source_config, client=client, census_id=census_id)
    assert first.assess(_company(), _candidate(), at=NOW).legal_status == "ACTIVE"
    resumed = OfficialCompanyMatcher(engine, source_config, client=client, census_id=census_id)
    with pytest.raises(OfficialSourceRetryLater):
        resumed.assess(_company("Autre société"), _candidate(), at=NOW)
    assert len(calls) == 1
