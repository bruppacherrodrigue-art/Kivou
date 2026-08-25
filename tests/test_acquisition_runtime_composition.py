from __future__ import annotations

import datetime as dt
import hashlib
import hmac
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa

from signals.acquisition_connectivity.apollo import ApolloComponents
from signals.acquisition_runtime.composition import (
    AcquisitionDomainComposition,
    build_acquisition_domain_composition,
)
from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeConfig,
    AcquisitionRuntimeDeployment,
    AcquisitionRuntimeLimits,
    AcquisitionRuntimeStage,
)
from signals.campaigns.contracts import CampaignDeploymentConfig
from signals.campaigns.service import CampaignService
from signals.campaigns.worker import CampaignWorker
from signals.company_research.service import CompanyResearchService
from signals.compliance.contracts import SenderComplianceConfig
from signals.compliance.service import ComplianceService
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.contact_discovery.service import ContactDiscoveryService
from signals.conversion.link import AttributionLinkBuilder
from signals.conversion.token import AttributionTokenKeyring
from signals.decision_engine.service import DecisionEngineService
from signals.personalization.service import PersonalizationService
from signals.supplier_discovery.contracts import SupplierTargetingConfig
from signals.supplier_discovery.service import SupplierDiscoveryService

NOW = dt.datetime(2026, 8, 25, 12, tzinfo=dt.UTC)
QA_RECIPIENT = "qa@example.com"
QA_KEY = "qa-runtime-binding-key"


class NoNetworkProvider:
    def __getattr__(self, name: str):
        raise AssertionError(f"provider I/O during composition: {name}")


class AuthorizationFactory:
    pass


class ApprovalProvider:
    def consume_for(self, context, *, opportunity_id):
        return ()


class MailboxReadiness:
    def get(self, provider_account_id: str, *, observed_at: dt.datetime):
        raise AssertionError("mailbox provider I/O during composition")


def _runtime_config() -> AcquisitionRuntimeConfig:
    binding = hmac.new(QA_KEY.encode(), QA_RECIPIENT.encode(), hashlib.sha256).hexdigest()
    return AcquisitionRuntimeConfig(
        environment="STAGING",
        deployment_path=Path("/etc/kivou/acquisition-runtime.json"),
        deployment=AcquisitionRuntimeDeployment(
            qa_only=True,
            allowed_opportunity_keys=("signal-qa-001",),
            qa_recipient_identity_hmac=binding,
            qa_recipient_key_version="runtime-qa-v1",
            qa_provider_mutations_capable=True,
            limits=AcquisitionRuntimeLimits(
                maximum_cycle_cost=Decimal("10"),
                maximum_provider_operations=3,
                maximum_wall_seconds=600,
                lease_seconds=900,
            ),
        ),
        qa_recipient=QA_RECIPIENT,
        qa_recipient_hmac_key=QA_KEY,
    )


def test_builder_composes_existing_services_and_closed_stage_handlers_without_io() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    provider = NoNetworkProvider()
    apollo = ApolloComponents(
        organization_search=provider,
        contact_discovery=provider,
        company_research=provider,
        identity=provider,
    )
    suppression = SuppressionIdentityKeyring(
        current_key_version="suppression-v1",
        keys={"suppression-v1": b"synthetic-suppression-key"},
    )
    composition = build_acquisition_domain_composition(
        engine=engine,
        runtime_config=_runtime_config(),
        apollo=apollo,
        instantly_provider=provider,
        authorization_factory=AuthorizationFactory(),
        approval_provider=ApprovalProvider(),
        targeting=SupplierTargetingConfig(max_pages=1, per_page=1, candidate_cap=1),
        suppression_keyring=suppression,
        sender_config=SenderComplianceConfig(
            sender_profile_ref="sender-profile:qa",
            sender_identity_ready=True,
            opt_out_ready=True,
            privacy_notice_ready=True,
            source_notice_ready=True,
            valid_until=NOW + dt.timedelta(days=1),
        ),
        campaign_deployment=CampaignDeploymentConfig(),
        mailbox_readiness=MailboxReadiness(),
        attribution_link_builder=AttributionLinkBuilder(
            public_site_url="https://staging.example.invalid",
            keyring=AttributionTokenKeyring(
                current_key_version="attribution-v1",
                keys={"attribution-v1": b"synthetic-attribution-key"},
            ),
        ),
        clock=lambda: NOW,
    )

    assert isinstance(composition, AcquisitionDomainComposition)
    assert isinstance(composition.supplier_service, SupplierDiscoveryService)
    assert isinstance(composition.contact_service, ContactDiscoveryService)
    assert isinstance(composition.company_service, CompanyResearchService)
    assert isinstance(composition.decision_service, DecisionEngineService)
    assert isinstance(composition.personalization_service, PersonalizationService)
    assert isinstance(composition.compliance_service, ComplianceService)
    assert isinstance(composition.campaign_service, CampaignService)
    assert isinstance(composition.campaign_worker, CampaignWorker)
    assert set(composition.handlers) == set(AcquisitionRuntimeStage)
    assert QA_RECIPIENT not in repr(composition)


def test_builder_refuses_supplier_limits_wider_than_one_candidate() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    provider = NoNetworkProvider()
    apollo = ApolloComponents(
        organization_search=provider,
        contact_discovery=provider,
        company_research=provider,
        identity=provider,
    )
    suppression = SuppressionIdentityKeyring(
        current_key_version="suppression-v1",
        keys={"suppression-v1": b"synthetic-suppression-key"},
    )

    try:
        build_acquisition_domain_composition(
            engine=engine,
            runtime_config=_runtime_config(),
            apollo=apollo,
            instantly_provider=provider,
            authorization_factory=AuthorizationFactory(),
            approval_provider=ApprovalProvider(),
            targeting=SupplierTargetingConfig(max_pages=1, per_page=2, candidate_cap=2),
            suppression_keyring=suppression,
            sender_config=SenderComplianceConfig(
                sender_profile_ref="sender-profile:qa",
                sender_identity_ready=True,
                opt_out_ready=True,
                privacy_notice_ready=True,
                source_notice_ready=True,
                valid_until=NOW + dt.timedelta(days=1),
            ),
            campaign_deployment=CampaignDeploymentConfig(),
            mailbox_readiness=MailboxReadiness(),
            attribution_link_builder=AttributionLinkBuilder(
                public_site_url="https://staging.example.invalid",
                keyring=AttributionTokenKeyring(
                    current_key_version="attribution-v1",
                    keys={"attribution-v1": b"synthetic-attribution-key"},
                ),
            ),
            clock=lambda: NOW,
        )
    except ValueError as error:
        assert "one candidate" in str(error)
    else:
        raise AssertionError("wider supplier targeting was accepted")
