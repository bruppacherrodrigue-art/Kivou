from __future__ import annotations

import datetime as dt
import json

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine

import signals.supplier_directory.domain_audit as domain_audit_module
from signals.persistence.database import alembic_config, create_database_engine
from signals.persistence.schema import (
    prospect_send_request,
    prospect_target,
    supplier_directory,
)
from signals.supplier_directory.domain_audit import audit_confirmed_domains, main
from signals.supplier_directory.store import SupplierDirectoryStore

NOW = dt.datetime(2026, 9, 11, 12, tzinfo=dt.UTC)


@pytest.fixture
def engine(tmp_path) -> Engine:
    value = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'domain-audit.db'}")
    command.upgrade(alembic_config(value), "head")
    return value


def _seed_directory_row(
    engine: Engine,
    *,
    siren: str,
    legal_name: str,
    domain: str,
    confirmed: bool = True,
    suppressed: bool = False,
) -> None:
    store = SupplierDirectoryStore(engine)
    store.upsert_identity(
        siren=siren,
        legal_name=legal_name,
        naf_code="43.99C",
        family_key="formwork",
        department="01",
        city="NEYRON",
        employees=12,
        observed_at=NOW - dt.timedelta(days=1),
    )
    store.record_directors(
        siren,
        directors=({"name": "Alice Martin", "title": "Gérante"},),
        observed_at=NOW - dt.timedelta(hours=23),
    )
    assert store.record_domain(
        siren,
        domain=domain,
        website_url=f"https://{domain}/accueil",
        source="serper",
        validation_method="registration_number",
        validation_evidence_url=f"https://{domain}/mentions-legales",
        observed_at=NOW - dt.timedelta(hours=22),
    )
    store.record_apollo(
        siren,
        organization_id=f"apollo-{siren}",
        status="resolved",
        observed_at=NOW - dt.timedelta(hours=21),
    )
    assert store.record_email(
        siren,
        email=f"contact@{domain}",
        source="site",
        verification_status="mx_verified",
        contact_name="Alice Martin",
        contact_title="Gérante",
        evidence_url=f"https://{domain}/contact",
        observed_at=NOW - dt.timedelta(hours=20),
    )
    assert store.record_contact_form(
        siren,
        url=f"https://{domain}/contact-form",
        observed_at=NOW - dt.timedelta(hours=19),
    )
    if not confirmed or suppressed:
        with engine.begin() as connection:
            connection.execute(
                sa.update(supplier_directory)
                .where(supplier_directory.c.siren == siren)
                .values(
                    domain_validation_method=(
                        None if not confirmed else "registration_number"
                    ),
                    suppressed_at=NOW if suppressed else None,
                )
            )


def _seed_started_send(engine: Engine, *, siren: str, target_id: str) -> None:
    request_id = "484be03d-fbe4-46b1-9900-b99b4068fcbd"
    with engine.begin() as connection:
        connection.execute(
            sa.insert(prospect_send_request).values(
                request_id=request_id,
                payload_fingerprint="f" * 64,
                target_ids=[target_id],
                request_day=NOW.date(),
                reserved_count=1,
                sent_count=0,
                status="started",
                created_by="rodrigue@kivou.eu",
                created_at=NOW,
            )
        )
        connection.execute(
            sa.insert(prospect_target).values(
                target_id=target_id,
                version=2,
                cycle_ref="cycle-1",
                opportunity_key="boamp-2026-42",
                procedure_award_key="notice-1:lot-1",
                acquisition_opportunity_id="a" * 64,
                siren=siren,
                company_name="AJEBAT",
                company_city="NEYRON",
                company_employees=12,
                vertical="general_building",
                family_key="formwork",
                family_label="coffrage",
                email_address="contact@neyron.localbiz.fr",
                email_source="site",
                email_verification_status="mx_verified",
                signal_holder="SAS Exemple",
                signal_subject="Construction d'un groupe scolaire",
                signal_amount_minor_units=125_000_000,
                signal_currency="eur",
                signal_location="Ain",
                signal_decision_date=dt.date(2026, 9, 10),
                signal_source_url="https://www.boamp.fr/avis/42",
                mail_subject="Construction d'un groupe scolaire",
                mail_text="Bonjour,\n\nVotre entreprise réalise-t-elle ce chantier ?",
                mail_html="<p>Bonjour,</p><p>Votre entreprise réalise-t-elle ce chantier ?</p>",
                attribution_url="https://kivou.eu/a/kat1.key.old.signature",
                attribution_member_ref="a" * 64,
                attribution_payload={"member_ref": "a" * 64},
                attribution_token_fingerprint="d" * 64,
                unsubscribe_url="https://kivou.eu/unsubscribe/token",
                mail_word_count=8,
                status="approved",
                delivery_status="not_sent",
                send_request_id=request_id,
                created_at=NOW,
                updated_at=NOW,
            )
        )


def test_domain_audit_is_dry_run_by_default_and_apply_is_idempotent(engine: Engine) -> None:
    _seed_directory_row(
        engine,
        siren="402274716",
        legal_name="AJEBAT",
        domain="neyron.localbiz.fr",
    )
    store = SupplierDirectoryStore(engine)
    before = store.get("402274716")
    assert before is not None

    dry_run = audit_confirmed_domains(engine, observed_at=NOW)

    assert dry_run.examined_count == 1
    assert dry_run.affected_count == 1
    assert dry_run.modified_count == 0
    assert [item.model_dump() for item in dry_run.affected] == [
        {
            "siren": "402274716",
            "domain": "neyron.localbiz.fr",
            "legal_name": "AJEBAT",
        }
    ]
    assert store.get("402274716") == before

    applied = audit_confirmed_domains(engine, observed_at=NOW, apply=True)
    row = store.get("402274716")

    assert applied.examined_count == 1
    assert applied.affected_count == 1
    assert applied.modified_count == 1
    assert row is not None
    assert row.domain is None
    assert row.website_url is None
    assert row.domain_source is None
    assert row.domain_validation_method is None
    assert row.domain_validation_evidence_url is None
    assert row.domain_observed_at is None
    assert row.apollo_organization_id is None
    assert row.apollo_status is None
    assert row.apollo_observed_at is None
    assert row.professional_email is None
    assert row.email_source is None
    assert row.email_verification_status is None
    assert row.email_contact_name is None
    assert row.email_contact_title is None
    assert row.email_evidence_url is None
    assert row.email_observed_at is None
    assert row.contact_form_url is None
    assert row.contact_form_observed_at is None
    assert row.reverification_required_at == NOW
    assert row.reverification_reason == "blocked_domain_audit"

    assert row.siren == before.siren
    assert row.legal_name == before.legal_name
    assert row.legal_name_observed_at == before.legal_name_observed_at
    assert row.naf_code == before.naf_code
    assert row.naf_observed_at == before.naf_observed_at
    assert row.family_keys == before.family_keys
    assert row.families_observed_at == before.families_observed_at
    assert row.department == before.department
    assert row.department_observed_at == before.department_observed_at
    assert row.city == before.city
    assert row.city_observed_at == before.city_observed_at
    assert row.employees == before.employees
    assert row.employees_observed_at == before.employees_observed_at
    assert row.directors == before.directors
    assert row.directors_observed_at == before.directors_observed_at
    assert row.suppressed_at is None

    second = audit_confirmed_domains(engine, observed_at=NOW, apply=True)

    assert second.examined_count == 0
    assert second.affected_count == 0
    assert second.modified_count == 0
    assert second.affected == ()


def test_domain_audit_is_deterministic_and_ignores_out_of_scope_rows(engine: Engine) -> None:
    _seed_directory_row(
        engine,
        siren="700000001",
        legal_name="ZETA",
        domain="zeta.localbiz.fr",
    )
    _seed_directory_row(
        engine,
        siren="100000001",
        legal_name="ALPHA",
        domain="localbiz.fr",
    )
    _seed_directory_row(
        engine,
        siren="200000001",
        legal_name="SITE PERMIS",
        domain="site-permis.fr",
    )
    _seed_directory_row(
        engine,
        siren="300000001",
        legal_name="NON CONFIRMEE",
        domain="candidate.localbiz.fr",
        confirmed=False,
    )
    _seed_directory_row(
        engine,
        siren="400000001",
        legal_name="SUPPRIMEE",
        domain="suppressed.localbiz.fr",
        suppressed=True,
    )
    store = SupplierDirectoryStore(engine)
    allowed_before = store.get("200000001")
    unconfirmed_before = store.get("300000001")
    suppressed_before = store.get("400000001")

    result = audit_confirmed_domains(engine, observed_at=NOW, apply=True)

    assert result.examined_count == 3
    assert result.affected_count == 2
    assert result.modified_count == 2
    assert [item.siren for item in result.affected] == ["100000001", "700000001"]
    assert store.get("100000001").domain is None
    assert store.get("700000001").domain is None
    assert store.get("200000001") == allowed_before
    assert store.get("300000001") == unconfirmed_before
    assert store.get("400000001") == suppressed_before


def test_apply_locks_only_blocked_candidates_in_siren_order_with_nowait(
    engine: Engine,
) -> None:
    _seed_directory_row(
        engine,
        siren="700000001",
        legal_name="ZETA",
        domain="zeta.localbiz.fr",
    )
    _seed_directory_row(
        engine,
        siren="100000001",
        legal_name="ALPHA",
        domain="localbiz.fr",
    )
    _seed_directory_row(
        engine,
        siren="200000001",
        legal_name="SITE PERMIS",
        domain="site-permis.fr",
    )
    statements: list[sa.sql.ClauseElement] = []

    def capture_statement(
        _connection,
        clauseelement,
        _multiparams,
        _params,
        _execution_options,
    ) -> None:
        statements.append(clauseelement)

    sa.event.listen(engine, "before_execute", capture_statement)
    try:
        result = audit_confirmed_domains(engine, observed_at=NOW, apply=True)
    finally:
        sa.event.remove(engine, "before_execute", capture_statement)

    lock_sql = [
        " ".join(
            str(
                statement.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            ).split()
        )
        for statement in statements
        if isinstance(statement, sa.sql.Select)
        and statement._for_update_arg is not None
    ]
    assert result.modified_count == 2
    assert len(lock_sql) == 1
    assert "supplier_directory.siren IN ('100000001', '700000001')" in lock_sql[0]
    assert "200000001" not in lock_sql[0]
    assert "ORDER BY supplier_directory.siren FOR UPDATE NOWAIT" in lock_sql[0]
    assert "supplier_directory.suppressed_at IS NULL" not in lock_sql[0]


def test_apply_revalidates_candidate_state_after_the_read_only_scan(
    engine: Engine, monkeypatch
) -> None:
    _seed_directory_row(
        engine,
        siren="100000001",
        legal_name="ALPHA",
        domain="alpha.localbiz.fr",
    )
    original = domain_audit_module._locked_candidate_domains

    def correct_domain_before_lock(connection, candidate_sirens):
        connection.execute(
            sa.update(supplier_directory)
            .where(supplier_directory.c.siren == "100000001")
            .values(domain="alpha.example")
        )
        return original(connection, candidate_sirens)

    monkeypatch.setattr(
        domain_audit_module,
        "_locked_candidate_domains",
        correct_domain_before_lock,
    )

    with pytest.raises(RuntimeError, match="domain audit conflict") as caught:
        audit_confirmed_domains(engine, observed_at=NOW, apply=True)

    assert type(caught.value).__name__ == "DomainAuditConflict"
    assert SupplierDirectoryStore(engine).get("100000001").domain == "alpha.localbiz.fr"


def test_domain_audit_rolls_back_all_changes_when_one_expected_update_is_lost(
    engine: Engine, monkeypatch
) -> None:
    _seed_directory_row(
        engine,
        siren="100000001",
        legal_name="ALPHA",
        domain="alpha.localbiz.fr",
    )
    _seed_directory_row(
        engine,
        siren="700000001",
        legal_name="ZETA",
        domain="zeta.localbiz.fr",
    )
    original = SupplierDirectoryStore.mark_for_reverification
    calls = 0

    def lose_second_update(self, siren, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            return False
        return original(self, siren, **kwargs)

    monkeypatch.setattr(
        SupplierDirectoryStore,
        "mark_for_reverification",
        lose_second_update,
    )

    with pytest.raises(RuntimeError, match="domain audit conflict") as caught:
        audit_confirmed_domains(engine, observed_at=NOW, apply=True)

    assert type(caught.value).__name__ == "DomainAuditConflict"
    assert SupplierDirectoryStore(engine).get("100000001").domain == "alpha.localbiz.fr"
    assert SupplierDirectoryStore(engine).get("700000001").domain == "zeta.localbiz.fr"


def test_domain_audit_refuses_to_quarantine_a_target_with_a_started_send(
    engine: Engine,
) -> None:
    _seed_directory_row(
        engine,
        siren="402274716",
        legal_name="AJEBAT",
        domain="neyron.localbiz.fr",
    )
    _seed_started_send(
        engine,
        siren="402274716",
        target_id="51d144ca-d697-47e4-a4dc-ee86d0a9c8ac",
    )
    before = SupplierDirectoryStore(engine).get("402274716")

    with pytest.raises(RuntimeError, match="domain audit conflict") as caught:
        audit_confirmed_domains(engine, observed_at=NOW, apply=True)

    assert type(caught.value).__name__ == "DomainAuditConflict"
    assert SupplierDirectoryStore(engine).get("402274716") == before


def test_audit_lock_contention_propagates_but_cli_reports_only_a_safe_error(
    engine: Engine, monkeypatch, capsys
) -> None:
    _seed_directory_row(
        engine,
        siren="402274716",
        legal_name="AJEBAT",
        domain="neyron.localbiz.fr",
    )

    class LockNotAvailable(RuntimeError):
        sqlstate = "55P03"

    database_error = sa.exc.OperationalError(
        "SELECT private_value FROM secret_table FOR UPDATE NOWAIT",
        {"credential": "do-not-leak"},
        LockNotAvailable("lock details with do-not-leak"),
    )

    def fail_to_lock(_connection, _candidate_sirens):
        raise database_error

    monkeypatch.setattr(
        domain_audit_module,
        "_locked_candidate_domains",
        fail_to_lock,
    )

    with pytest.raises(sa.exc.OperationalError) as caught:
        audit_confirmed_domains(engine, observed_at=NOW, apply=True)
    assert caught.value is database_error

    monkeypatch.setenv("KIVOU_DATABASE_URL", str(engine.url))
    assert main(["--apply"]) == 4

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "domain_audit_failed\n"
    assert "do-not-leak" not in captured.err
    assert "55P03" not in captured.err


def test_cli_is_dry_run_by_default(engine: Engine, monkeypatch, capsys) -> None:
    _seed_directory_row(
        engine,
        siren="402274716",
        legal_name="AJEBAT",
        domain="neyron.localbiz.fr",
    )
    monkeypatch.setenv("KIVOU_DATABASE_URL", str(engine.url))

    assert main([]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == (
        '{"affected":[{"domain":"neyron.localbiz.fr","legal_name":"AJEBAT",'
        '"siren":"402274716"}],"affected_count":1,"examined_count":1,'
        '"modified_count":0}\n'
    )
    assert SupplierDirectoryStore(engine).get("402274716").domain == "neyron.localbiz.fr"


def test_cli_reports_missing_database_configuration_without_details(monkeypatch, capsys) -> None:
    monkeypatch.delenv("KIVOU_DATABASE_URL", raising=False)

    assert main([]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "configuration_invalid\n"
    assert "KIVOU_DATABASE_URL" not in captured.err


def test_audit_rejects_a_naive_observation_time(engine: Engine) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        audit_confirmed_domains(engine, observed_at=NOW.replace(tzinfo=None))


def test_cli_json_is_valid_and_stably_keyed(engine: Engine, monkeypatch, capsys) -> None:
    monkeypatch.setenv("KIVOU_DATABASE_URL", str(engine.url))

    assert main([]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert list(payload) == [
        "affected",
        "affected_count",
        "examined_count",
        "modified_count",
    ]
