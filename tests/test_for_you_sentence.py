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
