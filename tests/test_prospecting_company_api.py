import sqlalchemy as sa
from test_saas_company_api import _insert_directory_company, _signup
from test_saas_company_api import app as app  # noqa: PLC0414 — pytest fixture re-export
from test_saas_company_api import engine as engine  # noqa: PLC0414 — pytest fixture re-export

from signals.engagement.prospecting_schema import account_company_membership


def test_discovery_directory_hides_fields_but_keeps_private_work(app, engine):
    with engine.begin() as connection:
        _insert_directory_company(connection, siren="331364729", name="Exemple béton")
    client = _signup(app, email="private-work@example.com")
    key = "cmp_directory_331364729"
    first = client.get("/companies/directory/331364729")
    assert first.status_code == 200
    body = first.json()
    assert body["private_subject_key"] == key
    assert body["capabilities"]["can_view_company_data"] is False
    assert "egli.example" not in first.text and "Anna Egli" not in first.text
    assert "employees" not in body["directory"]
    with engine.begin() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(account_company_membership)
            ).scalar_one()
            == 0
        )
    saved = client.put(
        f"/companies/{key}/manual-contact",
        json={
            "name": "Alice",
            "email": "alice@example.com",
            "expected_revision": 0,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    note = client.put(
        f"/companies/{key}/note", json={"body": "Mon rendez-vous", "expected_revision": 0}
    )
    assert note.status_code == 200, note.text
    assert note.json()["revision"] == 1
    assert client.put(f"/companies/{key}/note", json={"body": "Ancien client"}).status_code == 409
    follow = client.put(f"/companies/{key}/prospection", json={})
    assert follow.status_code == 200 and follow.json()["tracked"] is True
    second = client.get("/companies/directory/331364729").json()
    assert second["manual_contact"]["contact"]["name"] == "Alice"
    assert second["note"] == "Mon rendez-vous" and second["note_revision"] == 1
    assert second["membership"]["tracked"] is True
    other = _signup(app, email="private-work-other@example.com")
    foreign = other.get("/companies/directory/331364729").json()
    assert foreign.get("note") is None and foreign["manual_contact"]["contact"] is None
    assert foreign["membership"]["tracked"] is False
    assert (
        client.delete(f"/companies/{key}/manual-contact", headers={"If-Match": '"1"'}).status_code
        == 200
    )
    assert client.get(f"/companies/{key}/manual-contact").json()["revision"] == 2


def test_company_note_and_manual_contact_refuse_unknown_or_cross_account_authority(app, engine):
    with engine.begin() as connection:
        _insert_directory_company(connection, siren="331364729", name="Exemple béton")
    client = _signup(app, email="private-work-validation@example.com")
    root = "/companies/cmp_directory_331364729"
    assert client.put(root + "/prospection", json={"account_id": "other"}).status_code == 422
    assert (
        client.put(
            root + "/manual-contact",
            json={
                "name": "Alice",
                "email": "alice@example.com",
                "expected_revision": 0,
                "account_id": "other",
            },
        ).status_code
        == 422
    )
    assert client.delete(root + "/manual-contact").status_code == 422
    assert client.put("/companies/cmp_directory_732829320/prospection", json={}).status_code == 404


def test_directory_rejects_private_canonicalization_after_exact_identity_contradiction(app, engine):
    from test_saas_company_api import NOW

    from signals.client_value.company_identity import register_alias
    from signals.engagement.schema import company_note

    client = _signup(app, email="quarantine@example.com")
    owner = client.get("/me").json()["account_id"]
    key = "cmp_directory_331364729"
    wrong = "cmp_directory_732829320"
    with engine.begin() as connection:
        _insert_directory_company(connection, siren="331364729", name="Actual company")
        register_alias(connection, company_key=key, siren="732829320", now=NOW)
        connection.execute(
            company_note.insert(),
            {
                "account_id": owner,
                "company_key": wrong,
                "body": "Other legal company note",
                "revision": 1,
                "created_at": NOW,
                "updated_at": NOW,
            },
        )
    response = client.get("/companies/directory/331364729")
    assert response.status_code == 200
    body = response.json()
    assert body["identity_resolution"] == "unresolved"
    assert body["private_subject_key"] == key
    assert body.get("note") is None and "Other legal company note" not in response.text
    saved = client.put(
        f"/companies/{key}/note", json={"body": "Own isolated note", "expected_revision": 0}
    )
    assert saved.status_code == 200 and saved.json()["revision"] == 1
    assert client.get("/companies/directory/331364729").json()["note"] == "Own isolated note"
    with engine.connect() as connection:
        assert (
            connection.scalar(
                sa.select(company_note.c.body).where(company_note.c.company_key == wrong)
            )
            == "Other legal company note"
        )
