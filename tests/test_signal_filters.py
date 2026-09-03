"""PR2b tâche 3 — filtres serveur sur `GET /signals` : montant, texte, zone,
secteur et période, désormais disponibles en vue Récentes ET Historique.

`min_amount` et `cpv_prefix`/`date_from`/`date_to` filtrent en SQL, AVANT que
le candidat n'occupe une place du plafond de candidats (`CANDIDATE_SCAN_CAP`
en vue Récentes, `HISTORY_SCAN_CAP` en historique) ; `subdivision_code` et `q`
filtrent en Python, à la MÊME étape, pour la même raison — ils dépendent d'une
valeur dérivée (subdivision) ou de l'identité affichable (résolue après
lecture). `subdivision_code` et `q` incrémentent `excluded.by_filters` ;
`min_amount` et les filtres SQL n'y apparaissent jamais : ils n'atteignent
même pas la boucle qui compte.
"""

from __future__ import annotations

import datetime as dt
import pathlib
from decimal import Decimal

import pytest
from engagement_helpers import Clock, icp_of, make_app, make_engine, pay, signed_up
from fastapi.testclient import TestClient
from feed_helpers import materialize, simap_award

from signals.domain.awards import Awardee, AwardeeParty
from signals.domain.values import Money, OrganizationRef

#: Des avis SIMAP réels, dont on ne garde que la forme — titre, montant,
#: attributaire et lieu sont réécrits par chaque test. `signal_key` dérive de
#: l'identité SOURCE (notice, lot), jamais des champs qu'on réécrit ici : deux
#: appels sur le MÊME avis produiraient donc la MÊME révision, pas deux
#: signaux distincts — d'où un avis différent par signal voulu.
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


def _award(source: str, **overrides):
    event, awards = simap_award(source)
    return event, awards[0].model_copy(update=overrides)


def _awardee(name: str) -> tuple:
    return (AwardeeParty(members=(Awardee(organization=OrganizationRef(legal_name=name)),)),)


class _SourcePool:
    """Un avis distinct par appel — jamais deux fois le même (voir `SOURCES`)."""

    def __init__(self) -> None:
        self._remaining = list(SOURCES)

    def take(self) -> str:
        return self._remaining.pop(0)


def _seed(
    engine, icp: str, pool: _SourcePool, *, award_date: dt.date = dt.date(2026, 8, 13), **overrides
) -> str:
    """Un signal réel dont le titre, le montant, l'attributaire ou le lieu sont
    contrôlés par le test — via `model_copy`, comme `test_signal_fields.py`."""
    event, award = _award(pool.take(), award_date=award_date, **overrides)
    with engine.begin() as connection:
        return materialize(connection, event, award, target_icp_id=icp).signal_key


def _items(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_recent_view_now_accepts_the_previously_history_only_filters(alice, engine):
    """§26 (PR2b tâche 3) — `subdivision_code`, `cpv_prefix`, `date_from` sont
    désormais applicables en vue Récentes : ils ne renvoient plus 422. Seul
    `recency_status` reste un concept propre à l'historique."""
    icp = icp_of(alice)
    pay(engine, alice, plan="scale")  # niveau « advanced » : couvre tous les filtres
    pool = _SourcePool()
    _seed(engine, icp, pool)

    for query in (
        "subdivision_code=FR-92",
        "cpv_prefix=452",
        "date_from=2026-08-01",
        "date_to=2026-08-31",
    ):
        response = alice.get(f"/signals?view=recent&{query}")
        assert response.status_code == 200, f"{query} : {response.text}"

    still_history_only = alice.get("/signals?view=recent&recency_status=recent_award")
    assert still_history_only.status_code == 422
    assert (
        still_history_only.json()["detail"]["code"] == "history_filters_require_history_view"
    )


def test_min_amount_keeps_amounts_at_or_above_and_excludes_unpublished_amounts(alice, engine):
    icp = icp_of(alice)
    pay(engine, alice, plan="essential")
    pool = _SourcePool()
    below = _seed(
        engine, icp, pool, award_date=dt.date(2026, 8, 10), value=Money(amount=Decimal("500000"), currency="CHF")
    )
    at_threshold = _seed(
        engine, icp, pool, award_date=dt.date(2026, 8, 11), value=Money(amount=Decimal("1000000"), currency="CHF")
    )
    above = _seed(
        engine, icp, pool, award_date=dt.date(2026, 8, 12), value=Money(amount=Decimal("2500000"), currency="CHF")
    )
    unpublished_amount = _seed(engine, icp, pool, award_date=dt.date(2026, 8, 13), value=None)

    unfiltered = {item["signal_id"] for item in _items(alice.get("/signals?freshness=all"))}
    assert {below, at_threshold, above, unpublished_amount} <= unfiltered

    filtered = {
        item["signal_id"]
        for item in _items(alice.get("/signals?freshness=all&min_amount=1000000"))
    }
    assert at_threshold in filtered
    assert above in filtered
    assert below not in filtered
    assert unpublished_amount not in filtered


def test_q_matches_the_awardee_name_case_and_accent_insensitively(alice, engine):
    icp = icp_of(alice)
    pay(engine, alice, plan="essential")
    pool = _SourcePool()
    named = _seed(
        engine, icp, pool, award_date=dt.date(2026, 8, 13), awardee_parties=_awardee("Établissements Müller SA")
    )
    other = _seed(
        engine, icp, pool, award_date=dt.date(2026, 8, 12), awardee_parties=_awardee("Bâtiments du Léman Sàrl")
    )

    matched = {
        item["signal_id"]
        for item in _items(alice.get("/signals?freshness=all&q=etablissements muller"))
    }
    assert matched == {named}
    assert other not in matched

    matched_uppercase = {
        item["signal_id"]
        for item in _items(alice.get("/signals?freshness=all&q=MULLER"))
    }
    assert matched_uppercase == {named}


def test_q_matches_the_title_and_therefore_the_derived_short_object(alice, engine):
    """`object_short` (`factual_display`) n'est qu'un titre nettoyé et tronqué :
    un terme qui matche le titre matche donc aussi l'objet court qui en dérive
    — les deux ne sont jamais qu'UN champ recherché, pas deux mécanismes."""
    icp = icp_of(alice)
    pay(engine, alice, plan="essential")
    pool = _SourcePool()
    matching = _seed(
        engine,
        icp,
        pool,
        award_date=dt.date(2026, 8, 13),
        title="Réfection de la toiture de l'École municipale",
    )
    other = _seed(
        engine, icp, pool, award_date=dt.date(2026, 8, 12), title="Fourniture de mobilier de bureau"
    )

    matched = {
        item["signal_id"] for item in _items(alice.get("/signals?freshness=all&q=ecole"))
    }
    assert matched == {matching}
    assert other not in matched


def test_q_of_a_single_character_is_rejected(alice, engine):
    icp_of(alice)
    pay(engine, alice, plan="essential")

    response = alice.get("/signals?q=a")
    assert response.status_code == 422


def test_counts_reflect_min_amount_and_q_filters(alice, engine):
    icp = icp_of(alice)
    pay(engine, alice, plan="essential")
    pool = _SourcePool()
    matching = _seed(
        engine,
        icp,
        pool,
        award_date=dt.date(2026, 8, 13),
        value=Money(amount=Decimal("2000000"), currency="CHF"),
        awardee_parties=_awardee("Négoce Alpin SA"),
    )
    excluded_by_amount = _seed(
        engine,
        icp,
        pool,
        award_date=dt.date(2026, 8, 12),
        value=Money(amount=Decimal("100"), currency="CHF"),
        awardee_parties=_awardee("Négoce Alpin SA"),
    )
    excluded_by_text = _seed(
        engine,
        icp,
        pool,
        award_date=dt.date(2026, 8, 11),
        value=Money(amount=Decimal("3000000"), currency="CHF"),
        awardee_parties=_awardee("Autre Titulaire Sàrl"),
    )

    unfiltered = alice.get("/signals?freshness=all").json()
    unfiltered_total = sum(unfiltered["counts"].values())
    assert unfiltered_total >= 3

    filtered_response = alice.get("/signals?freshness=all&min_amount=1000000&q=negoce alpin")
    filtered = filtered_response.json()
    filtered_keys = {item["signal_id"] for item in filtered["items"]}
    assert filtered_keys == {matching}
    assert excluded_by_amount not in filtered_keys
    assert excluded_by_text not in filtered_keys
    assert sum(filtered["counts"].values()) == 1
    # `q` est un filtre Python (identité affichable) : il compte dans
    # `excluded.by_filters`, contrairement à `min_amount` qui est du SQL et
    # n'atteint jamais la boucle qui compte.
    assert filtered["excluded"]["by_filters"] >= 1


def test_a_basic_plan_can_use_min_amount_and_q_a_plan_without_it_cannot(alice, engine):
    # Discovery — pas de plan payant, niveau « minimum » : les deux filtres
    # sont refusés, jamais ignorés en silence.
    for query in ("min_amount=1000", "q=ab"):
        response = alice.get(f"/signals?{query}")
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "filter_not_entitled"

    pay(engine, alice, plan="essential")  # niveau « basic »
    for query in ("min_amount=1000", "q=ab"):
        response = alice.get(f"/signals?{query}")
        assert response.status_code == 200, response.text

    access = alice.get("/signals").json()["filter_access"]
    assert access["min_amount"] is True
    assert access["search"] is True
