from __future__ import annotations

import copy
import datetime as dt
import json

import sqlalchemy as sa
from feed_helpers import LINKED_BOAMP

from signals.connectors.boamp import parse_award_notice
from signals.ingestion.pipeline import IngestionPipeline
from signals.ingestion.runner import IngestionRunner, RunOptions
from signals.ingestion.sources import BoampSource
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import contract_award, opportunity_representation

NOW = dt.datetime(2026, 8, 19, 12, tzinfo=dt.UTC)

REAL_BOAMP_CONTRACT_REFERENCE = (
    "VdP : 2026S068920000 / EPPM : 2026-261930 / Ecole du Breuil : 2600008 / "
    "EIVP : 2026003C / CDE Paris Centre : 2026S02 / CDE 5 : 2026-1 / CDE 6 : "
    "2027PREVCDE6 / CDE 7 : 2027M01 / CDE 8 : PREVCDE08 / CDE 9 : 2701001 / "
    "CDE 10 : 2026 /07 / CDE 11 : PREV26 / CDE 12 : PREVP26 / CDE 13 : "
    "AO2027-01 / CDE 14 : 2026-04 RH / CDE 15 : 2026-03 / CDE 16 : 2026-03-03 / "
    "CDE17 : M26RH02 / CDE 19 : 2026-04 / CDE 20 : 2026M10"
)


def _record_with_real_long_reference() -> dict:
    record = copy.deepcopy(LINKED_BOAMP)
    record["idweb"] = "26-74073"
    document = json.loads(record["donnees"])
    notice_result = document["EFORMS"]["ContractAwardNotice"]
    for key in (
        "ext:UBLExtensions",
        "ext:UBLExtension",
        "ext:ExtensionContent",
        "efext:EformsExtension",
        "efac:NoticeResult",
    ):
        notice_result = notice_result[key]
    settled_contract = notice_result["efac:SettledContract"]
    settled_contract["efac:ContractReference"]["cbc:ID"] = REAL_BOAMP_CONTRACT_REFERENCE
    record["donnees"] = json.dumps(document, ensure_ascii=False)
    return record


class _OneRecordBoampClient:
    def __init__(self, record: dict) -> None:
        self.record = record

    def fetch_awards_since(self, since, *, until=None, max_records=None):
        yield self.record


def test_real_boamp_contract_reference_is_unbounded_text_and_round_trips(tmp_path):
    assert len(REAL_BOAMP_CONTRACT_REFERENCE) == 409
    record = _record_with_real_long_reference()
    _event, awards = parse_award_notice(record, retrieved_at=NOW)
    assert len(awards) == 1
    assert awards[0].contract_reference == REAL_BOAMP_CONTRACT_REFERENCE
    assert isinstance(contract_award.c.contract_reference.type, sa.Text)

    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'capacity.db'}")
    migrate_to_latest(engine)
    outcome = IngestionRunner(
        engine,
        sources={"boamp": BoampSource(_OneRecordBoampClient(record))},
        pipeline=IngestionPipeline(engine),
        clock=lambda: NOW,
    ).run(RunOptions(sources=("boamp",)))

    assert outcome.exit_code == 0
    with engine.connect() as connection:
        stored = connection.execute(
            sa.select(contract_award.c.contract_reference)
        ).scalar_one()
        representations = connection.execute(
            sa.select(sa.func.count()).select_from(opportunity_representation)
        ).scalar_one()
    assert stored == REAL_BOAMP_CONTRACT_REFERENCE
    assert representations == 1
