"""Fail-closed environment composition for one acquisition runtime invocation."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
from sqlalchemy.engine import Engine

from signals.acquisition_connectivity.apollo import (
    ApolloComponents,
    build_apollo_components,
)
from signals.acquisition_connectivity.config import (
    load_connectivity_config,
    validate_hermes_shadow_config,
)
from signals.acquisition_connectivity.contracts import AcquisitionConnectivityConfig
from signals.acquisition_runtime.composition import (
    AcquisitionDomainComposition,
    build_acquisition_domain_composition,
)
from signals.acquisition_runtime.config import load_runtime_config
from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeConfig,
    AcquisitionRuntimeStage,
    RuntimeActionResult,
    RuntimeCapabilityEvidence,
    RuntimeHermesIdentityEvidence,
    RuntimeRunRequest,
    RuntimeRunResult,
    RuntimeStageDependency,
    RuntimeStageStatus,
)
from signals.acquisition_runtime.registry import (
    AcquisitionActionHandler,
    AcquisitionActionRegistry,
)
from signals.acquisition_runtime.runner import AcquisitionRuntimeRunner
from signals.acquisition_runtime.runtime_policy import (
    DurableRuntimeApprovalProvider,
    LiveRuntimePolicyAuthorizationFactory,
    RuntimePolicyConfigurationError,
)
from signals.acquisition_runtime.store import AcquisitionRuntimeStore
from signals.acquisition_runtime.supervisor import AcquisitionHermesSupervisor
from signals.campaigns.contracts import (
    CampaignDeploymentConfig,
    FooterCatalog,
    FooterCatalogEntry,
    MailboxCatalog,
    MailboxCatalogEntry,
)
from signals.campaigns.instantly import (
    HttpInstantlyProvider,
    InstantlyMailboxReadinessSource,
    InstantlyProvider,
)
from signals.compliance.contracts import SenderComplianceConfig
from signals.compliance.suppression import SuppressionIdentityKeyring
from signals.conversion.link import AttributionLinkBuilder
from signals.conversion.token import AttributionTokenKeyring
from signals.decision_engine.policy import semantic_fingerprint
from signals.persistence.database import create_database_engine
from signals.policy.contracts import PolicyControlSnapshot, Scope
from signals.policy.store import PolicyStore
from signals.supervisor.contracts import SupervisorLimits
from signals.supervisor.hermes import HermesSupervisorAdapter
from signals.supervisor.pin import load_hermes_pin
from signals.supervisor.runtime import SupervisorSettings
from signals.supplier_discovery.contracts import SupplierTargetingConfig

_PUBLIC_APP_URL = "KIVOU_PUBLIC_APP_URL"
_ATTRIBUTION_KEY = "KIVOU_ATTRIBUTION_HMAC_KEY"
_ATTRIBUTION_KEY_VERSION = "KIVOU_ATTRIBUTION_HMAC_KEY_VERSION"


class RuntimeExecutionConfigurationError(RuntimeError):
    """A bounded configuration error which never carries configuration values."""

    def __init__(self, code: str) -> None:
        super().__init__(f"acquisition runtime execution configuration error: {code}")
        self.code = code


@dataclass(frozen=True)
class RuntimeLinkConfiguration:
    public_app_url: str
    attribution_hmac_key: bytes = field(repr=False)
    attribution_key_version: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.public_app_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or len(self.attribution_hmac_key) < 16
            or not self.attribution_key_version
            or len(self.attribution_key_version) > 100
        ):
            raise RuntimeExecutionConfigurationError("LINKS_NOT_CONFIGURED")
        object.__setattr__(self, "public_app_url", self.public_app_url.rstrip("/"))


class DomainCompositionSurface:
    """Narrow structural surface used by the executable root."""

    handlers: Mapping[AcquisitionRuntimeStage, AcquisitionActionHandler]


@dataclass(frozen=True)
class RuntimeExecutionComposition:
    store: AcquisitionRuntimeStore
    domain: DomainCompositionSurface
    registry: AcquisitionActionRegistry
    supervisor: AcquisitionHermesSupervisor
    runner: AcquisitionRuntimeRunner
    capability: RuntimeCapabilityEvidence
    config_fingerprint: str


def _required(source: Mapping[str, str], name: str) -> str:
    value = source.get(name)
    if value is None or not value.strip():
        raise RuntimeExecutionConfigurationError("LINKS_NOT_CONFIGURED")
    return value.strip()


def load_runtime_link_config(
    environ: Mapping[str, str] | None = None,
) -> RuntimeLinkConfiguration:
    source = os.environ if environ is None else environ
    try:
        return RuntimeLinkConfiguration(
            public_app_url=_required(source, _PUBLIC_APP_URL),
            attribution_hmac_key=_required(source, _ATTRIBUTION_KEY).encode("utf-8"),
            attribution_key_version=_required(source, _ATTRIBUTION_KEY_VERSION),
        )
    except RuntimeExecutionConfigurationError:
        raise
    except (TypeError, ValueError):
        raise RuntimeExecutionConfigurationError("LINKS_NOT_CONFIGURED") from None


def _exact_scope(control: PolicyControlSnapshot) -> Scope:
    if not (
        len(control.allowed_countries) == 1
        and len(control.allowed_languages) == 1
        and len(control.allowed_wedges) == 1
        and control.allowed_countries[0] in {"CH", "FR"}
        and control.allowed_languages[0] in {"fr", "en"}
    ):
        raise RuntimePolicyConfigurationError("POLICY_SCOPE_NOT_EXACT")
    return Scope(
        country=control.allowed_countries[0],
        language=control.allowed_languages[0],
        wedge=control.allowed_wedges[0],
    )


def _mailbox_fingerprint(values: Mapping[str, object]) -> str:
    encoded = json.dumps(
        values,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _campaign_configuration(
    connectivity: AcquisitionConnectivityConfig,
    *,
    links: RuntimeLinkConfiguration,
    scope: Scope,
) -> tuple[SenderComplianceConfig, CampaignDeploymentConfig]:
    if scope.country not in {"CH", "FR"} or scope.language not in {"fr", "en"}:
        raise RuntimePolicyConfigurationError("POLICY_SCOPE_NOT_EXACT")
    assert scope.wedge is not None
    sender_profile_ref = "sender-profile:acquisition-qa"
    timezone = "Europe/Zurich" if scope.country == "CH" else "Europe/Paris"
    mailboxes = tuple(
        MailboxCatalogEntry(
            mailbox_ref=binding.mailbox_ref,
            provider_account_id=str(binding.provider_account_id),
            sender_profile_ref=sender_profile_ref,
            eligible_countries=(scope.country,),
            eligible_languages=(scope.language,),
            eligible_wedges=(scope.wedge,),
            domain_ref=(
                "mailbox-domain:"
                + hashlib.sha256(binding.mailbox_ref.encode("utf-8")).hexdigest()
            ),
            timezone=timezone,
            kivou_daily_cap=1,
            kivou_campaign_cap=1,
            config_version="acquisition-runtime-mailbox-v1",
            config_fingerprint=_mailbox_fingerprint(
                {
                    "enabled": index == 0,
                    "mailbox_ref": binding.mailbox_ref,
                    "provider_account_id": str(binding.provider_account_id),
                    "scope": scope.model_dump(mode="json"),
                    "sender_profile_ref": sender_profile_ref,
                }
            ),
            enabled=index == 0,
        )
        for index, binding in enumerate(connectivity.deployment.mailboxes)
    )
    footer_text = {
        "fr": (
            "Contact professionnel issu de sources publiques.",
            "Répondez STOP pour ne plus être contacté.",
        ),
        "en": (
            "Business contact identified from public sources.",
            "Reply STOP to opt out of further contact.",
        ),
    }
    source_notice, opt_out = footer_text[scope.language]
    sender = SenderComplianceConfig(
        sender_profile_ref=sender_profile_ref,
        sender_identity_ready=True,
        opt_out_ready=True,
        privacy_notice_ready=True,
        source_notice_ready=True,
    )
    deployment = CampaignDeploymentConfig(
        provider_workspace_ref=connectivity.deployment.instantly_workspace_ref,
        wedge=scope.wedge,
        wedge_version="acquisition-runtime-wedge-v1",
        mailbox_pool_version="acquisition-runtime-mailbox-pool-v1",
        mailbox_catalog=MailboxCatalog(
            catalog_version="acquisition-runtime-mailbox-catalog-v1",
            entries=mailboxes,
        ),
        footer_catalog=FooterCatalog(
            catalog_version="acquisition-runtime-footer-catalog-v1",
            entries=(
                FooterCatalogEntry(
                    language=scope.language,
                    sender_profile_ref=sender_profile_ref,
                    sender_identity="Kivou",
                    source_notice=source_notice,
                    privacy_route=f"{links.public_app_url}/informations-legales",
                    visible_opt_out=opt_out,
                ),
            ),
        ),
    )
    return sender, deployment


def _configuration_fingerprint(
    *,
    runtime_config: AcquisitionRuntimeConfig,
    connectivity_config: AcquisitionConnectivityConfig,
    links: RuntimeLinkConfiguration,
    control: PolicyControlSnapshot,
    sender: SenderComplianceConfig,
    campaign: CampaignDeploymentConfig,
    registry_identity: str,
) -> str:
    return semantic_fingerprint(
        {
            "kind": "acquisition-runtime-execution-config-v1",
            "runtime": runtime_config.deployment.model_dump(mode="json"),
            "connectivity": connectivity_config.deployment.model_dump(mode="json"),
            "public_app_url": links.public_app_url,
            "attribution_key_version": links.attribution_key_version,
            "policy_snapshot_fingerprint": control.snapshot_fingerprint,
            "sender_config_fingerprint": sender.config_fingerprint,
            "campaign": campaign.model_dump(mode="json"),
            "registry_identity": registry_identity,
        }
    )


def _runtime_capability(registry: AcquisitionActionRegistry) -> RuntimeCapabilityEvidence:
    pin = load_hermes_pin()
    return RuntimeCapabilityEvidence(
        environment="STAGING",
        mode="SHADOW",
        qa_only=True,
        hermes=RuntimeHermesIdentityEvidence(
            repository=pin.repository,
            tag=pin.tag,
            commit=pin.commit,
            version=pin.version,
            python_contract=pin.python,
        ),
        registry_identity=registry.identity,
        native_tools=0,
        commands=registry.commands,
        dependencies=tuple(
            RuntimeStageDependency(stage=stage, status="READY")
            for stage in AcquisitionRuntimeStage
        ),
    )


def _default_hermes_runtime(
    connectivity: AcquisitionConnectivityConfig,
) -> HermesSupervisorAdapter:
    return HermesSupervisorAdapter(
        SupervisorSettings(
            hermes_python=connectivity.hermes_python,
            hermes_home=connectivity.hermes_home,
            working_directory=connectivity.hermes_cwd,
            limits=SupervisorLimits(
                invocation_timeout_seconds=30,
                max_planned_actions=1,
                max_output_tokens=2_048,
            ),
        )
    )


def build_runtime_execution_composition(
    *,
    engine: Engine,
    runtime_config: AcquisitionRuntimeConfig,
    connectivity_config: AcquisitionConnectivityConfig,
    links: RuntimeLinkConfiguration,
    clock: Callable[[], dt.datetime],
    client: httpx.Client | None = None,
    apollo: ApolloComponents | None = None,
    instantly_provider: InstantlyProvider | None = None,
    hermes_runtime: object | None = None,
    domain_builder: Callable[..., AcquisitionDomainComposition] = (
        build_acquisition_domain_composition
    ),
) -> RuntimeExecutionComposition:
    """Compose all real boundaries; construction itself performs no provider I/O."""

    now = clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise RuntimeExecutionConfigurationError("CLOCK_NOT_CONFIGURED")
    observed_at = now.astimezone(dt.UTC)
    control = PolicyStore(engine).get_effective_control(observed_at)
    scope = _exact_scope(control)
    sender_config, campaign_deployment = _campaign_configuration(
        connectivity_config,
        links=links,
        scope=scope,
    )
    if (apollo is None or instantly_provider is None) and client is None:
        raise RuntimeExecutionConfigurationError("PROVIDER_CLIENT_NOT_CONFIGURED")
    provider = instantly_provider
    if provider is None:
        assert client is not None
        provider = HttpInstantlyProvider(
            api_key=connectivity_config.instantly_api_key.get_secret_value(),
            client=client,
        )
    apollo_components = apollo
    if apollo_components is None:
        assert client is not None
        apollo_components = build_apollo_components(
            api_key=connectivity_config.apollo_api_key.get_secret_value(),
            client=client,
        )
    suppression_keyring = SuppressionIdentityKeyring(
        current_key_version=runtime_config.deployment.qa_recipient_key_version,
        keys={
            runtime_config.deployment.qa_recipient_key_version: (
                runtime_config.qa_recipient_hmac_key.get_secret_value().encode("utf-8")
            )
        },
    )
    link_builder = AttributionLinkBuilder(
        public_site_url=links.public_app_url,
        keyring=AttributionTokenKeyring(
            current_key_version=links.attribution_key_version,
            keys={links.attribution_key_version: links.attribution_hmac_key},
        ),
    )
    targeting = SupplierTargetingConfig(max_pages=1, per_page=1, candidate_cap=1)
    empty_registry = AcquisitionActionRegistry(
        {
            stage: lambda _context: RuntimeActionResult(
                status=RuntimeStageStatus.BLOCKED,
                reason_codes=("RUNTIME_NOT_COMPOSED",),
            )
            for stage in AcquisitionRuntimeStage
        }
    )
    config_fingerprint = _configuration_fingerprint(
        runtime_config=runtime_config,
        connectivity_config=connectivity_config,
        links=links,
        control=control,
        sender=sender_config,
        campaign=campaign_deployment,
        registry_identity=empty_registry.identity,
    )
    authorization_factory = LiveRuntimePolicyAuthorizationFactory(
        engine,
        runtime_revision=f"runtime-{config_fingerprint[:32]}",
    )
    approval_provider = DurableRuntimeApprovalProvider(
        engine,
        approval_ttl_seconds=min(
            1_800,
            runtime_config.deployment.limits.lease_seconds,
        ),
    )
    domain = domain_builder(
        engine=engine,
        runtime_config=runtime_config,
        apollo=apollo_components,
        instantly_provider=provider,
        authorization_factory=authorization_factory,
        approval_provider=approval_provider,
        targeting=targeting,
        suppression_keyring=suppression_keyring,
        sender_config=sender_config,
        campaign_deployment=campaign_deployment,
        mailbox_readiness=InstantlyMailboxReadinessSource(
            provider,
            require_sending_gap=False,
        ),
        attribution_link_builder=link_builder,
        clock=clock,
    )
    registry = AcquisitionActionRegistry(domain.handlers)
    if registry.identity != empty_registry.identity:
        raise RuntimeExecutionConfigurationError("REGISTRY_IDENTITY_MISMATCH")
    supervisor = AcquisitionHermesSupervisor(
        hermes_runtime or _default_hermes_runtime(connectivity_config),
        registry=registry,
    )
    capability = _runtime_capability(registry)
    store = AcquisitionRuntimeStore(engine)
    limits = runtime_config.deployment.limits
    runner = AcquisitionRuntimeRunner(
        store=store,
        supervisor=supervisor,
        registry=registry,
        allowed_opportunity_keys=runtime_config.deployment.allowed_opportunity_keys,
        config_fingerprint=config_fingerprint,
        maximum_cycle_cost=limits.maximum_cycle_cost,
        maximum_wall_seconds=limits.maximum_wall_seconds,
        lease_seconds=limits.lease_seconds,
        runtime_capability=capability,
        clock=clock,
    )
    return RuntimeExecutionComposition(
        store=store,
        domain=domain,
        registry=registry,
        supervisor=supervisor,
        runner=runner,
        capability=capability,
        config_fingerprint=config_fingerprint,
    )


def _owner_ref() -> str:
    return "runtime-owner:" + hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def execute_runtime_run_once(
    *,
    allow_qa_provider_mutations: bool,
) -> RuntimeRunResult:
    runtime_config = load_runtime_config()
    connectivity_config = load_connectivity_config()
    validate_hermes_shadow_config(connectivity_config)
    links = load_runtime_link_config()
    engine = create_database_engine()
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            apollo = build_apollo_components(
                api_key=connectivity_config.apollo_api_key.get_secret_value(),
                client=client,
            )
            instantly = HttpInstantlyProvider(
                api_key=connectivity_config.instantly_api_key.get_secret_value(),
                client=client,
            )
            composition = build_runtime_execution_composition(
                engine=engine,
                runtime_config=runtime_config,
                connectivity_config=connectivity_config,
                links=links,
                apollo=apollo,
                instantly_provider=instantly,
                clock=lambda: dt.datetime.now(dt.UTC),
            )
            return composition.runner.run_once(
                RuntimeRunRequest(
                    owner_ref=_owner_ref(),
                    allow_qa_provider_mutations=allow_qa_provider_mutations,
                )
            )
    finally:
        engine.dispose()


__all__ = [
    "RuntimeExecutionComposition",
    "RuntimeExecutionConfigurationError",
    "RuntimeLinkConfiguration",
    "build_runtime_execution_composition",
    "execute_runtime_run_once",
    "load_runtime_link_config",
]
