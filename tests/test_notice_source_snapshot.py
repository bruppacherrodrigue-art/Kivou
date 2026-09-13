from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import importlib
import importlib.util
import json
import zlib
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from signals.client_value.notice_facts import (
    MAX_SNAPSHOT_BYTES,
    SnapshotPolicy,
    decode_notice_snapshot,
    prepare_notice_snapshot,
)
from signals.connectors.boamp import parse_award_notice
from signals.connectors.boamp.facts import extract_boamp_notice_facts
from signals.persistence.database import create_database_engine
from signals.persistence.identity import award_key
from signals.persistence.schema import contract_award, source_event

NOW = dt.datetime(2026, 9, 13, 10, tzinfo=dt.UTC)
FIXTURE = Path(__file__).parent / "fixtures/france/boamp_notice_facts_minimal.json"


def raw_record():
    return json.loads(FIXTURE.read_text())


def snapshot(raw=None, **changes):
    options = {
        "source_notice_id": "26-fixture-facts",
        "notice_version": "01",
        "source_url": "https://www.boamp.fr/avis",
        "collected_at": NOW,
    }
    options.update(changes)
    return prepare_notice_snapshot(raw or raw_record(), **options)


def storage_api():
    module = importlib.import_module("signals.client_value.notice_facts")
    assert hasattr(module, "store_notice_facts"), "notice facts storage is not implemented"
    return module


@pytest.fixture
def connection():
    name = "signals.persistence.notice_schema"
    if not importlib.util.find_spec(name):
        yield None
        return
    schema = importlib.import_module(name)
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    source_event.create(engine)
    contract_award.create(engine)
    schema.notice_source_snapshot.create(engine)
    schema.notice_award_facts.create(engine)
    raw = raw_record()
    event, awards = parse_award_notice(raw, retrieved_at=NOW)
    with engine.begin() as opened:
        opened.execute(
            source_event.insert().values(
                event_key=event.ref().key(),
                source_system="boamp",
                source_country="FR",
                source_notice_id=event.provenance.source_notice_id,
                event_type="award_notice",
                procedure_buyers=[],
                created_at=NOW,
            )
        )
        for award in awards:
            opened.execute(
                contract_award.insert().values(
                    award_key=award_key(award),
                    event_key=event.ref().key(),
                    source_award_id=award.source_award_id,
                    lot_identifier=award.lot.identifier,
                    awardee_parties=[
                        party.model_dump(mode="json") for party in award.awardee_parties
                    ],
                    cpv_additional=[],
                    contract_signatories=[],
                    winner_status="identified",
                    created_at=NOW,
                )
            )
        yield opened
    engine.dispose()


def extraction(**changes):
    raw = raw_record()
    event, awards = parse_award_notice(raw, retrieved_at=NOW)
    return extract_boamp_notice_facts(raw, event=event, awards=awards, collected_at=NOW, **changes)


def test_snapshot_hash_is_deterministic_and_roundtrips_original_acquired_json():
    raw = raw_record()
    first = snapshot(raw)
    reordered = dict(reversed(list(raw.items())))
    second = snapshot(reordered, collected_at=NOW + dt.timedelta(days=1))
    assert first.snapshot_key == second.snapshot_key
    assert first.content_hash == second.content_hash
    assert decode_notice_snapshot(first) == raw
    assert first.byte_size > len(first.payload_compressed)
    raw["donnees"] = json.dumps(raw["donnees"], ensure_ascii=False)
    assert decode_notice_snapshot(snapshot(raw)) == raw


def test_changed_source_version_or_content_gets_a_new_snapshot_identity():
    assert snapshot().snapshot_key != snapshot(notice_version="02").snapshot_key
    raw = raw_record()
    raw["objet"] = "Un titre corrigé"
    assert snapshot().snapshot_key != snapshot(raw).snapshot_key


@pytest.mark.parametrize(
    "options",
    [{"max_bytes": MAX_SNAPSHOT_BYTES + 1}, {"max_bytes": 0}, {"ttl_days": 366}, {"ttl_days": 0}],
)
def test_configuration_cannot_disable_hard_size_and_retention_bounds(options):
    with pytest.raises(ValueError):
        SnapshotPolicy(**options)


def test_snapshot_requires_timezone_aware_collection_and_applies_configured_ttl():
    with pytest.raises(ValueError, match="timezone"):
        snapshot(collected_at=NOW.replace(tzinfo=None))
    prepared = snapshot(policy=SnapshotPolicy(ttl_days=30))
    assert prepared.expires_at == NOW + dt.timedelta(days=30)


def test_size_is_rejected_before_compression_and_bounded_during_decompression(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("oversized payload reached compression")

    with monkeypatch.context() as patch:
        patch.setattr(zlib, "compress", forbidden)
        with pytest.raises(ValueError, match="byte limit"):
            snapshot(policy=SnapshotPolicy(max_bytes=10))
    bomb = zlib.compress(b"x" * (MAX_SNAPSHOT_BYTES + 1))
    tampered = dataclasses.replace(snapshot(), payload_compressed=bomb, byte_size=1)
    with pytest.raises(ValueError, match="byte limit"):
        decode_notice_snapshot(tampered)


@pytest.mark.parametrize("kind", ["hash", "size", "trailing", "truncated"])
def test_snapshot_integrity_checks_reject_tampering(kind):
    prepared = snapshot()
    values = {
        "hash": {"content_hash": "0" * 64},
        "size": {"byte_size": prepared.byte_size - 1},
        "trailing": {"payload_compressed": prepared.payload_compressed + b"extra"},
        "truncated": {"payload_compressed": prepared.payload_compressed[:-1]},
    }
    with pytest.raises(ValueError):
        decode_notice_snapshot(dataclasses.replace(prepared, **values[kind]))


def test_store_is_idempotent_and_facts_roundtrip_without_loading_raw_payload(connection):
    api = storage_api()
    prepared = extraction()
    first = api.store_notice_facts(connection, prepared)
    second = api.store_notice_facts(connection, prepared)
    assert (first.snapshot_created, first.facts_created) == (True, 2)
    assert (second.snapshot_created, second.facts_created) == (False, 0)
    loaded = api.load_award_notice_facts(connection, prepared.awards[0].award_key)
    assert loaded == prepared.awards[0]
    assert "donnees" not in loaded.model_dump()
    assert "payload_compressed" not in loaded.model_dump()


def test_extractor_versions_append_facts_without_copying_source_snapshot(connection):
    api = storage_api()
    first, second = extraction(), extraction(extractor_version="boamp-notice-facts-v2")
    api.store_notice_facts(connection, first)
    stored = api.store_notice_facts(connection, second)
    assert stored.snapshot_created is False
    assert stored.facts_created == 2
    assert (
        api.load_award_notice_facts(
            connection, first.awards[0].award_key, extractor_version="boamp-notice-facts-v2"
        )
        == second.awards[0]
    )


def test_storage_rejects_cross_award_event_and_holder_alignment_before_any_write(connection):
    api = storage_api()
    schema = importlib.import_module("signals.persistence.notice_schema")
    prepared = extraction()
    first = prepared.awards[0].model_copy(update={"award_key": prepared.awards[1].award_key})
    malformed = dataclasses.replace(prepared, awards=(first,))
    with pytest.raises(ValueError, match="alignment"):
        api.store_notice_facts(connection, malformed)
    assert (
        connection.execute(
            sa.select(sa.func.count()).select_from(schema.notice_source_snapshot)
        ).scalar_one()
        == 0
    )


def test_source_payload_expires_but_typed_facts_and_provenance_remain(connection):
    api = storage_api()
    schema = importlib.import_module("signals.persistence.notice_schema")
    prepared = extraction()
    api.store_notice_facts(connection, prepared)
    assert api.purge_expired_notice_payloads(connection, now=NOW + dt.timedelta(days=364)) == 0
    assert api.purge_expired_notice_payloads(connection, now=NOW + dt.timedelta(days=365)) == 1
    row = connection.execute(sa.select(schema.notice_source_snapshot)).one()
    assert row.payload_compressed is None
    assert row.content_hash == prepared.snapshot.content_hash
    assert (
        api.load_award_notice_facts(connection, prepared.awards[0].award_key) == prepared.awards[0]
    )
    assert api.store_notice_facts(connection, prepared).snapshot_created is False
    assert (
        connection.execute(
            sa.select(schema.notice_source_snapshot.c.payload_compressed)
        ).scalar_one()
        is None
    )


def test_new_schema_has_real_foreign_keys_unique_versions_and_postgres_ddl(connection):
    storage_api()
    schema = importlib.import_module("signals.persistence.notice_schema")
    facts = schema.notice_award_facts
    assert {fk.target_fullname for fk in facts.foreign_keys} == {
        "source_event.event_key",
        "contract_award.award_key",
        "notice_source_snapshot.snapshot_key",
    }
    for table in [schema.notice_source_snapshot, facts]:
        assert "CREATE TABLE" in str(
            sa.schema.CreateTable(table).compile(dialect=postgresql.dialect())
        )
        assert any(isinstance(c, sa.UniqueConstraint) for c in table.constraints)
    stored = extraction()
    storage_api().store_notice_facts(connection, stored)
    row = dict(connection.execute(sa.select(facts)).first()._mapping)
    row["facts_key"] = hashlib.sha256(b"different-key-same-version").hexdigest()
    with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
        connection.execute(facts.insert().values(**row))


def test_related_tender_source_snapshot_is_persisted_with_its_duration_evidence(connection):
    from test_boamp_notice_facts import linked_tender_fixture

    raw, prior = linked_tender_fixture()
    event, awards = parse_award_notice(raw, retrieved_at=NOW)
    extracted = extract_boamp_notice_facts(
        raw, event=event, awards=awards, collected_at=NOW, related_records=(prior,)
    )
    result = storage_api().store_notice_facts(connection, extracted)
    schema = importlib.import_module("signals.persistence.notice_schema")
    assert (
        connection.execute(
            sa.select(sa.func.count()).select_from(schema.notice_source_snapshot)
        ).scalar_one()
        == 2
    )
    assert result.related_snapshots_created == 1
    assert (
        storage_api()
        .load_award_notice_facts(connection, extracted.awards[0].award_key)
        .initial_duration.notice_kind
        == "contract_notice"
    )


def test_duration_cannot_reference_an_unstored_or_mismatched_source_snapshot(connection):
    prepared = extraction()
    first = prepared.awards[0]
    changed = first.model_copy(
        update={
            "duration": first.duration.model_copy(
                update={"source_snapshot_key": "unrelated-snapshot"}
            )
        }
    )
    with pytest.raises(ValueError, match="provenance|alignment"):
        storage_api().store_notice_facts(
            connection, dataclasses.replace(prepared, awards=(changed,))
        )


def test_later_consultation_appends_distinct_source_set_without_overwriting_partial_facts(
    connection,
):
    from test_boamp_notice_facts import linked_tender_fixture

    from signals.persistence.notice_schema import notice_award_facts

    raw, prior = linked_tender_fixture()
    event, awards = parse_award_notice(raw, retrieved_at=NOW)
    partial = extract_boamp_notice_facts(raw, event=event, awards=awards, collected_at=NOW)
    enriched = extract_boamp_notice_facts(
        raw, event=event, awards=awards, collected_at=NOW, related_records=(prior,)
    )
    assert partial.awards[0].initial_duration is None
    assert enriched.awards[0].initial_duration.value == "12"
    assert storage_api().store_notice_facts(connection, partial).facts_created == 2
    assert storage_api().store_notice_facts(connection, enriched).facts_created == 2
    rows = connection.execute(sa.select(notice_award_facts)).mappings().all()
    assert len(rows) == 4
    assert len({row["source_set_hash"] for row in rows}) == 2
    assert {row["extractor_version"] for row in rows} == {"boamp-notice-facts-v1"}
    assert sum(row["facts"]["initial_duration"] is None for row in rows) == 3
    assert (
        storage_api()
        .load_award_notice_facts(connection, partial.awards[0].award_key)
        .initial_duration.value
        == "12"
    )
    assert storage_api().store_notice_facts(connection, enriched).facts_created == 0
