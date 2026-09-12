from __future__ import annotations

import datetime as dt

import sqlalchemy as sa

from signals.client_value.directory import directory_company, local_circuit
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import supplier_directory

NOW = dt.datetime(2026, 9, 11, 9, tzinfo=dt.UTC)


def row(
    siren: str,
    name: str,
    *,
    department: str = "38",
    city: str = "Grenoble",
    employees: int | None = 20,
    family_keys: tuple[str, ...] = ("ready_mix_concrete",),
    website_url: str | None = "https://example.test/",
    directors: tuple[dict[str, str], ...] = (
        {"name": "Alice Martin", "title": "Gérante", "entity_type": "personne physique"},
    ),
    suppressed_at: dt.datetime | None = None,
) -> dict[str, object]:
    return {
        "siren": siren,
        "legal_name": name,
        "legal_name_observed_at": NOW,
        "naf_code": "23.63Z",
        "naf_observed_at": NOW,
        "family_keys": list(family_keys),
        "families_observed_at": NOW,
        "department": department,
        "department_observed_at": NOW,
        "city": city,
        "city_observed_at": NOW,
        "employees": employees,
        "employees_observed_at": NOW if employees is not None else None,
        "domain": None,
        "website_url": website_url,
        "domain_source": "registre",
        "domain_validation_method": None,
        "domain_validation_evidence_url": None,
        "domain_observed_at": NOW if website_url else None,
        "apollo_organization_id": None,
        "apollo_status": None,
        "apollo_observed_at": None,
        "directors": list(directors),
        "directors_observed_at": NOW if directors else None,
        "professional_email": "alice@example.test",
        "email_source": "site",
        "email_verification_status": "mx_verified",
        "email_contact_name": "Alice Martin",
        "email_contact_title": "Gérante",
        "email_observed_at": NOW,
        "contact_form_url": None,
        "contact_form_observed_at": None,
        "reverification_required_at": None,
        "reverification_reason": None,
        "suppressed_at": suppressed_at,
        "created_at": NOW,
        "updated_at": NOW,
    }


def engine(tmp_path):
    value = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'directory-client.db'}")
    migrate_to_latest(value)
    return value


def test_directory_company_prefers_siren_and_never_exposes_professional_email(tmp_path) -> None:
    db = engine(tmp_path)
    with db.begin() as connection:
        connection.execute(sa.insert(supplier_directory), row("331364729", "ESCOLLE BETON"))
        result = directory_company(
            connection,
            siren="331364729",
            legal_name="un autre nom",
            department="69",
        )

    assert result == {
        "siren": "331364729",
        "name": "ESCOLLE BETON",
        "naf_code": "23.63Z",
        "family_labels": ["Béton prêt à l'emploi"],
        "department": "38",
        "department_label": "Isère",
        "city": "Grenoble",
        "employees": 20,
        "website_url": "https://example.test/",
        "website_source": "registre",
        "website_observed_at": NOW.replace(tzinfo=None).isoformat(),
        "directors": [{"name": "Alice Martin", "title": "Gérante"}],
        "directors_observed_at": NOW.replace(tzinfo=None).isoformat(),
        "source": "registre",
        "removal_path": "/contact",
    }
    assert "email" not in repr(result).lower()


def test_directory_company_discloses_name_matching_and_omits_suppressed_or_unsafe_data(
    tmp_path,
) -> None:
    db = engine(tmp_path)
    with db.begin() as connection:
        connection.execute(
            sa.insert(supplier_directory),
            [
                row(
                    "331364729",
                    "ÉCOLLE  BÉTON",
                    website_url="http://unsafe.example",
                    suppressed_at=NOW,
                ),
                row("350064226", "ÉCOLLE BÉTON", department="69"),
            ],
        )
        result = directory_company(
            connection,
            siren=None,
            legal_name="ecolle beton",
            department="38",
        )

    assert result is not None
    assert result["resolution_note"] == "rapprochement par nom"
    assert "website_url" not in result
    assert "directors" not in result


def test_directory_company_keeps_the_website_source_distinct_from_register_facts(
    tmp_path,
) -> None:
    db = engine(tmp_path)
    value = row("331364729", "ESCOLLE BETON")
    value["domain_source"] = "serper"
    with db.begin() as connection:
        connection.execute(sa.insert(supplier_directory), value)
        result = directory_company(
            connection,
            siren="331364729",
            legal_name=None,
            department=None,
        )

    assert result is not None
    assert result["website_url"] == "https://example.test/"
    assert result["website_source"] == "serper"


def test_directory_company_formats_the_published_director_for_the_client(tmp_path) -> None:
    db = engine(tmp_path)
    value = row(
        "481153435",
        "ALYA BATIMENT",
        directors=(
            {
                "name": "MOSBAH BENZAOUI (BENZAOUI)",
                "title": "Président",
                "entity_type": "personne physique",
            },
        ),
    )
    value.update(
        director_display_name="Mosbah Benzaoui",
        director_source="model",
        director_observed_at=NOW,
        phone="+33 4 74 00 00 00",
        phone_source="model",
        phone_observed_at=NOW,
        email_evidence_url="https://example.test/contact",
        enrichment_observed_at=NOW,
    )
    with db.begin() as connection:
        connection.execute(sa.insert(supplier_directory), value)
        result = directory_company(
            connection,
            siren="481153435",
            legal_name=None,
            department=None,
            include_public_contact=True,
        )

    assert result is not None
    assert result["directors"] == [{"name": "Mosbah Benzaoui", "title": "Président"}]
    assert result["directors_observed_at"] == NOW.replace(tzinfo=None).isoformat()
    assert result["director_display_name"] == "Mosbah Benzaoui"
    assert result["director_display_title"] == "Président"
    assert "published_email" not in result
    assert "published_email_source_url" not in result
    assert result["phone"] == "+33 4 74 00 00 00"
    assert result["phone_source"] == "model"
    assert result["phone_observed_at"] == NOW.replace(tzinfo=None).isoformat()


def test_directory_company_exposes_only_a_generic_mailbox_published_on_the_site(
    tmp_path,
) -> None:
    db = engine(tmp_path)
    value = row("481153435", "ALYA BATIMENT")
    value.update(
        professional_email="contact@example.test",
        email_source="site",
        email_evidence_url="https://example.test/contact",
        email_observed_at=NOW,
    )
    with db.begin() as connection:
        connection.execute(sa.insert(supplier_directory), value)
        result = directory_company(
            connection,
            siren="481153435",
            legal_name=None,
            department=None,
            include_public_contact=True,
        )

    assert result is not None
    assert result["published_email"] == "contact@example.test"
    assert result["published_email_source_url"] == "https://example.test/contact"
    assert result["published_email_observed_at"] == NOW.replace(tzinfo=None).isoformat()


def test_local_circuit_filters_the_profile_families_and_orders_proximity_then_size(
    tmp_path,
) -> None:
    from feed_helpers import make_account, make_icp

    db = engine(tmp_path)
    with db.begin() as connection:
        account_id = make_account(connection, "directory@example.test", "Client")
        target_icp_id = make_icp(
            connection,
            account_id,
            buyer_trades=("building_construction",),
        )
        values = [
            row(
                f"{330000000 + index:09d}",
                f"Entreprise {index:02d}",
                city="Grenoble" if index in {0, 1} else "Voiron",
                employees=5 + index,
            )
            for index in range(10)
        ]
        values.append(
            row(
                "440000001",
                "Hors métier",
                employees=500,
                family_keys=("plumbing",),
            )
        )
        values.append(row("440000002", "Hors zone", department="69", employees=600))
        connection.execute(sa.insert(supplier_directory), values)

        result = local_circuit(
            connection,
            target_icp_id=target_icp_id,
            department="38",
            city="Grenoble",
        )

    assert len(result) == 8
    assert [item["name"] for item in result[:2]] == ["Entreprise 01", "Entreprise 00"]
    assert [item["name"] for item in result[2:]] == [
        "Entreprise 09",
        "Entreprise 08",
        "Entreprise 07",
        "Entreprise 06",
        "Entreprise 05",
        "Entreprise 04",
    ]
    assert all(item["trade"] == "Béton prêt à l'emploi" for item in result)
    assert all(item["href"].startswith("/app/companies/directory/") for item in result)


def test_local_circuit_is_empty_without_department_or_matching_profile_family(tmp_path) -> None:
    from feed_helpers import make_account, make_icp

    db = engine(tmp_path)
    with db.begin() as connection:
        account_id = make_account(connection, "directory-empty@example.test", "Client")
        target_icp_id = make_icp(
            connection,
            account_id,
            buyer_trades=("rail_infrastructure",),
        )
        connection.execute(sa.insert(supplier_directory), row("331364729", "ESCOLLE BETON"))

        assert local_circuit(
            connection, target_icp_id=target_icp_id, department=None, city="Grenoble"
        ) == ()
        assert local_circuit(
            connection, target_icp_id=target_icp_id, department="38", city="Grenoble"
        ) == ()
