"""Production composition for one bounded acquisition runtime cycle."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sqlalchemy.engine import Engine

from signals.acquisition_connectivity.apollo import ApolloComponents
from signals.acquisition_runtime.actions import build_kivou_stage_handlers
from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeConfig,
    AcquisitionRuntimeStage,
    RuntimeRunResult,
)
from signals.acquisition_runtime.domain import (
    AcquisitionDomainActions,
    RuntimeApprovalProvider,
    RuntimePolicyAuthorizationFactory,
    SqlAcquisitionDomainTruth,
)
from signals.acquisition_runtime.registry import AcquisitionActionHandler
from signals.acquisition_runtime.transport import StagingQaRecipientOverride
from signals.campaigns.contracts import CampaignDeploymentConfig
from signals.campaigns.instantly import InstantlyProvider
from signals.campaigns.service import CampaignService, MailboxReadinessSource
from signals.campaigns.worker import CampaignWorker
from signals.company_research.service import CompanyResearchService
from signals.compliance.contracts import SenderComplianceConfig
from signals.compliance.service import ComplianceService
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.contact_discovery.contracts import (
    PROFILE_VERSION,
    ContactRunStatus,
    DecisionMakerSearchProfile,
)
from signals.contact_discovery.profile import (
    RUNTIME_QA_PROFILE_VERSION,
    build_decision_maker_profile,
    decision_maker_profile_semantics,
)
from signals.contact_discovery.service import ContactDiscoveryService
from signals.conversion.link import AttributionLinkBuilder
from signals.decision_engine.service import DecisionEngineService
from signals.personalization.service import PersonalizationService
from signals.supplier_discovery.contracts import SupplierTargetingConfig
from signals.supplier_discovery.service import SupplierDiscoveryService

RUNTIME_QA_CONTACT_PROFILE_VERSION = RUNTIME_QA_PROFILE_VERSION
RUNTIME_QA_CONTACT_REQUEUE_SOURCE_PROFILE_VERSION = PROFILE_VERSION


def runtime_qa_contact_profile_descriptor() -> dict[str, object]:
    return decision_maker_profile_semantics(RUNTIME_QA_CONTACT_PROFILE_VERSION)


def runtime_qa_contact_profile_requeue_descriptor() -> dict[str, str]:
    return {
        "source_profile_version": RUNTIME_QA_CONTACT_REQUEUE_SOURCE_PROFILE_VERSION,
        "target_profile_version": RUNTIME_QA_CONTACT_PROFILE_VERSION,
        "source_status": ContactRunStatus.CONTACT_SEARCH_TOO_BROAD.value,
    }


def build_runtime_qa_contact_profile(
    *,
    acquisition_opportunity_id: str,
    supplier_ref: str,
    provider_organization_id: str,
) -> DecisionMakerSearchProfile:
    return build_decision_maker_profile(
        acquisition_opportunity_id=acquisition_opportunity_id,
        supplier_ref=supplier_ref,
        provider_organization_id=provider_organization_id,
        profile_version=RUNTIME_QA_CONTACT_PROFILE_VERSION,
    )


@dataclass(frozen=True)
class AcquisitionDomainComposition:
    """Keep native services and their closed handlers alive for one run."""

    actions: AcquisitionDomainActions
    handlers: Mapping[AcquisitionRuntimeStage, AcquisitionActionHandler]
    supplier_service: SupplierDiscoveryService
    contact_service: ContactDiscoveryService
    company_service: CompanyResearchService
    decision_service: DecisionEngineService
    personalization_service: PersonalizationService
    compliance_service: ComplianceService
    campaign_service: CampaignService
    campaign_worker: CampaignWorker


def build_acquisition_domain_composition(
    *,
    engine: Engine,
    runtime_config: AcquisitionRuntimeConfig,
    apollo: ApolloComponents,
    instantly_provider: InstantlyProvider,
    authorization_factory: RuntimePolicyAuthorizationFactory,
    approval_provider: RuntimeApprovalProvider,
    targeting: SupplierTargetingConfig,
    suppression_keyring: SuppressionIdentityKeyring,
    sender_config: SenderComplianceConfig,
    campaign_deployment: CampaignDeploymentConfig,
    mailbox_readiness: MailboxReadinessSource,
    attribution_link_builder: AttributionLinkBuilder,
    clock: Callable[[], dt.datetime],
) -> AcquisitionDomainComposition:
    """Wire existing domains; construction performs no provider operation."""

    if targeting.max_pages != 1 or targeting.per_page != 1 or targeting.candidate_cap != 1:
        raise ValueError("runtime supplier discovery is capped at one candidate")
    supplier_service = SupplierDiscoveryService(
        engine,
        provider=apollo.organization_search,
        clock=clock,
    )
    contact_service = ContactDiscoveryService(
        engine,
        provider=apollo.contact_discovery,
        profile_builder=build_runtime_qa_contact_profile,
        profile_upgrade_requeue=(
            RUNTIME_QA_CONTACT_REQUEUE_SOURCE_PROFILE_VERSION,
            RUNTIME_QA_CONTACT_PROFILE_VERSION,
        ),
        clock=clock,
    )
    company_service = CompanyResearchService(
        engine,
        provider=apollo.company_research,
        clock=clock,
    )
    decision_service = DecisionEngineService(engine, clock=clock)
    personalization_service = PersonalizationService(engine, clock=clock)
    compliance_service = ComplianceService(
        engine,
        keyring=suppression_keyring,
        sender_config=sender_config,
        clock=clock,
        expected_contact_profile_version=RUNTIME_QA_CONTACT_PROFILE_VERSION,
    )
    campaign_service = CampaignService(
        engine,
        keyring=suppression_keyring,
        sender_config=sender_config,
        deployment=campaign_deployment,
        mailbox_readiness=mailbox_readiness,
        clock=clock,
        attribution_link_builder=attribution_link_builder,
    )
    # The override is a staging-only redirection to one controlled QA mailbox;
    # production must have no fallback recipient at all — a message reaches its
    # real contact or it does not go. `CampaignWorker` already accepts
    # `recipient_override=None` and guards every use behind `is not None`.
    recipient_override = (
        StagingQaRecipientOverride(
            runtime_config,
            transport_keyring=suppression_keyring,
        )
        if runtime_config.environment == "STAGING"
        else None
    )
    campaign_worker = CampaignWorker(
        engine,
        provider=instantly_provider,
        campaign_service=campaign_service,
        deployment=campaign_deployment,
        worker_ref="acquisition-runtime-worker",
        recipient_override=recipient_override,
        clock=clock,
    )
    actions = AcquisitionDomainActions(
        truth=SqlAcquisitionDomainTruth(engine),
        supplier_service=supplier_service,
        contact_service=contact_service,
        company_service=company_service,
        decision_service=decision_service,
        personalization_service=personalization_service,
        compliance_service=compliance_service,
        campaign_service=campaign_service,
        campaign_worker=campaign_worker,
        authorization_factory=authorization_factory,
        approval_provider=approval_provider,
        maximum_provider_operations=(runtime_config.deployment.limits.maximum_provider_operations),
        qa_transport_recipient_identity=(
            recipient_override.transport_recipient_identity
            if recipient_override is not None
            else None
        ),
        qa_transport_recipient_key_version=(
            recipient_override.transport_key_version
            if recipient_override is not None
            else None
        ),
        qa_scope=runtime_config.deployment.qa_scope,
        targeting=targeting,
    )
    return AcquisitionDomainComposition(
        actions=actions,
        handlers=build_kivou_stage_handlers(actions),
        supplier_service=supplier_service,
        contact_service=contact_service,
        company_service=company_service,
        decision_service=decision_service,
        personalization_service=personalization_service,
        compliance_service=compliance_service,
        campaign_service=campaign_service,
        campaign_worker=campaign_worker,
    )


__all__ = [
    "RUNTIME_QA_CONTACT_PROFILE_VERSION",
    "RUNTIME_QA_CONTACT_REQUEUE_SOURCE_PROFILE_VERSION",
    "AcquisitionDomainComposition",
    "build_acquisition_domain_composition",
    "build_runtime_qa_contact_profile",
    "execute_runtime_run_once",
    "runtime_qa_contact_profile_descriptor",
    "runtime_qa_contact_profile_requeue_descriptor",
]


def execute_runtime_run_once(
    *,
    allow_qa_provider_mutations: bool,
) -> RuntimeRunResult:
    """Load the fail-closed executable root lazily to avoid import cycles."""

    from signals.acquisition_runtime.execution import (
        execute_runtime_run_once as execute,
    )

    return execute(allow_qa_provider_mutations=allow_qa_provider_mutations)
