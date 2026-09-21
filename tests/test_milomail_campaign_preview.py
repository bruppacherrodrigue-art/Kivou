"""Versioned French copy yields a provider-shaped preview with no mutation."""

import datetime as dt

import pytest
from test_milomail_policy import NOW, ready_input

from signals.acquisition_programs.campaign_factory import (
    PublicPersonalizationFact,
    build_campaign_preview,
)
from signals.campaigns.instantly import ShadowInstantlyProvider, ShadowSendForbidden
from signals.compliance.milomail_rules import evaluate_milomail


class ForbiddenProvider:
    def __getattr__(self, name):
        raise AssertionError(f"external Instantly call: {name}")


TOKEN = "A" * 43


def test_french_preview_has_two_bounded_steps_and_opposition() -> None:
    value = ready_input()
    preview = build_campaign_preview(
        config=value.program,
        decision=evaluate_milomail(value),
        attribution_token=TOKEN,
    )
    assert preview.program_key == "milomail"
    assert preview.workspace_ref == value.program.instantly_workspace_ref
    assert preview.template_version == value.program.template_version
    assert len(preview.steps) == 2
    assert preview.steps[1].delay_days == 4
    assert preview.provider_config["stop_on_reply"] is True
    assert preview.provider_config["stop_on_auto_reply"] is True
    assert preview.provider_config["insert_unsubscribe_header"] is True
    assert preview.provider_config["daily_limit"] == 0
    assert all("Milo Mail" in step.body for step in preview.steps)
    assert all("ne modifie ni ne supprime aucun e-mail" in step.body for step in preview.steps)
    assert all("Milo Clean" in step.body for step in preview.steps)
    assert all("désinscription" in step.body.casefold() for step in preview.steps)
    assert TOKEN in preview.steps[0].body
    assert "founder@" not in repr(preview)


def test_public_fact_is_optional_and_deletion_leaves_exact_message() -> None:
    value = ready_input()
    decision = evaluate_milomail(value)
    base = build_campaign_preview(config=value.program, decision=decision, attribution_token=TOKEN)
    fact = PublicPersonalizationFact(
        text="Votre cabinet publie des offres de conseil.",
        evidence_id="company-research:public-1",
        source_url="https://cabinet.example/actualites",
        observed_at=NOW,
    )
    sourced_decision = decision.model_copy(
        update={"evidence_ids": (*decision.evidence_ids, fact.evidence_id)}
    )
    personalized = build_campaign_preview(
        config=value.program,
        decision=sourced_decision,
        attribution_token=TOKEN,
        public_fact=fact,
    )
    assert personalized.steps[0].body.replace(fact.text + "\n\n", "") == base.steps[0].body
    assert personalized.steps[1].body == base.steps[1].body
    with pytest.raises(ValueError):
        PublicPersonalizationFact(
            text=fact.text,
            evidence_id="",
            source_url=fact.source_url,
            observed_at=NOW + dt.timedelta(days=1),
        )


def test_shadow_facade_rejects_provider_create_even_with_preview() -> None:
    value = ready_input()
    preview = build_campaign_preview(
        config=value.program,
        decision=evaluate_milomail(value),
        attribution_token=TOKEN,
    )
    provider = ShadowInstantlyProvider(ForbiddenProvider())
    with pytest.raises(ShadowSendForbidden):
        provider.create_campaign(
            name=preview.campaign_name, provider_config=preview.provider_config
        )
