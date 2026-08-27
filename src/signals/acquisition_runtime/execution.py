"""Fail-closed environment composition for one acquisition runtime invocation."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol
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
from signals.acquisition_connectivity.contracts import (
    AcquisitionConnectivityConfig,
    ConnectivityErrorCode,
    ConnectivityFailure,
)
from signals.acquisition_connectivity.instantly import InstantlyConnectivityProbe
from signals.acquisition_runtime.composition import (
    AcquisitionDomainComposition,
    build_acquisition_domain_composition,
    runtime_qa_contact_profile_descriptor,
)
from signals.acquisition_runtime.config import load_runtime_config
from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeConfig,
    AcquisitionRuntimeStage,
    RuntimeActionResult,
    RuntimeCapabilityEvidence,
    RuntimeDependencyState,
    RuntimeHermesIdentityEvidence,
    RuntimeQaScope,
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
    SqlRuntimePolicyReadinessSource,
)
from signals.acquisition_runtime.store import AcquisitionRuntimeStore
from signals.acquisition_runtime.supervisor import (
    KIVOU_STAGE_COSTS,
    AcquisitionHermesSupervisor,
)
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
from signals.campaigns.runtime_webhook import (
    InstantlyWebhookRuntimeConfiguration,
    load_instantly_webhook_runtime_config,
)
from signals.compliance.contracts import SenderComplianceConfig
from signals.conversion.link import AttributionLinkBuilder
from signals.conversion.token import AttributionTokenKeyring
from signals.decision_engine.policy import semantic_fingerprint
from signals.persistence.database import create_database_engine
from signals.policy.contracts import PolicyControlSnapshot, Scope
from signals.policy.store import PolicyStore
from signals.supervisor.contracts import SupervisorLimits
from signals.supervisor.hermes import HermesSupervisorAdapter
from signals.supervisor.pin import load_hermes_pin
from signals.supervisor.runtime import HealthState, SupervisorSettings
from signals.supplier_discovery.contracts import SupplierTargetingConfig

_PUBLIC_APP_URL = "KIVOU_PUBLIC_APP_URL"
_ATTRIBUTION_KEY = "KIVOU_ATTRIBUTION_HMAC_KEY"
_ATTRIBUTION_KEY_VERSION = "KIVOU_ATTRIBUTION_HMAC_KEY_VERSION"
_APOLLO_LOCATION_BY_QA_COUNTRY = {
    "CH": "Switzerland",
    "FR": "France",
}


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
            or parsed.hostname != "staging.kivou.eu"
            or parsed.port is not None
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or self.public_app_url.rstrip("/") != "https://staging.kivou.eu"
            or len(self.attribution_hmac_key) < 16
            or not self.attribution_key_version
            or len(self.attribution_key_version) > 100
        ):
            raise RuntimeExecutionConfigurationError("LINKS_NOT_CONFIGURED")
        object.__setattr__(self, "public_app_url", self.public_app_url.rstrip("/"))


class DomainCompositionSurface:
    """Narrow structural surface used by the executable root."""

    handlers: Mapping[AcquisitionRuntimeStage, AcquisitionActionHandler]


class RuntimeDependencyProbe(Protocol):
    def check(
        self,
        *,
        observed_at: dt.datetime,
    ) -> tuple[RuntimeStageDependency, ...]: ...


class FailClosedRuntimeDependencyProbe:
    def check(
        self,
        *,
        observed_at: dt.datetime,
    ) -> tuple[RuntimeStageDependency, ...]:
        del observed_at
        return tuple(
            RuntimeStageDependency(
                stage=stage,
                status=RuntimeDependencyState.NOT_READY,
                reason_codes=("DEPENDENCY_PROBE_NOT_CONFIGURED",),
            )
            for stage in AcquisitionRuntimeStage
        )


class ProductionRuntimeDependencyProbe:
    """Read-only bounded probes; provider details never cross this boundary."""

    def __init__(
        self,
        *,
        apollo: ApolloComponents,
        instantly_provider: InstantlyProvider,
        connectivity: AcquisitionConnectivityConfig,
        hermes_runtime: object,
        webhook_configuration: InstantlyWebhookRuntimeConfiguration | None,
    ) -> None:
        self._apollo = apollo
        self._instantly = InstantlyConnectivityProbe(
            provider=instantly_provider,
            mailbox_readiness=InstantlyMailboxReadinessSource(
                instantly_provider,
                managed_airmail_sending_gaps=(
                    _managed_airmail_sending_gaps(connectivity)
                ),
            ),
        )
        self._connectivity = connectivity
        self._hermes = hermes_runtime
        self._webhook_ready = bool(
            webhook_configuration is not None
            and webhook_configuration.response_ingress_ready
            and webhook_configuration.provider_workspace_ref
            == connectivity.deployment.instantly_workspace_ref
        )

    def check(
        self,
        *,
        observed_at: dt.datetime,
    ) -> tuple[RuntimeStageDependency, ...]:
        observed_at = observed_at.astimezone(dt.UTC)
        apollo_reason: str | None = None
        instantly_reason: str | None = None
        hermes_reason: str | None = None
        try:
            self._apollo.identity.check()
        except Exception:  # noqa: BLE001 - provider detail is secret/private
            apollo_reason = "APOLLO_DEPENDENCY_NOT_READY"
        try:
            self._instantly.check(
                self._connectivity.deployment,
                observed_at=observed_at,
            )
        except ConnectivityFailure as error:
            instantly_reason = (
                "MAILBOX_DEPENDENCY_NOT_READY"
                if error.code is ConnectivityErrorCode.MAILBOX_NOT_READY
                else "INSTANTLY_DEPENDENCY_NOT_READY"
            )
        except Exception:  # noqa: BLE001 - provider detail is secret/private
            instantly_reason = "INSTANTLY_DEPENDENCY_NOT_READY"
        try:
            health = self._hermes.health()
            pin = load_hermes_pin()
            if (
                health.state is not HealthState.AVAILABLE
                or health.hermes_version != pin.version
                or health.source_commit != pin.commit
                or health.executable_tools != ()
            ):
                hermes_reason = "HERMES_DEPENDENCY_NOT_READY"
        except Exception:  # noqa: BLE001 - provider detail is secret/private
            hermes_reason = "HERMES_DEPENDENCY_NOT_READY"

        apollo_stages = {
            AcquisitionRuntimeStage.SUPPLIER_DISCOVERY,
            AcquisitionRuntimeStage.CONTACT_DISCOVERY,
            AcquisitionRuntimeStage.COMPANY_RESEARCH,
        }
        instantly_stages = {
            AcquisitionRuntimeStage.CAMPAIGN,
            AcquisitionRuntimeStage.PROVIDER_HANDOFF,
        }
        webhook_stages = {
            AcquisitionRuntimeStage.RESPONSE,
            AcquisitionRuntimeStage.ATTRIBUTION_CONVERSION,
        }
        dependencies: list[RuntimeStageDependency] = []
        for stage in AcquisitionRuntimeStage:
            reasons = [value for value in (hermes_reason,) if value is not None]
            if stage in apollo_stages and apollo_reason is not None:
                reasons.append(apollo_reason)
            if stage in instantly_stages and instantly_reason is not None:
                reasons.append(instantly_reason)
            if stage in webhook_stages and not self._webhook_ready:
                reasons.append("WEBHOOK_INGRESS_NOT_READY")
            dependencies.append(
                RuntimeStageDependency(
                    stage=stage,
                    status=(
                        RuntimeDependencyState.NOT_READY
                        if reasons
                        else RuntimeDependencyState.READY
                    ),
                    reason_codes=tuple(dict.fromkeys(reasons)),
                )
            )
        return tuple(dependencies)


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


def _exact_scope(
    control: PolicyControlSnapshot,
    qa_scope: RuntimeQaScope,
) -> Scope:
    if not (
        len(control.allowed_countries) == 1
        and len(control.allowed_languages) == 1
        and len(control.allowed_wedges) == 1
        and control.allowed_countries[0] in {"CH", "FR"}
        and control.allowed_languages[0] in {"fr", "en"}
        and control.allowed_countries[0] == qa_scope.country
        and control.allowed_languages[0] == qa_scope.language
        and control.allowed_wedges[0] == qa_scope.wedge
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


def _managed_airmail_sending_gaps(
    connectivity: AcquisitionConnectivityConfig,
) -> dict[str, int]:
    return {
        str(binding.provider_account_id).casefold(): gap
        for binding in connectivity.deployment.mailboxes
        if (gap := binding.managed_airmail_sending_gap_minutes) is not None
    }


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
                    "managed_airmail_sending_gap_minutes": (
                        binding.managed_airmail_sending_gap_minutes
                    ),
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
    webhook_configuration: InstantlyWebhookRuntimeConfiguration,
    sender: SenderComplianceConfig,
    campaign: CampaignDeploymentConfig,
    supplier_targeting: SupplierTargetingConfig,
    registry_identity: str,
) -> str:
    return semantic_fingerprint(
        {
            "kind": "acquisition-runtime-execution-config-v3",
            "runtime": runtime_config.deployment.model_dump(mode="json"),
            "connectivity": connectivity_config.deployment.model_dump(mode="json"),
            "public_app_url": links.public_app_url,
            "attribution_key_version": links.attribution_key_version,
            "webhook_workspace_ref": webhook_configuration.provider_workspace_ref,
            "webhook_fingerprint_key_versions": sorted(
                webhook_configuration.fingerprint_keyring.keys
            ),
            "suppression_key_versions": sorted(
                webhook_configuration.suppression_keyring.keys
            ),
            "response_source_key_versions": sorted(
                webhook_configuration.response_source_keyring.keys
            ),
            "response_content_key_versions": sorted(
                webhook_configuration.response_content_keyring.keys
            ),
            "sender_config_fingerprint": sender.config_fingerprint,
            "campaign": campaign.model_dump(mode="json"),
            "supplier_targeting": supplier_targeting.model_dump(mode="json"),
            "contact_profile": runtime_qa_contact_profile_descriptor(),
            "registry_identity": registry_identity,
        }
    )


def _runtime_capability(
    registry: AcquisitionActionRegistry,
    *,
    dependencies: tuple[RuntimeStageDependency, ...],
) -> RuntimeCapabilityEvidence:
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
        dependencies=dependencies,
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
    webhook_configuration: InstantlyWebhookRuntimeConfiguration,
    clock: Callable[[], dt.datetime],
    client: httpx.Client | None = None,
    apollo: ApolloComponents | None = None,
    instantly_provider: InstantlyProvider | None = None,
    hermes_runtime: object | None = None,
    dependency_probe: RuntimeDependencyProbe | None = None,
    domain_builder: Callable[..., AcquisitionDomainComposition] = (
        build_acquisition_domain_composition
    ),
) -> RuntimeExecutionComposition:
    """Compose all real boundaries; construction itself performs no provider I/O."""

    now = clock()
    if now.tzinfo is None or now.utcoffset() is None:
        raise RuntimeExecutionConfigurationError("CLOCK_NOT_CONFIGURED")
    observed_at = now.astimezone(dt.UTC)
    if len(runtime_config.deployment.allowed_opportunity_keys) != 1:
        raise RuntimeExecutionConfigurationError("QA_SIGNAL_SCOPE_NOT_EXACT")
    if runtime_config.deployment.limits.maximum_cycle_cost < sum(
        KIVOU_STAGE_COSTS.values()
    ):
        raise RuntimeExecutionConfigurationError(
            "RUNTIME_RECOVERY_COST_ENVELOPE_TOO_SMALL"
        )
    if (
        not webhook_configuration.response_ingress_ready
        or webhook_configuration.provider_workspace_ref
        != connectivity_config.deployment.instantly_workspace_ref
    ):
        raise RuntimeExecutionConfigurationError("WEBHOOK_INGRESS_NOT_CONFIGURED")
    control = PolicyStore(engine).get_effective_control(observed_at)
    scope = _exact_scope(control, runtime_config.deployment.qa_scope)
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
    suppression_keyring = webhook_configuration.suppression_keyring
    link_builder = AttributionLinkBuilder(
        public_site_url=links.public_app_url,
        keyring=AttributionTokenKeyring(
            current_key_version=links.attribution_key_version,
            keys={links.attribution_key_version: links.attribution_hmac_key},
        ),
    )
    supplier_location = _APOLLO_LOCATION_BY_QA_COUNTRY.get(scope.country)
    if supplier_location is None:
        raise RuntimeExecutionConfigurationError(
            "SUPPLIER_TARGETING_COUNTRY_UNSUPPORTED"
        )
    targeting = SupplierTargetingConfig(
        organization_locations=(supplier_location,),
        max_pages=1,
        per_page=1,
        candidate_cap=1,
    )
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
        webhook_configuration=webhook_configuration,
        sender=sender_config,
        campaign=campaign_deployment,
        supplier_targeting=targeting,
        registry_identity=empty_registry.identity,
    )
    dependencies = (dependency_probe or FailClosedRuntimeDependencyProbe()).check(
        observed_at=observed_at,
    )
    runtime_revision = f"runtime-{config_fingerprint[:32]}"
    authorization_factory = LiveRuntimePolicyAuthorizationFactory(
        engine,
        runtime_revision=runtime_revision,
        qa_signal_ref=(
            "procurement-opportunity:"
            + runtime_config.deployment.allowed_opportunity_keys[0]
        ),
        qa_scope=runtime_config.deployment.qa_scope,
        readiness=SqlRuntimePolicyReadinessSource(
            engine,
            dependencies=dependencies,
        ),
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
            managed_airmail_sending_gaps=(
                _managed_airmail_sending_gaps(connectivity_config)
            ),
        ),
        attribution_link_builder=link_builder,
        clock=clock,
    )
    registry = AcquisitionActionRegistry(domain.handlers)
    if registry.identity != empty_registry.identity:
        raise RuntimeExecutionConfigurationError("REGISTRY_IDENTITY_MISMATCH")
    supervisor_runtime = hermes_runtime or _default_hermes_runtime(connectivity_config)
    supervisor = AcquisitionHermesSupervisor(
        supervisor_runtime,
        registry=registry,
    )
    capability = _runtime_capability(registry, dependencies=dependencies)
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


def execute_runtime_dependency_check(
    *,
    clock: Callable[[], dt.datetime] | None = None,
) -> tuple[RuntimeStageDependency, ...]:
    """Run only the fresh, read-only production dependency probes."""

    connectivity = load_connectivity_config()
    validate_hermes_shadow_config(connectivity)
    webhook_configuration = load_instantly_webhook_runtime_config(required=True)
    if webhook_configuration is None:
        raise RuntimeExecutionConfigurationError("WEBHOOK_NOT_CONFIGURED")
    observed_at = (clock or (lambda: dt.datetime.now(dt.UTC)))()
    with httpx.Client(timeout=10.0, follow_redirects=False) as client:
        apollo = build_apollo_components(
            api_key=connectivity.apollo_api_key.get_secret_value(),
            client=client,
        )
        instantly = HttpInstantlyProvider(
            api_key=connectivity.instantly_api_key.get_secret_value(),
            client=client,
        )
        hermes = _default_hermes_runtime(connectivity)
        return ProductionRuntimeDependencyProbe(
            apollo=apollo,
            instantly_provider=instantly,
            connectivity=connectivity,
            hermes_runtime=hermes,
            webhook_configuration=webhook_configuration,
        ).check(observed_at=observed_at)


def execute_runtime_run_once(
    *,
    allow_qa_provider_mutations: bool,
) -> RuntimeRunResult:
    runtime_config = load_runtime_config()
    connectivity_config = load_connectivity_config()
    validate_hermes_shadow_config(connectivity_config)
    links = load_runtime_link_config()
    webhook_configuration = load_instantly_webhook_runtime_config(required=True)
    assert webhook_configuration is not None
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
            hermes = _default_hermes_runtime(connectivity_config)
            composition = build_runtime_execution_composition(
                engine=engine,
                runtime_config=runtime_config,
                connectivity_config=connectivity_config,
                links=links,
                webhook_configuration=webhook_configuration,
                apollo=apollo,
                instantly_provider=instantly,
                hermes_runtime=hermes,
                dependency_probe=ProductionRuntimeDependencyProbe(
                    apollo=apollo,
                    instantly_provider=instantly,
                    connectivity=connectivity_config,
                    hermes_runtime=hermes,
                    webhook_configuration=webhook_configuration,
                ),
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
    "execute_runtime_dependency_check",
    "execute_runtime_run_once",
    "load_runtime_link_config",
]
