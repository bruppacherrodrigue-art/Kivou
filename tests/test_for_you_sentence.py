from __future__ import annotations

from signals.personalization.for_you import ForYouInput, validate_sentence


def context() -> ForYouInput:
    return ForYouInput(
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
        "Votre offre de gros œuvre peut servir la rénovation en Isère pour Martin Construction SA.",
        context(),
    )
    assert result.accepted is True
    assert result.reason is None


def test_rejects_invented_number() -> None:
    result = validate_sentence("Ce marché de 300000 EUR correspond à votre offre.", context())
    assert result.reason == "invented_number"


def test_rejects_invented_date_and_name_or_place() -> None:
    assert validate_sentence("Ce besoin débute le 15 septembre 2026.", context()).reason == "invented_date"
    assert validate_sentence("Votre offre intéresse Dupont à Lyon.", context()).reason == "invented_name_or_place"


def test_rejects_editorial_violations() -> None:
    assert validate_sentence("Une excellente correspondance pour vous !", context()).reason == "exclamation"
    assert validate_sentence("Votre offre est la meilleure pour ce marché.", context()).reason == "superlative"
    long = " ".join(["mot"] * 26) + "."
    assert validate_sentence(long, context()).reason == "too_many_words"


def test_shared_provider_generates_one_sentence_without_naming_model_elsewhere(monkeypatch) -> None:
    import httpx

    from signals.documents.providers import AnthropicTextGenerator

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-local-not-a-real-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert b"UNTRUSTED VERIFIED INPUT" in request.content
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "Votre offre répond au besoin de gros œuvre en Isère."}],
                "usage": {"input_tokens": 80, "output_tokens": 14},
            },
        )

    provider = AnthropicTextGenerator()
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    assert provider.generate_sentence(context()) == "Votre offre répond au besoin de gros œuvre en Isère."
    assert provider.usage.calls == 1


def test_openrouter_provider_generates_the_sentence_through_chat_completions(monkeypatch) -> None:
    import httpx

    from signals.documents.openrouter import OpenRouterTextGenerator

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-local-not-a-real-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-local-not-a-real-key"
        payload = __import__("json").loads(request.content)
        assert payload["model"] == "anthropic/claude-sonnet-4.6"
        assert "UNTRUSTED VERIFIED INPUT" in payload["messages"][0]["content"]
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
    assert provider.generate_sentence(context()) == "Votre offre répond au besoin de gros œuvre en Isère."
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
