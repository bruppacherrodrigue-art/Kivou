from __future__ import annotations

import datetime as dt

from signals.acquisition_runtime.shadow_mail import ShadowMailInput, render_shadow_mail


def test_shadow_mail_contains_only_the_bait_facts_and_required_links() -> None:
    mail = render_shadow_mail(
        ShadowMailInput(
            family_key="ready_mix_concrete",
            object="LOT 02 GROS ŒUVRE",
            holder="Entreprise Exemple",
            amount_minor_units=12_500_000,
            currency="eur",
            city=None,
            department="Rhône",
            date=dt.date(2026, 9, 8),
            director_name="ALICE MARIE MARTIN",
            attribution_url="https://kivou.eu/a/token-1",
            source_url="https://www.boamp.fr/avis/1",
            unsubscribe_url="https://kivou.eu/unsubscribe/token-1",
        )
    )

    assert mail.subject == "Entreprise Exemple vient de gagner un chantier béton en Rhône"
    assert mail.body.startswith("Bonjour Alice Martin,")
    assert "Entreprise Exemple vient d'être retenu pour le gros œuvre" in mail.body
    assert "125 k€" in mail.body
    assert "8 septembre" in mail.body
    assert "Il leur faudra du béton prêt à l'emploi sur place." in mail.body
    assert "https://kivou.eu/a/token-1" in mail.body
    assert "Source : registres publics et avis d'attribution officiel" in mail.body
    assert "https://www.boamp.fr/avis/1" in mail.body
    assert "Ne plus recevoir" in mail.body
    assert len(mail.body.split("\n\n—\n", maxsplit=1)[0].split()) <= 90
