"""Frozen, controlled copy for SPEC-024 deterministic personalization."""

from __future__ import annotations

from dataclasses import dataclass

from signals.feed.copy import NEED_LABELS

LANGUAGE_POLICY_VERSION = "personalization-language-policy-v1"
TEMPLATE_VERSION = "personalization-template-v1"
CATALOG_VERSION = "personalization-catalog-v1"
SUPPORTED_LANGUAGES = ("fr", "en")


class PersonalizationLanguageUnsupported(ValueError):
    """The caller requested a language outside the explicit v1 policy."""


class NeedLabelError(ValueError):
    """The selected need is not in Kivou's controlled NeedCategory catalog."""


@dataclass(frozen=True)
class CatalogMessage:
    language: str
    subject: str
    greeting: str
    body: str
    cta: str


_SUBJECTS = {
    "fr": "Un marché public attribué à {awardee}",
    "en": "A public contract awarded to {awardee}",
}
_GREETINGS = {"fr": "Bonjour{suffix},", "en": "Hello{suffix},"}
_INFERENCES = {
    "fr": "Ce type de marché peut créer des besoins autour de {need_label}.",
    "en": "This type of contract may create needs around {need_label}.",
}
_CTAS = {
    "fr": "Kivou repère ce type de signaux dans les marchés publics. Souhaitez-vous voir quelques exemples ?",
    "en": "Kivou identifies these kinds of signals in public procurement. Would you like to see a few examples?",
}


def _need_label(category: str, language: str) -> str:
    try:
        return NEED_LABELS[category][language]
    except KeyError as exc:
        raise NeedLabelError(category) from exc


def render_catalog_message(
    *,
    language: str,
    awardee: str,
    public_event_sentence: str,
    need_category: str,
    first_name: str | None,
) -> CatalogMessage:
    """Render only the approved catalog; public-event wording comes from recency.claim."""
    if language not in SUPPORTED_LANGUAGES:
        raise PersonalizationLanguageUnsupported(language)
    suffix = f" {first_name}" if first_name else ""
    return CatalogMessage(
        language=language,
        subject=_SUBJECTS[language].format(awardee=awardee),
        greeting=_GREETINGS[language].format(suffix=suffix),
        body="\n\n".join(
            (
                public_event_sentence,
                _INFERENCES[language].format(
                    need_label=_need_label(need_category, language)
                ),
            )
        ),
        cta=_CTAS[language],
    )
