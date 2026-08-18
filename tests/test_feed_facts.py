"""SPEC-012 §8, §13, §14, §21, §27 — ce que la source a publié, et ce que Kivou en déduit.

La réponse porte deux blocs nommés. `contract`, `company` et `source` disent ce
que la source publie ; `analysis` dit ce que Kivou en tire. Un objet plat où les
deux se liraient pareil transformerait une hypothèse en promesse commerciale —
et c'est précisément la faute que SPEC-009C a mesurée sur cent signaux frais.

Les preuves sont l'autre moitié de la promesse. Elles étayent les FAITS. Une
preuve rattachée à un besoin plausible étaye les faits d'ENTRÉE de l'hypothèse,
jamais l'hypothèse ; le contrat de réponse doit le dire.
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
    SIMAP_RICH,
    materialize_boamp,
    materialize_simap,
)

from signals.api import ApiConfig, create_app
from signals.persistence.database import create_database_engine, migrate_to_latest

#: §8 — aucun de ces mots n'a le droit d'apparaître dans une réponse client.
FORBIDDEN_CERTAINTY = (
    "confirmed_need",
    "purchase_intent",
    "guaranteed_demand",
    "will_buy",
    "confirmed_demand",
    "besoin_confirme",
)

#: §4 — les rouages internes ne franchissent pas la frontière HTTP.
FORBIDDEN_INTERNALS = (
    "need-rules",
    "icp-match-v",
    "signal-score",
    "rule_ids",
    "raw_points",
    "score_component",
    "hard_filter",
    "maximum_applicable_points",
    "normalized_score",
    "bkp-trade",
    "externalisability",
)


class Clock:
    def __init__(self, day: dt.date = dt.date(2026, 8, 25)) -> None:
        self.now = dt.datetime.combine(day, dt.time(9, 0), tzinfo=dt.UTC)

    def __call__(self) -> dt.datetime:
        return self.now


@pytest.fixture
def engine(tmp_path: pathlib.Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path / 'kivou.db'}")
    migrate_to_latest(engine)
    return engine


def app_for(engine, locale: str = "fr") -> TestClient:
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


@pytest.fixture
def client(engine) -> TestClient:
    return app_for(engine)


def icp_of(client: TestClient) -> str:
    return client.post(
        "/target-icps", json={"label": "Intrants", "customer_input": COMPLETE_ICP_INPUT}
    ).json()["target_icp_id"]


@pytest.fixture
def rich(client: TestClient, engine):
    """Un avis SIMAP réel : trois besoins plausibles, dont deux ciblés par l'ICP."""
    icp = icp_of(client)
    with engine.begin() as connection:
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp)
    return signal


def detail(client: TestClient, signal_key: str) -> dict:
    response = client.get(f"/signals/{signal_key}")
    assert response.status_code == 200, response.text
    return response.json()


# ─── §27.1 à §27.5 — les faits publiés survivent ──────────────────────────────


def test_the_winner_fact_survives_into_the_customer_answer(client, rich):
    body = detail(client, rich.signal_key)
    assert body["company"]["name"] == "Egli Gartenbau AG Sursee"
    assert body["company"]["country"] == "CH"


def test_the_buyer_fact_survives_into_the_customer_answer(client, engine):
    icp = icp_of(client)
    with engine.begin() as connection:
        signal = materialize_boamp(connection, BOAMP_AGING, target_icp_id=icp)

    buyer = detail(client, signal.signal_key)["contract"]["buyer"]
    assert buyer["name"] == "Ville de Saint Orens de Gameville"
    assert buyer["identifier"] == {"scheme": "SIRET", "value": "21310506700010"}


def test_the_amount_and_currency_survive_together_or_not_at_all(client, rich):
    amount = detail(client, rich.signal_key)["contract"]["amount"]
    assert amount is not None
    assert amount["currency"] == "CHF"
    assert float(amount["value"]) > 0


def test_the_contract_dates_survive_unchanged(client, rich):
    dates = detail(client, rich.signal_key)["contract"]["dates"]
    assert dates["award"] == "2026-05-19"
    assert dates["publication"] == "2026-08-15"


def test_the_public_source_url_survives(client, rich):
    source = detail(client, rich.signal_key)["source"]
    assert source["system"] == "simap"
    assert source["url"].startswith("https://")
    assert source["notice_id"]


def test_the_location_of_the_contract_is_published_as_a_fact(client, engine):
    icp = icp_of(client)
    with engine.begin() as connection:
        signal = materialize_boamp(connection, BOAMP_AGING, target_icp_id=icp)

    location = detail(client, signal.signal_key)["contract"]["location"]
    assert location["country"] == "FR"
    assert location["locality"] == "Saint-Orens de Gameville"


# ─── §27.6, §27.7 — l'hypothèse reste une hypothèse ───────────────────────────


def test_a_plausible_need_is_never_presented_as_established(client, rich):
    needs = detail(client, rich.signal_key)["analysis"]["plausible_needs"]
    assert "jamais un besoin confirmé" in needs["note"]
    assert len(needs["items"]) == 3
    for need in needs["items"]:
        assert need["confidence"] in {"medium", "low"}, "la politique interdit `high`"
        assert need["statement"]
        assert need["reasoning"]


def test_the_needs_live_under_analysis_and_never_beside_the_facts(client, rich):
    body = detail(client, rich.signal_key)
    assert "plausible_needs" in body["analysis"]
    assert "plausible_needs" not in body["contract"]
    assert set(body["contract"]) & set(body["analysis"]) == set()


def test_the_contract_reading_is_placed_as_analysis_not_as_a_published_fact(client, rich):
    """§27.7 — le résumé est une lecture du moteur, pas une citation de l'avis."""
    body = detail(client, rich.signal_key)
    reading = body["analysis"]["contract_reading"]
    assert reading["summary"].startswith("Marché")
    assert "Lecture automatique" in reading["note"]
    assert "summary" not in body["contract"]


def test_the_matched_needs_are_marked_as_targeted_by_the_customer_profile(client, rich):
    needs = detail(client, rich.signal_key)["analysis"]["plausible_needs"]["items"]
    targeted = {need["category"] for need in needs if need["targeted_by_your_profile"]}
    assert targeted == {"materials_or_components", "equipment_or_rental"}


def test_a_signal_without_any_plausible_need_stays_empty_rather_than_invented(client, engine):
    """§11 — remplir la carte avec un besoin fabriqué serait le faux signal type."""
    icp = icp_of(client)
    with engine.begin() as connection:
        signal = materialize_boamp(connection, BOAMP_AGING, target_icp_id=icp)

    needs = detail(client, signal.signal_key)["analysis"]["plausible_needs"]
    assert needs["items"] == []
    assert needs["note"]


# ─── §27.8, §4, §12 — ni certitude, ni rouages ────────────────────────────────


@pytest.mark.parametrize("forbidden", FORBIDDEN_CERTAINTY)
def test_no_certainty_field_is_ever_returned(client, rich, forbidden: str):
    body = str(detail(client, rich.signal_key)) + client.get("/signals?freshness=all").text
    assert forbidden not in body.lower()


@pytest.mark.parametrize("forbidden", FORBIDDEN_INTERNALS)
def test_no_engine_internal_crosses_the_http_boundary(client, rich, forbidden: str):
    body = str(detail(client, rich.signal_key)) + client.get("/signals?freshness=all").text
    assert forbidden not in body.lower()


def test_the_fit_explains_rather_than_scores(client, rich):
    fit = detail(client, rich.signal_key)["analysis"]["fit"]
    assert fit["label"] == "Correspond aux besoins que vous ciblez"
    assert any("Matériaux ou composants" in reason for reason in fit["reasons"])
    assert fit["target_icp_label"] == "Intrants"
    assert "score" not in str(fit).lower()


# ─── §13, §14 — la preuve, groupée par le fait qu'elle étaye ──────────────────


def test_the_public_facts_are_grouped_by_the_fact_they_support(client, rich):
    groups = detail(client, rich.signal_key)["evidence"]["public_facts"]
    by_fact = {group["fact"]: group for group in groups}
    assert {"winner", "amount", "award_date", "procedure_buyers"} <= set(by_fact)
    assert by_fact["award_date"]["label"] == "Date d'attribution"
    assert by_fact["winner"]["items"], "un fait affiché sans ancrage n'est pas vérifiable"


def test_an_evidence_item_carries_what_is_needed_to_verify_it(client, rich):
    item = detail(client, rich.signal_key)["evidence"]["public_facts"][0]["items"][0]
    assert item["source_system"] == "simap"
    assert item["url"].startswith("https://")
    assert item["notice_id"]
    assert item["path"]


def test_the_evidence_of_a_need_never_claims_to_prove_the_need(client, rich):
    """§27.9 — elle prouve les faits publiés qui ont produit l'hypothèse."""
    inputs = detail(client, rich.signal_key)["evidence"]["analysis_inputs"]
    assert "ne démontrent pas que le besoin existera" in inputs["note"]
    assert inputs["groups"], "l'avis riche produit bien des faits d'entrée"
    for group in inputs["groups"]:
        assert group["plausible_need"] in {
            "workforce_capacity",
            "equipment_or_rental",
            "materials_or_components",
        }


def test_need_evidence_is_never_mixed_into_the_public_facts(client, rich):
    evidence = detail(client, rich.signal_key)["evidence"]
    facts = {group["fact"] for group in evidence["public_facts"]}
    needs = {group["plausible_need"] for group in evidence["analysis_inputs"]["groups"]}
    assert facts & needs == set()


def test_no_internal_path_is_ever_exposed_as_evidence(client, rich):
    body = str(detail(client, rich.signal_key))
    for forbidden in ("/home/", "tests/fixtures", ".json", "src/signals", "scratchpad"):
        assert forbidden not in body, forbidden


def test_the_feed_card_carries_no_evidence_at_all(client, rich):
    """§16 — la carte est rapide ; la vérification appartient au détail."""
    item = client.get("/signals?freshness=all").json()["items"][0]
    assert "evidence" not in item
    assert "reasoning" not in str(item)
    assert "evidence" in detail(client, rich.signal_key)


# ─── §21 — deux langues, les mêmes faits ──────────────────────────────────────


def test_the_same_signal_reads_safely_in_french_and_in_english(engine):
    french, english = app_for(engine, "fr"), app_for(engine, "en")
    # Le second compte a son propre profil : les faits sont les mêmes, la
    # propriété reste distincte.
    icp, other = icp_of(french), icp_of(english)
    with engine.begin() as connection:
        signal = materialize_simap(connection, SIMAP_RICH, target_icp_id=icp)
        twin = materialize_simap(connection, SIMAP_RICH, target_icp_id=other)

    fr = detail(french, signal.signal_key)
    en = detail(english, twin.signal_key)

    assert fr["language"] == "fr"
    assert en["language"] == "en"
    assert "attributaire d'un marché public" in fr["event"]["headline"]
    assert "awardee of an" in en["event"]["headline"]
    assert "Attribution ancienne" in fr["event"]["why_now"]
    assert "Old award" in en["event"]["why_now"]


def test_the_language_never_changes_a_single_published_fact(engine):
    french, english = app_for(engine, "fr"), app_for(engine, "en")
    # Les profils sont créés AVANT d'ouvrir la transaction : SQLite n'accepte
    # qu'un écrivain, et l'API en ouvre une pour chaque création.
    french_icp, english_icp = icp_of(french), icp_of(english)
    with engine.begin() as connection:
        first = materialize_simap(connection, SIMAP_RICH, target_icp_id=french_icp)
        second = materialize_simap(connection, SIMAP_RICH, target_icp_id=english_icp)

    fr, en = detail(french, first.signal_key), detail(english, second.signal_key)
    assert fr["contract"] == en["contract"]
    assert fr["company"] == en["company"]
    assert fr["source"] == en["source"]
    assert fr["event"]["status"] == en["event"]["status"]
    assert fr["event"]["date"] == en["event"]["date"]


def test_the_need_labels_are_translated_but_the_categories_are_not(engine):
    french, english = app_for(engine, "fr"), app_for(engine, "en")
    french_icp, english_icp = icp_of(french), icp_of(english)
    with engine.begin() as connection:
        first = materialize_simap(connection, SIMAP_RICH, target_icp_id=french_icp)
        second = materialize_simap(connection, SIMAP_RICH, target_icp_id=english_icp)

    fr = detail(french, first.signal_key)["analysis"]["plausible_needs"]["items"]
    en = detail(english, second.signal_key)["analysis"]["plausible_needs"]["items"]

    assert [need["category"] for need in fr] == [need["category"] for need in en]
    assert [need["label"] for need in fr] != [need["label"] for need in en]
    assert "Matériaux ou composants" in [need["label"] for need in fr]
    assert "Materials or components" in [need["label"] for need in en]
