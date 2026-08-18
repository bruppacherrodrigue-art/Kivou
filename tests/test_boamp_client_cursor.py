"""SPEC-009E §37, §38 — l'adapter BOAMP est appelable « depuis un curseur ».

Aucun daemon n'est construit ici. Ce qui est vérifié, c'est que la forme de
l'appel supporte un futur polling : une fenêtre exprimée par une date, une
pagination déterministe, et aucune dépendance à l'état local du développeur.

Ces tests ne touchent pas le réseau : ils portent sur la construction de la
requête, qui est une fonction pure.
"""

from __future__ import annotations

import datetime as dt

import pytest

from signals.connectors.boamp.client import (
    BOAMP_DATASET_URL,
    PAGE_SIZE,
    AwardCursor,
    award_query,
)


def test_a_cursor_is_expressed_as_a_publication_date_not_an_offset():
    """Un offset se périme dès qu'un avis est inséré ; une date, jamais."""
    cursor = AwardCursor(since=dt.date(2026, 8, 1))
    assert cursor.since == dt.date(2026, 8, 1)
    assert "dateparution>=date'2026-08-01'" in award_query(cursor)["where"]


def test_the_query_selects_award_notices_only():
    query = award_query(AwardCursor(since=dt.date(2026, 8, 1)))
    assert 'nature="ATTRIBUTION"' in query["where"]


def test_the_ordering_is_deterministic_so_pages_never_overlap_or_skip():
    query = award_query(AwardCursor(since=dt.date(2026, 8, 1)))
    assert query["order_by"] == "dateparution asc, idweb asc"


def test_the_same_cursor_builds_the_same_query_every_time():
    """§37 — idempotence : aucune horloge, aucun aléa dans la requête."""
    cursor = AwardCursor(since=dt.date(2026, 8, 1), offset=200)
    assert award_query(cursor) == award_query(cursor)


def test_paging_advances_by_the_declared_page_size():
    cursor = AwardCursor(since=dt.date(2026, 8, 1))
    assert award_query(cursor)["offset"] == 0
    assert award_query(cursor.next_page())["offset"] == PAGE_SIZE
    assert award_query(cursor.next_page().next_page())["offset"] == 2 * PAGE_SIZE


def test_advancing_the_window_resets_the_offset():
    """Passer à une nouvelle fenêtre repart du début : sinon on saute des avis."""
    advanced = AwardCursor(since=dt.date(2026, 8, 1), offset=300).advance_to(dt.date(2026, 8, 15))
    assert advanced.since == dt.date(2026, 8, 15)
    assert advanced.offset == 0


def test_an_upper_bound_is_optional_and_appears_only_when_given():
    open_ended = award_query(AwardCursor(since=dt.date(2026, 8, 1)))
    assert "dateparution<=" not in open_ended["where"]
    bounded = award_query(AwardCursor(since=dt.date(2026, 8, 1), until=dt.date(2026, 8, 18)))
    assert "dateparution<=date'2026-08-18'" in bounded["where"]


def test_a_window_that_ends_before_it_starts_is_refused():
    with pytest.raises(ValueError, match="fenêtre"):
        AwardCursor(since=dt.date(2026, 8, 18), until=dt.date(2026, 8, 1))


def test_the_page_size_stays_within_the_portal_limit():
    assert 0 < PAGE_SIZE <= 100


def test_the_dataset_url_is_the_public_opendatasoft_catalog():
    assert BOAMP_DATASET_URL.startswith("https://boamp-datadila.opendatasoft.com/")
    assert "datasets/boamp" in BOAMP_DATASET_URL
