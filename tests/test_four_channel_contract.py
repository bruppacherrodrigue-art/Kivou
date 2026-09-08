from __future__ import annotations

import pytest

from signals.alerts.content import line_from_card, render_html, render_text


def test_four_channels_reuse_the_same_signal_facts_and_persisted_sentence():
    sentence = "Le marché « Travaux de voirie » à Isère (250000 EUR, attribué le 2026-09-01) peut concerner votre activité."
    card = {
        "signal_id": "sig-contract",
        "company": {"name": "ACME"},
        "event": {"headline": "Attribution publiée", "why_now": "Cette semaine"},
        "factual_display": {
            "object_short": "Travaux de voirie",
            "date": {"kind": "award", "value": "2026-09-01"},
        },
        "contract": {
            "title": "Travaux de voirie",
            "amount": {"value": "250000", "currency": "EUR"},
            "location": {"locality": "Isère"},
            "dates": {"award": "2026-09-01"},
            "buyer": {"name": "Acheteur public"},
        },
        "analysis": {
            "fit": {"for_you_sentence": sentence},
            "plausible_needs": {"items": [{"label": "Besoin", "timing": "maintenant"}]},
        },
    }

    line = line_from_card(card, url="https://kivou.test/signals/sig-contract", lang="fr")
    text = render_text([line], lang="fr", preferences_link="https://kivou.test/settings")
    html = render_html([line], lang="fr", preferences_link="https://kivou.test/settings")

    assert line.company == "ACME"
    assert line.contract_title == "Travaux de voirie"
    assert line.amount == "250\u00a0000\u00a0€"
    assert line.location == "Isère"
    assert line.awarded_on == "1 sept."
    assert line.date_label == "Attribué le"
    assert line.for_you_sentence.encode("utf-8") == sentence.encode("utf-8")
    for value in (sentence, line.company, line.contract_title, line.amount, line.location, line.awarded_on):
        assert value
        assert value in text
        assert value in html


@pytest.mark.parametrize(
    ("kind", "label"),
    [("award", "Attribué le"), ("notification", "Attribué le"),
     ("contract_notification", "Attribué le"), ("publication", "Publié le")],
)
def test_email_date_label_distinguishes_award_from_publication(kind, label):
    card = {
        "signal_id": "sig-date",
        "company": {"name": "ACME"},
        "contract": {"title": "Travaux de voirie", "dates": {kind: "2026-09-01"}},
        "factual_display": {"date": {"kind": kind, "value": "2026-09-01"}},
        "analysis": {"fit": {"for_you_sentence": "Dans votre zone et votre secteur."}},
    }
    line = line_from_card(card, url="https://kivou.test/app/signals/sig-date", lang="fr")
    assert line.date_label == label
    for body in (
        render_text([line], lang="fr", preferences_link="https://kivou.test/settings"),
        render_html([line], lang="fr", preferences_link="https://kivou.test/settings"),
    ):
        assert f"{label} 1 sept." in body
        assert "Notifié le" not in body
