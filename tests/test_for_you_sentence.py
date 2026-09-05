from __future__ import annotations

import pytest

from signals.personalization.for_you import (
    FOR_YOU_SYSTEM_PROMPT,
    ForYouInput,
    build_for_you_prompt,
    client_safe_sentence,
    compose_generated_sentence,
    fallback_sentence,
    parse_generated_fragments,
    validate_sentence,
)


def test_fallback_and_legacy_cache_never_expose_engine_vocabulary() -> None:
    assert fallback_sentence(context()) == "Ce marché correspond à votre profil cible."
    assert client_safe_sentence("besoin principal couvert : materials_or_components") is None
    assert client_safe_sentence("Votre offre répond aux besoins de ce marché.") == (
        "Votre offre répond aux besoins de ce marché."
    )


def context() -> ForYouInput:
    return ForYouInput(
        buyer_name="Ville de Grenoble",
        holder="Martin Construction SA",
        title="Rénovation d'une école à Grenoble",
        amount="250000 EUR",
        location="Grenoble, Isère",
        awarded_on="2026-08-12",
        cpv="45210000",
        cpv_label="Travaux de construction de bâtiments",
        plausible_needs=("Travaux de gros œuvre",),
        fit_reasons=("Le besoin de gros œuvre correspond à votre offre.",),
        profile_sector="Travaux de construction",
        profile_zones=("Isère",),
        offer_summary="Vous fournissez des matériaux de gros œuvre",
    )


def test_accepts_grounded_sentence_with_reference_labels() -> None:
    result = validate_sentence(
        "Martin Construction SA a gagné la rénovation à Grenoble : vos matériaux de gros œuvre répondent au chantier.",
        context(),
    )
    assert result.accepted is True
    assert result.reason is None


def test_accepts_verified_buyer_and_trade_acronyms() -> None:
    sentence = "Martin Construction SA a gagné MOE CVC Ville Grenoble : vos matériaux de gros œuvre répondent au chantier."
    assert validate_sentence(sentence, context()).accepted is True


def test_rejects_invented_number() -> None:
    result = validate_sentence(
        "Martin Construction SA a gagné la rénovation (300 k€) : vos matériaux de gros œuvre répondent au chantier.",
        context(),
    )
    assert result.reason == "invented_number"


def test_rejects_invented_date_and_name_or_place() -> None:
    invented_date = "Martin Construction SA a gagné la rénovation (septembre 2027) : vos matériaux de gros œuvre répondent au chantier."
    invented_place = "Martin Construction SA a gagné la rénovation à Lyon : vos matériaux de gros œuvre répondent au chantier."
    assert validate_sentence(invented_date, context()).reason == "invented_date"
    assert validate_sentence(invented_place, context()).reason == "invented_name_or_place"


def test_rejects_editorial_violations() -> None:
    assert (
        validate_sentence("Une excellente correspondance pour vous !", context()).reason
        == "exclamation"
    )
    assert (
        validate_sentence("Votre offre est la meilleure pour ce marché.", context()).reason
        == "superlative"
    )
    long = " ".join(["mot"] * 26) + "."
    assert validate_sentence(long, context()).reason == "too_many_words"


@pytest.mark.parametrize(
    ("location", "amount", "awarded_on", "sentence"),
    [
        (
            "Grenoble, Isère",
            "250000 EUR",
            "2026-08-12",
            "Martin Construction SA a gagné la rénovation à Grenoble (250 k€, août 2026) : vos matériaux de gros œuvre répondent au chantier.",
        ),
        (
            None,
            "250000 EUR",
            "2026-08-12",
            "Martin Construction SA a gagné la rénovation (250 k€, août 2026) : vos matériaux de gros œuvre répondent au chantier.",
        ),
        (
            "Grenoble, Isère",
            None,
            None,
            "Martin Construction SA a gagné la rénovation à Grenoble : vos matériaux de gros œuvre répondent au chantier.",
        ),
        (
            None,
            None,
            None,
            "Martin Construction SA a gagné la rénovation : vos matériaux de gros œuvre répondent au chantier.",
        ),
    ],
)
def test_accepts_the_four_adaptive_template_shapes(location, amount, awarded_on, sentence) -> None:
    value = context().model_copy(
        update={"location": location, "amount": amount, "awarded_on": awarded_on}
    )
    assert "—" not in sentence
    assert validate_sentence(sentence, value).accepted is True


@pytest.mark.parametrize(
    ("amount", "awarded_on", "parenthetical"),
    [
        ("250000 EUR", None, "(250 k€)"),
        (None, "2026-08-12", "(août 2026)"),
    ],
)
def test_accepts_a_parenthetical_with_only_the_available_fact(
    amount, awarded_on, parenthetical
) -> None:
    value = context().model_copy(update={"amount": amount, "awarded_on": awarded_on})
    sentence = (
        f"Martin Construction SA a gagné la rénovation à Grenoble {parenthetical} : "
        "vos matériaux de gros œuvre répondent au chantier."
    )
    assert validate_sentence(sentence, value).accepted is True


@pytest.mark.parametrize(
    ("value", "sentence"),
    [
        (
            context(),
            "Martin Construction SA a gagné la rénovation (250 k€) : vos matériaux de gros œuvre répondent au chantier.",
        ),
        (
            context(),
            "Martin Construction SA a gagné la rénovation (250 000 €) : vos matériaux de gros œuvre répondent au chantier.",
        ),
        (
            context().model_copy(update={"amount": "1200000 EUR"}),
            "Martin Construction SA a gagné la rénovation (1,2 M€) : vos matériaux de gros œuvre répondent au chantier.",
        ),
        (
            ForYouInput(**{**context().model_dump(), "duration": "24 mois"}),
            "Martin Construction SA a gagné la maintenance : vos matériaux de gros œuvre accompagnent les 2 ans de travaux.",
        ),
        (
            context(),
            "Martin Construction SA a gagné la rénovation (août 2026) : vos matériaux de gros œuvre répondent au chantier.",
        ),
        (
            context(),
            "Martin Construction SA a gagné la rénovation (12 août 2026) : vos matériaux de gros œuvre répondent au chantier.",
        ),
        (
            context().model_copy(update={"location": "38000 Grenoble"}),
            "Martin Construction SA a gagné la rénovation en Isère : vos matériaux de gros œuvre répondent au chantier.",
        ),
    ],
)
def test_accepts_verified_formatted_equivalences(value, sentence) -> None:
    assert validate_sentence(sentence, value).accepted is True


@pytest.mark.parametrize(
    "sentence",
    [
        "La société a gagné la rénovation à Grenoble : vos matériaux de gros œuvre répondent au chantier.",
        "Martin Construction SA a gagné la rénovation à Grenoble : le chantier concerne une école.",
        "Martin Construction SA a gagné la rénovation à Grenoble : votre offre pourrait nécessiter un chantier.",
        "Martin Construction SA a gagné la rénovation à Grenoble : Ce marché porte sur votre offre de gros œuvre.",
    ],
)
def test_rejects_missing_holder_profile_consequence_and_banned_fillers(sentence) -> None:
    assert validate_sentence(sentence, context()).reason == "invalid_content"


def test_prompt_imposes_the_adaptive_client_template() -> None:
    prompt = build_for_you_prompt(context())

    assert "{titulaire} a gagné {objet court}" in prompt
    assert "à {lieu}" in prompt
    assert "({montant}, {mois année})" in prompt
    assert "Omettre le lieu" in prompt
    assert "Omettre les parenthèses" in prompt
    assert "pourrait nécessiter" in prompt
    assert "Ce marché porte sur" in prompt
    assert "détail propre" in prompt
    assert "Ne réutilise pas une formule générique" in prompt
    assert "Vise 18 mots" in prompt
    assert "limite absolue de 25 mots" in prompt
    assert "BEGIN UNTRUSTED VERIFIED INPUT" in prompt
    assert '"fit"' in prompt
    assert '"none"' in prompt
    assert FOR_YOU_SYSTEM_PROMPT == (
        "Tu réponds uniquement par un objet JSON {short_object, consequence, fit}. "
        "Aucun texte hors JSON."
    )


@pytest.mark.parametrize(
    ("location", "amount", "awarded_on", "expected_middle"),
    [
        ("Grenoble, Isère", "250000 EUR", "2026-08-12", " à Grenoble, Isère (250 k€, août 2026)"),
        (None, "250000 EUR", "2026-08-12", " (250 k€, août 2026)"),
        ("Grenoble, Isère", None, None, " à Grenoble, Isère"),
        (None, None, None, ""),
    ],
)
def test_composes_the_verified_shell_around_generated_object_and_consequence(
    location, amount, awarded_on, expected_middle
) -> None:
    value = context().model_copy(
        update={"location": location, "amount": amount, "awarded_on": awarded_on}
    )

    sentence = compose_generated_sentence(
        '{"short_object":"rénovation thermique école","consequence":"vos bardages métalliques isolent les façades","fit":"strong"}',
        value,
    )

    assert sentence == (
        f"Martin Construction SA a gagné rénovation thermique école{expected_middle} : "
        "vos bardages métalliques isolent les façades."
    )


def test_generated_composition_requires_two_bounded_fragments() -> None:
    assert compose_generated_sentence("phrase libre", context()) is None
    assert (
        compose_generated_sentence(
            '{"short_object":"objet beaucoup trop long avec sept mots ici","consequence":"vos bardages isolent"}',
            context(),
        )
        is None
    )
    assert (
        compose_generated_sentence(
            '{"short_object":"travaux","consequence":"conséquence beaucoup trop longue avec plus de huit mots pour le profil"}',
            context(),
        )
        is None
    )


@pytest.mark.parametrize(
    "raw",
    [
        '{"short_object":"rénovation thermique école","consequence":"vos bardages métalliques isolent les façades","fit":"strong"}',
        '```json\n{"short_object":"rénovation thermique école","consequence":"vos bardages métalliques isolent les façades","fit":"strong"}\n```',
        'Voici la réponse : {"short_object":"rénovation thermique école","consequence":"vos bardages métalliques isolent les façades","fit":"strong"} fin.',
    ],
)
def test_extracts_the_first_json_object(raw: str) -> None:
    parsed = parse_generated_fragments(raw)
    assert parsed is not None
    assert (parsed.short_object, parsed.consequence, parsed.fit) == (
        "rénovation thermique école",
        "vos bardages métalliques isolent les façades",
        "strong",
    )


def test_parses_none_fit_without_forced_consequence() -> None:
    parsed = parse_generated_fragments(
        '{"short_object":"maintenance médicale","consequence":null,"fit":"none"}'
    )
    assert parsed is not None
    assert parsed.fit == "none"
    assert parsed.consequence is None
    assert (
        compose_generated_sentence(
            '{"short_object":"maintenance médicale","consequence":null,"fit":"none"}', context()
        )
        is None
    )


@pytest.mark.parametrize("raw", [None, "aucun JSON", "{}", '{"short_object":"travaux"}'])
def test_missing_usable_json_fragments_is_invalid_shape(raw: str | None) -> None:
    assert parse_generated_fragments(raw) is None
    assert compose_generated_sentence(raw, context()) is None


def test_does_not_skip_an_invalid_first_json_object() -> None:
    raw = '{} then {"short_object":"travaux bâtiment","consequence":"vos matériaux répondent aux travaux"}'
    assert parse_generated_fragments(raw) is None


def test_composition_omits_identifier_only_holder() -> None:
    value = context().model_copy(update={"holder": "80941190300010"})
    sentence = compose_generated_sentence(
        '{"short_object":"rénovation thermique école","consequence":"vos bardages métalliques isolent les façades","fit":"strong"}',
        value,
    )
    assert sentence == (
        "Rénovation thermique école à Grenoble, Isère (250 k€, août 2026) : "
        "vos bardages métalliques isolent les façades."
    )


def test_shared_provider_generates_one_sentence_without_naming_model_elsewhere(monkeypatch) -> None:
    import httpx

    from signals.documents.providers import AnthropicTextGenerator

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-local-not-a-real-key")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = __import__("json").loads(request.content)
        assert payload["system"] == FOR_YOU_SYSTEM_PROMPT
        assert payload["messages"] == [{"role": "user", "content": build_for_you_prompt(context())}]
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "Votre offre répond au besoin de gros œuvre en Isère."}
                ],
                "usage": {"input_tokens": 80, "output_tokens": 14},
            },
        )

    provider = AnthropicTextGenerator()
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    assert (
        provider.generate_sentence(context())
        == "Votre offre répond au besoin de gros œuvre en Isère."
    )
    assert provider.usage.calls == 1


def test_openrouter_provider_generates_the_sentence_through_chat_completions(monkeypatch) -> None:
    import httpx

    from signals.documents.openrouter import OpenRouterTextGenerator

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-local-not-a-real-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-local-not-a-real-key"
        payload = __import__("json").loads(request.content)
        assert payload["model"] == "anthropic/claude-sonnet-4.6"
        assert payload["messages"] == [
            {"role": "system", "content": FOR_YOU_SYSTEM_PROMPT},
            {"role": "user", "content": build_for_you_prompt(context())},
        ]
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "Votre offre répond au besoin de gros œuvre en Isère."}}
                ],
                "usage": {"prompt_tokens": 80, "completion_tokens": 14, "cost": 0.001},
            },
        )

    provider = OpenRouterTextGenerator(model="anthropic/claude-sonnet-4.6")
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    assert (
        provider.generate_sentence(context())
        == "Votre offre répond au besoin de gros œuvre en Isère."
    )
    assert provider.usage.calls == 1
    assert provider.reported_cost_usd == 0.001


def test_environment_factory_prefers_the_configured_openrouter_key(monkeypatch) -> None:
    from signals.documents.openrouter import OpenRouterTextGenerator
    from signals.documents.providers import text_generator_from_environment

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-local-not-a-real-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("KIVOU_FOR_YOU_MODEL", "anthropic/claude-sonnet-4.6")

    provider = text_generator_from_environment()

    assert isinstance(provider, OpenRouterTextGenerator)
    assert provider.model == "anthropic/claude-sonnet-4.6"
