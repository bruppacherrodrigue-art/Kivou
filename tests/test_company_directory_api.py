import sqlalchemy as sa
from test_saas_company_api import _insert_directory_company, _signup
from test_saas_company_api import app as app  # noqa: PLC0414 — pytest fixture re-export
from test_saas_company_api import engine as engine  # noqa: PLC0414 — pytest fixture re-export

from signals.persistence.schema import supplier_directory


def test_directory_searches_all_pages_and_binds_cursor_to_filters(app, engine):
    with engine.begin() as connection:
        for index in range(47):
            _insert_directory_company(
                connection,
                siren=f"{331364700 + index:09}",
                name=f"Entreprise {index:02}",
                city="Nice" if index == 46 else "Paris",
            )
    client = _signup(app, email="directory-pages@example.com")
    response = client.get("/companies/directory?limit=20&sort=name")
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["counts"] == {"total": 47, "exact": True}
    assert len(first["items"]) == 20 and first["page"]["has_more"] is True
    cursor = first["page"]["next_cursor"]
    second = client.get(
        "/companies/directory", params={"limit": 20, "sort": "name", "cursor": cursor}
    ).json()
    assert not {item["company_key"] for item in first["items"]} & {
        item["company_key"] for item in second["items"]
    }
    found = client.get("/companies/directory?q=Nice").json()
    assert found["counts"]["total"] == 1 and found["items"][0]["name"] == "Entreprise 46"
    assert (
        client.get("/companies/directory", params={"cursor": cursor, "q": "Nice"}).status_code
        == 422
    )
    assert client.get("/companies/directory?limit=51").status_code == 422
    assert client.get("/companies/directory?account_id=other").status_code == 422
    assert "Anna Egli" not in response.text and "egli.example" not in response.text


def test_directory_modes_do_not_depend_on_owned_signal_list(app, engine):
    with engine.begin() as connection:
        _insert_directory_company(
            connection, siren="331364729", name="Sans marché accessible", department="06"
        )
    client = _signup(app, email="directory-independent@example.com")
    rows = client.get("/companies/directory?department=06&family=ready_mix_concrete").json()
    assert rows["counts"]["total"] == 1
    assert client.get("/companies/directory?department=75").json()["counts"]["total"] == 0
    assert client.get("/companies/directory?sort=hostile").status_code == 422


def test_directory_keyword_search_includes_activity_without_changing_identity(app, engine):
    with engine.begin() as connection:
        _insert_directory_company(connection, siren="331364729", name="Entreprise Exemple")
        connection.execute(
            sa.update(supplier_directory)
            .where(supplier_directory.c.siren == "331364729")
            .values(naf_label="Fabrication de béton", naf_code="2363Z")
        )
    client = _signup(app, email="directory-activity@example.com")
    for query in ["béton", "2363Z"]:
        response = client.get("/companies/directory", params={"q": query})
        assert response.status_code == 200
        assert response.json()["counts"]["total"] == 1
        assert response.json()["items"][0]["name"] == "Entreprise Exemple"


def test_directory_uses_the_mail_holder_normalizer_in_list_and_profile(app, engine):
    with engine.begin() as connection:
        _insert_directory_company(
            connection,
            siren="331364729",
            name="CONSTRUCTION DE MAISONS ET CHARPENTES DU DAUPHINE - CMCD",
        )
    client = _signup(app, email="directory-name-parity@example.com")

    listed = client.get("/companies/directory").json()["items"]
    profile = client.get("/companies/directory/331364729").json()

    assert listed[0]["name"] == "CMCD"
    assert listed[0]["directory"]["name"] == "CMCD"
    assert profile["directory"]["name"] == "CMCD"


def test_directory_options_are_authenticated_bounded_and_match_existing_catalog(app):
    from starlette.testclient import TestClient

    from signals.supplier_discovery.families import load_supplier_family_catalog

    assert TestClient(app).get("/companies/directory/options").status_code == 401
    client = _signup(app, email="directory-options@example.com")
    response = client.get("/companies/directory/options")
    assert response.status_code == 200, response.text
    data = response.json()
    actual = {family["key"]: family["label"] for family in data["families"]}
    expected = {
        family.key: family.label_fr
        for families in load_supplier_family_catalog().values()
        for family in families
    }
    assert actual == expected
    assert {"code": "06", "label": "Alpes-Maritimes"} in data["departments"]
    assert len(data["departments"]) <= 110
    assert "apollo_tags" not in response.text
    assert client.get("/companies/directory/options?account_id=other").status_code == 422
