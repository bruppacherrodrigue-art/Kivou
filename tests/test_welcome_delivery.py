from signals.accounts.welcome_delivery import build_welcome_message


def test_welcome_message_links_login_signal_and_prospect_unsubscribe() -> None:
    message = build_welcome_message(
        email="prospect@example.test",
        locale="fr",
        signal_key="sig/42",
        signal_holder="CMCD",
        signal_subject="Charpente bois",
        signal_location="en Savoie",
        unsubscribe_url="https://kivou.eu/unsubscribe/unique-token",
        site_url="https://kivou.eu",
        message_id="<welcome@test>",
    )

    assert message.subject == "Bienvenue sur Kivou — votre accès est créé"
    assert "https://kivou.eu/login" in message.text_body
    assert "CMCD · Charpente bois · en Savoie" in message.text_body
    assert "https://kivou.eu/app/signals/sig%2F42" in message.text_body
    assert "https://kivou.eu/unsubscribe/unique-token" in message.text_body
    assert message.preferences_url == "https://kivou.eu/unsubscribe/unique-token"
