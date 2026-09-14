"""Only the audited staging fixture manifest may be hidden, never deleted."""

import datetime as dt
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from test_saas_company_api import _insert_directory_company
from test_saas_company_api import engine as engine  # noqa: PLC0414

from signals.persistence.schema import supplier_directory

CREATED = dt.datetime(2026, 9, 11, 11, 1, 5, 975418, tzinfo=dt.UTC)
NOW = dt.datetime(2026, 9, 14, 12, tzinfo=dt.UTC)


def subject():
    path = (
        Path(__file__).resolve().parents[1] / "docs/reports/prospecting-v11/catalogue-quarantine.py"
    )
    if not path.exists():
        pytest.fail("exact-target recoverable catalogue quarantine is missing")
    spec = importlib.util.spec_from_file_location("catalogue_quarantine", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def seed_manifest(engine):
    with engine.begin() as connection:
        for index in range(1, 31):
            _insert_directory_company(
                connection, siren=f"9900000{index:02d}", name=f"Entreprise test {index:02d}"
            )
        connection.execute(supplier_directory.update().values(city="Blois", created_at=CREATED))
        _insert_directory_company(connection, siren="481153435", name="Entreprise test réelle")


def test_preview_apply_and_replay_preserve_every_row(engine):
    module = subject()
    seed_manifest(engine)
    with engine.begin() as connection:
        assert module.run(connection, now=NOW, execute=False) == {
            "manifest": 30,
            "eligible": 30,
            "quarantined": 0,
        }
        assert module.run(connection, now=NOW, execute=True)["quarantined"] == 30
        assert module.run(connection, now=NOW, execute=True)["quarantined"] == 0
        assert connection.scalar(sa.select(sa.func.count()).select_from(supplier_directory)) == 31
        assert connection.scalars(
            sa.select(supplier_directory.c.siren).where(
                supplier_directory.c.suppressed_at.is_(None)
            )
        ).all() == ["481153435"]


def test_manifest_mismatch_refuses_before_any_change(engine):
    module = subject()
    seed_manifest(engine)
    with engine.begin() as connection:
        connection.execute(
            supplier_directory.update()
            .where(supplier_directory.c.siren == "990000030")
            .values(legal_name="Vraie société")
        )
        with pytest.raises(ValueError, match="manifest"):
            module.run(connection, now=NOW, execute=True)
        assert (
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(supplier_directory)
                .where(supplier_directory.c.suppressed_at.is_not(None))
            )
            == 0
        )


@pytest.mark.parametrize(
    "environment,database",
    [
        ("PRODUCTION", "kivou"),
        ("PRODUCTION", "kivou_staging"),
        ("STAGING", "kivou"),
        ("STAGING", "kivou_staging?dbname=kivou"),
    ],
)
def test_cli_refuses_ambiguous_or_production_targets_without_connecting(
    monkeypatch, environment, database
):
    module = subject()
    monkeypatch.setenv("KIVOU_ACQUISITION_ENVIRONMENT", environment)
    monkeypatch.setenv("KIVOU_DATABASE_URL", f"postgresql+psycopg://localhost/{database}")
    monkeypatch.setattr(
        module,
        "create_database_engine",
        lambda *args, **kwargs: pytest.fail("unsafe database opened"),
    )
    assert module.main(["--apply"]) == 1


def test_manifest_timestamp_uses_the_instant_not_the_database_session_timezone():
    module = subject()
    east = dt.timezone(dt.timedelta(hours=2))
    record = {"siren": "990000001", "legal_name": "Entreprise test 01", "city": "Blois"}
    assert module.matches({**record, "created_at": CREATED.astimezone(east)})
    assert not module.matches({**record, "created_at": CREATED.replace(tzinfo=east)})
