"""Program versions are immutable and idempotently registered."""

import datetime as dt
from pathlib import Path

import sqlalchemy as sa

from signals.acquisition_programs.config import load_program_config
from signals.acquisition_programs.store import AcquisitionProgramStore
from signals.persistence.database import migrate_to_latest
from signals.persistence.schema import acquisition_program

EXAMPLE = Path(__file__).resolve().parents[1] / "ops/examples/milomail-acquisition.json.example"


def test_register_preserves_two_versions_without_mutating_history() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    migrate_to_latest(engine)
    store = AcquisitionProgramStore(engine)
    first = load_program_config(EXAMPLE)
    second = first.model_copy(update={"template_version": "milomail-gmail-audit-fr-v2"})
    at = dt.datetime(2026, 9, 21, tzinfo=dt.UTC)
    first_id = store.register(first, at=at)
    assert store.register(first, at=at) == first_id
    second_id = store.register(second, at=at)
    assert first_id != second_id
    with engine.connect() as connection:
        rows = connection.execute(sa.select(acquisition_program)).mappings().all()
    assert len(rows) == 2
    assert {row["config_snapshot"]["template_version"] for row in rows} == {
        first.template_version,
        second.template_version,
    }
