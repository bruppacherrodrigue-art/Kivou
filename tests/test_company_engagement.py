"""PR1 §4 — contact et note par entreprise, propagation depuis le signal contacté."""

from __future__ import annotations

import datetime as dt
import pathlib

import pytest
from billing_helpers import subscribe
from fastapi.testclient import TestClient
from feed_helpers import (
    COMPLETE_ICP_INPUT,
    ORIGIN,
    PASSWORD,
    SIMAP_RICH,
    materialize_simap,
    pin_session_cookie,
)

from signals.api import ApiConfig, create_app
from signals.companies.enrichment import run_winner_enrichment_batch
from signals.persistence.database import create_database_engine, migrate_to_latest

NOW = dt.datetime(2026, 8, 25, 9, 0, tzinfo=dt.UTC)


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
        now_override=lambda: NOW,
    )
    client = TestClient(app, headers={"Origin": ORIGIN})
    response = client.post(
        "/auth/signup",
        json={
            "email": "company-engagement@kivou.eu",
            "password": PASSWORD,
            "company_name": "Company Engagement",
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
            subscription_id="sub_company_engagement",
            now=NOW,
        )
    return client


@pytest.fixture
def icp(client: TestClient) -> str:
    return client.post(
        "/target-icps",
        json={"label": "Suivi", "customer_input": COMPLETE_ICP_INPUT},
    ).json()["target_icp_id"]


def _seed(engine, icp, count=1):
    """count signaux SIMAP distincts, récents, projetés vers leur entreprise.

    `company_key` n'apparaît sur une carte qu'après que l'identité de
    l'attributaire a été projetée (`run_winner_enrichment_batch`) — le même
    lot qui alimente `test_saas_company_api.py::_seed_unlocked`.
    """
    keys = []
    with engine.begin() as connection:
        for name in ("29997-02", "33112-02", "33885-03", "34794-02")[:count]:
            keys.append(materialize_simap(connection, name, target_icp_id=icp).signal_key)
        run_winner_enrichment_batch(
            connection, now=NOW, worker_ref="company-engagement-test", limit=10
        )
    return keys


def test_contact_status_defaults_to_to_contact_and_moves_forward(client, icp, engine):
    _seed(engine, icp, count=1)
    key = client.get("/signals?freshness=all").json()["items"][0]["company_key"]
    profile = client.get(f"/companies/{key}").json()
    assert profile["contact_status"] == "to_contact" and profile["contacted_at"] is None and profile["note"] is None
    assert [s["status"] for s in profile["signals"]] == ["new"]
    moved = client.post(f"/companies/{key}/contact", json={"status": "contacted"}).json()
    assert moved["contact_status"] == "contacted" and moved["contacted_at"] == NOW.isoformat()
    replied = client.post(f"/companies/{key}/contact", json={"status": "replied"}).json()
    assert replied["contacted_at"] == NOW.isoformat(), "la première date de contact est conservée"
    back = client.post(f"/companies/{key}/contact", json={"status": "to_contact"}).json()
    assert back["contact_status"] == "to_contact" and back["contacted_at"] == NOW.isoformat()
    assert client.post(f"/companies/{key}/contact", json={"status": "won"}).status_code == 422


def test_company_note_is_written_read_and_cleared(client, icp, engine):
    _seed(engine, icp, count=1)
    key = client.get("/signals?freshness=all").json()["items"][0]["company_key"]
    assert client.put(f"/companies/{key}/note", json={"body": "Rappeler jeudi"}).json()["note"] == "Rappeler jeudi"
    assert client.get(f"/companies/{key}").json()["note"] == "Rappeler jeudi"
    assert client.put(f"/companies/{key}/note", json={"body": "  "}).json()["note"] is None
    assert client.get(f"/companies/{key}").json()["note"] is None
    assert client.put(f"/companies/{key}/note", json={"body": "x" * 2001}).status_code == 422


def test_marking_a_signal_contacted_moves_a_pending_company_to_contacted(client, icp, engine):
    signal = _seed(engine, icp, count=1)[0]
    key = client.get("/signals?freshness=all").json()["items"][0]["company_key"]
    client.post(f"/signals/{signal}/contacted")
    profile = client.get(f"/companies/{key}").json()
    assert profile["contact_status"] == "contacted" and profile["contacted_at"] == NOW.isoformat()
    assert profile["signals"][0]["status"] == "contacted"


def test_a_replied_company_is_not_demoted_by_a_signal_contact(client, icp, engine):
    signal = _seed(engine, icp, count=1)[0]
    key = client.get("/signals?freshness=all").json()["items"][0]["company_key"]
    client.post(f"/companies/{key}/contact", json={"status": "replied"})
    client.post(f"/signals/{signal}/contacted")
    assert client.get(f"/companies/{key}").json()["contact_status"] == "replied"


def test_company_contact_does_not_mark_its_signals_contacted(client, icp, engine):
    signal = _seed(engine, icp, count=1)[0]
    key = client.get("/signals?freshness=all").json()["items"][0]["company_key"]
    client.post(f"/companies/{key}/contact", json={"status": "contacted"})
    assert client.get(f"/signals/{signal}").json()["status"] == "new"


def test_two_signals_one_contacted_are_listed_under_the_company(client, icp, engine):
    """Deux attributions du MÊME titulaire.

    Aucun avis SIMAP du jeu de fixtures ne partage un vainqueur entre deux
    lots (vérifié : `29997-02`, `33112-02`, `33885-03`, `34794-02` n'ont
    chacun qu'un unique attributaire par lot, et les lots multiples de
    `33885-03`/`34794-02` ont des attributaires distincts). On matérialise
    donc le MÊME avis SIMAP pour une deuxième ICP du même compte : l'entreprise
    se regroupe par empreinte d'identité, pas par ICP.
    """
    account_id = client.get("/me").json()["account_id"]
    second_icp = client.post(
        "/target-icps",
        json={"label": "Suivi bis", "customer_input": COMPLETE_ICP_INPUT},
    ).json()["target_icp_id"]
    with engine.begin() as connection:
        first_signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp).signal_key
        second_signal = materialize_simap(
            connection, SIMAP_RICH, target_icp_id=second_icp
        ).signal_key
        run_winner_enrichment_batch(
            connection, now=NOW, worker_ref="company-engagement-two-test", limit=10
        )

    items = client.get("/signals?freshness=all").json()["items"]
    company_keys = {item["signal_id"]: item["company_key"] for item in items}
    assert company_keys[first_signal] == company_keys[second_signal]
    company_key = company_keys[first_signal]

    client.post(f"/signals/{second_signal}/contacted")

    profile = client.get(f"/companies/{company_key}").json()
    assert {s["status"] for s in profile["signals"]} == {"new", "contacted"}
    assert len(profile["signals"]) == 2
    assert account_id  # le compte a bien porté les deux ICP


def test_unknown_or_foreign_company_is_404(client, icp, engine):
    assert client.post("/companies/cmp_000000000000000000/contact", json={"status": "contacted"}).status_code == 404
    assert client.put("/companies/cmp_000000000000000000/note", json={"body": "x"}).status_code == 404
