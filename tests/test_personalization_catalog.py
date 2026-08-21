from __future__ import annotations

import pytest

from signals.personalization.catalog import (
    LANGUAGE_POLICY_VERSION,
    NeedLabelError,
    PersonalizationLanguageUnsupported,
    render_catalog_message,
)


def test_french_catalog_is_exact_and_uses_one_selected_need() -> None:
    message = render_catalog_message(
        language="fr",
        awardee="Acme SA",
        public_event_sentence="Acme SA vient de remporter un marché public.",
        need_category="workforce_capacity",
        first_name="Alice",
    )

    assert message.language == "fr"
    assert message.subject == "Un marché public attribué à Acme SA"
    assert message.greeting == "Bonjour Alice,"
    assert message.body == (
        "Acme SA vient de remporter un marché public.\n\n"
        "Ce type de marché peut créer des besoins autour de Capacité de main-d'œuvre."
    )
    assert message.cta == (
        "Kivou repère ce type de signaux dans les marchés publics. "
        "Souhaitez-vous voir quelques exemples ?"
    )
    assert LANGUAGE_POLICY_VERSION == "personalization-language-policy-v1"


def test_english_catalog_uses_neutral_greeting_when_name_is_absent() -> None:
    message = render_catalog_message(
        language="en",
        awardee="Acme SA",
        public_event_sentence="An award notice concerning Acme SA has recently been published.",
        need_category="logistics_and_transport",
        first_name=None,
    )

    assert message.subject == "A public contract awarded to Acme SA"
    assert message.greeting == "Hello,"
    assert message.body.endswith("This type of contract may create needs around Logistics and transport.")


def test_unsupported_language_fails_closed() -> None:
    with pytest.raises(PersonalizationLanguageUnsupported):
        render_catalog_message(
            language="de",
            awardee="Acme SA",
            public_event_sentence="ignored",
            need_category="workforce_capacity",
            first_name=None,
        )


def test_unknown_need_category_is_not_rendered() -> None:
    with pytest.raises(NeedLabelError):
        render_catalog_message(
            language="fr",
            awardee="Acme SA",
            public_event_sentence="ignored",
            need_category="invented_need",  # type: ignore[arg-type]
            first_name=None,
        )
