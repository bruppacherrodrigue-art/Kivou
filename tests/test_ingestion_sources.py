from __future__ import annotations

import datetime as dt
import json
import logging
import pathlib

import pytest
from feed_helpers import LINKED_BOAMP, LINKED_DECP

from signals.connectors.decp import DecpBatch
from signals.connectors.simap import PublicationRef
from signals.connectors.ted import NoticeRef
from signals.connectors.ted.errors import TedHttpError
from signals.ingestion.sources import (
    AcquisitionFailure,
    BoampSource,
    DecpSource,
    SimapSource,
    SourceWindow,
    TedAcquisitionFailure,
    TedSource,
    checkpoint_window,
)
from signals.ingestion.ted_convergence import plan_ted_cycle

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
NOW = dt.datetime(2026, 8, 19, 10, tzinfo=dt.UTC)
WINDOW = SourceWindow(dt.date(2026, 8, 1), dt.date(2026, 8, 19))


class SimapStub:
    def __init__(self):
        self._returned = False

    def search_awards(self, **kwargs):
        if self._returned:
            return [], None
        self._returned = True
        return [PublicationRef("project", "publication", search_entry={})], None

    def fetch_publication(self, project_id, publication_id):
        return json.loads((FIXTURES / "simap" / "33112-02.json").read_text())


class BoampStub:
    def fetch_awards_since(self, since, *, until=None, max_records=None):
        records = [LINKED_BOAMP, LINKED_BOAMP, LINKED_BOAMP]
        yield from records if max_records is None else records[:max_records]


class UnsupportedBoampStub:
    def __init__(self, kind="FNSimple"):
        self.kind = kind

    def fetch_awards_since(self, since, *, until=None, max_records=None):
        yield {"idweb": "unsupported", "donnees": json.dumps({self.kind: {}})}


class DspThenSupportedBoampStub:
    def fetch_awards_since(self, since, *, until=None, max_records=None):
        yield {
            "idweb": "26-dsp-safe-skip",
            "donnees": json.dumps(
                {
                    "DSP": {
                        "nature": "delegation_service_public",
                        "objet": "Avis distinct volontairement non normalise",
                    }
                }
            ),
        }
        yield LINKED_BOAMP


class MalformedBoampStub:
    def __init__(self, donnees):
        self.donnees = donnees

    def fetch_awards_since(self, since, *, until=None, max_records=None):
        yield {"idweb": "malformed", "donnees": self.donnees}


class DecpStub:
    def fetch_contracts_since(
        self,
        since,
        *,
        until=None,
        max_records=None,
        should_stop=None,
    ):
        if should_stop is not None:
            should_stop()
        records = [LINKED_DECP]
        yield from records if max_records is None else records[:max_records]


class TedStub:
    def __init__(self):
        self.queries = []
        self.limits = []

    def search(self, query, *, limit=25, page=1):
        self.queries.append(query)
        self.limits.append(limit)
        if page > 1:
            return [], 1
        return [NoticeRef("565942-2026")], 1

    def fetch_notice_xml(self, publication_number):
        return (FIXTURES / "ted" / "565942-2026.xml").read_bytes()


def test_all_four_sources_use_the_existing_normalization_paths():
    ted = TedStub()
    results = (
        SimapSource(SimapStub()).acquire(WINDOW, retrieved_at=NOW),
        BoampSource(BoampStub()).acquire(WINDOW, retrieved_at=NOW),
        DecpSource(DecpStub()).acquire(WINDOW, retrieved_at=NOW),
        TedSource(ted).acquire(WINDOW, retrieved_at=NOW),
    )
    assert [result.source for result in results] == ["simap", "boamp", "decp", "ted"]
    assert all(result.fetched >= 1 for result in results)
    assert all(result.accepted >= 1 for result in results)
    assert all(result.publications for result in results)
    assert [result.publications[0].event.provenance.source_system for result in results] == [
        "simap",
        "boamp",
        "decp",
        "ted",
    ]
    assert ted.queries == [
        (
            "form-type=result AND publication-date>=20260801 "
            "AND publication-date<=20260819 SORT BY publication-number DESC"
        )
    ]
    assert ted.limits == [250]


def test_ted_window_is_incomplete_when_the_api_total_is_not_fully_paged():
    class TruncatedTedStub(TedStub):
        def search(self, query, *, limit=25, page=1):
            self.queries.append(query)
            self.limits.append(limit)
            return [], 1

    result = TedSource(TruncatedTedStub()).acquire(WINDOW, retrieved_at=NOW)

    assert result.fetched == 0
    assert result.complete is False


def test_ted_failure_carries_the_records_already_fetched_and_normalized():
    class PartiallyFailingTedStub(TedStub):
        def search(self, query, *, limit=25, page=1):
            self.queries.append(query)
            self.limits.append(limit)
            return [NoticeRef("565942-2026"), NoticeRef("unavailable-2026")], 2

        def fetch_notice_xml(self, publication_number):
            if publication_number == "unavailable-2026":
                raise TedHttpError("limited", status_code=429)
            return super().fetch_notice_xml(publication_number)

    with pytest.raises(AcquisitionFailure) as raised:
        TedSource(PartiallyFailingTedStub()).acquire(WINDOW, retrieved_at=NOW)

    assert raised.value.partial.fetched == 2
    assert raised.value.partial.accepted == 1
    assert len(raised.value.partial.publications) == 1
    assert raised.value.status_code == 429


def test_ted_unit_searches_one_page_without_downloading_xml() -> None:
    class UnitTedStub:
        def __init__(self) -> None:
            self.calls = []

        def search(self, query, *, limit=25, page=1):
            self.calls.append(("search", limit, page))
            return [NoticeRef("565942-2026"), NoticeRef("550374-2026")], 3

        def fetch_notice_xml(self, publication_number):
            self.calls.append(("xml", publication_number))
            raise AssertionError("search unit must not download XML")

    client = UnitTedStub()
    cursor = plan_ted_cycle(cursor=None, window=WINDOW, page_size=2)

    unit = TedSource(client).acquire_unit(cursor, retrieved_at=NOW)

    assert client.calls == [("search", 2, 1)]
    assert unit.acquisition.fetched == 2
    assert unit.acquisition.accepted == 0
    assert unit.acquisition.publications == ()
    assert unit.cursor_after.pending_publication_numbers == (
        "565942-2026",
        "550374-2026",
    )
    assert unit.cursor_after.next_index == 0
    assert unit.cursor_after.more_pages is True


def test_ted_unit_downloads_and_normalizes_exactly_one_pending_notice() -> None:
    class UnitTedStub:
        def __init__(self) -> None:
            self.calls = []

        def search(self, query, *, limit=25, page=1):
            self.calls.append(("search", limit, page))
            return [NoticeRef("565942-2026"), NoticeRef("550374-2026")], 2

        def fetch_notice_xml(self, publication_number):
            self.calls.append(("xml", publication_number))
            return (FIXTURES / "ted" / f"{publication_number}.xml").read_bytes()

    client = UnitTedStub()
    source = TedSource(client)
    fresh = plan_ted_cycle(cursor=None, window=WINDOW, page_size=2)
    searched = source.acquire_unit(fresh, retrieved_at=NOW).cursor_after

    unit = source.acquire_unit(searched, retrieved_at=NOW)

    assert client.calls == [
        ("search", 2, 1),
        ("xml", "565942-2026"),
    ]
    assert unit.acquisition.fetched == 0
    assert unit.acquisition.accepted == 1
    assert len(unit.acquisition.publications) == 1
    assert unit.acquisition.publications[0].event.provenance.source_system == "ted"
    assert unit.cursor_after.next_index == 1


def test_ted_unit_failure_retains_the_exact_unfinished_cursor() -> None:
    class LimitedTedStub:
        def search(self, query, *, limit=25, page=1):
            return [NoticeRef("limited-2026")], 1

        def fetch_notice_xml(self, publication_number):
            raise TedHttpError("limited", status_code=429, category="rate_limited")

    source = TedSource(LimitedTedStub())
    fresh = plan_ted_cycle(cursor=None, window=WINDOW, page_size=1)
    searched = source.acquire_unit(fresh, retrieved_at=NOW).cursor_after

    with pytest.raises(TedAcquisitionFailure) as raised:
        source.acquire_unit(searched, retrieved_at=NOW)

    assert raised.value.cursor_after == searched
    assert raised.value.partial.fetched == 0
    assert raised.value.partial.accepted == 0
    assert raised.value.partial.publications == ()
    assert raised.value.category == "rate_limited"


def test_a_maximum_record_probe_is_explicitly_incomplete_when_more_data_exists():
    result = BoampSource(BoampStub()).acquire(WINDOW, retrieved_at=NOW, max_records=2)
    assert result.fetched == 2
    assert result.complete is False


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("FNSimple", "unsupported_notice_family_fnsimple"),
        ("MAPA", "unsupported_notice_family_mapa"),
    ],
)
def test_recognized_non_eforms_boamp_is_a_safe_terminal_skip(kind, reason):
    result = BoampSource(UnsupportedBoampStub(kind)).acquire(WINDOW, retrieved_at=NOW)

    assert result.complete is True
    assert result.fetched == 1
    assert result.accepted == 0
    assert result.rejected == 1
    assert result.rejection_reasons == {reason: 1}


def test_dsp_is_a_structured_safe_skip_and_later_supported_records_continue(caplog):
    with caplog.at_level(logging.INFO, logger="signals.ingestion.sources"):
        result = BoampSource(DspThenSupportedBoampStub()).acquire(WINDOW, retrieved_at=NOW)

    assert result.complete is True
    assert result.fetched == 2
    assert result.accepted == 1
    assert result.rejected == 1
    assert result.rejection_reasons == {"unsupported_notice_family_dsp": 1}
    assert result.publications[0].event.provenance.source_notice_id == "26-79799"
    dsp_log = next(record for record in caplog.records if record.reason_code.endswith("_dsp"))
    assert dsp_log.source == "boamp"
    assert dsp_log.source_notice_id == "26-dsp-safe-skip"


@pytest.mark.parametrize(
    "payload",
    [
        "{not-json",
        json.dumps({"EFORMS": {}}),
        json.dumps({"EFORMS": {"ContractAwardNotice": {}}}),
        json.dumps({"UNKNOWN_SOURCE_SCHEMA": {}}),
    ],
)
def test_malformed_boamp_is_a_processing_failure_not_a_terminal_skip(payload):
    with pytest.raises(AcquisitionFailure) as raised:
        BoampSource(MalformedBoampStub(payload)).acquire(WINDOW, retrieved_at=NOW)

    assert raised.value.category == "malformed"
    assert raised.value.partial.complete is False
    assert raised.value.partial.fetched == 1
    assert raised.value.partial.rejected == 0


def test_checkpoint_windows_apply_source_specific_overlap():
    checkpoint = dt.datetime(2026, 8, 18, 12, tzinfo=dt.UTC)
    until = dt.datetime(2026, 8, 19, 12, tzinfo=dt.UTC)
    assert checkpoint_window("simap", checkpoint_end=checkpoint, until=until).since == dt.date(
        2026, 8, 15
    )
    assert checkpoint_window("boamp", checkpoint_end=checkpoint, until=until).since == dt.date(
        2026, 8, 11
    )
    assert checkpoint_window("decp", checkpoint_end=checkpoint, until=until).since == dt.date(
        2026, 7, 19
    )
    assert checkpoint_window("ted", checkpoint_end=checkpoint, until=until).since == dt.date(
        2026, 8, 15
    )


def test_an_explicit_since_is_never_rewritten_by_checkpoint_policy():
    explicit = dt.date(2026, 8, 17)
    window = checkpoint_window(
        "decp", checkpoint_end=None, until=NOW, explicit_since=explicit
    )
    assert window == SourceWindow(explicit, NOW.date())


def test_decp_stop_is_reported_with_only_the_completed_acquisition_progress() -> None:
    calls = 0

    class StopRequested(RuntimeError):
        category = "terminated"

    class PartiallyStoppedDecpStub:
        def fetch_contracts_since(
            self,
            since,
            *,
            until=None,
            max_records=None,
            should_stop=None,
        ):
            nonlocal calls
            yield LINKED_DECP
            calls += 1
            assert should_stop is not None
            should_stop()

    def stop() -> None:
        raise StopRequested("termination requested")

    with pytest.raises(AcquisitionFailure) as raised:
        DecpSource(PartiallyStoppedDecpStub()).acquire(
            WINDOW,
            retrieved_at=NOW,
            should_stop=stop,
        )

    assert calls == 1
    assert raised.value.category == "terminated"
    assert raised.value.partial.fetched == 1
    assert raised.value.partial.accepted == 1
    assert raised.value.partial.complete is False


def test_decp_source_normalizes_one_resumable_batch_and_preserves_its_progress() -> None:
    class BatchDecpStub:
        def fetch_contract_batch(
            self,
            day,
            *,
            offset,
            expected_total,
            batch_size,
        ):
            assert day == WINDOW.since
            assert offset == 2
            assert expected_total == 5
            assert batch_size == 1
            return DecpBatch(
                records=(LINKED_DECP,),
                next_offset=3,
                window_total=5,
                day_complete=False,
                reset=False,
            )

    batch = DecpSource(BatchDecpStub()).acquire_batch(
        SourceWindow(WINDOW.since, WINDOW.since),
        retrieved_at=NOW,
        offset=2,
        expected_total=5,
        batch_size=1,
    )

    assert batch.acquisition.fetched == 1
    assert batch.acquisition.accepted == 1
    assert len(batch.acquisition.publications) == 1
    assert batch.next_offset == 3
    assert batch.window_total == 5
    assert batch.day_complete is False
    assert batch.reset is False
