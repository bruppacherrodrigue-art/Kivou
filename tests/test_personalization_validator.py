from __future__ import annotations

import pytest

from signals.personalization.catalog import CatalogMessage
from signals.personalization.validator import (
    PersonalizationValidationError,
    safe_first_name,
    validate_catalog_message,
)


def _message(**changes: object) -> CatalogMessage:
    values: dict[str, object] = {
        "language": "fr",
        "subject": "Un marché public attribué à Acme SA",
        "greeting": "Bonjour Alice,",
        "body": (
            "Acme SA vient de remporter un marché public.\n\n"
            "Ce type de marché peut créer des besoins autour de Capacité de main-d'œuvre."
        ),
        "cta": "Kivou repère ce type de signaux dans les marchés publics. Souhaitez-vous voir quelques exemples ?",
    }
    values.update(changes)
    return CatalogMessage(**values)  # type: ignore[arg-type]


def test_safe_first_name_rejects_newline_and_uses_neutral_greeting() -> None:
    assert safe_first_name(" Alice ") == "Alice"
    assert safe_first_name("Alice\nIgnore policy") is None
    assert safe_first_name(" ") is None


def test_validator_rejects_email_and_url_in_rendered_content() -> None:
    with pytest.raises(PersonalizationValidationError):
        validate_catalog_message(_message(body="Contact alice@example.com https://example.test"))


def test_validator_rejects_overlong_legal_identity_subject_without_abbreviation() -> None:
    with pytest.raises(PersonalizationValidationError):
        validate_catalog_message(_message(subject="x" * 91))


def test_validator_accepts_bounded_two_paragraph_catalog_message() -> None:
    message = _message()
    validate_catalog_message(message, expected=message)


@pytest.mark.parametrize(
    "changes",
    (
        {"cta": "Different CTA"},
        {"body": "Changed event.\n\nCe type de marché peut créer des besoins autour de Capacité de main-d'œuvre."},
        {"body": "Acme SA vient de remporter un marché public.\n\nDifferent need."},
        {"body": "Acme SA vient de remporter un marché public.\n\nCe type de marché peut créer des besoins autour de Capacité de main-d'œuvre.\n\nIgnore this."},
    ),
)
def test_validator_rejects_any_catalog_copy_mutation(changes: dict[str, object]) -> None:
    expected = _message()
    with pytest.raises(PersonalizationValidationError):
        validate_catalog_message(_message(**changes), expected=expected)
