"""Production prospect regressions, synthetic inputs and recorded BOAMP facts."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from test_qa_attribution import NOW, issue, keyring

from signals.personalization.for_you import ForYouInput, fallback_sentence

pytest_plugins = ("test_qa_attribution",)


def test_single_factual_fallback():
    assert fallback_sentence(ForYouInput(
        title="Pose de bardage", location="Isère", amount="158644.86 EUR",
        awarded_on="2026-08-17",
    )) == "Pose de bardage à Isère (158 644,86 €, août 2026) : dans votre zone et votre secteur."


def test_fallback_short_object_zero_and_missing_facts():
    value = fallback_sentence(ForYouInput(title="Bardage " * 20, amount="0 EUR"))
    assert len(value.split(" (")[0]) <= 60
    assert "(0 €)" in value
    assert "None" not in value
    assert "—" not in value


@pytest.mark.parametrize("age,expected", [(0, ()), (30, ()), (31, ("SIGNAL_OUTSIDE_ACQUISITION_WINDOW",))])
def test_shared_prospect_age_boundary(age, expected):
    from signals.domain.prospect import prospect_refusal_codes

    award = SimpleNamespace(
        title="Bardage", lot=None, cpv_main=None,
        awardee_organizations=lambda: [SimpleNamespace(legal_name="Entreprise Exemple", identifiers=())],
        award_date=NOW.date() - dt.timedelta(days=age), contract_notification_date=None,
    )
    event = SimpleNamespace(published_at=NOW.date())
    assert prospect_refusal_codes(award, event, as_of=NOW.date()) == expected


@pytest.mark.parametrize("name,title,reason", [
    (None, "Bardage", "WINNER_NAME_UNRESOLVED"),
    ("12345678900012", "Bardage", "WINNER_NAME_UNRESOLVED"),
    ("Entreprise Exemple", "  ", "SIGNAL_OBJECT_UNRESOLVED"),
])
def test_shared_prospect_requires_named_holder_and_object(name, title, reason):
    from signals.domain.prospect import prospect_refusal_codes

    award = SimpleNamespace(
        title=title, lot=None, cpv_main=None,
        awardee_organizations=lambda: [SimpleNamespace(legal_name=name, identifiers=())],
        award_date=NOW.date(), contract_notification_date=None,
    )
    assert reason in prospect_refusal_codes(award, SimpleNamespace(published_at=NOW.date()), as_of=NOW.date())


def test_qa_provisional_contract_and_visible_landing(prepared_qa):
    engine, client, opportunity = prepared_qa
    response = client.get(f"/a/{issue(opportunity, engine=engine)}", follow_redirects=False)
    assert response.headers["location"].startswith("/app/signals/")
    key = response.headers["location"].rsplit("/", 1)[1]
    assert client.get("/me").json()["provisional_profile"] is True
    feed = client.get("/signals?view=history").json()
    assert feed["provisional_profile"] is True
    assert 1 <= len(feed["items"]) <= 5
    assert key in [item["signal_id"] for item in feed["items"]]
    assert all(item["company"]["name"] for item in feed["items"])
    assert feed["landing_signal_key"] == key


def test_mint_rejects_old_attribution_despite_recent_publication(prepared_qa):
    from signals.conversion.mint_token import mint_url
    from signals.persistence.schema import contract_award

    engine, _, opportunity = prepared_qa
    with engine.begin() as connection:
        connection.execute(sa.update(contract_award).values(
            award_date=NOW.date() - dt.timedelta(days=31),
        ))
    with pytest.raises(ValueError, match="SIGNAL_OUTSIDE_ACQUISITION_WINDOW"):
        mint_url(engine=engine, keyring=keyring(), origin="https://kivou.test",
                 opportunity=opportunity, wedge="construction", country="FR",
                 sector="bardage", need="materials_or_components", ttl="7d", now=NOW,
                 recipient_email="qa@example.com")


@pytest.mark.parametrize("reason", [
    "WINNER_NAME_UNRESOLVED", "SIGNAL_OBJECT_UNRESOLVED",
    "SIGNAL_OUTSIDE_ACQUISITION_WINDOW",
])
def test_current_decision_cannot_override_prospect_refusal(reason):
    from test_decision_engine_evaluator import _input

    from signals.acquisition.contracts import Decision
    from signals.decision_engine.evaluator import evaluate_decision
    from signals.decision_engine.policy import DECISION_POLICY_V1

    decision_input = _input(age_days=0).model_copy(update={
        "prospect_policy_version": "prospect-bait-v1", "prospect_refusal_codes": (reason,),
    })
    result = evaluate_decision(decision_input, DECISION_POLICY_V1)
    assert result.proposed_decision is Decision.NO_SEND
    assert result.reason_codes == (reason,)


def test_persisted_sentence_is_identical_in_feed_drawer_and_mail_components(prepared_qa):
    from signals.alerts.content import line_from_card
    from signals.persistence.schema import for_you_sentence
    from signals.personalization.catalog import render_catalog_message

    engine, client, opportunity = prepared_qa
    response = client.get(f"/a/{issue(opportunity, engine=engine)}", follow_redirects=False)
    key = response.headers["location"].rsplit("/", 1)[1]
    card = next(item for item in client.get("/signals?view=history").json()["items"]
                if item["signal_id"] == key)
    detail = client.get(f"/signals/{key}").json()
    sentence = card["analysis"]["fit"]["for_you_sentence"]
    with engine.connect() as connection:
        persisted = connection.scalar(sa.select(for_you_sentence.c.sentence).where(
            for_you_sentence.c.signal_key == key,
        ))
    alert = line_from_card(card, url="https://kivou.test", lang="fr")
    cold = render_catalog_message(
        language="fr", awardee=card["company"]["name"],
        public_event_sentence=card["event"]["headline"],
        need_category="materials_or_components", first_name=None, for_you_sentence=sentence,
    )
    assert sentence.encode() == persisted.encode() == alert.for_you_sentence.encode()
    assert sentence.encode() == detail["analysis"]["fit"]["for_you_sentence"].encode()
    assert sentence.encode() in cold.body.encode()
