"""Public contact continuity without merging organizations or private work."""

import datetime as dt
import importlib
import importlib.util
import json

import pytest
from test_notice_projection import facts_with_contacts

from signals.api.notice_projection import project_notice_facts
from signals.billing.catalogue import entitlements_for
from signals.client_value.notice_facts import IdentifierFact, TextFact


def contact_api():
    name = "signals.client_value.company_contacts"
    assert importlib.util.find_spec(name), "the shared public contact projection is missing"
    return importlib.import_module(name)


def grouped_facts():
    facts = facts_with_contacts()
    holder = facts.winning_parties[0].members[0]
    first = holder.model_copy(
        update={
            "identifiers": (
                IdentifierFact(scheme="SIRET", value="56213603600885", source_path="id"),
            ),
        }
    )
    second = holder.model_copy(
        update={
            "organization_ref": "ORG-AGENCY",
            "name": TextFact(value="Agence distincte", source_path="name"),
            "identifiers": (
                IdentifierFact(scheme="SIRET", value="56213603600018", source_path="id"),
            ),
            "email": TextFact(value="agency@example.com", source_path="email"),
        }
    )
    stranger = holder.model_copy(
        update={
            "organization_ref": "ORG-OTHER",
            "identifiers": (),
            "email": TextFact(value="stranger@example.com", source_path="email"),
        }
    )
    return facts.model_copy(
        update={
            "winning_parties": (
                facts.winning_parties[0].model_copy(update={"members": (first, second, stranger)}),
            )
        }
    )


def test_notice_contacts_include_their_exact_identity_and_publication_source():
    facts = grouped_facts()
    contact = project_notice_facts(facts, entitlements=entitlements_for("pro"))["contacts"][0]
    assert contact.get("source_url") == facts.source.source_url
    assert contact.get("identifiers") == [{"scheme": "SIRET", "value": "56213603600885"}]


def test_establishment_contacts_keep_full_siret_and_never_match_names():
    contacts = contact_api().notice_contacts(
        grouped_facts(), identifiers=[{"scheme": "BOAMP-COMPANY-ID", "value": "562 136 036 00885"}]
    )
    assert [contact["email"] for contact in contacts] == ["contact@example.com"]
    assert contact_api().notice_contacts(grouped_facts(), identifiers=[]) == []


def test_canonical_entity_keeps_each_matching_agency_but_excludes_unidentified_members():
    contacts = contact_api().notice_contacts(grouped_facts(), siren="562136036")
    assert {contact["email"] for contact in contacts} == {
        "contact@example.com",
        "agency@example.com",
    }
    assert len({json.dumps(contact["identifiers"]) for contact in contacts}) == 2


def test_suppressed_public_notice_company_has_no_contact_availability():
    contacts = contact_api().notice_contacts(
        grouped_facts(), siren="562136036", suppressed_sirens={"562136036"}
    )
    assert contacts == []


def test_conflicting_french_identifiers_are_not_contact_identity_proof():
    facts = grouped_facts()
    holder = facts.winning_parties[0].members[0]
    contradictory = holder.model_copy(
        update={
            "identifiers": (
                *holder.identifiers,
                IdentifierFact(scheme="SIREN", value="481153435", source_path="id"),
            )
        }
    )
    facts = facts.model_copy(
        update={
            "winning_parties": (
                facts.winning_parties[0].model_copy(update={"members": (contradictory,)}),
            )
        }
    )
    assert (
        contact_api().notice_contacts(
            facts,
            identifiers=[
                {"scheme": "SIRET", "value": "56213603600885"},
            ],
        )
        == []
    )


@pytest.mark.parametrize("plan", ["discovery", "essential", "pro"])
def test_public_contact_rights_remove_values_and_provenance_together(plan):
    contacts = contact_api().notice_contacts(grouped_facts(), siren="562136036")
    projection = contact_api().project_contacts(contacts, entitlements=entitlements_for(plan))
    assert set(projection["available_contact_fields"]) == {"phone", "email", "website"}
    assert projection["contacts_locked"] is (plan == "discovery")
    assert bool(projection["public_contacts"]) is (plan != "discovery")
    if plan == "discovery":
        assert "contact@example.com" not in json.dumps(projection)
        assert "ORG-" not in json.dumps(projection)


def test_discovery_phone_only_contact_advertises_only_phone_in_both_views():
    facts = facts_with_contacts()
    party = facts.winning_parties[0]
    phone_only = party.members[0].model_copy(update={"email": None, "website": None})
    facts = facts.model_copy(
        update={"winning_parties": (party.model_copy(update={"members": (phone_only,)}),)}
    )
    rights = entitlements_for("discovery")
    signal = project_notice_facts(facts, entitlements=rights)
    company = contact_api().project_contacts(
        contact_api().notice_contacts(facts), entitlements=rights
    )
    assert signal["available_contact_fields"] == company["available_contact_fields"] == ["phone"]
    assert signal["contacts_locked"] is company["contacts_locked"] is True
    assert signal["contacts"] == company["public_contacts"] == []


@pytest.fixture
def public_profile(tmp_path):
    from fastapi.testclient import TestClient
    from feed_helpers import ORIGIN, materialize
    from test_notice_holder_alignment import NOW, _record
    from test_saas_company_api import _icp, _pay, _signup

    from signals.api import ApiConfig, create_app
    from signals.client_value.notice_facts import store_notice_facts
    from signals.companies.enrichment import run_winner_enrichment_batch
    from signals.connectors.boamp import parse_award_notice
    from signals.connectors.boamp.facts import extract_boamp_notice_facts
    from signals.persistence.database import create_database_engine, migrate_to_latest

    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'public-contacts.db'}")
    migrate_to_latest(engine)
    app = create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN, session_ttl=dt.timedelta(days=365)),
        now_override=lambda: NOW,
    )
    client: TestClient = _signup(app, email="public-contacts@client.example")
    icp = _icp(client)
    _pay(engine, client)
    raw = _record()
    from test_boamp_notice_facts import extension

    extension(raw)["efac:Organizations"]["efac:Organization"][2]["efac:Company"]["cac:Contact"][
        "cbc:ElectronicMail"
    ] = "agence@razelbec.fr"
    event, awards = parse_award_notice(raw, retrieved_at=NOW)
    extraction = extract_boamp_notice_facts(raw, event=event, awards=awards, collected_at=NOW)
    with engine.begin() as connection:
        signal = materialize(connection, event, awards[0], target_icp_id=icp, as_of=NOW.date())
        store_notice_facts(connection, extraction)
        run_winner_enrichment_batch(connection, now=NOW, worker_ref="public-contact-test", limit=10)
    detail = client.get(f"/signals/{signal.signal_key}")
    assert detail.status_code == 200, detail.text
    assert detail.json().get("company_key"), detail.text
    yield engine, client, detail.json(), raw, icp
    client.close()
    engine.dispose()


def test_signal_and_both_dossier_addresses_share_public_contacts(public_profile):
    from test_saas_company_api import _insert_directory_company

    engine, client, detail, _, _ = public_profile
    response = client.get(f"/companies/{detail['company_key']}")
    assert response.status_code == 200, response.text
    assert response.json()["public_contacts"] == detail["notice_facts"]["contacts"]
    with engine.begin() as connection:
        _insert_directory_company(connection, siren="562136036", name="Libellé registre distinct")
    direct = client.get("/companies/directory/562136036")
    canonical = client.get("/companies/cmp_directory_562136036")
    assert direct.status_code == canonical.status_code == 200
    assert (
        direct.json()["public_contacts"]
        == canonical.json()["public_contacts"]
        == response.json()["public_contacts"]
    )


def test_tracked_dossier_keeps_exact_contact_when_current_profile_changes(public_profile):
    _, client, detail, _, icp = public_profile
    key = detail["company_key"]
    assert client.put(f"/companies/{key}/prospection", json={}).status_code == 200
    assert client.patch(f"/target-icps/{icp}", json={"customer_input": {}}).status_code == 200
    response = client.get(f"/companies/{key}")
    assert response.status_code == 200, response.text
    assert response.json()["signals"] == []
    assert response.json()["public_contacts"][0]["email"] == "agence@razelbec.fr"


def test_suppression_removes_notice_contacts_from_signal_and_dossiers(public_profile):
    from test_notice_holder_alignment import NOW
    from test_saas_company_api import _insert_directory_company

    from signals.persistence.schema import supplier_directory

    engine, client, detail, _, _ = public_profile
    with engine.begin() as connection:
        _insert_directory_company(connection, siren="562136036", name="RAZEL")
        connection.execute(supplier_directory.update().values(suppressed_at=NOW))
    response = client.get(f"/signals/{detail['signal_id']}").json()
    assert response["notice_facts"]["contacts"] == []
    assert response["notice_facts"]["available_contact_fields"] == []
    dossier = client.get("/companies/directory/562136036").json()
    assert dossier["public_contacts"] == []
    assert dossier["available_contact_fields"] == []
    assert "agence@razelbec.fr" not in json.dumps(dossier)


def test_latest_fact_version_replaces_previous_contact_without_name_search(public_profile):
    from test_boamp_notice_facts import extension
    from test_notice_holder_alignment import NOW

    from signals.client_value.notice_facts import store_notice_facts
    from signals.connectors.boamp import parse_award_notice
    from signals.connectors.boamp.facts import extract_boamp_notice_facts

    engine, client, detail, raw, _ = public_profile
    extension(raw)["efac:Organizations"]["efac:Organization"][2]["efac:Company"]["cac:Contact"][
        "cbc:ElectronicMail"
    ] = "nouveau@razelbec.fr"
    later = NOW + dt.timedelta(minutes=5)
    event, awards = parse_award_notice(raw, retrieved_at=later)
    extraction = extract_boamp_notice_facts(raw, event=event, awards=awards, collected_at=later)
    with engine.begin() as connection:
        store_notice_facts(connection, extraction)
    response = client.get(f"/companies/{detail['company_key']}").json()
    assert [row["email"] for row in response["public_contacts"]] == ["nouveau@razelbec.fr"]


def test_canonical_contacts_do_not_rejoin_a_quarantined_alias(public_profile):
    import sqlalchemy as sa
    from test_notice_holder_alignment import NOW
    from test_saas_company_api import _insert_directory_company

    from signals.client_value.company_identity import register_alias
    from signals.companies.schema import saas_company

    engine, client, detail, _, _ = public_profile
    client.get(f"/companies/{detail['company_key']}")
    with engine.begin() as connection:
        alias = connection.scalar(sa.select(saas_company.c.company_key))
        register_alias(connection, company_key=alias, siren="481153435", now=NOW)
        _insert_directory_company(connection, siren="562136036", name="RAZEL")
    response = client.get("/companies/directory/562136036")
    assert response.status_code == 200, response.text
    assert response.json()["public_contacts"] == []
    assert response.json()["available_contact_fields"] == []


def test_canonical_contact_filter_excludes_quarantined_cowinner_from_shared_notice(public_profile):
    import sqlalchemy as sa
    from test_notice_holder_alignment import NOW
    from test_saas_company_api import _insert_directory_company

    from signals.client_value.company_identity import register_alias
    from signals.companies.schema import saas_company
    from signals.persistence.notice_schema import notice_award_facts

    engine, client, detail, _, _ = public_profile
    client.get(f"/companies/{detail['company_key']}")
    with engine.begin() as connection:
        original = dict(connection.execute(sa.select(saas_company)).mappings().one())
        sibling_key = "cmp_quarantined_second_agency"
        connection.execute(
            saas_company.insert().values(
                {
                    **original,
                    "company_key": sibling_key,
                    "identity_fingerprint": "f" * 64,
                    "official_identifiers": [{"scheme": "SIRET", "value": "56213603600018"}],
                }
            )
        )
        register_alias(connection, company_key=sibling_key, siren="562136036", now=NOW)
        register_alias(connection, company_key=sibling_key, siren="481153435", now=NOW)
        payload = connection.scalar(sa.select(notice_award_facts.c.facts))
        holder = payload["winning_parties"][0]["members"][0]
        payload["winning_parties"][0]["members"].append(
            {
                **holder,
                "organization_ref": "ORG-SIBLING",
                "identifiers": [
                    {"scheme": "SIRET", "value": "56213603600018", "source_path": "id"}
                ],
                "email": {"value": "sibling@razelbec.fr", "source_path": "email"},
            }
        )
        connection.execute(notice_award_facts.update().values(facts=payload))
        _insert_directory_company(connection, siren="562136036", name="RAZEL")
    response = client.get("/companies/directory/562136036")
    assert response.status_code == 200, response.text
    assert [row["email"] for row in response.json()["public_contacts"]] == ["agence@razelbec.fr"]


def test_discovery_directory_keeps_same_public_catalogue_without_contact_payload(public_profile):
    from test_saas_company_api import _insert_directory_company, _signup

    engine, client, _, _, _ = public_profile
    with engine.begin() as connection:
        _insert_directory_company(connection, siren="562136036", name="RAZEL")
    discovery = _signup(client.app, email="discovery-contact@client.example")
    result = discovery.get("/companies/directory/562136036")
    assert result.status_code == 200, result.text
    assert result.json()["directory"]["siren"] == "562136036"
    assert result.json()["public_contacts"] == []
    assert result.json()["contacts_locked"] is True
    assert {"email", "phone"} <= set(result.json()["available_contact_fields"])
    assert "agence@razelbec.fr" not in result.text
    assert "ORG-1" not in result.text
