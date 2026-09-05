"""PR1 §5 — `GET /dashboard` : nouveautés depuis la dernière visite, relances.

Les fixtures et l'aveu (« un `company_key` n'apparaît qu'après
`run_winner_enrichment_batch` ») sont copiés de `test_companies_list.py`.

`NOW = 2026-08-20` est choisi pour que TROIS faits tiennent ensemble sans se
contredire :
  - `33885-03` (avis SIMAP à trois lots, trois titulaires distincts — APEXA
    GmbH, Detecon (Schweiz) AG, Digizone GmbH) a une date d'attribution du
    2026-08-13 : sept jours avant `NOW`, donc `recent_award` — le SEUL des
    quatre avis dont le statut appartient aux « nouveautés » (§5).
  - `29997-02` (attribué 2026-06-22), `33112-02` (2026-05-19) et `34794-02`
    (2026-07-09) sont tous trop anciens pour être `recent_award` à cette date,
    mais restent des signaux accessibles ordinaires — utiles au suivi
    commercial (`to_follow_up`) sans polluer les nouveautés.
  - Les quatre avis sont publiés entre le 2026-08-13 et le 2026-08-15, donc
    TOUS dans la fenêtre `[NOW - 7 j, NOW] = [2026-08-13, 2026-08-20]` — ce qui
    rend `week.new` calculable directement depuis les avis choisis.
"""

from __future__ import annotations

import datetime as dt
import pathlib
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from billing_helpers import subscribe
from engagement_helpers import NOW as HELPERS_NOW
from engagement_helpers import icp_of, make_app, make_engine, pay, seed, signed_up
from fastapi.testclient import TestClient
from feed_helpers import (
    COMPLETE_ICP_INPUT,
    ORIGIN,
    PASSWORD,
    materialize_simap,
    pin_session_cookie,
)

from signals.accounts import service as accounts_service
from signals.api import ApiConfig, create_app
from signals.cockpit.contracts import CockpitWeek
from signals.cockpit.service import WeeklyCommercialCockpitService
from signals.companies.enrichment import run_winner_enrichment_batch
from signals.dashboard.service import _FOLLOW_UP_LIMIT
from signals.persistence.database import create_database_engine, migrate_to_latest
from signals.persistence.schema import for_you_sentence, materialized_signal

NOW = dt.datetime(2026, 8, 20, 9, 0, tzinfo=dt.UTC)


class Clock:
    def __init__(self, start: dt.datetime = NOW) -> None:
        self.now = start

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, delta: dt.timedelta) -> None:
        self.now += delta


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


@pytest.fixture
def app(engine, clock: Clock):
    return create_app(
        engine,
        ApiConfig(cookie_secure=False, allowed_origin=ORIGIN, session_ttl=dt.timedelta(days=365)),
        now_override=clock,
    )


@pytest.fixture
def client(app, engine) -> TestClient:
    client = TestClient(app, headers={"Origin": ORIGIN})
    response = client.post(
        "/auth/signup",
        json={
            "email": "dashboard@kivou.eu",
            "password": PASSWORD,
            "company_name": "Dashboard",
            "locale": "fr",
        },
    )
    assert response.status_code == 201, response.text
    pin_session_cookie(client, response)
    account_id = client.get("/me").json()["account_id"]
    with engine.begin() as connection:
        subscribe(
            connection,
            account_id=account_id,
            plan="scale",
            subscription_id="sub_dashboard",
            now=NOW,
        )
    return client


@pytest.fixture
def icp(client: TestClient) -> str:
    return client.post(
        "/target-icps",
        json={"label": "Suivi", "customer_input": COMPLETE_ICP_INPUT},
    ).json()["target_icp_id"]


def _seed_new_signals(client: TestClient, engine) -> list[str]:
    """Trois ICP actifs, un seul avis `recent_award` — trois signaux distincts.

    `signal_key` se dérive de `(opportunity_key, target_icp_id)` (PR1 §5,
    `signals.persistence.identity.signal_key`) : matérialiser les trois lots de
    `33885-03` sous le MÊME icp ne ferait qu'un seul signal, la dernière
    écriture l'emportant sur les précédentes. Trois ICP distincts, en revanche,
    produisent trois signaux bel et bien séparés à partir du MÊME lot — donc
    de la MÊME date d'attribution, ce qui les rend tous `recent_award`.
    """
    icps = [
        client.post(
            "/target-icps",
            json={"label": f"Suivi {n}", "customer_input": COMPLETE_ICP_INPUT},
        ).json()["target_icp_id"]
        for n in range(3)
    ]
    keys = []
    with engine.begin() as connection:
        for target_icp_id in icps:
            keys.append(
                materialize_simap(connection, "33885-03", target_icp_id=target_icp_id).signal_key
            )
        run_winner_enrichment_batch(connection, now=NOW, worker_ref="dashboard-test", limit=10)
    return keys


def _set_band_and_score(engine, signal_key: str, *, band: str, score: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key == signal_key)
            .values(icp_match_band=band, icp_match_normalized_score=score)
        )


def _set_model_fit(engine, signal_key: str, model_fit: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.update(for_you_sentence)
            .where(for_you_sentence.c.signal_key == signal_key)
            .values(model_fit=model_fit)
        )


def _company_key_for(client: TestClient, signal_key: str) -> str:
    items = client.get("/signals?freshness=all").json()["items"]
    return next(item["company_key"] for item in items if item["signal_id"] == signal_key)


def _dashboard(client: TestClient) -> dict:
    response = client.get("/dashboard")
    assert response.status_code == 200, response.text
    return response.json()


def test_zone_labels_deduplicate_legacy_country_composites() -> None:
    from signals.api.routes_dashboard import _unique_zone_labels

    assert _unique_zone_labels(("FR · France", "France")) == ["France"]


def test_fresh_account_counts_new_signals_then_resets_after_the_first_visit(client, engine):
    _seed_new_signals(client, engine)

    first = _dashboard(client)
    assert first["last_seen_at"] is None
    assert first["as_of"] == NOW.date().isoformat()
    assert first["new_since_last_visit"] == 3
    assert first["profile"]["name"].startswith("Suivi ")
    assert first["profile"]["sector_label"].strip(" —")
    assert first["profile"]["zone_labels"] == ["Suisse"]
    assert first["plan"]["name"] == "Scale"
    assert first["plan"]["opened"] == 0
    assert first["plan"]["quota"] is None
    assert first["plan"]["period_end"] is None

    second = _dashboard(client)
    assert dt.datetime.fromisoformat(second["last_seen_at"]) == NOW
    assert second["new_since_last_visit"] == 0


def test_strong_matches_counts_only_new_signals_with_a_strong_band(client, engine):
    keys = _seed_new_signals(client, engine)
    _set_band_and_score(engine, keys[0], band="strong", score=80)

    payload = _dashboard(client)

    assert payload["new_since_last_visit"] == 3
    assert payload["strong_matches"] == 1
    assert payload["strong_matches"] <= payload["new_since_last_visit"]


def test_top3_is_ordered_by_band_then_score_and_carries_a_company_key(client, engine):
    keys = _seed_new_signals(client, engine)
    _set_band_and_score(engine, keys[0], band="weak", score=10)
    _set_band_and_score(engine, keys[1], band="strong", score=50)
    _set_band_and_score(engine, keys[2], band="promising", score=90)

    payload = _dashboard(client)
    top3 = payload["top3"]

    assert len(top3) == 3
    assert [item["signal_id"] for item in top3] == [keys[1], keys[2], keys[0]]
    for item in top3:
        assert item["status"] == "new"
        assert item["company_key"]


def test_model_fit_none_downgrades_a_strong_signal_and_counts_the_disagreement(client, engine):
    keys = _seed_new_signals(client, engine)
    _set_band_and_score(engine, keys[0], band="strong", score=99)
    _set_model_fit(engine, keys[0], "none")

    dashboard = _dashboard(client)
    assert dashboard["strong_matches"] == 0
    assert keys[0] not in {item["signal_id"] for item in dashboard["top3"]}

    signal = next(
        item for item in client.get("/signals?freshness=all").json()["items"]
        if item["signal_id"] == keys[0]
    )
    assert signal["analysis"]["fit"]["band"] == "weak"

    report = WeeklyCommercialCockpitService(engine).generate(
        week=CockpitWeek(
            week_start=dt.datetime(2026, 8, 17, tzinfo=ZoneInfo("Europe/Zurich")),
            week_end=dt.datetime(2026, 8, 24, tzinfo=ZoneInfo("Europe/Zurich")),
        )
    )
    assert report.data_quality.matching_disagreement == 1


def test_to_follow_up_lists_companies_contacted_a_week_or_more_ago(client, icp, engine, clock):
    with engine.begin() as connection:
        key_a = materialize_simap(connection, "29997-02", target_icp_id=icp).signal_key
        key_b = materialize_simap(connection, "33112-02", target_icp_id=icp).signal_key
        run_winner_enrichment_batch(
            connection, now=NOW, worker_ref="dashboard-follow-up", limit=10
        )

    company_a = _company_key_for(client, key_a)
    company_b = _company_key_for(client, key_b)

    contacted_a = client.post(f"/companies/{company_a}/contact", json={"status": "contacted"})
    assert contacted_a.status_code == 200

    clock.advance(dt.timedelta(days=7))
    contacted_b = client.post(f"/companies/{company_b}/contact", json={"status": "contacted"})
    assert contacted_b.status_code == 200

    clock.advance(dt.timedelta(days=1))
    payload = _dashboard(client)

    follow_up = {item["company_key"]: item for item in payload["to_follow_up"]}
    assert company_a in follow_up
    assert follow_up[company_a]["days_since_contact"] == 8
    assert follow_up[company_a]["last_signal"]["company_key"] == company_a
    assert follow_up[company_a]["last_signal"]["signal_id"] == key_a
    assert company_b not in follow_up
    assert payload["to_follow_up_truncated"] is False


def test_week_counts_relevant_contacted_and_replied_within_the_window(client, icp, engine):
    new_keys = _seed_new_signals(client, engine)
    with engine.begin() as connection:
        key_a = materialize_simap(connection, "29997-02", target_icp_id=icp).signal_key
        key_b = materialize_simap(connection, "33112-02", target_icp_id=icp).signal_key
        key_c = materialize_simap(connection, "34794-02", target_icp_id=icp).signal_key
        run_winner_enrichment_batch(connection, now=NOW, worker_ref="dashboard-week", limit=10)

    relevant = client.put(f"/signals/{key_a}/feedback", json={"relevance": "relevant"})
    assert relevant.status_code == 200

    # §6 — contacter un signal sans avis préalable enregistre AUSSI `relevant`
    # (`engagement/feedback.py::mark_contacted`) : ce signal compte donc à la
    # fois dans `saved` et dans `contacted`.
    contacted = client.post(f"/signals/{key_b}/contacted")
    assert contacted.status_code == 200

    company_c = _company_key_for(client, key_c)
    replied = client.post(f"/companies/{company_c}/contact", json={"status": "replied"})
    assert replied.status_code == 200

    payload = _dashboard(client)

    # Les quatre avis (`33885-03` × 3 ICP, `29997-02`, `33112-02`, `34794-02`)
    # sont tous publiés entre le 2026-08-13 et le 2026-08-15 — dans la fenêtre
    # `[2026-08-13, 2026-08-20]` — donc les six signaux comptent dans `new`.
    assert payload["week"] == {
        "new": len(new_keys) + 3,
        "saved": 2,
        "contacted": 1,
        "replied": 1,
    }


def test_fresh_account_without_any_signal_sees_an_empty_dashboard(app):
    anonymous_client = TestClient(app, headers={"Origin": ORIGIN})
    response = anonymous_client.post(
        "/auth/signup",
        json={
            "email": "fresh-dashboard@kivou.eu",
            "password": PASSWORD,
            "company_name": "Fresh Dashboard",
            "locale": "fr",
        },
    )
    assert response.status_code == 201, response.text
    pin_session_cookie(anonymous_client, response)

    payload = _dashboard(anonymous_client)

    assert payload["last_seen_at"] is None
    assert payload["new_since_last_visit"] == 0
    assert payload["strong_matches"] == 0
    assert payload["top3"] == []
    assert payload["to_follow_up"] == []
    assert payload["week"] == {"new": 0, "saved": 0, "contacted": 0, "replied": 0}
    assert payload["scan_truncated"] is False


def test_new_since_last_visit_includes_a_signal_published_the_same_day_as_the_visit(
    client, engine
):
    """Fix round 1 (I4) — la borne est INCLUSIVE : `published_on >= previous_seen.date()`.

    Une visite le jour J et une parution le MÊME jour J ne doivent pas se
    perdre l'une l'autre : la parution compte à la visite SUIVANTE, quitte à
    être comptée deux fois si le client revient plusieurs fois le même jour —
    ce qui est accepté (voir le docstring de `build_dashboard`).
    """
    keys = _seed_new_signals(client, engine)  # publiés le 2026-08-14
    account_id = client.get("/me").json()["account_id"]
    visit_on_publication_day = dt.datetime(2026, 8, 14, 18, 0, tzinfo=dt.UTC)
    with engine.begin() as connection:
        accounts_service.touch_last_seen_at(
            connection, account_id=account_id, now=visit_on_publication_day
        )

    payload = _dashboard(client)

    assert dt.datetime.fromisoformat(payload["last_seen_at"]) == visit_on_publication_day
    assert payload["new_since_last_visit"] == len(keys)


def test_unpaid_account_without_discovery_grants_sees_no_signal_on_the_dashboard(tmp_path):
    """Fix round 1 (C1, contournement du mur payant) — `admit=access.is_unlocked`.

    Un compte fraîchement inscrit, sans abonnement et sans avoir jamais appelé
    `GET /signals` (donc sans le moindre déblocage Discovery consommé), ne
    doit recevoir NI carte complète NI décompte pour un signal qu'il n'a pas
    le droit de voir — avant le correctif, `top3`/`new_since_last_visit`/
    `strong_matches`/`week.new` lisaient `feed_page` sans jamais consulter
    `access.is_unlocked`.
    """
    engine = make_engine(tmp_path)
    app = make_app(engine, lambda: HELPERS_NOW)
    client = signed_up(app)
    icp = icp_of(client)
    seed(engine, icp, count=3)

    response = client.get("/dashboard")
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["top3"] == []
    assert payload["new_since_last_visit"] == 0
    assert payload["strong_matches"] == 0
    assert payload["week"]["new"] == 0


# ─── fix round 2 (F1) — les nombres portent sur TOUT, pas sur une page ────────


def test_dashboard_counts_and_ranks_beyond_a_single_page(tmp_path):
    """Soixante nouveautés se comptent soixante, et la soixantième peut gagner.

    `build_dashboard` lisait `feed_page(..., limit=MAXIMUM_PAGE_SIZE).items` :
    les trois agrégats (`new_since_last_visit`, `strong_matches`, `top3`)
    étaient donc plafonnés à cinquante, et un signal `strong` classé au-delà de
    la cinquantième place par date ne pouvait plus JAMAIS atteindre `top3` —
    exactement le signal que l'écran est censé remonter.

    Douze avis distincts (`engagement_helpers.SIGNAL_SOURCES`) sous cinq ICP
    donnent soixante signaux `recent_award` distincts. Leur date d'attribution
    décroît avec l'indice de la source, donc les cinq signaux de la source 11
    occupent les places 56 à 60 : hors de la première page, par construction.
    """
    engine = make_engine(tmp_path)
    app = make_app(engine, lambda: HELPERS_NOW)
    client = signed_up(app, email="beyond-one-page@kivou.eu")
    pay(engine, client, plan="scale", now=HELPERS_NOW)

    keys: list[str] = []
    for index in range(5):
        keys.extend(seed(engine, icp_of(client, label=f"Suivi {index}"), count=12))
    assert len(keys) == 60

    #: La source 11 est la plus ancienne : ce signal est le 56e au tri du feed.
    last_ranked = keys[11]
    _set_band_and_score(engine, last_ranked, band="strong", score=90)

    payload = _dashboard(client)

    assert payload["new_since_last_visit"] == 60
    assert payload["strong_matches"] == 1
    assert payload["top3"][0]["signal_id"] == last_ranked
    assert payload["scan_truncated"] is False


# ─── fix round 2 (F3) — `published_since` présélectionne AUSSI en SQL ─────────


def _age_signal(engine, signal_key: str, *, published_on: dt.date, award_date: dt.date) -> None:
    """Vieillit la parution ET l'attribution d'un signal, à sa source."""
    from signals.persistence.schema import contract_award, source_event

    with engine.begin() as connection:
        award_key = connection.execute(
            sa.select(materialized_signal.c.materialization_award_key).where(
                materialized_signal.c.signal_key == signal_key
            )
        ).scalar_one()
        event_key = connection.execute(
            sa.select(contract_award.c.event_key).where(contract_award.c.award_key == award_key)
        ).scalar_one()
        connection.execute(
            sa.update(contract_award)
            .where(contract_award.c.award_key == award_key)
            .values(award_date=award_date)
        )
        connection.execute(
            sa.update(source_event)
            .where(source_event.c.event_key == event_key)
            .values(published_on=published_on)
        )


def test_week_new_survives_a_tight_scan_cap_full_of_old_publications(
    client, icp, engine, monkeypatch
):
    """Les parutions hors fenêtre ne consomment plus le plafond de candidats.

    `published_since` n'était qu'un filtre Python : les deux avis anciens,
    matérialisés en dernier donc lus en premier, remplissaient le plafond et
    `week.new` rendait zéro alors que deux parutions de la semaine attendaient
    derrière. La borne est désormais aussi une clause SQL — les lignes hors
    fenêtre ne sont plus lues du tout.
    """
    from signals.feed import policy

    with engine.begin() as connection:
        recent = [
            materialize_simap(connection, name, target_icp_id=icp).signal_key
            for name in ("33885-03", "34794-02")
        ]
        old = [
            materialize_simap(connection, name, target_icp_id=icp).signal_key
            for name in ("29997-02", "33112-02")
        ]

    for signal_key in old:
        _age_signal(
            engine,
            signal_key,
            published_on=dt.date(2026, 6, 1),
            award_date=dt.date(2026, 5, 20),
        )
    # Les avis anciens sont les plus récemment matérialisés : ils sont donc lus
    # les premiers, et seraient seuls à consommer le plafond.
    with engine.begin() as connection:
        connection.execute(
            sa.update(materialized_signal)
            .where(materialized_signal.c.signal_key.in_(old))
            .values(materialized_at=dt.datetime(2026, 8, 19, 10, 0, tzinfo=dt.UTC))
        )
    monkeypatch.setattr(policy, "CANDIDATE_SCAN_CAP", 2)

    payload = _dashboard(client)

    assert payload["week"]["new"] == len(recent)


# ─── fix round 2 (F4) — dix relances au plus, et le dire ─────────────────────


def test_to_follow_up_keeps_the_ten_oldest_and_announces_the_rest(tmp_path):
    """Le bloc coûtait un balayage complet PAR entreprise contactée.

    Il est désormais borné : tri par `contacted_at` d'abord, découpe à dix
    ensuite, et une seule lecture par relance retenue — par la clé du dernier
    signal, déjà connue de l'agrégation. Ce qui dépasse n'est pas caché :
    `to_follow_up_truncated` le dit.
    """
    engine = make_engine(tmp_path)
    clock = Clock(HELPERS_NOW)
    app = make_app(engine, clock)
    client = signed_up(app, email="follow-up-cap@kivou.eu")
    pay(engine, client, plan="scale", now=HELPERS_NOW)
    seed(engine, icp_of(client), count=12)
    with engine.begin() as connection:
        run_winner_enrichment_batch(
            connection, now=HELPERS_NOW, worker_ref="dashboard-follow-up-cap", limit=50
        )

    company_keys = sorted(
        {
            item["company_key"]
            for item in client.get("/signals?freshness=all&limit=50").json()["items"]
            if item.get("company_key")
        }
    )
    assert len(company_keys) > _FOLLOW_UP_LIMIT, "il faut plus de dix relances pour déborder"

    for company_key in company_keys:
        # Une minute d'écart : `contacted_at` croît dans l'ordre de la boucle,
        # donc « les dix plus anciennes » est une affirmation vérifiable.
        clock.advance(dt.timedelta(minutes=1))
        response = client.post(f"/companies/{company_key}/contact", json={"status": "contacted"})
        assert response.status_code == 200, response.text

    clock.advance(dt.timedelta(days=8))
    payload = _dashboard(client)

    assert payload["to_follow_up_truncated"] is True
    assert [item["company_key"] for item in payload["to_follow_up"]] == (
        company_keys[:_FOLLOW_UP_LIMIT]
    )
    for item in payload["to_follow_up"]:
        assert item["days_since_contact"] == 8
        assert item["last_signal"]["locked"] is False
