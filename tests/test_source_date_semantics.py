"""SPEC-009E §16, §44 — chaque source déclare ce que ses dates veulent dire.

SPEC-009D a montré que la couverture de `award_date` varie du simple au triple
selon le portail : 100 % sur SIMAP, 38,2 % sur TED, 27,6 % sur BOAMP, nulle sur
DECP. Masquer cette différence derrière un champ unique ferait passer une
absence de donnée pour une donnée absente de sens.

Le registre est donc du code, et ces tests en vérifient l'honnêteté : aucune
source ne peut y déclarer qu'un champ ambigu porte une date d'attribution.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from signals.connectors.boamp import parse_award_notice
from signals.connectors.decp import parse_contract
from signals.recency import assess_recency
from signals.recency.sources import (
    SOURCE_DATE_SEMANTICS,
    award_date_capability,
    source_date_field,
)

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "france"
BOAMP = {
    record["idweb"]: record
    for record in json.loads((FIXTURE / "boamp_records.json").read_text(encoding="utf-8"))[
        "records"
    ]
}
DECP = json.loads((FIXTURE / "decp2022_records.json").read_text(encoding="utf-8"))["records"]

AS_OF = dt.date(2026, 8, 18)
ALL_SOURCES = ("simap", "ted", "boamp", "decp")


# ─── le registre lui-même ───────────────────────────────────────────────────────


@pytest.mark.parametrize("source", ALL_SOURCES)
def test_every_source_declares_its_award_date_capability(source: str):
    spec = SOURCE_DATE_SEMANTICS[source]
    assert spec["award_date_status"] in {"published", "sometimes_published", "not_published"}
    assert spec["award_date_field"] is not None or spec["award_date_status"] == "not_published"
    assert spec["publication_date_field"]
    assert spec["measured_award_date_coverage"] is not None
    assert spec["measured_on"], f"{source} déclare une couverture sans dire sur quoi"


@pytest.mark.parametrize("source", ALL_SOURCES)
def test_no_source_declares_an_ambiguous_field_as_an_award_date(source: str):
    """§20 — un champ dont la sémantique n'est pas établie ne devient pas award_date."""
    spec = SOURCE_DATE_SEMANTICS[source]
    for field, description in spec["other_dates"].items():
        assert description["can_represent_award_date"] in {"NO", "AMBIGUOUS"}, (
            f"{source}/{field} prétend porter une date d'attribution"
        )
        assert description["canonical_field"] != "award_date", (
            f"{source}/{field} est mappé sur award_date malgré son ambiguïté"
        )


def test_the_boamp_sentinel_field_is_documented_as_a_trap():
    """Le champ nommé `AwardDate` qui n'en est pas un doit être nommé, pas oublié."""
    other = SOURCE_DATE_SEMANTICS["boamp"]["other_dates"]
    assert "cac:TenderResult/cbc:AwardDate" in other
    trap = other["cac:TenderResult/cbc:AwardDate"]
    assert trap["can_represent_award_date"] == "NO"
    assert "2000-01-01" in trap["reason"]


def test_decp_declares_that_it_publishes_no_award_date():
    assert award_date_capability("decp") == "not_published"
    assert SOURCE_DATE_SEMANTICS["decp"]["measured_award_date_coverage"] == 0.0


def test_the_award_date_field_of_each_source_is_retrievable_by_name():
    assert source_date_field("simap", "award_date") == "publication.award_decision_date"
    assert source_date_field("ted", "award_date") == "efac:SettledContract/cbc:AwardDate"
    assert source_date_field("boamp", "award_date") == "efac:SettledContract/cbc:AwardDate"
    assert source_date_field("decp", "award_date") is None


# ─── §44 SIMAP — la meilleure source de référence ───────────────────────────────


def test_simap_is_declared_as_the_reference_case_for_recent_awards():
    spec = SOURCE_DATE_SEMANTICS["simap"]
    assert spec["award_date_status"] == "published"
    assert spec["measured_award_date_coverage"] == 100.0


def test_a_simap_style_known_award_date_yields_a_recent_award():
    """Le cas réel de SPEC-009D : décision la veille, avis paru le lendemain."""
    got = assess_recency(award_date=dt.date(2026, 8, 17), publication_date=AS_OF, as_of=AS_OF)
    assert got.status == "recent_award"
    assert got.publication_delay_days == 1


# ─── §44 TED — connu contre inconnu, sans rétrograder l'ensemble ────────────────


def test_ted_is_declared_as_publishing_the_award_date_only_sometimes():
    spec = SOURCE_DATE_SEMANTICS["ted"]
    assert spec["award_date_status"] == "sometimes_published"
    assert spec["measured_award_date_coverage"] == 38.2


def test_a_ted_award_with_a_known_date_can_still_be_recent():
    got = assess_recency(
        award_date=dt.date(2026, 8, 10), publication_date=dt.date(2026, 8, 14), as_of=AS_OF
    )
    assert got.status == "recent_award"
    assert got.may_claim_just_won


def test_a_ted_award_without_a_date_is_recently_published_only():
    got = assess_recency(award_date=None, publication_date=dt.date(2026, 8, 14), as_of=AS_OF)
    assert got.status == "recently_published_award"
    assert not got.may_claim_just_won


# ─── §44 BOAMP / DECP — dérivés des champs réellement observés ──────────────────


def test_a_boamp_award_with_bt_1451_flows_through_to_a_dated_status():
    event, awards = parse_award_notice(BOAMP["26-80978"])
    dated = [a for a in awards if a.award_date]
    assert dated
    got = assess_recency(
        award_date=dated[0].award_date, publication_date=event.published_at, as_of=AS_OF
    )
    assert got.award_age_days == 32
    assert got.status == "aging_award"
    assert not got.may_claim_just_won


def test_a_boamp_award_without_bt_1451_can_only_be_recently_published():
    event, awards = parse_award_notice(BOAMP["26-80922"])
    got = assess_recency(
        award_date=awards[0].award_date, publication_date=event.published_at, as_of=AS_OF
    )
    assert got.status == "recently_published_award"


def test_no_decp_contract_can_ever_reach_a_dated_status():
    """DECP n'ayant aucune date de DÉCISION, aucun de ses contrats n'est « récent »."""
    for record in DECP:
        event, contract = parse_contract(record)
        got = assess_recency(
            award_date=contract.award_date,
            contract_notification_date=contract.contract_notification_date,
            publication_date=event.published_at,
            as_of=AS_OF,
        )
        assert got.award_clock.status == "unknown"
        assert not got.may_claim_just_won


def test_a_current_decp_contract_speaks_through_its_notification_clock():
    """Le jeu courant est frais : ses contrats sortent en `recently_notified_contract`."""
    for record in DECP:
        event, contract = parse_contract(record)
        got = assess_recency(
            award_date=contract.award_date,
            contract_notification_date=contract.contract_notification_date,
            publication_date=event.published_at,
            as_of=AS_OF,
        )
        assert got.notification_clock.is_dated
        assert got.status == "recently_notified_contract"
