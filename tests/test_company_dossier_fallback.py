"""Persistent private work does not require a current matching signal or a registry cache."""

import pytest
import sqlalchemy as sa
from engagement_helpers import Clock, icp_of, make_app, make_engine, pay, seed, signed_up


@pytest.fixture
def prepared(tmp_path):
    engine = make_engine(tmp_path)
    app = make_app(engine, Clock())
    client = signed_up(app)
    pay(engine, client, plan="pro")
    return engine, app, client


def test_followed_company_dossier_and_private_work_survive_profile_change(prepared):
    engine, app, client = prepared
    profile = icp_of(client)
    seed(engine, profile, count=1)
    company_key = client.get("/companies").json()["items"][0]["company_key"]
    assert not company_key.startswith("cmp_directory_")
    assert client.put(f"/companies/{company_key}/prospection", json={}).status_code == 200
    text = "  Première ligne\n\n  Deuxième ligne  \n"
    assert (
        client.put(
            f"/companies/{company_key}/note", json={"body": text, "expected_revision": 0}
        ).status_code
        == 200
    )
    changed = client.patch(f"/target-icps/{profile}", json={"customer_input": {}})
    assert changed.status_code == 200
    assert changed.json()["status"] == "draft"
    assert [row["company_key"] for row in client.get("/companies").json()["items"]] == [company_key]
    response = client.get(f"/companies/{company_key}")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["official_identity"]["name"]
    assert result["signals"] == result["related_signals"] == []
    assert result["note"] == text
    assert all(event["signal_key"] is None for event in result["history"])
    assert result["membership"]["tracked"] is True
    assert (
        client.put(
            f"/companies/{company_key}/note", json={"body": text + "Suite", "expected_revision": 1}
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/companies/{company_key}/manual-contact",
            json={"name": "Alice", "email": "alice@example.com", "expected_revision": 0},
        ).status_code
        == 200
    )
    other = signed_up(app, "no-follow@example.com")
    assert other.get(f"/companies/{company_key}").status_code == 404
    assert other.get(f"/companies/{company_key}/manual-contact").status_code == 404


def test_canonical_siren_key_opens_owned_holder_without_a_registry_cache(prepared):
    engine, app, client = prepared
    seed(engine, icp_of(client), count=1, offset=9)
    listed = client.get("/companies")
    assert listed.status_code == 200, listed.text
    key = listed.json()["items"][0]["company_key"]
    assert key.startswith("cmp_directory_")
    response = client.get(f"/companies/{key}")
    assert response.status_code == 200, response.text
    assert response.json()["official_identity"]["name"]
    assert response.json()["related_signals"]
    assert response.json()["company_key"] == key
    assert (
        client.put(
            f"/companies/{key}/note", json={"body": "Note BOAMP", "expected_revision": 0}
        ).status_code
        == 200
    )
    other = signed_up(app, "no-canonical-access@example.com")
    assert other.get(f"/companies/{key}").status_code == 404


@pytest.mark.parametrize("cached_directory", [False, True])
def test_canonical_dossier_uses_exact_history_without_global_award_scan(
    prepared, monkeypatch, cached_directory
):
    from test_saas_company_api import _insert_directory_company

    from signals.client_value import history

    engine, _, client = prepared
    seed(engine, icp_of(client), count=1, offset=9)
    key = client.get("/companies").json()["items"][0]["company_key"]
    assert key.startswith("cmp_directory_")
    if cached_directory:
        with engine.begin() as connection:
            _insert_directory_company(
                connection,
                siren=key.removeprefix("cmp_directory_"),
                name="Libellé du registre différent de l'avis",
            )
    fallback_calls = []
    fallback = history._fallback_award_rows

    def record_fallback(*args, **kwargs):
        fallback_calls.append(True)
        return fallback(*args, **kwargs)

    monkeypatch.setattr(history, "_fallback_award_rows", record_fallback)
    response = client.get(f"/companies/{key}")
    assert response.status_code == 200, response.text
    assert fallback_calls == []
    assert response.json()["market_summary"]["resolution"] == "company_key"
    assert response.json()["market_summary"]["last_12_months"]["awards_count"] == 1


def test_quarantined_signal_holder_is_not_regrouped_by_list_or_canonical_fallback(prepared):
    from test_company_entity_aliases import NOW

    from signals.client_value.company_identity import register_alias
    from signals.companies.schema import saas_company

    engine, _, client = prepared
    seed(engine, icp_of(client), count=1, offset=9)
    initial = client.get("/companies").json()["items"][0]
    canonical = initial["company_key"]
    assert canonical.startswith("cmp_directory_") and canonical != "cmp_directory_732829320"
    with engine.connect() as connection:
        alias = connection.scalar(sa.select(saas_company.c.company_key))
    assert client.get(f"/companies/{alias}").status_code == 200
    with engine.begin() as connection:
        register_alias(connection, company_key=alias, siren="732829320", now=NOW)
    # Neither a source-identity fallback nor a durable old override may undo
    # quarantine in the list or grant access via the former canonical key.
    listed = client.get("/companies")
    assert listed.status_code == 200
    assert [row["company_key"] for row in listed.json()["items"]] == [alias]
    assert client.get(f"/companies/{canonical}").status_code == 404
    profile = client.get(f"/companies/{alias}")
    assert profile.status_code == 200
    assert profile.json()["identity_resolution"] == "unresolved"


def test_note_read_models_preserve_whitespace_for_both_dossier_variants():
    # Validate just the field's inherited schema: neither model may normalize
    # account-owned text as if it were an official source label.
    from pydantic import TypeAdapter

    from signals.companies.contracts import CompanyProfile, DirectoryCompanyProfileView

    for model in (CompanyProfile, DirectoryCompanyProfileView):
        field = model.model_fields["note"]
        text = "  Garder\n\n  les espaces  \n"
        assert (
            TypeAdapter(
                field.rebuild_annotation(), config={"str_strip_whitespace": True}
            ).validate_python(text)
            == text
        )


def test_discovery_cannot_queue_directory_enrichment(prepared, monkeypatch):
    from signals.api import routes_companies

    engine, app, _ = prepared
    client = signed_up(app, "discovery-enrichment@example.com")
    seed(engine, icp_of(client), count=1)
    client.get("/signals")
    key = client.get("/companies").json()["items"][0]["company_key"]
    assert client.get(f"/companies/{key}").json()["capabilities"]["can_enrich_company"] is False
    calls = []
    monkeypatch.setattr(
        routes_companies,
        "requeue_winner_enrichments",
        lambda *args, **kwargs: calls.append(kwargs) or 1,
    )
    response = client.post(f"/companies/{key}/directory-enrichment")
    assert response.status_code == 403, response.text
    assert calls == []

    class Lookup:
        def research(self, **kwargs):
            calls.append(kwargs)
            raise AssertionError("a locked lookup must not call the provider service")

    app.state.company_contact_lookup_service = Lookup()
    lookup = client.post(f"/companies/{key}/contact-lookup")
    assert lookup.status_code == 403, lookup.text
    assert lookup.json()["detail"]["code"] == "contact_lookup_locked"
    assert calls == []


def test_discovery_private_only_profile_masks_official_website_without_hiding_availability(
    prepared,
):
    from signals.companies.schema import saas_company

    engine, app, _ = prepared
    client = signed_up(app, "private-website@example.com")
    profile = icp_of(client)
    seed(engine, profile, count=1)
    client.get("/signals")
    key = client.get("/companies").json()["items"][0]["company_key"]
    assert client.put(f"/companies/{key}/prospection", json={}).status_code == 200
    assert client.patch(f"/target-icps/{profile}", json={"customer_input": {}}).status_code == 200
    with engine.begin() as connection:
        connection.execute(
            sa.update(saas_company)
            .where(saas_company.c.company_key == key)
            .values(official_website_url="https://protected-website.example.com/")
        )
    response = client.get(f"/companies/{key}")
    assert response.status_code == 200, response.text
    assert response.json()["official_identity"]["website_url"] is None
    assert "protected-website.example.com" not in response.text
    assert "website" in response.json()["available_fields"]


def test_directory_note_roundtrip_keeps_exact_spaces_and_newlines(prepared):
    from test_saas_company_api import _insert_directory_company

    engine, _, client = prepared
    with engine.begin() as connection:
        _insert_directory_company(connection, siren="331364729", name="Exact note")
    key = "cmp_directory_331364729"
    text = "  Ligne A\n\n  Ligne B  \n"
    written = client.put(f"/companies/{key}/note", json={"body": text, "expected_revision": 0})
    assert written.status_code == 200
    assert client.get(f"/companies/{key}").json()["note"] == text
