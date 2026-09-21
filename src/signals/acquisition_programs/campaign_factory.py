"""Configured, source-backed campaign preview; no provider mutation."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from urllib.parse import urlencode, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from signals.acquisition_programs.contracts import AcquisitionProgramConfig
from signals.acquisition_programs.mail_provider import normalize_domain
from signals.compliance.milomail_rules import MilomailPolicyDecision

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PublicPersonalizationFact(_ClosedModel):
    """A Kivou Company Research assertion with a durable public citation."""

    text: str = Field(min_length=1, max_length=250)
    evidence_id: str = Field(min_length=1, max_length=128)
    source_url: str = Field(min_length=1, max_length=2048)
    observed_at: dt.datetime

    @field_validator("text")
    @classmethod
    def no_private_mailbox_claim(cls, value: str) -> str:
        lowered = value.casefold()
        if any(
            token in lowered
            for token in (
                "boîte",
                "gmail",
                "e-mail",
                "courriel",
                "message",
                "heures perdues",
            )
        ):
            raise ValueError("public fact must not assert private mailbox information")
        return value

    @field_validator("source_url")
    @classmethod
    def valid_public_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("public fact needs an HTTP source URL")
        normalize_domain(parsed.hostname)
        return value

    @field_validator("observed_at")
    @classmethod
    def aware(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("public fact observation must be timezone-aware")
        return value


class ProgramCampaignStep(_ClosedModel):
    sequence: int = Field(ge=1, le=2)
    delay_days: int = Field(ge=0, le=14)
    subject: str
    body: str


class ProgramCampaignPreview(_ClosedModel):
    program_key: str
    campaign_name: str
    workspace_ref: str
    template_version: str
    steps: tuple[ProgramCampaignStep, ProgramCampaignStep]
    provider_config: dict[str, object]
    evidence_ids: tuple[str, ...]


def build_campaign_preview(
    *,
    config: AcquisitionProgramConfig,
    decision: MilomailPolicyDecision,
    attribution_token: str,
    public_fact: PublicPersonalizationFact | None = None,
) -> ProgramCampaignPreview:
    if config.campaign_mode != "SHADOW" or decision.decision != "SEND":
        raise ValueError("campaign preview requires a theoretical SEND in SHADOW")
    if not _TOKEN.fullmatch(attribution_token):
        raise ValueError("attribution token must be opaque and fixed-length")
    if not all(
        (config.landing_url, config.privacy_url, config.opt_out_url, config.instantly_workspace_ref)
    ):
        raise ValueError("French campaign destination or workspace unavailable")
    workspace_ref = config.instantly_workspace_ref
    if workspace_ref is None:
        raise ValueError("Instantly workspace unavailable")
    if not config.sender_legal_name or not config.sender_postal_address:
        raise ValueError("exact sender legal identity is unavailable")
    if public_fact is not None and (
        public_fact.observed_at > decision.decided_at
        or public_fact.evidence_id not in decision.evidence_ids
    ):
        raise ValueError("personalization fact has no current policy evidence")

    # Deletion test: this optional, sourced sentence can be removed without
    # changing any claim about the prospect or the offer in the base message.
    insertion = f"{public_fact.text}\n\n" if public_fact else ""
    landing = f"{config.landing_url}?{urlencode({'a': attribution_token})}"
    footer = (
        f"{config.messages.sender_identity}\n"
        f"{config.sender_legal_name}\n{config.sender_postal_address}\n"
        f"{config.messages.source_notice}\n"
        f"Politique de confidentialité : {config.privacy_url}\n"
        f"Désinscription simple et gratuite : {config.opt_out_url}"
    )
    initial = (
        f"Bonjour,\n\n{insertion}{config.messages.initial_body}\n\n"
        f"{config.messages.cta_text} {landing}\n\n{footer}"
    )
    follow_up = f"Bonjour,\n\n{config.messages.follow_up_body}\n\n{footer}"
    steps = (
        ProgramCampaignStep(
            sequence=1, delay_days=0, subject=config.messages.subject, body=initial
        ),
        ProgramCampaignStep(
            sequence=2,
            delay_days=config.messages.follow_up_delay_days,
            subject="",
            body=follow_up,
        ),
    )
    provider_steps = [
        {
            "type": "email",
            "delay": step.delay_days,
            "variants": [{"subject": step.subject, "body": step.body, "v_disabled": False}],
        }
        for step in steps
    ]
    provider_config: dict[str, object] = {
        "sequences": [{"steps": provider_steps}],
        "stop_on_reply": True,
        "stop_on_auto_reply": True,
        "stop_for_company": False,
        "insert_unsubscribe_header": True,
        "allow_risky_contacts": False,
        "disable_bounce_protect": False,
        "open_tracking": False,
        "link_tracking": False,
        "daily_limit": 0,
        "email_list": [],
    }
    fingerprint = hashlib.sha256(
        json.dumps(config.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()[:12]
    return ProgramCampaignPreview(
        program_key=config.program_key,
        campaign_name=f"{config.program_key}:{config.template_version}:{fingerprint}",
        workspace_ref=workspace_ref,
        template_version=config.template_version,
        steps=steps,
        provider_config=provider_config,
        evidence_ids=(*decision.evidence_ids, *((public_fact.evidence_id,) if public_fact else ())),
    )


__all__ = ["ProgramCampaignPreview", "PublicPersonalizationFact", "build_campaign_preview"]
