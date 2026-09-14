"""Offline durable company requests, independent of automatic winner selection."""

import dataclasses
import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from engagement_helpers import Clock, make_app, make_engine, pay, signed_up

from signals.company_research.company_requests import (
    enrichment_view,
    request_enrichment,
    run_company_enrichment_requests,
)
from signals.company_research.enrichment import CompanyEnrichmentInput
from signals.model_runtime.budget import DailyModelBudgetExhausted
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import supplier_directory
from signals.supplier_directory.store import SupplierDirectoryStore

NOW = dt.datetime(2026, 9, 14, 10, tzinfo=dt.UTC)
SIREN = "481153435"


@pytest.fixture
def shared_prepared(tmp_path):
    engine = make_engine(tmp_path)
    app = make_app(engine, Clock())
    client = signed_up(app)
    pay(engine, client, plan="pro")
    return engine, app, client


@pytest.fixture
def prepared(shared_prepared):
    _, app, _ = shared_prepared
    app.state.config = dataclasses.replace(
        app.state.config, company_directory_enrichment_enabled=True
    )
    return shared_prepared


@pytest.fixture
def engine(tmp_path):
    result = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'requests.db'}")
    migrate_to_latest(result)
    yield result
    result.dispose()


def seed(engine, **values):
    SupplierDirectoryStore(engine).upsert_identity(
        siren=SIREN,
        legal_name="ALYA",
        naf_code="43.99C",
        family_key="",
        department="01",
        city="GUEREINS",
        employees=19,
        observed_at=NOW,
    )
    if values:
        with engine.begin() as connection:
            connection.execute(sa.update(supplier_directory).values(**values))


def request(engine, now=NOW):
    with engine.begin() as connection:
        return request_enrichment(connection, siren=SIREN, now=now)


def view(engine, now=NOW):
    with engine.connect() as connection:
        return enrichment_view(connection, siren=SIREN, now=now)


def run(engine, action, now=NOW, **kwargs):
    return run_company_enrichment_requests(
        engine,
        now=now,
        worker_ref="test-worker",
        limit=5,
        identity_source=lambda siren: CompanyEnrichmentInput(
            siren=siren,
            legal_name="ALYA",
            city="GUEREINS",
            department="01",
            naf_code="43.99C",
            naf_label=None,
            employees=19,
        ),
        enrichment_service=SimpleNamespace(enrich=action),
        **kwargs,
    )


def persist(engine, now=NOW, **values):
    with engine.begin() as connection:
        connection.execute(
            sa.update(supplier_directory).values(
                enrichment_observed_at=now,
                **values,
            )
        )
    return SimpleNamespace(cached=False, cost_usd=Decimal("0.001"))


def test_existing_directory_is_not_ready_and_requests_deduplicate(engine):
    seed(engine)
    assert view(engine)["state"] == "available"
    first = request(engine)
    assert first["state"] == "queued" and first["queued"]
    second = request(engine)
    assert not second["queued"] and second["job_id"] == first["job_id"]
    assert view(engine)["state"] == "queued"


def test_directory_only_job_persists_added_fields_without_any_signal(engine):
    request(engine)
    result = run(
        engine,
        lambda *_args, **_kwargs: persist(
            engine,
            phone="+33412345678",
            phone_source="model",
            phone_observed_at=NOW,
        ),
    )
    assert result.completed == 1
    actual = view(engine)
    assert actual["state"] == "partial" and actual["outcome"] == "enriched"
    assert actual["added_fields"] == ["phone"]
    assert request(engine)["job_id"] == actual["job_id"]
    assert request(engine, NOW + dt.timedelta(hours=1))["queued"]


def test_no_change_result_is_terminal_and_preserves_known_data(engine):
    seed(engine, phone="+33412345678")
    request(engine)
    run(engine, lambda *_args, **_kwargs: persist(engine))
    actual = view(engine)
    assert actual["outcome"] == "no_change" and actual["added_fields"] == []
    assert not actual["can_refresh"]


def test_fresh_complete_result_reuses_cache_but_stale_result_queues(engine):
    seed(
        engine,
        phone="+33412345678",
        website_url="https://alya.fr",
        domain="alya.fr",
        professional_email="contact@alya.fr",
        email_evidence_url="https://alya.fr/contact",
        email_source="site",
        email_verification_status="mx_verified",
        enrichment_observed_at=NOW,
        domain_observed_at=NOW,
        phone_observed_at=NOW,
        email_observed_at=NOW,
    )
    assert request(engine)["state"] == "ready"
    assert not request(engine)["queued"]
    assert request(engine, NOW + dt.timedelta(days=91))["queued"]


def test_budget_wait_preserves_request_and_uses_next_zurich_day(engine):
    request(engine)

    def exhausted(*_args, **_kwargs):
        raise DailyModelBudgetExhausted(
            usage="enrichment_judge",
            cap_usd=Decimal(2),
            actual_usd=Decimal(2),
            reserved_usd=Decimal(0),
            requested_usd=Decimal(".01"),
        )

    result = run(engine, exhausted)
    assert result.budget_usage == "enrichment_judge"
    actual = view(engine)
    assert actual["state"] == "budget_wait"
    assert actual["retry_after"] == "2026-09-14T22:00:00+00:00"
    assert run(engine, lambda *_args, **_kwargs: pytest.fail("not due")).processed == 0


def test_provider_failures_are_bounded_and_suppression_cannot_claim_success(engine):
    request(engine)

    def failure(*_args, **_kwargs):
        raise RuntimeError("provider detail must not leak")

    for offset in range(3):
        assert run(engine, failure, NOW + dt.timedelta(minutes=10 * offset)).failed == 1
    assert run(engine, failure, NOW + dt.timedelta(minutes=40)).processed == 0
    assert view(engine)["state"] == "failed"
    request(engine, NOW + dt.timedelta(hours=2))

    def suppressed(*_args, **_kwargs):
        return persist(engine, NOW + dt.timedelta(hours=2), suppressed_at=NOW)

    run(engine, suppressed, NOW + dt.timedelta(hours=2))
    assert view(engine)["state"] == "failed"


def test_reclaims_expired_lease_and_rejects_stale_completion(engine):
    from signals.companies.schema import company_directory_enrichment_job as job

    request(engine)
    with engine.begin() as connection:
        connection.execute(
            sa.update(job).values(
                status="running",
                attempt_count=1,
                claimed_by="dead-worker",
                lease_id="dead",
                started_at=NOW - dt.timedelta(hours=1),
                lease_expires_at=NOW - dt.timedelta(seconds=1),
            )
        )
    assert run(engine, lambda *_args, **_kwargs: persist(engine)).completed == 1
    assert view(engine)["outcome"] == "no_change"


@pytest.mark.parametrize(
    "website, stored_domain",
    [
        (None, "alya.fr"),
        ("alya.fr", "alya.fr"),
        ("alya.fr", "www.alya.fr"),
        ("new-alya.fr", "alya.fr"),
    ],
)
def test_model_pass_preserves_known_public_facts_and_stable_apollo_binding(
    engine, website, stored_domain
):
    seed(
        engine,
        phone="+33412345678",
        website_url="https://alya.fr",
        domain=stored_domain,
        apollo_organization_id="org-known",
        apollo_status="resolved",
        apollo_observed_at=NOW,
        professional_email="contact@alya.fr",
        email_source="model",
        enrichment_evidence={
            "candidate_pages": [
                {
                    "url": "https://alya.fr/contact",
                    "status_code": 200,
                    "published_emails": ["contact@alya.fr"],
                }
            ]
        },
        email_evidence_url="https://alya.fr/contact",
        email_observed_at=NOW,
    )
    store = SupplierDirectoryStore(engine)
    store.record_model_enrichment(
        SIREN,
        website=website,
        website_confidence=Decimal(".99") if website else None,
        website_evidence_url=f"https://{website}" if website else None,
        email=None,
        email_confidence=None,
        email_evidence_url=None,
        family=None,
        family_confidence=None,
        family_confirmed=False,
        director_display_name=None,
        director_title="Entreprise",
        phone=None,
        directors=(),
        notes="No additional email found",
        call_id=None,
        model="test/judge",
        cost_usd=Decimal(0),
        input_tokens=10,
        output_tokens=10,
        evidence={},
        decision={},
        reverification_reason="insufficient_evidence",
        observed_at=NOW + dt.timedelta(hours=1),
    )
    actual = store.get(SIREN)
    assert actual.phone == "+33412345678"
    assert actual.website_url == f"https://{website or 'alya.fr'}"
    if website != "new-alya.fr":
        assert actual.apollo_organization_id == "org-known" and actual.apollo_status == "resolved"
        assert actual.professional_email == "contact@alya.fr"
        assert actual.email_observed_at == NOW
        assert actual.email_source == "site"
        assert "email" not in view(engine)["missing_fields"]
    else:
        assert actual.apollo_organization_id is None and actual.apollo_status is None
        assert actual.professional_email is None


def test_paid_directory_click_queues_real_job_and_get_only_reads_progress(prepared):
    from signals.companies.schema import company_contact_lookup_attempt

    engine, _app, client = prepared
    seed(engine)
    key = f"cmp_directory_{SIREN}"
    before = client.get(f"/companies/{key}")
    assert before.status_code == 200
    assert before.json()["directory_enrichment"]["state"] == "available"
    clicked = client.post(f"/companies/{key}/directory-enrichment")
    assert clicked.status_code == 200, clicked.text
    assert clicked.json()["state"] == "queued"
    assert (
        client.get(f"/companies/{key}").json()["directory_enrichment"]["job_id"]
        == clicked.json()["job_id"]
    )
    assert not client.post(f"/companies/{key}/directory-enrichment").json()["queued"]
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(sa.func.count()).select_from(company_contact_lookup_attempt)
            )
            == 0
        )


def test_non_french_identity_never_queues_a_name_matched_company(prepared):
    from engagement_helpers import icp_of
    from engagement_helpers import seed as seed_signal

    engine, _, client = prepared
    seed_signal(engine, icp_of(client), count=1)
    key = client.get("/companies").json()["items"][0]["company_key"]
    result = client.post(f"/companies/{key}/directory-enrichment")
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "company_enrichment_identity_unavailable"


def test_request_migration_refuses_destructive_downgrade(tmp_path):
    from alembic import command

    from signals.persistence.database import alembic_config

    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'rollback.db'}")
    command.upgrade(alembic_config(engine), "0062_company_enrichment_requests")
    first = request(engine)
    with pytest.raises(RuntimeError, match="restore previous application"):
        command.downgrade(alembic_config(engine), "0061_company_live_merge")
    assert view(engine)["job_id"] == first["job_id"]
    engine.dispose()


def test_admission_bounds_global_queue_but_keeps_deduplicated_requests_readable(
    engine, monkeypatch
):
    from signals.company_research import company_requests as requests

    monkeypatch.setattr(requests, "MAX_PENDING_REQUESTS", 1)
    first = request(engine)
    assert request(engine)["job_id"] == first["job_id"]
    with engine.begin() as connection, pytest.raises(requests.CompanyEnrichmentQueueFull):
        requests.request_enrichment(connection, siren="732829320", now=NOW)


def test_account_admission_is_concurrent_work_limit_not_contact_quota(prepared, monkeypatch):
    from signals.companies.schema import company_directory_enrichment_job as jobs
    from signals.company_research import company_requests as requests

    engine, _, client = prepared
    seed(engine)
    monkeypatch.setattr(requests, "MAX_ACCOUNT_PENDING_REQUESTS", 1)
    first = client.post(f"/companies/cmp_directory_{SIREN}/directory-enrichment")
    assert first.status_code == 200 and first.json()["queued"]
    SupplierDirectoryStore(engine).upsert_identity(
        siren="732829320",
        legal_name="Second company",
        naf_code=None,
        family_key="",
        department=None,
        city=None,
        employees=None,
        observed_at=NOW,
    )
    second = client.post("/companies/cmp_directory_732829320/directory-enrichment")
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "company_enrichment_busy"
    # Once the first request terminates, the same account can start another.
    with engine.begin() as connection:
        connection.execute(sa.update(jobs).values(status="partial", outcome="no_change"))
    assert client.post("/companies/cmp_directory_732829320/directory-enrichment").json()["queued"]


def test_concurrent_admission_cannot_overfill_global_queue(engine, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from signals.company_research import company_requests as requests

    monkeypatch.setattr(requests, "MAX_PENDING_REQUESTS", 1)
    ready = Barrier(2)

    def enqueue(siren):
        ready.wait(timeout=5)
        try:
            with engine.begin() as connection:
                return requests.request_enrichment(connection, siren=siren, now=NOW)["queued"]
        except requests.CompanyEnrichmentQueueFull:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(enqueue, (SIREN, "732829320")))
    assert sorted(outcomes) == [False, True]


def test_exact_company_alias_deduplicates_even_when_account_admission_is_full(
    prepared, monkeypatch
):
    from engagement_helpers import icp_of
    from engagement_helpers import seed as seed_signal

    from signals.companies.schema import saas_company
    from signals.company_research import company_requests as requests

    engine, _, client = prepared
    seed_signal(engine, icp_of(client), count=1, offset=9)
    canonical = client.get("/companies").json()["items"][0]["company_key"]
    with engine.connect() as connection:
        alias = connection.scalar(sa.select(saas_company.c.company_key))
    assert canonical != alias
    monkeypatch.setattr(requests, "MAX_ACCOUNT_PENDING_REQUESTS", 1)
    first = client.post(f"/companies/{canonical}/directory-enrichment")
    second = client.post(f"/companies/{alias}/directory-enrichment")
    assert first.status_code == second.status_code == 200
    assert first.json()["queued"] and not second.json()["queued"]
    assert first.json()["job_id"] == second.json()["job_id"]


def test_stale_worker_lease_cannot_finish_replacement_generation(engine):
    from signals.companies.schema import company_directory_enrichment_job as job
    from signals.company_research.company_requests import _claim, _finish

    request(engine)
    claimed = _claim(engine, now=NOW, worker_ref="first-worker", limit=1)[0]
    with engine.begin() as connection:
        connection.execute(
            sa.update(job).values(
                job_id="replacement",
                status="queued",
                lease_id=None,
                lease_expires_at=None,
            )
        )
    assert not _finish(engine, claimed, NOW, status="partial", outcome="no_change")
    assert view(engine)["job_id"] == "replacement" and view(engine)["state"] == "queued"


def test_requests_only_command_reuses_budgeted_factory_without_winner_activation(
    engine, monkeypatch, tmp_path
):
    from signals.company_research import winner_worker as worker
    from signals.company_research.company_requests import CompanyRequestBatch

    monkeypatch.delenv("KIVOU_WINNER_ENRICHMENT_ACTIVATED_AT", raising=False)
    monkeypatch.setenv("KIVOU_WINNER_ENRICHMENT_LOCK_FILE", str(tmp_path / "worker.lock"))
    monkeypatch.setenv("KIVOU_SERPER_API_KEY", "offline-test")
    monkeypatch.setattr(worker, "create_database_engine", lambda: engine)
    monkeypatch.setattr(
        worker, "CompanyWebCollector", lambda **_kwargs: SimpleNamespace(_renderer=None)
    )
    monkeypatch.setattr(
        worker,
        "AnnuaireRawDirectorClient",
        lambda **_kwargs: SimpleNamespace(profile=lambda _: None),
    )
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(judge=object(), arbiter=object())

    monkeypatch.setattr(worker, "company_enrichment_providers_from_environment", factory)
    monkeypatch.setattr(
        worker, "run_company_enrichment_requests", lambda *_args, **kwargs: CompanyRequestBatch()
    )
    monkeypatch.setattr(
        worker,
        "run_winner_company_enrichment_batch",
        lambda *_args, **_kwargs: pytest.fail("automatic winners are out of scope"),
    )
    assert worker.main(["--requests-only", "--limit", "5"]) == 0
    assert len(calls) == 1 and calls[0]["engine"] is engine


def test_disabled_worker_hides_enrichment_capability_and_rejects_post(shared_prepared):
    from signals.companies.schema import company_directory_enrichment_job as jobs

    engine, _, client = shared_prepared
    seed(engine)
    key = f"cmp_directory_{SIREN}"
    actual = client.get(f"/companies/{key}").json()
    assert actual["capabilities"]["can_enrich_company"] is False
    denied = client.post(f"/companies/{key}/directory-enrichment")
    assert (
        denied.status_code == 503
        and denied.json()["detail"]["code"] == "company_enrichment_unavailable"
    )
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(jobs)) == 0


def test_manual_worker_availability_is_explicit_and_false_by_default(monkeypatch):
    from signals.api.config import ApiConfig

    monkeypatch.delenv("KIVOU_COMPANY_DIRECTORY_ENRICHMENT_ENABLED", raising=False)
    assert ApiConfig().company_directory_enrichment_enabled is False
    assert ApiConfig.from_environment().company_directory_enrichment_enabled is False
    monkeypatch.setenv("KIVOU_COMPANY_DIRECTORY_ENRICHMENT_ENABLED", "true")
    assert ApiConfig.from_environment().company_directory_enrichment_enabled is True


def test_no_result_pass_does_not_mark_preserved_stale_contacts_fresh(engine):
    old = NOW - dt.timedelta(days=91)
    seed(
        engine,
        phone="+33412345678",
        website_url="https://alya.fr",
        domain="alya.fr",
        professional_email="contact@alya.fr",
        email_evidence_url="https://alya.fr/contact",
        email_source="site",
        enrichment_observed_at=old,
        domain_observed_at=old,
        phone_observed_at=old,
        email_observed_at=old,
    )
    request(engine)
    run(engine, lambda *_args, **_kwargs: persist(engine))
    actual = view(engine)
    assert actual["state"] == "partial"
    assert actual["outcome"] == "no_change"
    assert actual["stale_fields"] == ["email", "phone", "website"]
    assert actual["missing_fields"] == []
    assert request(engine, NOW + dt.timedelta(hours=1))["queued"]


def test_real_completion_clock_accepts_observations_after_batch_start(engine):
    request(engine)
    observed = NOW + dt.timedelta(seconds=1)
    finished = NOW + dt.timedelta(seconds=2)
    current = [NOW]

    def enrich(*_args, **_kwargs):
        current[0] = finished
        return persist(
            engine,
            observed,
            phone="+33412345678",
            website_url="https://alya.fr",
            domain="alya.fr",
            professional_email="contact@alya.fr",
            email_evidence_url="https://alya.fr/contact",
            email_source="site",
            domain_observed_at=observed,
            phone_observed_at=observed,
            email_observed_at=observed,
        )

    assert run(engine, enrich, clock=lambda: current[0]).completed == 1
    actual = view(engine, finished)
    assert actual["state"] == "ready" and actual["stale_fields"] == []
    assert actual["finished_at"] == finished.isoformat()


def test_changed_existing_phone_is_enriched_without_claiming_an_added_field(engine):
    seed(engine, phone="+33412345678", phone_observed_at=NOW)
    request(engine)
    run(
        engine,
        lambda *_args, **_kwargs: persist(engine, phone="+33412345679", phone_observed_at=NOW),
    )
    actual = view(engine)
    assert actual["outcome"] == "enriched"
    assert actual["added_fields"] == []


def test_fresh_complete_data_supplied_after_partial_job_reuses_existing_result(engine):
    request(engine)
    run(engine, lambda *_args, **_kwargs: persist(engine))
    completed = view(engine)
    assert completed["state"] == "partial"
    later = NOW + dt.timedelta(hours=2)
    persist(
        engine,
        later,
        phone="+33412345678",
        website_url="https://alya.fr",
        domain="alya.fr",
        professional_email="contact@alya.fr",
        email_evidence_url="https://alya.fr/contact",
        email_source="site",
        domain_observed_at=later,
        phone_observed_at=later,
        email_observed_at=later,
    )
    reused = request(engine, later)
    assert reused["state"] == "ready"
    assert not reused["queued"] and reused["job_id"] == completed["job_id"]
