"""The scheduled transport cannot import into production or follow redirects."""

import dataclasses
import importlib

import httpx
import pytest
from test_catalogue_publication import NOW, TOKEN, publication, seed
from test_saas_company_api import engine as engine  # noqa: PLC0414


def worker():
    try:
        return importlib.import_module("signals.supplier_directory.catalogue_worker")
    except ModuleNotFoundError:
        pytest.fail("the staging-only catalogue transport is not implemented")


def test_worker_config_is_closed_and_secret_free(monkeypatch):
    module = worker()
    for key in (
        "KIVOU_ACQUISITION_ENVIRONMENT",
        "KIVOU_DATABASE_URL",
        "KIVOU_CATALOGUE_PUBLICATION_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError):
        module.MirrorConfiguration.from_environment()
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", "STAGING")
    monkeypatch.setenv("KIVOU_DATABASE_URL", "postgresql+psycopg://localhost/kivou_staging")
    monkeypatch.setenv("KIVOU_CATALOGUE_PUBLICATION_TOKEN", TOKEN)
    config = module.MirrorConfiguration.from_environment()
    assert TOKEN not in repr(config) and "postgresql" not in repr(config)
    assert config.environment == "STAGING"
    for url in (
        "postgresql://localhost/kivou",
        "sqlite:///kivou_staging",
        "postgresql://localhost/kivou_staging?dbname=kivou",
    ):
        with pytest.raises(ValueError):
            dataclasses.replace(config, database_url=url)
    with pytest.raises(ValueError):
        dataclasses.replace(config, environment="PRODUCTION")


def test_download_uses_fixed_https_source_and_validates_snapshot(engine):
    module = worker()
    seed(engine)
    with engine.connect() as connection:
        payload = publication().build_snapshot(connection, now=NOW).model_dump(mode="json")
    calls = []

    def respond(request):
        calls.append(request)
        assert request.url == "https://kivou.eu/api/internal/company-catalogue"
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False) as client:
        result = module.download_snapshot(client, token=TOKEN)
    assert result.total == 1 and len(calls) == 1


@pytest.mark.parametrize("status", [301, 302, 307, 401, 403, 500])
def test_download_never_follows_redirect_or_accepts_http_error(status):
    module = worker()
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://elsewhere.invalid/"})

    # Even a caller-supplied redirect-following client must not forward the secret.
    with (
        httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True) as client,
        pytest.raises(ValueError, match="transport"),
    ):
        module.download_snapshot(client, token=TOKEN)
    assert len(calls) == 1


def test_download_rejects_oversized_body_before_parsing(monkeypatch):
    module = worker()
    monkeypatch.setattr(module, "MAX_SNAPSHOT_BYTES", 64)
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"{" + b" " * 100 + b"}")
            )
        ) as client,
        pytest.raises(ValueError, match="size"),
    ):
        module.download_snapshot(client, token=TOKEN)
