from __future__ import annotations

from signals.alerts.content import line_from_card, render_html, render_text


def test_four_channels_reuse_the_same_signal_facts_and_persisted_sentence():
    sentence = "Le marché « Travaux de voirie » à Isère (250000 EUR, attribué le 2026-09-01) peut concerner votre activité."
    card = {
        "signal_id": "sig-contract",
        "company": {"name": "ACME"},
        "event": {"headline": "Attribution publiée", "why_now": "Cette semaine"},
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

    for value in (sentence, line.company, line.contract_title, line.amount, line.location, line.awarded_on):
        assert value
        assert value in text
        assert value in html
