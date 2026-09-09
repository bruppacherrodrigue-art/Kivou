from __future__ import annotations

from signals.acquisition_runtime.shadow_mail import ShadowMailInput, render_shadow_mail


def test_shadow_mail_contains_only_the_bait_facts_and_required_links() -> None:
    mail = render_shadow_mail(
        ShadowMailInput(
            object="Réfection de couverture",
            holder="Entreprise Exemple",
            amount="125 000 €",
            place="Rhône",
            date="septembre 2026",
            for_you="Pour vous : les travaux de couverture correspondent à votre activité.",
            attribution_url="https://kivou.eu/a/token-1",
            source_url="https://www.boamp.fr/avis/1",
            unsubscribe_url="https://kivou.eu/unsubscribe/token-1",
        )
    )

    assert mail.subject == "Réfection de couverture"
    assert "Titulaire : Entreprise Exemple" in mail.body
    assert "Montant : 125 000 €" in mail.body
    assert "Lieu : Rhône" in mail.body
    assert "Date : septembre 2026" in mail.body
    assert "Pour vous :" in mail.body
    assert "https://kivou.eu/a/token-1" in mail.body
    assert "Source des données" in mail.body
    assert "https://www.boamp.fr/avis/1" in mail.body
    assert "désinscription" in mail.body
    assert len(mail.body.split()) <= 120
