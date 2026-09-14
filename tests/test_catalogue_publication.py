"""Only shareable company facts cross the isolated environment boundary."""

import dataclasses
import datetime as dt
import importlib
import json
from decimal import Decimal

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_saas_company_api import _insert_directory_company
from test_saas_company_api import engine as engine  # noqa: PLC0414

from signals.api import ApiConfig, create_app
from signals.persistence.schema import supplier_directory

NOW = dt.datetime(2026, 9, 14, 9, tzinfo=dt.UTC)
TOKEN = "catalogue-read-only-test-token-1234567890"


def publication():
    try:
        return importlib.import_module("signals.supplier_directory.catalogue_publication")
    except ModuleNotFoundError:
        pytest.fail("the bounded public catalogue publisher is not implemented")


def seed(engine, *, siren="481153435", name="Entreprise réelle"):
    with engine.begin() as connection:
        _insert_directory_company(connection, siren=siren, name=name)
        connection.execute(
            supplier_directory.update()
            .where(supplier_directory.c.siren == siren)
            .values(
                domain="entreprise.fr",
                website_url="https://entreprise.fr/",
                professional_email="bonjour@entreprise.fr",
                email_source="site",
                email_evidence_url="https://entreprise.fr/contact",
                email_observed_at=NOW,
                domain_observed_at=NOW,
                updated_at=NOW,
                family_confidence=Decimal("0.95"),
                enrichment_observed_at=NOW,
                enrichment_notes="PRIVATE_MODEL_TRACE",
                enrichment_model_id="PRIVATE_MODEL",
                enrichment_evidence={"private": "RAW_PAGE_CONTENT"},
                apollo_organization_id="LICENSED_PROVIDER_ID",
                apollo_status="resolved",
            )
        )


def test_snapshot_is_complete_and_excludes_internal_and_unpublished_fields(engine):
    module = publication()
    seed(engine)
    seed(engine, siren="808315972", name="Non publiée")
    with engine.begin() as connection:
        connection.execute(
            supplier_directory.update()
            .where(supplier_directory.c.siren == "808315972")
            .values(professional_email="private@entreprise.fr", email_source="manual")
        )
        snapshot = module.build_snapshot(connection, now=NOW)
    payload = snapshot.model_dump(mode="json")
    assert payload["version"] == 1 and payload["complete"] is True
    assert payload["source"] == "production" and payload["total"] == 2
    assert len(payload["rows"]) == 2
    first = next(row for row in payload["rows"] if row["siren"] == "481153435")
    assert first["professional_email"] == "bonjour@entreprise.fr"
    assert first["email_source"] == "site"
    assert first["email_evidence_url"] == "https://entreprise.fr/contact"
    second = next(row for row in payload["rows"] if row["siren"] == "808315972")
    assert second["professional_email"] is None
    raw = json.dumps(payload)
    for forbidden in (
        "PRIVATE_MODEL",
        "RAW_PAGE",
        "LICENSED_PROVIDER",
        "private@",
        "enrichment_call_id",
        "account_id",
        "enrichment_cost_usd",
    ):
        assert forbidden not in raw
    assert module.CatalogueSnapshot.model_validate(payload) == snapshot


def test_suppressed_companies_are_not_published(engine):
    module = publication()
    seed(engine)
    with engine.begin() as connection:
        connection.execute(supplier_directory.update().values(suppressed_at=NOW))
        result = module.build_snapshot(connection, now=NOW)
    assert result.total == 0 and result.rows == ()


def test_publication_endpoint_fails_closed_by_environment_and_token(engine):
    assert "catalogue_publication_token" in ApiConfig.__dataclass_fields__, (
        "catalogue credential must be explicit, absent by default and excluded from repr"
    )
    config = ApiConfig(acquisition_environment="PRODUCTION", catalogue_publication_token=TOKEN)
    assert TOKEN not in repr(config)
    seed(engine)
    client = TestClient(create_app(engine, config, now_override=lambda: NOW))
    calls = []

    @sa.event.listens_for(engine, "before_cursor_execute")
    def record_sql(*args):
        calls.append(True)

    try:
        assert client.get("/internal/company-catalogue").status_code == 404
        assert (
            client.get(
                "/internal/company-catalogue", headers={"Authorization": "Bearer wrong"}
            ).status_code
            == 404
        )
        assert not calls
        response = client.get(
            "/internal/company-catalogue", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.headers["cache-control"] == "no-store"
        staging = TestClient(
            create_app(engine, dataclasses.replace(config, acquisition_environment="STAGING"))
        )
        assert (
            staging.get(
                "/internal/company-catalogue", headers={"Authorization": f"Bearer {TOKEN}"}
            ).status_code
            == 404
        )
    finally:
        sa.event.remove(engine, "before_cursor_execute", record_sql)


def test_snapshot_rejects_tampering_duplicates_and_unknown_fields(engine):
    module = publication()
    seed(engine)
    with engine.connect() as connection:
        original = module.build_snapshot(connection, now=NOW).model_dump(mode="json")
    for mutation in (
        lambda value: value.update(total=99),
        lambda value: value.update(complete=False),
        lambda value: value["rows"][0].update(legal_name="Tampered"),
        lambda value: value["rows"][0].update(account_id="private"),
        lambda value: value.update(source="staging"),
    ):
        payload = json.loads(json.dumps(original))
        mutation(payload)
        with pytest.raises(ValueError):
            module.CatalogueSnapshot.model_validate(payload)


def test_publisher_strips_unsafe_urls_and_director_extras(engine):
    module = publication()
    seed(engine)
    with engine.begin() as connection:
        connection.execute(
            supplier_directory.update().values(
                website_url="https://user:SECRET_PASSWORD@entreprise.fr/",
                contact_form_url="javascript:alert(1)",
                domain_validation_evidence_url="http://localhost/private",
                directors=[{"name": "Nom Public", "title": "Président", "private": "EXTRA_SECRET"}],
            )
        )
        payload = module.build_snapshot(connection, now=NOW).model_dump(mode="json")
    company = payload["rows"][0]
    assert company["website_url"] is None
    assert company["contact_form_url"] is None
    assert company["domain_validation_evidence_url"] is None
    assert company["professional_email"] is None
    assert "SECRET" not in json.dumps(payload)


def test_valid_digest_is_not_enough_for_unsafe_import_or_duplicate_identity(engine):
    module = publication()
    seed(engine)
    with engine.connect() as connection:
        original = module.build_snapshot(connection, now=NOW)
    with pytest.raises(ValueError, match="duplicate"):
        module.make_snapshot(original.rows + original.rows, now=NOW)
    for patch in (
        {"website_url": "https://user:password@entreprise.fr/"},
        {"email_evidence_url": "https://other-company.fr/contact"},
        {"email_source": "manual"},
        {"website_url": 123},
        {"directors": None},
    ):
        modified = {**original.rows[0], **patch}
        with pytest.raises(ValueError):
            module.make_snapshot((modified,), now=NOW)
