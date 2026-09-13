from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path

import pytest
import sqlalchemy as sa

from signals.client_value.notice_backfill import _extract_existing, backfill_notice_facts
from signals.client_value.notice_facts import (
    SnapshotPolicy,
    decode_notice_snapshot,
    load_award_notice_facts,
    store_notice_facts,
)
from signals.connectors.boamp import parse_award_notice
from signals.persistence.database import create_database_engine
from signals.persistence.identity import award_key
from signals.persistence.notice_schema import notice_award_facts, notice_source_snapshot
from signals.persistence.schema import contract_award, source_event

NOW = dt.datetime(2026, 9, 13, 20, tzinfo=dt.UTC)
EVENT_KEY = "boamp:26-87113:"
HISTORICAL_IDENTIFIER = {"scheme": "BOAMP-COMPANY-ID", "value": "562 136 036 00885"}


def _record():
    """Minimal eForms reproducing the exact historical RAZEL holder identity."""
    raw = json.loads(
        (Path(__file__).parent / "fixtures/france/boamp_notice_facts_minimal.json").read_text()
    )
    raw.update(idweb="26-87113", dateparution="2026-09-10")
    raw["url_avis"] = "https://www.boamp.fr/pages/avis/?q=idweb:26-87113"
    notice = raw["donnees"]["EFORMS"]["ContractAwardNotice"]
    notice["cac:ProcurementProjectLot"] = notice["cac:ProcurementProjectLot"][:1]
    notice["cac:ProcurementProjectLot"][0]["cbc:ID"] = "LOT-0001"
    extension = notice["ext:UBLExtensions"]["ext:UBLExtension"]["ext:ExtensionContent"][
        "efext:EformsExtension"
    ]
    result = extension["efac:NoticeResult"]
    for key in ("efac:LotResult", "efac:LotTender", "efac:TenderingParty", "efac:SettledContract"):
        result[key] = result[key][:1]
    result["efac:LotResult"][0]["efac:TenderLot"]["cbc:ID"] = "LOT-0001"
    result["efac:LotResult"][0]["efac:SettledContract"]["cbc:ID"] = "CON-0001"
    result["efac:LotTender"][0]["efac:TenderLot"]["cbc:ID"] = "LOT-0001"
    result["efac:SettledContract"][0]["cbc:ID"] = "CON-0001"
    result["efac:SettledContract"][0].pop("cbc:AwardDate")
    holder = extension["efac:Organizations"]["efac:Organization"][2]["efac:Company"]
    holder["cac:PartyName"]["cbc:Name"] = "RAZEL-BEC SAS"
    holder["cac:PartyLegalEntity"]["cbc:CompanyID"] = HISTORICAL_IDENTIFIER["value"]
    return raw


@pytest.fixture
def historical():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    for table in (source_event, contract_award, notice_source_snapshot, notice_award_facts):
        table.create(engine)
    raw = _record()
    event, awards = parse_award_notice(raw, retrieved_at=NOW)
    assert event.ref().key() == EVENT_KEY
    assert len(awards) == 1
    award = awards[0]
    parties = [party.model_dump(mode="json") for party in award.awardee_parties]
    parties[0]["members"][0]["organization"]["identifiers"] = [HISTORICAL_IDENTIFIER.copy()]
    with engine.begin() as connection:
        connection.execute(
            source_event.insert().values(
                event_key=EVENT_KEY,
                source_system="boamp",
                source_country="FR",
                source_notice_id="26-87113",
                notice_version=None,
                published_on=dt.date(2026, 9, 10),
                event_type="award_notice",
                procedure_buyers=[],
                created_at=NOW,
            )
        )
        connection.execute(
            contract_award.insert().values(
                award_key=award_key(award),
                event_key=EVENT_KEY,
                source_award_id="CON-0001",
                lot_identifier="LOT-0001",
                awardee_parties=parties,
                cpv_additional=[],
                contract_signatories=[],
                winner_status="identified",
                created_at=NOW,
            )
        )
    try:
        yield engine, raw, parties
    finally:
        engine.dispose()


def _extract(engine, raw):
    return _extract_existing(
        engine,
        {"event_key": EVENT_KEY, "source_notice_id": "26-87113", "notice_version": None},
        raw,
        collected_at=NOW,
        policy=SnapshotPolicy(),
    )


@pytest.mark.parametrize(
    "identifier",
    [
        HISTORICAL_IDENTIFIER,
        {"scheme": "BOAMP-COMPANY-ID", "value": "56213603600885"},
        {"scheme": "SIRET", "value": "562 136 036 00885"},
        {"scheme": "BOAMP-COMPANY-ID", "value": "562\u00a0136\t036\n00885"},
    ],
)
def test_historical_equivalent_holder_stores_without_rewriting_canonical_or_snapshot(
    historical, identifier
):
    engine, raw, parties = historical
    parties = copy.deepcopy(parties)
    parties[0]["members"][0]["organization"]["identifiers"] = [identifier]
    with engine.begin() as connection:
        connection.execute(contract_award.update().values(awardee_parties=parties))
    extracted = _extract(engine, raw)
    assert not extracted.rejections
    assert (
        extracted.awards[0].winning_parties[0].members[0].identifiers[0].value == "56213603600885"
    )
    with engine.begin() as connection:
        assert store_notice_facts(connection, extracted).facts_created == 1
        assert store_notice_facts(connection, extracted).facts_created == 0
        assert connection.scalar(sa.select(contract_award.c.awardee_parties)) == parties
        assert (
            load_award_notice_facts(connection, extracted.awards[0].award_key)
            == extracted.awards[0]
        )
    assert decode_notice_snapshot(extracted.snapshot) == raw


@pytest.mark.parametrize(
    "breakage",
    [
        "wrong_digits",
        "other_establishment",
        "punctuation",
        "other_scheme",
        "missing_identifier",
        "additional_identifier",
        "wrong_name",
        "different_group",
    ],
)
def test_holder_normalization_never_weakens_full_identity_alignment(historical, breakage):
    engine, raw, parties = historical
    parties = copy.deepcopy(parties)
    organization = parties[0]["members"][0]["organization"]
    identifier = organization["identifiers"][0]
    if breakage == "wrong_digits":
        identifier["value"] = "563 136 036 00885"
    elif breakage == "other_establishment":
        identifier["value"] = "562 136 036 00893"
    elif breakage == "punctuation":
        identifier["value"] = "562-136-036-00885"
    elif breakage == "other_scheme":
        identifier["scheme"] = "OTHER-COMPANY-ID"
    elif breakage == "missing_identifier":
        organization["identifiers"] = []
    elif breakage == "additional_identifier":
        organization["identifiers"].append({"scheme": "SIRET", "value": "56313603600885"})
    elif breakage == "wrong_name":
        organization["legal_name"] = "Another holder"
    elif breakage == "different_group":
        parties.append(copy.deepcopy(parties[0]))
    with engine.begin() as connection:
        connection.execute(contract_award.update().values(awardee_parties=parties))
    extracted = _extract(engine, raw)
    with engine.begin() as connection:
        with pytest.raises(ValueError, match="holder/source alignment mismatch"):
            store_notice_facts(connection, extracted)
        for table in (notice_source_snapshot, notice_award_facts):
            assert connection.scalar(sa.select(sa.func.count()).select_from(table)) == 0


def test_backfill_replays_historical_holder_once_without_provider_or_canonical_mutation(historical):
    engine, raw, parties = historical

    class OfflineReader:
        def __init__(self):
            self.calls = []

        def fetch_record(self, notice_id):
            self.calls.append(notice_id)
            assert notice_id == "26-87113"
            return raw

    reader = OfflineReader()
    result = backfill_notice_facts(
        engine, now=NOW, dry_run=False, client=reader, event_keys=(EVENT_KEY,)
    )
    assert [(item.status, item.reason) for item in result.items] == [("stored", None)]
    assert result.facts_created == 1
    assert not result.cursor.pending and not result.cursor.terminal
    again = backfill_notice_facts(
        engine, now=NOW, dry_run=False, client=reader, event_keys=(EVENT_KEY,)
    )
    assert again.selected == 0
    assert reader.calls == ["26-87113"]
    with engine.connect() as connection:
        assert connection.scalar(sa.select(contract_award.c.awardee_parties)) == parties
