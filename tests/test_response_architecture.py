from __future__ import annotations

import importlib
from pathlib import Path

from signals.acquisition.contracts import STATE_MACHINE_VERSION, AcquisitionState, EventType
from signals.campaigns.contracts import (
    CampaignDeploymentConfig,
    ResponseIngressCapability,
)
from signals.responses.classifier import UnconfiguredResponseClassifier
from signals.responses.instantly_email import UnconfiguredInstantlyEmailReader

RESPONSE_ROOT = Path(__file__).parents[1] / "src" / "signals" / "responses"


def test_state_machine_and_event_vocabulary_remain_v1_without_spec027_additions() -> None:
    assert STATE_MACHINE_VERSION == "acquisition-state-v1"
    assert AcquisitionState.REPLIED.value == "REPLIED"
    assert {item.value for item in EventType} == {
        "OPPORTUNITY_CREATED",
        "STATE_TRANSITIONED",
        "DECISION_RECORDED",
        "NEXT_ACTION_SET",
        "RETRY_SCHEDULED",
        "SUPERVISOR_PLAN_OBSERVED",
        "POLICY_EVALUATED",
        "CONTACT_SELECTED",
        "OUTCOME_RECORDED",
    }


def test_response_ingress_and_execution_defaults_are_fail_closed() -> None:
    deployment = CampaignDeploymentConfig()

    assert deployment.response_ingress_capability is ResponseIngressCapability.NONE
    assert UnconfiguredResponseClassifier.classifier_version.endswith("unconfigured-v1")
    assert not hasattr(UnconfiguredInstantlyEmailReader(), "send")
    assert not hasattr(UnconfiguredInstantlyEmailReader(), "reply")


def test_response_package_has_no_agent_send_or_unrelated_runtime_dependencies() -> None:
    source = "\n".join(path.read_text() for path in RESPONSE_ROOT.glob("*.py"))

    for forbidden in (
        "openai",
        "openrouter",
        "smtp",
        "send_email",
        "reply_email",
        "apollo",
        "stripe",
        "matchingengine",
        "conversion_attribution",
    ):
        assert forbidden not in source.casefold()


def test_importing_response_package_performs_no_http_or_model_execution(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("response package import attempted network execution")

    monkeypatch.setattr("httpx.Client.request", forbidden)
    monkeypatch.setattr("httpx.AsyncClient.request", forbidden)

    module = importlib.import_module("signals.responses")
    importlib.reload(module)
