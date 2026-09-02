"""SPEC-012 §17, §29, §31 — une lecture bornée, un ordre stable, aucune ligne perdue.

Le choix retenu est la pagination par décalage (`offset`), et il est assumé :
l'ordre du feed dépend de la fraîcheur RÉÉVALUÉE au jour de la lecture, qui ne
peut pas être triée en SQL sans figer un instantané — exactement ce que SPEC-010
interdit d'exposer. Un curseur de clé porterait donc sur une colonne qui n'est
pas celle du tri, et sauterait des lignes.

Le prix est connu : la page N relit les mêmes candidats. Le volume actuel le
permet, la lecture est plafonnée en amont, et la troncature est ANNONCÉE plutôt
que silencieuse. Le jour où le volume l'exigera, il faudra persister un rang de
fraîcheur — c'est-à-dire changer le modèle, pas la pagination.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
from fastapi.testclient import TestClient
from feed_helpers import (
    BOAMP_AGING,
    COMPLETE_ICP_INPUT,
    ORIGIN,
    PASSWORD,
    RESEARCH_ICP_ID,
    materialize,
    materialize_boamp,
    simap_award,
)

from signals.api import ApiConfig, create_app
from signals.feed import policy
from signals.persistence.database import create_database_engine, migrate_to_latest

READ_ON = dt.date(2026, 8, 25)


class Clock:
    def __init__(self) -> None:
        self.now = dt.datetime.combine(READ_ON, dt.time(9, 0), tzinfo=dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.now


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def client(engine) -> TestClient:
    app = create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN, session_ttl=dt.timedelta(days=365)),
        now_override=Clock(),
    )
    client = TestClient(app, headers={"Origin": ORIGIN})
    client.post(
        "/auth/signup",
        json={
            "email": "alice@negoce-romand.ch",
            "password": PASSWORD,
            "company_name": "Negoce Romand SA",
            "locale": "fr",
        },
    )
    return client


@pytest.fixture
def icp(client: TestClient) -> str:
    return client.post(
        "/target-icps", json={"label": "Intrants", "customer_input": COMPLETE_ICP_INPUT}
    ).json()["target_icp_id"]


SIMAP_NAMES = (
    "29997-02",
    "33112-02",
    "33885-03",
    "34794-02",
    "38918-02",
    "41098-01",
    "42486-01",
)


#: Antérieure à la parution de tous les avis SIMAP utilisés ici (13 au 15 août).
#: Une décision postérieure à sa propre publication est refusée par la politique
#: de fraîcheur — et c'est elle qui a raison, pas le jeu de test.
AWARDED_FROM = dt.date(2026, 8, 13)


def seed(engine, icp: str, *, count: int) -> list[str]:
    """`count` signaux réels, tous `recent_award` à la date de lecture.

    Les dates d'attribution sont décalées d'un jour l'une de l'autre pour rendre
    l'ordre observable — les avis d'origine ne suffisent pas, plusieurs partagent
    la même date.
    """
    keys = []
    with engine.begin() as connection:
        for index in range(count):
            name = SIMAP_NAMES[index % len(SIMAP_NAMES)]
            event, awards = simap_award(name)
            award = awards[0].model_copy(
                update={"award_date": AWARDED_FROM - dt.timedelta(days=index)}
            )
            keys.append(materialize(connection, event, award, target_icp_id=icp).signal_key)
    return keys


def page(client: TestClient, **params) -> dict:
    query = "&".join(f"{name}={value}" for name, value in params.items())
    response = client.get(f"/signals?{query}")
    assert response.status_code == 200, response.text
    return response.json()


# ─── §29.1 — le plafond est imposé par le serveur ─────────────────────────────


def test_a_page_larger_than_the_maximum_is_refused_rather_than_trimmed(client, icp, engine):
    seed(engine, icp, count=3)
    response = client.get(f"/signals?limit={policy.MAXIMUM_PAGE_SIZE + 1}")
    assert response.status_code == 422, "un plafond rogné en silence se découvre trop tard"


def test_the_default_page_size_is_bounded(client, icp, engine):
    seed(engine, icp, count=7)
    body = page(client)
    assert body["page"]["limit"] == policy.DEFAULT_PAGE_SIZE
    assert len(body["items"]) <= policy.DEFAULT_PAGE_SIZE


def test_a_zero_or_negative_page_size_is_refused(client, icp):
    assert client.get("/signals?limit=0").status_code == 422
    assert client.get("/signals?offset=-1").status_code == 422


# ─── §29.2 — l'ordre est déterministe ─────────────────────────────────────────


def test_the_same_request_twice_returns_exactly_the_same_page(client, icp, engine):
    seed(engine, icp, count=7)
    first = [item["signal_id"] for item in page(client, limit=3)["items"]]
    second = [item["signal_id"] for item in page(client, limit=3)["items"]]
    assert first == second


def test_the_order_follows_the_event_date_descending(client, icp, engine):
    seed(engine, icp, count=7)
    dates = [item["event"]["date"] for item in page(client, limit=10)["items"]]
    assert dates == sorted(dates, reverse=True)


# ─── §29.3, §29.4 — ni recouvrement, ni oubli ─────────────────────────────────


def test_two_pages_never_overlap(client, icp, engine):
    seed(engine, icp, count=7)
    first = {item["signal_id"] for item in page(client, limit=3, offset=0)["items"]}
    second = {item["signal_id"] for item in page(client, limit=3, offset=3)["items"]}
    assert len(first) == len(second) == 3
    assert first & second == set()


def test_walking_every_page_yields_every_signal_exactly_once(client, icp, engine):
    expected = set(seed(engine, icp, count=7))

    seen: list[str] = []
    offset = 0
    while True:
        body = page(client, limit=2, offset=offset)
        seen += [item["signal_id"] for item in body["items"]]
        if not body["page"]["has_more"]:
            break
        offset += 2

    assert len(seen) == len(set(seen)), "aucun signal servi deux fois"
    assert set(seen) == expected, "aucun signal sauté"


def test_has_more_says_the_truth_on_the_last_page(client, icp, engine):
    seed(engine, icp, count=7)
    assert page(client, limit=3, offset=0)["page"]["has_more"] is True
    assert page(client, limit=3, offset=6)["page"]["has_more"] is False
    assert page(client, limit=50, offset=0)["page"]["has_more"] is False


def test_an_offset_beyond_the_end_is_an_empty_page_not_an_error(client, icp, engine):
    seed(engine, icp, count=3)
    body = page(client, limit=5, offset=99)
    assert body["items"] == []
    assert body["page"]["has_more"] is False


# ─── §29.5 — l'étranger et le non-lié ne déplacent rien ───────────────────────


def test_unbound_signals_never_shift_the_customer_pages(client, icp, engine):
    expected = seed(engine, icp, count=5)
    with engine.begin() as connection:
        materialize_boamp(connection, BOAMP_AGING, target_icp_id=RESEARCH_ICP_ID)

    walked: list[str] = []
    for offset in (0, 2, 4):
        walked += [item["signal_id"] for item in page(client, limit=2, offset=offset)["items"]]
    assert walked == [item["signal_id"] for item in page(client, limit=50)["items"]]
    assert set(walked) == set(expected)


def test_a_foreign_account_signal_never_shifts_the_pages(client, icp, engine):
    from feed_helpers import make_account, make_icp

    expected = seed(engine, icp, count=5)
    with engine.begin() as connection:
        other = make_account(connection, "bob@materiaux-leman.ch", "Materiaux Leman")
        other_icp = make_icp(connection, other, "Chez Bob")
        # Un avis absent du jeu d'Alice : deux comptes, deux marchés distincts.
        event, awards = simap_award("41098-01")
        materialize(
            connection,
            event,
            awards[0].model_copy(update={"award_date": AWARDED_FROM}),
            target_icp_id=other_icp,
        )

    assert {item["signal_id"] for item in page(client, limit=50)["items"]} == set(expected)


# ─── §17, §31 — la lecture est bornée, et le dit ──────────────────────────────


def test_the_scan_cap_is_announced_rather_than_silent(client, icp, engine, monkeypatch):
    """Une troncature tue reviendrait à dire « voilà tout » alors qu'il en restait."""
    seed(engine, icp, count=5)
    monkeypatch.setattr(policy, "CANDIDATE_SCAN_CAP", 2)

    body = page(client, limit=50)
    assert body["page"]["scan_truncated"] is True
    assert len(body["items"]) <= 2


def test_a_complete_read_reports_no_truncation(client, icp, engine):
    seed(engine, icp, count=5)
    assert page(client, limit=50)["page"]["scan_truncated"] is False


def test_listing_a_page_does_not_query_evidence_once_per_row(client, icp, engine):
    """§31 — la carte n'a pas de preuve, donc pas de N+1 à l'affichage."""
    import sqlalchemy as sa

    seed(engine, icp, count=7)
    statements: list[str] = []

    @sa.event.listens_for(engine, "before_cursor_execute")
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    try:
        assert len(page(client, limit=7)["items"]) == 7
    finally:
        sa.event.remove(engine, "before_cursor_execute", record)

    normalized = [" ".join(statement.lower().split()) for statement in statements]
    evidence_hydrations = [
        statement for statement in normalized if statement.startswith("select evidence.")
    ]
    presentation_batches = [
        statement
        for statement in normalized
        if statement.startswith("select card_presentation_artifact.")
    ]

    assert evidence_hydrations == [], "aucune preuve n'est hydratée par carte de feed"
    assert len(presentation_batches) == 1, "les présentations sont chargées en un seul batch"


# ─── Le plafond compte les candidats AFFICHABLES, pas les lignes lues ──────────


def _strip_legal_names(award):
    """Le cas DECP 2022 : un SIRET recopié en guise de nom."""
    parties = []
    for party in award.awardee_parties:
        members = [
            member.model_copy(
                update={
                    "organization": member.organization.model_copy(
                        update={"legal_name": member.organization.identifiers[0].value}
                    )
                }
            )
            for member in party.members
        ]
        parties.append(party.model_copy(update={"members": tuple(members)}))
    return award.model_copy(update={"awardee_parties": tuple(parties)})


def test_nameless_rows_do_not_consume_the_scan_cap(client, icp, engine, monkeypatch):
    """Staging, 2026-09-02 : 491 notifications DECP sans nom remplissaient les
    500 lignes lues et cachaient les signaux nommés matérialisés avant elles.
    Le plafond porte désormais sur les candidats qu'on peut montrer."""
    import sqlalchemy as sa

    from signals.feed import query
    from signals.persistence.schema import materialized_signal

    named = seed(engine, icp, count=1)[0]
    nameless: list[str] = []
    with engine.begin() as connection:
        for name in SIMAP_NAMES[1:4]:
            event, awards = simap_award(name)
            award = _strip_legal_names(awards[0].model_copy(update={"award_date": AWARDED_FROM}))
            nameless.append(materialize(connection, event, award, target_icp_id=icp).signal_key)
        # Les lignes sans nom sont les plus récemment matérialisées : c'est
        # exactement la situation qui masquait le signal nommé.
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key.in_(nameless))
            .values(materialized_at=dt.datetime(2026, 8, 18, 10, 0, tzinfo=dt.UTC))
        )
    monkeypatch.setattr(policy, "CANDIDATE_SCAN_CAP", 2)
    monkeypatch.setattr(query, "RECENT_SCAN_BATCH", 2)

    body = page(client, limit=50)
    assert [item["signal_id"] for item in body["items"]] == [named]
    assert body["excluded"]["without_display_name"] == 3
    assert body["page"]["scan_truncated"] is False


def test_the_row_ceiling_still_announces_truncation(client, icp, engine, monkeypatch):
    """Le plafond absolu de lignes lues borne le coût ; quand il tombe avant la
    fin, la troncature est dite, jamais tue — même quand aucun candidat lu
    n'était affichable (rien à opposer au plafond des candidats affichables,
    §285)."""
    import sqlalchemy as sa

    from signals.feed import query
    from signals.persistence.schema import materialized_signal

    seed(engine, icp, count=1)
    nameless: list[str] = []
    with engine.begin() as connection:
        for name in SIMAP_NAMES[1:4]:
            event, awards = simap_award(name)
            award = _strip_legal_names(awards[0].model_copy(update={"award_date": AWARDED_FROM}))
            nameless.append(materialize(connection, event, award, target_icp_id=icp).signal_key)
        # Les lignes sans nom sont les plus récemment matérialisées : elles
        # sont donc lues en premier, et consomment seules le plafond absolu.
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key.in_(nameless))
            .values(materialized_at=dt.datetime(2026, 8, 18, 10, 0, tzinfo=dt.UTC))
        )
    monkeypatch.setattr(policy, "CANDIDATE_SCAN_CAP", 2)
    monkeypatch.setattr(query, "RECENT_SCAN_BATCH", 1)
    monkeypatch.setattr(query, "RECENT_SCAN_ROW_FACTOR", 1)

    body = page(client, limit=50)
    assert body["items"] == []
    assert body["excluded"]["without_display_name"] == 2
    assert body["page"]["scan_truncated"] is True
