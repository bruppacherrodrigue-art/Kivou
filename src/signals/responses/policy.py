"""Kivou-owned exact Policy evidence and authorization for response classification."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Callable

from signals.acquisition.store import AcquisitionStore
from signals.policy.contracts import (
    POLICY_VERSION,
    BudgetUsage,
    ComplianceAssessment,
    ComplianceState,
    EvidenceReadiness,
    EvidenceStatus,
    OperationalReadiness,
    PolicyRequest,
    Scope,
)
from signals.policy.gateway import PolicyGateway
from signals.responses.worker import (
    ResponsePolicyAuthorization,
    ResponsePolicyFacts,
)


def _sha(domain: str, value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(f"{domain}\0".encode() + encoded).hexdigest()


def _safe_arguments(facts: ResponsePolicyFacts) -> dict[str, object]:
    return {
        "version": "response-evidence-v1",
        "response_ref": facts.response_ref,
        "provider_event_ref": facts.provider_event_ref,
        "provider_event_fingerprint": facts.provider_event_fingerprint,
        "provider_workspace_ref": facts.provider_workspace_ref,
        "campaign_ref": facts.campaign_ref,
        "member_ref": facts.member_ref,
        "acquisition_opportunity_id": facts.acquisition_opportunity_id,
        "contact_ref": facts.contact_ref,
        "provider_email_id": facts.provider_email_id,
        "source_fingerprint": facts.source_fingerprint,
        "content_fingerprint": facts.content_fingerprint,
        "content_fingerprint_version": facts.content_fingerprint_version,
        "content_fingerprint_key_version": facts.content_fingerprint_key_version,
        "resolver_version": facts.resolver_version,
        "normalizer_version": facts.normalizer_version,
        "safety_version": facts.safety_version,
        "taxonomy_version": facts.taxonomy_version,
        "classifier_version": facts.classifier_version,
        "language": facts.language,
        "human_response_confirmed": facts.human_response_confirmed,
        "provider_auto_reply": facts.provider_auto_reply,
        "observed_at": facts.observed_at.isoformat(),
        "max_proposed_cost": format(facts.max_proposed_cost, "f"),
    }


def build_classify_response_policy_request(
    facts: ResponsePolicyFacts,
    *,
    expected_opportunity_version: int,
    operational: OperationalReadiness,
    currency: str,
) -> PolicyRequest:
    """Build exact evidence from Kivou facts; callers cannot choose the vocabulary."""

    arguments = _safe_arguments(facts)
    action = {
        "command": "classify_response",
        "target_ref": facts.response_ref,
        "arguments": arguments,
        "country": facts.country,
        "language": facts.language,
        "wedge": facts.wedge,
    }
    action_fingerprint = _sha("kivou:classify-response-action:v1", action)
    evaluation_id = _sha(
        "kivou:classify-response-policy-evaluation:v1",
        {
            "response_ref": facts.response_ref,
            "classifier_version": facts.classifier_version,
            "action_fingerprint": action_fingerprint,
        },
    )
    return PolicyRequest(
        evaluation_id=evaluation_id,
        request_id=evaluation_id,
        command="classify_response",
        target_ref=facts.response_ref,
        acquisition_opportunity_id=facts.acquisition_opportunity_id,
        expected_opportunity_version=expected_opportunity_version,
        actor_type="SYSTEM",
        actor_ref="kivou-response-intelligence",
        canonical_arguments=json.dumps(
            arguments, allow_nan=False, sort_keys=True, separators=(",", ":")
        ),
        action_fingerprint=action_fingerprint,
        scope=Scope(country=facts.country, language=facts.language, wedge=facts.wedge),
        proposed_cost=facts.max_proposed_cost,
        currency=currency,
        proposed_volume=0,
        reason_codes=("RESPONSE_CLASSIFICATION_REQUESTED",),
        evidence_refs=(
            f"response:{facts.response_ref}",
            f"provider-event:{facts.provider_event_ref}",
            f"provider-email:{facts.provider_email_id}",
        ),
        evidence=EvidenceReadiness(
            status=EvidenceStatus.READY,
            claims=("RESPONSE",),
            assessment_version="response-evidence-v1",
            observed_at=facts.observed_at,
        ),
        compliance=ComplianceAssessment(
            state=ComplianceState.UNKNOWN,
            assessment_version="response-classification-no-compliance-gate-v1",
            observed_at=facts.observed_at,
        ),
        operational=operational,
        expected_policy_version=POLICY_VERSION,
    )


class GatewayResponsePolicyAuthorizer:
    """Evaluate and dual-audit the exact response request through PolicyGateway."""

    def __init__(
        self,
        engine,
        *,
        operational_provider: Callable[
            [ResponsePolicyFacts, dt.datetime], OperationalReadiness
        ],
        budget_usage_provider: Callable[
            [ResponsePolicyFacts, dt.datetime], BudgetUsage
        ],
        currency: str,
    ) -> None:
        self._acquisition = AcquisitionStore(engine)
        self._gateway = PolicyGateway(engine, acquisition_store=self._acquisition)
        self._operational_provider = operational_provider
        self._budget_usage_provider = budget_usage_provider
        self._currency = currency

    def authorize(
        self, facts: ResponsePolicyFacts, *, now: dt.datetime
    ) -> ResponsePolicyAuthorization:
        opportunity = self._acquisition.get_opportunity(
            facts.acquisition_opportunity_id
        )
        request = build_classify_response_policy_request(
            facts,
            expected_opportunity_version=opportunity.stream_version,
            operational=self._operational_provider(facts, now),
            currency=self._currency,
        )
        decision = self._gateway.evaluate_and_record(
            request,
            evaluated_at=now,
            budget_usage=self._budget_usage_provider(facts, now),
        )
        return ResponsePolicyAuthorization(
            allowed=decision.allowed,
            policy_evaluation_id=decision.evaluation_id,
            policy_action_fingerprint=decision.action_fingerprint,
            policy_status=decision.status.value,
        )


__all__ = [
    "GatewayResponsePolicyAuthorizer",
    "build_classify_response_policy_request",
]
