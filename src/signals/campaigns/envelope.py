"""Exact-copy campaign envelope construction; provider prose is forbidden."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from signals.campaigns.contracts import (
    CAMPAIGN_ENVELOPE_VERSION,
    CAMPAIGN_SEQUENCE_POLICY_VERSION,
    CampaignContract,
    Fingerprint,
    FooterCatalog,
    StableRef,
)
from signals.decision_engine.policy import semantic_fingerprint

FOLLOW_UP_FR = (
    "Je me permets de revenir sur mon précédent message. Si le sujet vous intéresse, "
    "je peux vous montrer quelques exemples des signaux que Kivou repère dans les "
    "marchés publics."
)
FOLLOW_UP_EN = (
    "Just following up on my previous message. If this is relevant to you, I can show "
    "you a few examples of the signals Kivou identifies in public procurement."
)


class EnvelopeInput(CampaignContract):
    language: Literal["fr", "en"]
    sender_profile_ref: StableRef
    subject: str = Field(min_length=1, max_length=90)
    greeting: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=700)
    cta: str = Field(min_length=1, max_length=256)
    attribution_url: str | None = Field(default=None, min_length=1, max_length=4096)
    catalog: FooterCatalog

    @field_validator("subject", "greeting", "body", "cta")
    @classmethod
    def exact_core_has_no_template_language(cls, value: str) -> str:
        if any(token in value for token in ("{{", "}}", "{%", "%}", "[[", "]]")):
            raise ValueError("template syntax is forbidden in personalization core")
        return value

    @field_validator("attribution_url")
    @classmethod
    def exact_kivou_attribution_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith("/a/kat1.")
        ):
            raise ValueError("attribution URL must be a fixed Kivou HTTPS /a/ token")
        return value


class CampaignStep(CampaignContract):
    step: Literal[1, 2]
    delay_calendar_days: Literal[0, 4]
    subject: str
    body: str


class CampaignEnvelope(CampaignContract):
    envelope_version: Literal["campaign-envelope-v1"] = CAMPAIGN_ENVELOPE_VERSION
    sequence_policy_version: Literal["campaign-sequence-policy-v1"] = CAMPAIGN_SEQUENCE_POLICY_VERSION
    subject: str
    initial_envelope: str
    follow_up_subject: Literal[""] = ""
    follow_up_body: str
    footer_fingerprint: Fingerprint
    envelope_fingerprint: Fingerprint
    provider_subject_template: Literal["{{kivou_subject}}"] = "{{kivou_subject}}"
    provider_body_template: Literal["{{kivou_envelope}}"] = "{{kivou_envelope}}"
    custom_variables: dict[str, str]
    steps: tuple[CampaignStep, CampaignStep]


def build_envelope(value: EnvelopeInput) -> CampaignEnvelope:
    match = [
        entry
        for entry in value.catalog.entries
        if entry.language == value.language and entry.sender_profile_ref == value.sender_profile_ref
    ]
    if len(match) != 1:
        raise ValueError("exactly one configured footer is required")
    footer_entry = match[0]
    footer = (
        f"{footer_entry.sender_identity}\n{footer_entry.source_notice}\n"
        f"{footer_entry.privacy_route}\n{footer_entry.visible_opt_out}"
    )
    attribution = f"\n\n{value.attribution_url}" if value.attribution_url else ""
    initial = f"{value.greeting}\n\n{value.body}\n\n{value.cta}{attribution}\n\n{footer}"
    follow_up_copy = FOLLOW_UP_FR if value.language == "fr" else FOLLOW_UP_EN
    follow_up = f"{value.greeting}\n\n{follow_up_copy}{attribution}\n\n{footer}"
    footer_fingerprint = semantic_fingerprint(
        {"kind": "campaign-footer-v1", **footer_entry.model_dump(mode="json")}
    )
    fingerprint = semantic_fingerprint(
        {
            "kind": "campaign-envelope-v1",
            "language": value.language,
            "sender_profile_ref": value.sender_profile_ref,
            "subject": value.subject,
            "initial_envelope": initial,
            "follow_up_subject": "",
            "follow_up_body": follow_up,
            "footer_fingerprint": footer_fingerprint,
        }
    )
    steps = (
        CampaignStep(step=1, delay_calendar_days=0, subject=value.subject, body=initial),
        CampaignStep(step=2, delay_calendar_days=4, subject="", body=follow_up),
    )
    custom_variables = {"kivou_subject": value.subject, "kivou_envelope": initial}
    if value.attribution_url:
        custom_variables["kivou_attribution_url"] = value.attribution_url
    return CampaignEnvelope(
        subject=value.subject,
        initial_envelope=initial,
        follow_up_body=follow_up,
        footer_fingerprint=footer_fingerprint,
        envelope_fingerprint=fingerprint,
        custom_variables=custom_variables,
        steps=steps,
    )
