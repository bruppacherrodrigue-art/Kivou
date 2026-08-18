"""SPEC-012 closeout §1, §2, §3 — la phrase et le type d'événement ne peuvent pas mentir.

Deux corrections, toutes deux du même genre : une formulation qui était vraie
dans le cas fréquent, et fausse dans le cas que le modèle multi-horloges rend
justement possible.

    §1 — une notification récente ne dit rien de la décision
    ───────────────────────────────────────────────────────
    Depuis `award-recency-v0.3` les horloges sont indépendantes : une
    attribution vieille de quatre-vingt-dix jours notifiée hier ressort
    `recently_notified_contract` **avec** une date de décision connue. La phrase
    « la date de décision n'est pas publiée » aurait donc été fausse — et fausse
    précisément dans le cas français le plus courant.

    §2 — un raccourci interne ne doit pas devenir un type client
    ───────────────────────────────────────────────────────────
    `recency.claim.mvp_event_type` rattache `award_date_unknown` et
    `invalid_award_date` à `RECENTLY_PUBLISHED_AWARD`. À l'intérieur du moteur
    c'est un raccourci de reporting ; rendu tel quel, il étiquetterait
    « publication récente » un avis dont aucune date n'est exploitable.
"""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
from fastapi.testclient import TestClient
from feed_helpers import (
    BOAMP_AGING,
    BOAMP_PUBLICATION_ONLY,
    COMPLETE_ICP_INPUT,
    ORIGIN,
    PASSWORD,
    boamp_award,
    materialize,
    materialize_boamp,
)

from signals.api import ApiConfig, create_app
from signals.feed import policy
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.recency import assess_recency
from signals.recency.claim import CLAIM_TEMPLATES, JUST_WON_MARKERS

READ_ON = dt.date(2026, 8, 25)

#: Toute manière d'affirmer qu'une date de décision manque. Aucune ne doit
#: apparaître quand la source publie cette date.
UNKNOWN_AWARD_MARKERS = (
    "date de décision n'est pas publiée",
    "date de décision d'attribution n'est pas publiée",
    "sans date de décision",
    "date de décision est inconnue",
    "decision date is not published",
    "no published decision date",
    "decision date is unknown",
)


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


def app_for(engine, locale: str) -> TestClient:
    app = create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN, session_ttl=dt.timedelta(days=365)),
        now_override=Clock(),
    )
    client = TestClient(app, headers={"Origin": ORIGIN})
    assert (
        client.post(
            "/auth/signup",
            json={
                "email": f"alice-{locale}@negoce-romand.ch",
                "password": PASSWORD,
                "company_name": "Negoce Romand SA",
                "locale": locale,
            },
        ).status_code
        == 201
    )
    return client


def icp_of(client: TestClient) -> str:
    return client.post(
        "/target-icps", json={"label": "Intrants", "customer_input": COMPLETE_ICP_INPUT}
    ).json()["target_icp_id"]


def store_notified(engine, icp: str, *, award: dt.date | None, notified: dt.date):
    """Un avis réel dont on ne change QUE les deux horloges étudiées."""
    event, awards = boamp_award(BOAMP_AGING)
    tuned = awards[0].model_copy(
        update={"award_date": award, "contract_notification_date": notified}
    )
    with engine.begin() as connection:
        return materialize(connection, event, tuned, target_icp_id=icp)


def only(client: TestClient, **params) -> dict:
    query = "&".join(f"{name}={value}" for name, value in params.items())
    response = client.get(f"/signals?{query}" if query else "/signals")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1, items
    return items[0]


# ─── closeout §1 — la notification ne parle que d'elle-même ───────────────────


@pytest.mark.parametrize(
    ("label", "award_date", "expected_clock"),
    [
        ("A — décision J-90, notification J-1", dt.date(2026, 5, 27), "stale"),
        ("B — décision J-40, notification J-1", dt.date(2026, 7, 16), "aging"),
        ("C — décision absente, notification J-1", None, "unknown"),
    ],
)
@pytest.mark.parametrize("lang", ["fr", "en"])
def test_a_recent_notification_never_claims_the_award_date_is_missing(
    engine, label: str, award_date: dt.date | None, expected_clock: str, lang: str
):
    """§1 A/B/C/D — la phrase doit rester vraie dans les trois configurations."""
    client = app_for(engine, lang)
    icp = icp_of(client)
    store_notified(engine, icp, award=award_date, notified=dt.date(2026, 8, 24))

    event = only(client)["event"]

    assert event["status"] == "recently_notified_contract", label
    assert event["clock"] == "notification"
    assert event["date"] == "2026-08-24"
    assert event["award_clock_status"] == expected_clock

    expected_copy = {
        "fr": "Notification récente du marché.",
        "en": "Recent contract notification.",
    }
    assert event["why_now"] == expected_copy[lang]

    if expected_clock == "unknown":
        return
    lowered = (event["why_now"] + " " + event["award_date_note"]).lower()
    for marker in UNKNOWN_AWARD_MARKERS:
        assert marker not in lowered, f"{label} / {lang} : « {marker} » alors que la date existe"


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_the_optional_note_reads_the_award_clock_rather_than_the_headline_status(engine, lang: str):
    """§1 — le complément est vrai parce qu'il inspecte l'horloge d'attribution."""
    client = app_for(engine, lang)
    icp = icp_of(client)
    store_notified(engine, icp, award=dt.date(2026, 5, 27), notified=dt.date(2026, 8, 24))

    event = only(client)["event"]
    expected = {
        "fr": "La décision d'attribution est ancienne.",
        "en": "The award decision is old.",
    }
    assert event["award_date_note"] == expected[lang]


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_a_missing_award_date_is_the_only_case_that_says_so(engine, lang: str):
    client = app_for(engine, lang)
    icp = icp_of(client)
    store_notified(engine, icp, award=None, notified=dt.date(2026, 8, 24))

    event = only(client)["event"]
    expected = {
        "fr": "La date de décision d'attribution n'est pas publiée par la source.",
        "en": "The award decision date is not published by the source.",
    }
    assert event["award_date_note"] == expected[lang]
    assert event["award_clock_status"] == "unknown"


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_a_recent_notification_never_borrows_the_wording_of_a_win(engine, lang: str):
    client = app_for(engine, lang)
    icp = icp_of(client)
    store_notified(engine, icp, award=dt.date(2026, 5, 27), notified=dt.date(2026, 8, 24))

    event = only(client)["event"]
    assert not any(marker in event["headline"].lower() for marker in JUST_WON_MARKERS)
    expected = {"fr": "vient d'être notifié", "en": "has recently been notified"}
    assert expected[lang] in event["headline"]


def test_the_notification_wording_holds_for_every_award_clock_state(engine):
    """La sécurité ne doit pas dépendre du jeu de dates choisi par le test."""
    for award_date in (None, dt.date(2026, 5, 27), dt.date(2026, 7, 16), dt.date(2026, 8, 20)):
        recency = assess_recency(
            award_date=award_date,
            contract_notification_date=dt.date(2026, 8, 24),
            publication_date=dt.date(2026, 8, 18),
            as_of=READ_ON,
        )
        if recency.status != "recently_notified_contract":
            continue
        from signals.feed.copy import WHY_NOW

        for lang in ("fr", "en"):
            assert "décision" not in WHY_NOW[recency.status][lang].lower()
            assert "decision" not in WHY_NOW[recency.status][lang].lower()


# ─── closeout §2 — le type client ne relaie pas le raccourci interne ──────────


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("recent_award", "recent_award"),
        ("recently_notified_contract", "recently_notified_contract"),
        ("recently_published_award", "recently_published_award"),
        ("aging_award", None),
        ("stale_award", None),
        ("invalid_award_date", None),
        ("award_date_unknown", None),
    ],
)
def test_the_customer_event_type_is_null_for_everything_that_is_not_new(
    status: str, expected: str | None
):
    assert policy.customer_event_type(status) == expected


def test_every_recency_status_has_a_customer_event_type_decision():
    """Un statut oublié rendrait `None` par accident, pas par décision."""
    for status in CLAIM_TEMPLATES:
        assert status in policy.STATUS_RANK, status
        assert policy.customer_event_type(status) in {None, status}


def test_the_customer_type_never_relays_the_internal_publication_shortcut():
    """§2 — c'est exactement le raccourci que le feed doit neutraliser."""
    from signals.recency.claim import mvp_event_type

    for status in ("award_date_unknown", "invalid_award_date"):
        assert mvp_event_type(status) == "RECENTLY_PUBLISHED_AWARD"
        assert policy.customer_event_type(status) is None


def test_an_unusable_notice_carries_no_event_type_in_the_api(engine):
    """Un avis sans aucune date exploitable ne peut pas être une « publication récente »."""
    client = app_for(engine, "fr")
    icp = icp_of(client)
    with engine.begin() as connection:
        materialize_boamp(connection, BOAMP_PUBLICATION_ONLY, target_icp_id=icp)

    # Lu longtemps après la parution : plus aucune horloge ne parle.
    from signals.feed import query

    with engine.connect() as connection:
        account_id = query.owned_target_icps(connection, account_id=_account(client))
        assert icp in account_id
        page = query.feed_page(
            connection,
            account_id=_account(client),
            as_of=dt.date(2027, 6, 1),
            freshness="all",
        )
    item = page.items[0]
    assert item.status == "award_date_unknown"
    assert policy.customer_event_type(item.status) is None


def _account(client: TestClient) -> str:
    return client.get("/me").json()["account_id"]


def test_a_stale_signal_is_exposed_without_any_event_type(engine):
    client = app_for(engine, "fr")
    icp = icp_of(client)
    with engine.begin() as connection:
        materialize_boamp(connection, BOAMP_AGING, target_icp_id=icp)

    item = only(client, freshness="recent_or_aging")
    assert item["event"]["status"] == "aging_award"
    assert item["event"]["type"] is None
    assert item["event"]["is_new_opportunity"] is False


# ─── closeout §3 — le filtre porte sur l'événement COURANT ────────────────────


def test_a_current_recent_publication_matches_the_publication_filter(engine):
    """§3 A."""
    client = app_for(engine, "fr")
    icp = icp_of(client)
    with engine.begin() as connection:
        signal = materialize_boamp(connection, BOAMP_PUBLICATION_ONLY, target_icp_id=icp)

    item = only(client, primary_event="recently_published_award")
    assert item["signal_id"] == signal.signal_key
    assert item["event"]["type"] == "recently_published_award"


def test_an_old_notice_without_any_date_never_matches_the_publication_filter(engine):
    """§3 B — le raccourci interne l'aurait fait remonter."""
    client = app_for(engine, "fr")
    icp = icp_of(client)
    with engine.begin() as connection:
        materialize_boamp(connection, BOAMP_PUBLICATION_ONLY, target_icp_id=icp)

    from signals.feed import query

    with engine.connect() as connection:
        late = query.feed_page(
            connection,
            account_id=_account(client),
            as_of=dt.date(2027, 6, 1),
            freshness="all",
            primary_event="recently_published_award",
        )
        history = query.feed_page(
            connection, account_id=_account(client), as_of=dt.date(2027, 6, 1), freshness="all"
        )
    assert history.items, "le signal existe toujours"
    assert history.items[0].status == "award_date_unknown"
    assert late.items == (), "il ne doit pas répondre au filtre de publication récente"


def test_an_invalid_award_date_never_matches_the_publication_filter(engine):
    """§3 C."""
    client = app_for(engine, "fr")
    icp = icp_of(client)
    # Une décision postérieure à sa propre parution : la source est incohérente.
    store_notified(engine, icp, award=dt.date(2026, 8, 24), notified=None)

    from signals.feed import query

    with engine.connect() as connection:
        history = query.feed_page(
            connection, account_id=_account(client), as_of=READ_ON, freshness="all"
        )
        filtered = query.feed_page(
            connection,
            account_id=_account(client),
            as_of=READ_ON,
            freshness="all",
            primary_event="recently_published_award",
        )
    assert history.items[0].status == "invalid_award_date"
    assert filtered.items == ()


def test_a_signal_materialized_as_recent_stops_matching_the_recent_filter(engine):
    """§3 D — l'instantané dit « récent » ; la lecture du jour dit le contraire."""
    import sqlalchemy as sa

    from signals.feed import query
    from signals.persistence.schema import materialized_signal

    client = app_for(engine, "fr")
    icp = icp_of(client)
    with engine.begin() as connection:
        materialize_boamp(
            connection,
            BOAMP_AGING,
            target_icp_id=icp,
        )

    with engine.connect() as connection:
        snapshot = connection.execute(
            sa.select(materialized_signal.c.materialized_recency_status)
        ).scalar_one()
        fresh = query.feed_page(
            connection,
            account_id=_account(client),
            as_of=dt.date(2026, 7, 20),
            primary_event="recent_award",
        )
        late = query.feed_page(
            connection,
            account_id=_account(client),
            as_of=dt.date(2026, 12, 1),
            freshness="all",
            primary_event="recent_award",
        )

    assert snapshot == "aging_award", "l'instantané reste ce qu'il était"
    assert len(fresh.items) == 1, "le 20 juillet, la décision est bien récente"
    assert late.items == (), "le 1er décembre, elle ne l'est plus"


def test_the_filter_refuses_a_value_that_is_not_a_customer_event(engine):
    """Rendre une page vide sans dire pourquoi serait pire qu'un refus."""
    client = app_for(engine, "fr")
    icp_of(client)
    assert client.get("/signals?primary_event=stale_award").status_code == 422
    assert client.get("/signals?primary_event=RECENT_AWARD").status_code == 422


def test_the_filter_never_reads_the_materialized_snapshot():
    """§3 — un filtre branché sur l'instantané rejouerait la faute de SPEC-009D.

    L'analyse porte sur l'arbre syntaxique, pas sur le texte : les commentaires
    ont le droit de NOMMER l'instantané pour expliquer pourquoi on ne s'en sert
    pas, et un test qui les confondrait avec du code punirait l'explication.
    """
    import ast
    import inspect

    from signals.feed import query, view

    forbidden = {"materialized_primary_event", "materialized_recency_status"}
    for module in (query, view):
        tree = ast.parse(inspect.getsource(module))
        used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)} | {
            node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
        }
        assert forbidden & used == set(), module.__name__
