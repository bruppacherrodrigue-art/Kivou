"""PR2b tâche 4 — `GET /signals/filters` : la nomenclature RÉELLEMENT présente.

Le sélecteur d'un filtre (zone, secteur) ne doit pas proposer la nomenclature
entière — des milliers d'entrées CPV, tous les départements français — mais
seulement ce que le compte peut voir dans SES signaux accessibles, dans la
même portée bornée que `GET /companies` (`_scan_accessible_signals`).
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
from engagement_helpers import Clock, icp_of, make_app, make_engine, pay, signed_up
from fastapi.testclient import TestClient
from feed_helpers import materialize, simap_award

from signals.domain.values import CpvCode, Location

#: Des avis SIMAP réels distincts — `signal_key` dérive de l'identité SOURCE
#: (avis, lot), jamais des champs réécrits ci-dessous : réutiliser le même
#: avis produirait la MÊME révision, pas un second signal.
SOURCES = (
    "28066-04",
    "29997-02",
    "33112-02",
    "33885-03",
    "34794-02",
    "38147-02",
    "38918-02",
    "41098-01",
    "42486-01",
)

#: `FR-92` (Hauts-de-Seine) et `FR-75` (Paris) — voir
#: `signals.domain.french_departments.department_from_postal_code`.
HAUTS_DE_SEINE = Location(country="FR", postal_code="92350")
PARIS = Location(country="FR", postal_code="75001")

TRAVAUX_DE_CONSTRUCTION = CpvCode(code="45000000")
PRODUITS_ALIMENTAIRES = CpvCode(code="15000000")


class _SourcePool:
    """Un avis distinct par appel — jamais deux fois le même (voir `SOURCES`)."""

    def __init__(self) -> None:
        self._remaining = list(SOURCES)

    def take(self) -> str:
        return self._remaining.pop(0)


def _seed(engine, icp: str, pool: _SourcePool, *, award_date: dt.date, **overrides) -> str:
    """Un signal réel dont le lieu ou le CPV sont contrôlés par le test."""
    event, awards = simap_award(pool.take())
    award = awards[0].model_copy(update={"award_date": award_date, **overrides})
    with engine.begin() as connection:
        return materialize(connection, event, award, target_icp_id=icp).signal_key


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    return make_engine(tmp_path)


@pytest.fixture
def app(engine, clock: Clock):
    return make_app(engine, clock)


@pytest.fixture
def alice(app) -> TestClient:
    return signed_up(app)


def test_three_signals_in_two_departments_return_two_subdivisions_sorted_by_label(alice, engine):
    """Deux signaux à Hauts-de-Seine, un à Paris → deux subdivisions, triées par
    libellé (« Hauts-de-Seine » avant « Paris ») et les doublons fusionnés."""
    icp = icp_of(alice)
    pay(engine, alice, plan="pro")  # `filter_level="advanced"` : couvre les deux filtres
    pool = _SourcePool()
    _seed(engine, icp, pool, award_date=dt.date(2026, 8, 10), place_of_performance=HAUTS_DE_SEINE)
    _seed(engine, icp, pool, award_date=dt.date(2026, 8, 11), place_of_performance=HAUTS_DE_SEINE)
    _seed(engine, icp, pool, award_date=dt.date(2026, 8, 12), place_of_performance=PARIS)

    response = alice.get("/signals/filters")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["subdivisions"] == [
        {"code": "FR-92", "label": "Hauts-de-Seine", "country": "FR"},
        {"code": "FR-75", "label": "Paris", "country": "FR"},
    ]


def test_sectors_carry_french_labels(alice, engine):
    from signals.domain.cpv_labels import cpv_label

    icp = icp_of(alice)
    pay(engine, alice, plan="pro")
    pool = _SourcePool()
    _seed(engine, icp, pool, award_date=dt.date(2026, 8, 10), cpv_main=TRAVAUX_DE_CONSTRUCTION)
    _seed(engine, icp, pool, award_date=dt.date(2026, 8, 11), cpv_main=PRODUITS_ALIMENTAIRES)

    payload = alice.get("/signals/filters").json()

    by_prefix = {entry["prefix"]: entry["label"] for entry in payload["sectors"]}
    assert by_prefix["45"] == "Travaux de construction"
    assert by_prefix["15"] == cpv_label("15000000", lang="fr")
    # Les libellés sont triés alphabétiquement entre eux — pas les préfixes.
    assert [entry["label"] for entry in payload["sectors"]] == sorted(by_prefix.values())


def test_an_account_without_basic_access_gets_empty_lists_but_200(alice, engine):
    """Discovery (`filter_level=minimum`) ne couvre ni `subdivision_code` ni
    `cpv_prefix` : les deux listes sont vides, mais la route répond 200 — le
    client grise le contrôle via `filter_access`, pas via une erreur."""
    icp = icp_of(alice)
    pool = _SourcePool()
    _seed(engine, icp, pool, award_date=dt.date(2026, 8, 10), place_of_performance=HAUTS_DE_SEINE,
          cpv_main=TRAVAUX_DE_CONSTRUCTION)

    response = alice.get("/signals/filters")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["subdivisions"] == []
    assert payload["sectors"] == []
    assert payload["filter_access"]["subdivision"] is False
    assert payload["filter_access"]["sector"] is False
    assert payload["plan_code"] == "discovery"


def test_an_essential_plan_unlocks_subdivisions_but_not_sectors(alice, engine):
    """`essential` est `filter_level="basic"` : la zone s'ouvre, le secteur (qui
    exige `advanced`) reste vide."""
    icp = icp_of(alice)
    pay(engine, alice, plan="essential")
    pool = _SourcePool()
    _seed(engine, icp, pool, award_date=dt.date(2026, 8, 10), place_of_performance=HAUTS_DE_SEINE,
          cpv_main=TRAVAUX_DE_CONSTRUCTION)

    payload = alice.get("/signals/filters").json()

    assert payload["subdivisions"] == [{"code": "FR-92", "label": "Hauts-de-Seine", "country": "FR"}]
    assert payload["sectors"] == []


def test_an_account_without_any_accessible_signal_gets_empty_lists(alice, engine):
    icp_of(alice)
    pay(engine, alice, plan="pro")

    payload = alice.get("/signals/filters").json()

    assert payload["subdivisions"] == []
    assert payload["sectors"] == []
    assert payload["scan_truncated"] is False


def test_scan_truncated_is_reported_when_the_history_scan_cap_is_hit(alice, engine, monkeypatch):
    """Le même plafond que `GET /companies` (`feed_query.HISTORY_SCAN_CAP`),
    relu à l'appel : le lier à l'import rendrait ce `monkeypatch` sans effet."""
    from signals.feed import query as feed_query

    icp = icp_of(alice)
    pay(engine, alice, plan="pro")
    pool = _SourcePool()
    _seed(engine, icp, pool, award_date=dt.date(2026, 8, 10), place_of_performance=HAUTS_DE_SEINE)
    _seed(engine, icp, pool, award_date=dt.date(2026, 8, 11), place_of_performance=PARIS)
    monkeypatch.setattr(feed_query, "HISTORY_SCAN_CAP", 1)

    payload = alice.get("/signals/filters").json()

    assert payload["scan_truncated"] is True


def test_the_route_is_not_captured_by_the_signal_detail_path(alice, engine):
    """`/signals/filters` doit être servie par la nouvelle route, pas confondue
    avec `GET /signals/{signal_key}` (ce qui rendrait `signal_not_found`)."""
    pay(engine, alice, plan="pro")

    response = alice.get("/signals/filters")

    assert response.status_code == 200, response.text
    assert "code" not in response.json()
