from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import importlib
import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa

from signals.client_value.notice_facts import store_notice_facts
from signals.connectors.boamp import BoampHttpError, parse_award_notice
from signals.connectors.boamp.facts import extract_boamp_notice_facts
from signals.persistence.database import create_database_engine
from signals.persistence.identity import award_key
from signals.persistence.notice_schema import notice_award_facts, notice_source_snapshot
from signals.persistence.schema import contract_award, source_event

NOW = dt.datetime(2026, 9, 13, 10, tzinfo=dt.UTC)
FIXTURE = Path(__file__).parent / "fixtures/france/boamp_notice_facts_minimal.json"


def record():
    return json.loads(FIXTURE.read_text())


def api():
    name = "signals.client_value.notice_backfill"
    assert importlib.util.find_spec(name), "bounded notice backfill is not implemented"
    return importlib.import_module(name)


@pytest.fixture
def engine():
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    for table in (source_event, contract_award, notice_source_snapshot, notice_award_facts):
        table.create(engine)
    event, awards = parse_award_notice(record(), retrieved_at=NOW)
    with engine.begin() as connection:
        connection.execute(
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
            connection.execute(
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
    yield engine
    engine.dispose()


class Client:
    def __init__(self, *, payload=None, error=None):
        self.payload = payload if payload is not None else record()
        self.error = error
        self.calls = []

    def fetch_record(self, identity):
        self.calls.append(identity)
        if self.error:
            raise self.error
        return self.payload


def _event_key():
    return parse_award_notice(record(), retrieved_at=NOW)[0].ref().key()


def _extra_event(engine, key="boamp:00-unrelated:", *, source_system="boamp"):
    with engine.begin() as connection:
        event = dict(
            connection.execute(
                sa.select(source_event).where(source_event.c.event_key == _event_key())
            )
            .mappings()
            .one()
        )
        award = dict(
            connection.execute(
                sa.select(contract_award).where(contract_award.c.event_key == _event_key())
            )
            .mappings()
            .first()
        )
        connection.execute(
            source_event.insert().values(
                {**event, "event_key": key, "source_notice_id": key, "source_system": source_system}
            )
        )
        connection.execute(
            contract_award.insert().values(
                {**award, "award_key": f"extra-award-{key}", "event_key": key}
            )
        )
    return key


def test_exact_event_selection_skips_earlier_unrelated_notices_without_network(engine):
    unrelated = _extra_event(engine)
    client = Client()
    result = api().backfill_notice_facts(
        engine, now=NOW, client=client, limit=1, event_keys=(_event_key(),)
    )
    assert [item.event_key for item in result.items] == [_event_key()]
    assert unrelated not in {item.event_key for item in result.items}
    assert result.cursor.after_event_key == ""
    assert len(result.cursor.selection_hash) == 64
    assert client.calls == []
    with engine.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(notice_award_facts)) == 0


def test_exact_selection_execute_and_resume_never_fetch_unselected_notices(engine):
    _extra_event(engine)
    module = api()
    selected = (_event_key(),)
    failure = Client(error=ValueError("unavailable"))
    first = module.backfill_notice_facts(
        engine, now=NOW, dry_run=False, client=failure, event_keys=selected
    )
    assert first.cursor.pending[0].attempts == 1
    cursor = module.NoticeBackfillCursor.model_validate_json(first.cursor.model_dump_json())
    client = Client()
    completed = module.backfill_notice_facts(
        engine, now=NOW, dry_run=False, client=client, event_keys=selected, cursor=cursor
    )
    assert client.calls == [record()["idweb"]]
    assert completed.cursor.pending == ()
    assert completed.cursor.selection_hash == cursor.selection_hash
    assert completed.facts_created == 2
    repeated = module.backfill_notice_facts(
        engine, now=NOW, dry_run=False, client=client, event_keys=selected, cursor=completed.cursor
    )
    assert repeated.selected == 0
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    "selection",
    [
        (),
        (_event_key(), _event_key()),
        ("unknown",),
        tuple(f"event-{i}" for i in range(101)),
        "one-key",
        (True,),
    ],
)
def test_invalid_exact_selection_fails_before_any_fetch_or_checkpoint(engine, selection):
    client = Client()
    checkpoints = []
    with pytest.raises(ValueError, match="event_keys"):
        api().backfill_notice_facts(
            engine,
            now=NOW,
            dry_run=False,
            client=client,
            event_keys=selection,
            checkpoint=checkpoints.append,
        )
    assert client.calls == checkpoints == []


def test_exact_selection_rejects_an_existing_non_boamp_event(engine):
    other_source = _extra_event(engine, "simap:foreign-source:", source_system="simap")
    client = Client()
    with pytest.raises(ValueError, match="event_keys"):
        api().backfill_notice_facts(
            engine, now=NOW, dry_run=False, client=client, event_keys=(other_source,)
        )
    assert client.calls == []


def test_selection_hash_is_order_independent_but_cursor_cannot_change_or_lose_scope(engine):
    module = api()
    other = _extra_event(engine)
    selected = (_event_key(), other)
    first = module.backfill_notice_facts(engine, now=NOW, event_keys=selected)
    reversed_order = module.backfill_notice_facts(
        engine, now=NOW, event_keys=tuple(reversed(selected)), cursor=first.cursor
    )
    assert reversed_order.cursor.selection_hash == first.cursor.selection_hash
    for changed in ((_event_key(),), None):
        with pytest.raises(ValueError, match="selection"):
            module.backfill_notice_facts(engine, now=NOW, event_keys=changed, cursor=first.cursor)
    legacy_progressed = module.NoticeBackfillCursor(after_event_key=other)
    with pytest.raises(ValueError, match="selection"):
        module.backfill_notice_facts(engine, now=NOW, event_keys=selected, cursor=legacy_progressed)
    # Existing unscoped progress remains valid for the global administrative run.
    unscoped = module.backfill_notice_facts(engine, now=NOW, cursor=legacy_progressed)
    assert unscoped.cursor.selection_hash is None


def test_scoped_cursor_rejects_an_outside_pending_identity_before_fetch(engine):
    module = api()
    other = _extra_event(engine)
    scoped = module.backfill_notice_facts(engine, now=NOW, event_keys=(_event_key(),)).cursor
    forged = scoped.model_copy(
        update={
            "pending": (module.NoticeBackfillAttempt(event_key=other, attempts=1),),
        }
    )
    client = Client()
    with pytest.raises(ValueError, match="selection"):
        module.backfill_notice_facts(
            engine,
            now=NOW,
            dry_run=False,
            client=client,
            event_keys=(_event_key(),),
            cursor=forged,
        )
    assert client.calls == []


def test_cli_repeatable_event_key_is_a_read_only_exact_selection(engine, monkeypatch, capsys):
    module = api()
    other = _extra_event(engine)
    monkeypatch.setattr(module, "create_database_engine", lambda: engine)

    def forbidden_client():
        pytest.fail("dry-run must not instantiate a provider client")

    monkeypatch.setattr(module, "BoampClient", forbidden_client)
    monkeypatch.setattr(
        "sys.argv",
        ["notice-backfill", "--event-key", _event_key(), "--event-key", other, "--limit", "1"],
    )
    module.main()
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is True
    assert result["selected"] == 1
    assert result["items"][0]["event_key"] == other
    assert result["cursor"]["after_event_key"] == ""
    assert len(result["cursor"]["selection_hash"]) == 64


def test_cli_exact_execute_checkpoints_selection_before_fetch(
    engine, monkeypatch, capsys, tmp_path
):
    module = api()
    path = tmp_path / "exact-selection.json"

    class CheckpointReader(Client):
        def fetch_record(self, identity):
            checkpoint = json.loads(path.read_text())
            assert len(checkpoint["selection_hash"]) == 64
            assert checkpoint["pending"][0]["event_key"] == _event_key()
            assert checkpoint["pending"][0]["attempts"] == 1
            return super().fetch_record(identity)

    client = CheckpointReader()
    monkeypatch.setattr(module, "create_database_engine", lambda: engine)
    monkeypatch.setattr(module, "BoampClient", lambda: contextlib.nullcontext(client))
    monkeypatch.setattr(
        "sys.argv",
        [
            "notice-backfill",
            "--event-key",
            _event_key(),
            "--execute",
            "--cursor-file",
            str(path),
        ],
    )
    module.main()
    result = json.loads(capsys.readouterr().out)
    checkpoint = json.loads(path.read_text())
    assert result["facts_created"] == 2
    assert checkpoint["pending"] == []
    assert checkpoint["selection_hash"] == result["cursor"]["selection_hash"]
    assert client.calls == [record()["idweb"]]


def test_backfill_defaults_to_read_only_dry_run_without_network_or_cursor_advance(engine):
    client = Client()
    result = api().backfill_notice_facts(engine, now=NOW, client=client)
    assert result.dry_run is True
    assert result.selected == 1
    assert result.facts_created == 0
    assert result.cursor.after_event_key == ""
    assert client.calls == []
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(notice_source_snapshot)
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize("limit", [0, 101])
def test_notice_limit_cannot_exceed_one_hundred(engine, limit):
    with pytest.raises(ValueError, match="100"):
        api().backfill_notice_facts(engine, now=NOW, limit=limit)


def test_default_dry_run_limits_a_larger_database_to_one_hundred_notices(engine):
    with engine.begin() as connection:
        event = dict(connection.execute(sa.select(source_event)).first()._mapping)
        award = dict(connection.execute(sa.select(contract_award)).first()._mapping)
        for index in range(101):
            key = f"boamp:bounded-{index:03}:"
            connection.execute(
                source_event.insert().values(
                    {**event, "event_key": key, "source_notice_id": f"bounded-{index:03}"}
                )
            )
            connection.execute(
                contract_award.insert().values(
                    {**award, "award_key": f"bounded-award-{index:03}", "event_key": key}
                )
            )
    result = api().backfill_notice_facts(engine, now=NOW)
    assert result.selected == len(result.items) == 100


def test_execute_uses_one_exact_lookup_and_is_idempotent(engine):
    client = Client()
    result = api().backfill_notice_facts(engine, now=NOW, dry_run=False, client=client)
    assert result.facts_created == 2
    assert result.snapshots_created == 1
    assert client.calls == ["26-fixture-facts"]
    repeated = api().backfill_notice_facts(engine, now=NOW, dry_run=False, client=client)
    assert repeated.selected == 0
    assert len(client.calls) == 1
    assert "donnees" not in result.model_dump_json()
    assert "winner-one@example.test" not in result.model_dump_json()


def test_stored_unexpired_source_is_used_before_any_network_lookup(engine):
    raw = record()
    event, awards = parse_award_notice(raw, retrieved_at=NOW)
    extracted = extract_boamp_notice_facts(raw, event=event, awards=awards, collected_at=NOW)
    with engine.begin() as connection:
        store_notice_facts(connection, dataclasses.replace(extracted, awards=()))
    client = Client(error=AssertionError("network must not be needed"))
    result = api().backfill_notice_facts(engine, now=NOW, dry_run=False, client=client)
    assert result.cache_hits == 1
    assert result.facts_created == 2
    assert client.calls == []


def test_failures_remain_in_cursor_and_stop_after_three_durable_attempts(engine):
    module = api()
    client = Client(error=BoampHttpError("provider unavailable", category="server_error"))
    cursor = module.NoticeBackfillCursor()
    checkpoints = []
    for attempt in range(1, 4):
        result = module.backfill_notice_facts(
            engine,
            now=NOW,
            dry_run=False,
            client=client,
            cursor=cursor,
            checkpoint=checkpoints.append,
        )
        cursor = module.NoticeBackfillCursor.model_validate_json(result.cursor.model_dump_json())
        assert len(client.calls) == attempt
        assert checkpoints[-1] == cursor
        if attempt < 3:
            assert cursor.pending[0].attempts == attempt
        else:
            assert cursor.pending == ()
            assert cursor.terminal[0].attempts == 3
            assert result.items[0].status == "exhausted"
    result = module.backfill_notice_facts(
        engine, now=NOW, dry_run=False, client=client, cursor=cursor
    )
    assert result.selected == 0
    assert len(client.calls) == 3


def test_provider_exception_content_is_not_copied_into_report_or_durable_cursor(engine):
    client = Client(error=ValueError('Invalid JSON {"email": "private@example.test"}'))
    result = api().backfill_notice_facts(engine, now=NOW, dry_run=False, client=client)
    assert result.items[0].status == "failed"
    assert "private@example.test" not in result.model_dump_json()


def test_attempt_checkpoint_is_written_before_external_fetch(engine):
    saved = []

    class OrderedClient(Client):
        def fetch_record(self, identity):
            assert saved and saved[-1].pending[0].attempts == 1
            return super().fetch_record(identity)

    result = api().backfill_notice_facts(
        engine,
        now=NOW,
        dry_run=False,
        client=OrderedClient(),
        checkpoint=saved.append,
    )
    assert result.facts_created == 2
    assert saved[-1].pending == ()


def test_unsupported_family_is_reported_durably_without_adapting_or_retrying(engine):
    raw = record()
    raw["donnees"] = {"MAPA": {"text": "not parsed"}}
    result = api().backfill_notice_facts(engine, now=NOW, dry_run=False, client=Client(payload=raw))
    assert result.items[0].status == "unsupported"
    assert result.cursor.terminal[0].reason == "unsupported_notice_family"
    assert result.facts_created == 0
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(notice_source_snapshot)
            ).scalar_one()
            == 0
        )


def test_wrong_notice_identity_is_reported_and_does_not_change_canonical_facts(engine):
    raw = record()
    raw["idweb"] = "26-other"
    result = api().backfill_notice_facts(engine, now=NOW, dry_run=False, client=Client(payload=raw))
    assert result.items[0].status == "failed"
    assert result.facts_created == 0
    with engine.connect() as connection:
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(contract_award)).scalar_one()
            == 2
        )
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(notice_source_snapshot)
            ).scalar_one()
            == 0
        )


def test_backfill_fetches_only_explicit_related_notice_and_stores_both_sources(engine):
    from test_boamp_notice_facts import linked_tender_fixture

    raw, prior = linked_tender_fixture()

    class RelatedClient(Client):
        def fetch_record(self, identity):
            self.calls.append(identity)
            return raw if identity == raw["idweb"] else prior

    client = RelatedClient()
    result = api().backfill_notice_facts(engine, now=NOW, dry_run=False, client=client)
    assert result.facts_created == 2
    assert client.calls == [raw["idweb"], prior["idweb"]]
    assert result.snapshots_created == 2


def test_backfill_enriches_persisted_partial_facts_from_explicit_consultation_once(engine):
    from test_boamp_notice_facts import linked_tender_fixture

    from signals.client_value.notice_facts import load_award_notice_facts

    raw, prior = linked_tender_fixture()
    event, awards = parse_award_notice(raw, retrieved_at=NOW)
    partial = extract_boamp_notice_facts(raw, event=event, awards=awards, collected_at=NOW)
    with engine.begin() as connection:
        store_notice_facts(connection, partial)
    client = Client(payload=prior)
    result = api().backfill_notice_facts(engine, now=NOW, dry_run=False, client=client)
    assert result.selected == 1
    assert result.facts_created == 2
    assert client.calls == [prior["idweb"]]
    with engine.connect() as connection:
        assert (
            load_award_notice_facts(connection, partial.awards[0].award_key).initial_duration.value
            == "12"
        )
    repeated = api().backfill_notice_facts(engine, now=NOW, dry_run=False, client=client)
    assert repeated.selected == 0
    assert len(client.calls) == 1


def test_fresh_consultation_keeps_own_collection_time_when_attribution_uses_old_cache(engine):
    from test_boamp_notice_facts import linked_tender_fixture

    raw, prior = linked_tender_fixture()
    old = NOW - dt.timedelta(days=10)
    event, awards = parse_award_notice(raw, retrieved_at=old)
    partial = extract_boamp_notice_facts(raw, event=event, awards=awards, collected_at=old)
    with engine.begin() as connection:
        store_notice_facts(connection, dataclasses.replace(partial, awards=()))
    result = api().backfill_notice_facts(
        engine, now=NOW, dry_run=False, client=Client(payload=prior)
    )
    assert result.facts_created == 2
    with engine.connect() as connection:
        rows = {
            row.source_notice_id: row
            for row in connection.execute(sa.select(notice_source_snapshot))
        }
    assert rows[raw["idweb"]].collected_at == old.replace(tzinfo=None)
    assert rows[prior["idweb"]].collected_at == NOW.replace(tzinfo=None)
    assert rows[prior["idweb"]].expires_at == (NOW + dt.timedelta(days=365)).replace(tzinfo=None)


def test_explicit_but_nonmatching_consultation_does_not_trigger_unbounded_research(engine):
    from test_boamp_notice_facts import linked_tender_fixture

    from signals.client_value.notice_facts import load_award_notice_facts

    raw, prior = linked_tender_fixture()
    prior["contractfolderid"] = "different-procedure"
    event, awards = parse_award_notice(raw, retrieved_at=NOW)
    partial = extract_boamp_notice_facts(raw, event=event, awards=awards, collected_at=NOW)
    with engine.begin() as connection:
        store_notice_facts(connection, partial)
    client = Client(payload=prior)
    result = api().backfill_notice_facts(engine, now=NOW, dry_run=False, client=client)
    assert result.selected == 1
    assert result.facts_created == 2
    with engine.connect() as connection:
        persisted = load_award_notice_facts(connection, partial.awards[0].award_key)
        assert persisted.initial_duration is None
    for _ in range(3):
        assert (
            api().backfill_notice_facts(engine, now=NOW, dry_run=False, client=client).selected == 0
        )
    assert client.calls == [prior["idweb"]]


def test_cached_consultation_keeps_its_original_observation_and_custom_expiry(engine):
    from test_boamp_notice_facts import linked_tender_fixture

    from signals.client_value.notice_facts import SnapshotPolicy
    from signals.connectors.boamp.facts import prepare_related_notice_snapshot

    raw, prior = linked_tender_fixture()
    old = NOW - dt.timedelta(days=10)
    related_time = NOW - dt.timedelta(days=3)
    event, awards = parse_award_notice(raw, retrieved_at=old)
    partial = extract_boamp_notice_facts(raw, event=event, awards=awards, collected_at=old)
    related_snapshot = prepare_related_notice_snapshot(
        prior, collected_at=related_time, policy=SnapshotPolicy(ttl_days=30)
    )
    with engine.begin() as connection:
        store_notice_facts(
            connection,
            dataclasses.replace(
                partial,
                related_snapshots=(related_snapshot,),
                awards=(),
            ),
        )
    client = Client(error=AssertionError("both source records must use their own cache"))
    result = api().backfill_notice_facts(engine, now=NOW, dry_run=False, client=client)
    assert result.facts_created == 2 and result.cache_hits == 2
    assert client.calls == []
    with engine.connect() as connection:
        persisted = connection.execute(
            sa.select(notice_source_snapshot).where(
                notice_source_snapshot.c.source_notice_id == prior["idweb"],
            )
        ).one()
    assert persisted.collected_at == related_time.replace(tzinfo=None)
    assert persisted.expires_at == (related_time + dt.timedelta(days=30)).replace(tzinfo=None)
