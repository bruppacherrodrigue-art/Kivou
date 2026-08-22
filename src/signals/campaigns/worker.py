"""Explicit campaign worker primitives; importing this module starts no loop."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

import sqlalchemy as sa

from signals.campaigns.contracts import (
    CampaignDeploymentConfig,
    CampaignInputChanged,
    ProviderOperationKind,
    ProviderOperationState,
)
from signals.campaigns.envelope import EnvelopeInput, build_envelope
from signals.campaigns.instantly import (
    InstantlyErrorCode,
    InstantlyProvider,
    InstantlyProviderError,
    build_provider_campaign_config,
    provider_campaign_config_fingerprint,
    provider_campaign_configs_match,
)
from signals.campaigns.service import CampaignService
from signals.campaigns.store import CampaignStore
from signals.decision_engine.policy import semantic_fingerprint
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_contact,
    acquisition_personalization_artifact,
    acquisition_provider_operation,
)


class SendAuthorization(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    UNAUTHORIZED = "UNAUTHORIZED"


def classify_email_sent(
    *,
    step: int,
    occurred_at: dt.datetime,
    due_at: dt.datetime | None,
    deadline: dt.datetime,
) -> tuple[SendAuthorization, str | None]:
    """Preserve provider truth while separately recording authorization."""
    if step == 1:
        if (due_at is not None and occurred_at < due_at) or occurred_at >= deadline:
            return (
                SendAuthorization.UNAUTHORIZED,
                "STEP1_SENT_OUTSIDE_AUTHORIZED_WINDOW",
            )
        return SendAuthorization.AUTHORIZED, None
    if step != 2 or due_at is None:
        return SendAuthorization.UNAUTHORIZED, "PROVIDER_STEP_UNRESOLVED"
    if occurred_at < due_at:
        return SendAuthorization.UNAUTHORIZED, "STEP2_SENT_BEFORE_AUTHORIZED_WINDOW"
    if occurred_at >= deadline:
        return SendAuthorization.UNAUTHORIZED, "STEP2_SENT_OUTSIDE_AUTHORIZED_WINDOW"
    return SendAuthorization.AUTHORIZED, None


class CampaignWorker:
    """Explicitly invoked saga worker. Construction/import performs no provider I/O."""

    def __init__(
        self,
        engine: sa.Engine,
        *,
        provider: InstantlyProvider,
        campaign_service: CampaignService,
        deployment: CampaignDeploymentConfig,
        worker_ref: str,
    ) -> None:
        self._engine = engine
        self._provider = provider
        self._service = campaign_service
        self._deployment = deployment
        self._worker_ref = worker_ref
        self._store = CampaignStore(engine)

    def process(self, operation_ref: str, now: dt.datetime) -> ProviderOperationState:
        existing = self._store.get_operation(operation_ref)
        if existing.state is ProviderOperationState.CONFIRMED:
            return existing.state
        if existing.state is ProviderOperationState.RECONCILE_REQUIRED:
            return self._reconcile(existing, now)
        claimed = self._store.claim_operation(
            operation_ref,
            worker_ref=self._worker_ref,
            now=now,
            lease_seconds=60,
        )
        if (
            claimed.state is not ProviderOperationState.IN_FLIGHT
            or claimed.lease_owner != self._worker_ref
        ):
            return claimed.state
        if not self._dependencies_confirmed(claimed.kind, claimed.campaign_ref):
            self._store.set_operation_state(
                operation_ref,
                ProviderOperationState.PLANNED,
                now=now,
                error_code="DEPENDENCY_NOT_CONFIRMED",
            )
            return ProviderOperationState.PLANNED
        remote_attempted = False
        try:
            if claimed.kind is ProviderOperationKind.CREATE_CAMPAIGN:
                self._service.require_provider_mutation(
                    claimed.kind,
                    claimed.campaign_ref,
                    member_ref=None,
                    captured_at=now,
                )
                campaign, _, config = self._context(claimed.campaign_ref)
                remote_attempted = True
                remote = self._provider.create_campaign(
                    name=campaign["provider_campaign_name"], provider_config=config
                )
                readback = self._provider.get_campaign(remote.provider_campaign_id)
                if (
                    remote.name != campaign["provider_campaign_name"]
                    or readback.provider_campaign_id != remote.provider_campaign_id
                    or readback.name != campaign["provider_campaign_name"]
                    or str(readback.status).lower() not in {"draft", "paused", "0", "2"}
                    or not provider_campaign_configs_match(
                        readback.normalized_config, config
                    )
                ):
                    raise InstantlyProviderError(
                        InstantlyErrorCode.REMOTE_STATE_CONFLICT,
                        reconciliation_required=True,
                    )
                self._service.require_provider_mutation(
                    claimed.kind,
                    claimed.campaign_ref,
                    member_ref=None,
                    captured_at=now,
                )
                self._store.bind_provider_campaign(
                    claimed.campaign_ref,
                    provider_campaign_id=remote.provider_campaign_id,
                    current_config_fingerprint=None,
                    now=now,
                )
                result_fp = semantic_fingerprint(
                    {
                        "kind": "provider-campaign-result-v1",
                        "provider_campaign_id": remote.provider_campaign_id,
                        "name": remote.name,
                    }
                )
                self._store.set_operation_state(
                    operation_ref,
                    ProviderOperationState.CONFIRMED,
                    now=now,
                    provider_identity=remote.provider_campaign_id,
                    provider_result_fingerprint=result_fp,
                )
            elif claimed.kind is ProviderOperationKind.CONFIGURE_CAMPAIGN:
                self._service.require_provider_mutation(
                    claimed.kind,
                    claimed.campaign_ref,
                    member_ref=None,
                    captured_at=now,
                )
                campaign, _, config = self._context(claimed.campaign_ref)
                provider_id = campaign["provider_campaign_id"]
                remote_attempted = True
                self._provider.configure_campaign(provider_id, provider_config=config)
                readback = self._provider.get_campaign(provider_id)
                if not provider_campaign_configs_match(
                    readback.normalized_config, config
                ):
                    raise RuntimeError("provider campaign readback conflict")
                self._service.require_provider_mutation(
                    claimed.kind,
                    claimed.campaign_ref,
                    member_ref=None,
                    captured_at=now,
                )
                self._store.bind_provider_campaign(
                    claimed.campaign_ref,
                    provider_campaign_id=provider_id,
                    current_config_fingerprint=campaign[
                        "desired_provider_config_fingerprint"
                    ],
                    now=now,
                )
                self._store.set_operation_state(
                    operation_ref,
                    ProviderOperationState.CONFIRMED,
                    now=now,
                    provider_identity=provider_id,
                    provider_result_fingerprint=campaign[
                        "desired_provider_config_fingerprint"
                    ],
                )
            elif claimed.kind is ProviderOperationKind.ADD_LEAD:
                self._service.require_provider_mutation(
                    claimed.kind,
                    claimed.campaign_ref,
                    member_ref=claimed.member_ref,
                    captured_at=now,
                )
                campaign, member, _ = self._context(
                    claimed.campaign_ref, member_ref=claimed.member_ref
                )
                if member is None or campaign["lifecycle"] != "BUILDING":
                    raise RuntimeError("member cannot be added to non-BUILDING campaign")
                remote_campaign = self._provider.get_campaign(
                    campaign["provider_campaign_id"]
                )
                _, _, expected_config = self._context(
                    claimed.campaign_ref, member_ref=claimed.member_ref
                )
                if (
                    str(remote_campaign.status).lower() not in {"draft", "paused", "0", "2"}
                    or not provider_campaign_configs_match(
                        remote_campaign.normalized_config, expected_config
                    )
                ):
                    raise CampaignInputChanged(
                        "provider campaign is not exact and non-sending before ADD_LEAD"
                    )
                lead = self._lead_payload(member, campaign)
                remote_attempted = True
                raw = self._provider.create_lead_or_batch(
                    provider_campaign_id=campaign["provider_campaign_id"], leads=(lead,)
                )
                if not isinstance(raw, dict) or not raw.get("id"):
                    raise RuntimeError("provider lead response is malformed")
                provider_lead_id = str(raw["id"])
                readback = self._provider.get_lead(provider_lead_id)
                self._require_exact_lead_binding(
                    readback,
                    provider_campaign_id=campaign["provider_campaign_id"],
                    expected=lead,
                )
                binding = semantic_fingerprint(
                    {
                        "kind": "provider-lead-binding-v1",
                        "campaign_ref": claimed.campaign_ref,
                        "member_ref": claimed.member_ref,
                        "provider_campaign_id": campaign["provider_campaign_id"],
                        "provider_lead_id": provider_lead_id,
                        "custom_variables": lead["custom_variables"],
                    }
                )
                try:
                    self._service.require_provider_mutation(
                        claimed.kind,
                        claimed.campaign_ref,
                        member_ref=claimed.member_ref,
                        captured_at=now,
                    )
                except CampaignInputChanged:
                    self._service.stop_after_provider_exposure(
                        claimed.campaign_ref,
                        claimed.member_ref,
                        provider_lead_id=provider_lead_id,
                        binding_fingerprint=binding,
                        captured_at=now,
                    )
                    self._store.set_operation_state(
                        operation_ref,
                        ProviderOperationState.CONFIRMED,
                        now=now,
                        provider_identity=provider_lead_id,
                        provider_result_fingerprint=binding,
                        error_code="POST_PROVIDER_AUTHORIZATION_CHANGED",
                    )
                    return ProviderOperationState.CONFIRMED
                self._store.bind_provider_lead(
                    claimed.member_ref,
                    provider_lead_id=provider_lead_id,
                    binding_fingerprint=binding,
                    now=now,
                )
                self._store.set_operation_state(
                    operation_ref,
                    ProviderOperationState.CONFIRMED,
                    now=now,
                    provider_identity=provider_lead_id,
                    provider_result_fingerprint=binding,
                )
            elif claimed.kind is ProviderOperationKind.ACTIVATE_CAMPAIGN:
                campaign = self._store.get_campaign(claimed.campaign_ref)
                step_2_resume = campaign["lifecycle"] == "PAUSED"
                if step_2_resume:
                    self._service.require_step_2_safety(
                        claimed.campaign_ref, captured_at=now
                    )
                else:
                    self._service.require_activation(
                        claimed.campaign_ref, captured_at=now
                    )
                remote_attempted = True
                remote = self._provider.activate_campaign(campaign["provider_campaign_id"])
                if step_2_resume:
                    self._service.require_step_2_safety(
                        claimed.campaign_ref, captured_at=now
                    )
                else:
                    self._service.require_activation(
                        claimed.campaign_ref, captured_at=now
                    )
                with self._engine.begin() as connection:
                    connection.execute(
                        sa.update(acquisition_campaign)
                        .where(acquisition_campaign.c.campaign_ref == claimed.campaign_ref)
                        .values(lifecycle="ACTIVE", updated_at=now)
                    )
                self._store.set_operation_state(
                    operation_ref,
                    ProviderOperationState.CONFIRMED,
                    now=now,
                    provider_identity=remote.provider_identity,
                    provider_result_fingerprint=semantic_fingerprint(
                        {"kind": "provider-activation-v1", "status": remote.status}
                    ),
                )
            elif claimed.kind is ProviderOperationKind.PAUSE_CAMPAIGN:
                campaign = self._store.get_campaign(claimed.campaign_ref)
                remote_attempted = True
                remote = self._provider.pause_campaign(campaign["provider_campaign_id"])
                readback = self._provider.get_campaign(campaign["provider_campaign_id"])
                if (
                    str(remote.status).lower() not in {"paused", "2"}
                    or str(readback.status).lower() not in {"paused", "2"}
                ):
                    raise InstantlyProviderError(
                        InstantlyErrorCode.REMOTE_STATE_CONFLICT,
                        reconciliation_required=True,
                    )
                with self._engine.begin() as connection:
                    connection.execute(
                        sa.update(acquisition_campaign)
                        .where(acquisition_campaign.c.campaign_ref == claimed.campaign_ref)
                        .values(lifecycle="PAUSED", updated_at=now)
                    )
                self._store.set_operation_state(
                    operation_ref,
                    ProviderOperationState.CONFIRMED,
                    now=now,
                    provider_identity=remote.provider_identity,
                    provider_result_fingerprint=semantic_fingerprint(
                        {"kind": "provider-pause-v1", "status": remote.status}
                    ),
                )
            elif claimed.kind is ProviderOperationKind.PAUSE_LEAD:
                if claimed.member_ref is None:
                    raise RuntimeError("PAUSE_LEAD requires a member")
                _, member, _ = self._context(
                    claimed.campaign_ref, member_ref=claimed.member_ref
                )
                remote_attempted = True
                result = self._provider.pause_lead(member["provider_lead_id"])
                readback = self._provider.get_lead(member["provider_lead_id"])
                result_status = result.get("status") if isinstance(result, dict) else None
                readback_status = (
                    readback.get("status") if isinstance(readback, dict) else None
                )
                safe_statuses = {2, 3, -1, -2, -3}
                if (
                    result_status not in safe_statuses
                    or readback_status not in safe_statuses
                ):
                    raise InstantlyProviderError(
                        InstantlyErrorCode.REMOTE_STATE_CONFLICT,
                        reconciliation_required=True,
                    )
                self._store.set_operation_state(
                    operation_ref,
                    ProviderOperationState.CONFIRMED,
                    now=now,
                    provider_identity=member["provider_lead_id"],
                    provider_result_fingerprint=semantic_fingerprint(
                        {
                            "kind": "provider-lead-pause-v1",
                            "result_status": result_status,
                            "readback_status": readback_status,
                        }
                    ),
                )
            else:
                raise RuntimeError("operation kind is not implemented by the scheduling worker")
        except InstantlyProviderError as error:
            unknown_after_mutation = remote_attempted and error.code in {
                InstantlyErrorCode.TIMEOUT,
                InstantlyErrorCode.NETWORK,
                InstantlyErrorCode.SERVER_ERROR,
                InstantlyErrorCode.MALFORMED_RESPONSE,
            }
            terminal = error.code in {
                InstantlyErrorCode.AUTH,
                InstantlyErrorCode.PERMISSION,
                InstantlyErrorCode.PLAN_REQUIRED,
                InstantlyErrorCode.CLIENT_CONTRACT_ERROR,
                InstantlyErrorCode.REMOTE_STATE_CONFLICT,
            }
            if error.reconciliation_required or unknown_after_mutation:
                state = ProviderOperationState.RECONCILE_REQUIRED
            elif terminal:
                state = ProviderOperationState.TERMINAL_FAILED
            else:
                state = ProviderOperationState.RETRYABLE_FAILED
            retry_after = (
                now + dt.timedelta(seconds=error.retry_after_seconds)
                if state is ProviderOperationState.RETRYABLE_FAILED
                and error.retry_after_seconds is not None
                else None
            )
            self._store.set_operation_state(
                operation_ref,
                state,
                now=now,
                error_code=error.code.value,
                retry_after=retry_after,
            )
            return state
        except CampaignInputChanged:
            if (
                not remote_attempted
                and claimed.kind is ProviderOperationKind.ADD_LEAD
                and claimed.member_ref is not None
            ):
                self._service.stop_before_provider_exposure(
                    claimed.campaign_ref,
                    claimed.member_ref,
                    captured_at=now,
                )
            state = (
                ProviderOperationState.RECONCILE_REQUIRED
                if remote_attempted
                else ProviderOperationState.TERMINAL_FAILED
            )
            self._store.set_operation_state(
                operation_ref,
                state,
                now=now,
                error_code="CAMPAIGN_INPUT_CHANGED",
            )
            if remote_attempted and claimed.kind is ProviderOperationKind.ACTIVATE_CAMPAIGN:
                campaign = self._store.get_campaign(claimed.campaign_ref)
                self._store.plan_operation(
                    ProviderOperationKind.PAUSE_CAMPAIGN,
                    campaign_ref=claimed.campaign_ref,
                    member_ref=None,
                    desired_request_fingerprint=campaign[
                        "desired_provider_config_fingerprint"
                    ],
                    correlation_id=f"activation-drift:{claimed.campaign_ref}",
                    now=now,
                )
            raise
        except Exception:
            state = (
                ProviderOperationState.RECONCILE_REQUIRED
                if remote_attempted
                else ProviderOperationState.TERMINAL_FAILED
            )
            self._store.set_operation_state(
                operation_ref,
                state,
                now=now,
                error_code="REMOTE_STATE_CONFLICT",
            )
            raise
        return ProviderOperationState.CONFIRMED

    def plan_step_2_release(self, campaign_ref: str, now: dt.datetime) -> str:
        """Create durable Step-2 release work only after the live safety check."""
        self._service.require_step_2_safety(campaign_ref, captured_at=now)
        campaign, _, config = self._context(campaign_ref)
        remote = self._provider.get_campaign(campaign["provider_campaign_id"])
        if (
            str(remote.status).lower() not in {"paused", "2"}
            or not provider_campaign_configs_match(remote.normalized_config, config)
        ):
            raise CampaignInputChanged(
                "provider campaign is not exactly paused for Step 2 release"
            )
        with self._engine.connect() as connection:
            timing_fingerprints = tuple(
                connection.execute(
                    sa.select(
                        acquisition_campaign_member.c.sequence_timing_fingerprint
                    )
                    .where(
                        acquisition_campaign_member.c.campaign_ref == campaign_ref,
                        acquisition_campaign_member.c.sequence_state
                        == "WAITING_STEP2",
                    )
                    .order_by(acquisition_campaign_member.c.member_ref)
                ).scalars()
            )
        operation = self._store.plan_operation(
            ProviderOperationKind.ACTIVATE_CAMPAIGN,
            campaign_ref=campaign_ref,
            member_ref=None,
            desired_request_fingerprint=semantic_fingerprint(
                {
                    "kind": "step2-live-safety-release-v1",
                    "campaign_ref": campaign_ref,
                    "sequence_timing_fingerprints": timing_fingerprints,
                    "provider_config_fingerprint": campaign[
                        "desired_provider_config_fingerprint"
                    ],
                }
            ),
            correlation_id=f"step2-live-safety:{campaign_ref}",
            now=now,
        )
        return operation.operation_ref

    def _reconcile(self, operation, now: dt.datetime) -> ProviderOperationState:
        if operation.kind is ProviderOperationKind.CREATE_CAMPAIGN:
            campaign = self._store.get_campaign(operation.campaign_ref)
            matches = tuple(
                item
                for item in self._provider.list_campaigns(
                    search=campaign["provider_campaign_name"]
                )
                if item.name == campaign["provider_campaign_name"]
            )
            if len(matches) == 1:
                candidate = matches[0]
                remote = self._provider.get_campaign(candidate.provider_campaign_id)
                _, _, config = self._context(operation.campaign_ref)
                if (
                    remote.provider_campaign_id != candidate.provider_campaign_id
                    or remote.name != campaign["provider_campaign_name"]
                    or str(remote.status).lower() not in {"draft", "paused", "0", "2"}
                    or not provider_campaign_configs_match(
                        remote.normalized_config, config
                    )
                ):
                    self._store.set_operation_state(
                        operation.operation_ref,
                        ProviderOperationState.TERMINAL_FAILED,
                        now=now,
                        error_code="REMOTE_STATE_CONFLICT",
                    )
                    return ProviderOperationState.TERMINAL_FAILED
                self._store.bind_provider_campaign(
                    operation.campaign_ref,
                    provider_campaign_id=remote.provider_campaign_id,
                    current_config_fingerprint=None,
                    now=now,
                )
                self._store.set_operation_state(
                    operation.operation_ref,
                    ProviderOperationState.CONFIRMED,
                    now=now,
                    provider_identity=remote.provider_campaign_id,
                    provider_result_fingerprint=semantic_fingerprint(
                        {
                            "kind": "provider-campaign-reconciliation-v1",
                            "provider_campaign_id": remote.provider_campaign_id,
                        }
                    ),
                )
                return ProviderOperationState.CONFIRMED
            if len(matches) == 0:
                self._store.set_operation_state(
                    operation.operation_ref,
                    ProviderOperationState.RETRYABLE_FAILED,
                    now=now,
                    error_code="RECONCILIATION_PROVED_ABSENCE",
                )
                return ProviderOperationState.RETRYABLE_FAILED
        elif operation.kind is ProviderOperationKind.CONFIGURE_CAMPAIGN:
            campaign, _, config = self._context(operation.campaign_ref)
            remote = self._provider.get_campaign(campaign["provider_campaign_id"])
            if provider_campaign_configs_match(remote.normalized_config, config):
                self._store.bind_provider_campaign(
                    operation.campaign_ref,
                    provider_campaign_id=campaign["provider_campaign_id"],
                    current_config_fingerprint=campaign[
                        "desired_provider_config_fingerprint"
                    ],
                    now=now,
                )
                self._store.set_operation_state(
                    operation.operation_ref,
                    ProviderOperationState.CONFIRMED,
                    now=now,
                    provider_identity=campaign["provider_campaign_id"],
                    provider_result_fingerprint=campaign[
                        "desired_provider_config_fingerprint"
                    ],
                )
                return ProviderOperationState.CONFIRMED
        elif operation.kind is ProviderOperationKind.ADD_LEAD:
            if operation.member_ref is None:
                return ProviderOperationState.TERMINAL_FAILED
            campaign, member, _ = self._context(
                operation.campaign_ref, member_ref=operation.member_ref
            )
            lead_payload = self._lead_payload(member, campaign)
            remote_campaign = self._provider.get_campaign(
                campaign["provider_campaign_id"]
            )
            _, _, expected_config = self._context(
                operation.campaign_ref, member_ref=operation.member_ref
            )
            provider_non_sending = bool(
                str(remote_campaign.status).lower() in {"draft", "paused", "0", "2"}
                and provider_campaign_configs_match(
                    remote_campaign.normalized_config, expected_config
                )
            )
            response = self._provider.list_leads(
                provider_campaign_id=campaign["provider_campaign_id"]
            )
            items = response.get("items", []) if isinstance(response, dict) else []
            matches = [
                item
                for item in items
                if isinstance(item, dict)
                and self._lead_binding_matches(
                    item,
                    provider_campaign_id=campaign["provider_campaign_id"],
                    expected=lead_payload,
                )
            ]
            if len(matches) == 1 and matches[0].get("id"):
                provider_lead_id = str(matches[0]["id"])
                binding = semantic_fingerprint(
                    {
                        "kind": "provider-lead-binding-v1",
                        "campaign_ref": operation.campaign_ref,
                        "member_ref": operation.member_ref,
                        "provider_campaign_id": campaign["provider_campaign_id"],
                        "provider_lead_id": provider_lead_id,
                        "custom_variables": lead_payload["custom_variables"],
                    }
                )
                try:
                    self._service.require_provider_mutation(
                        operation.kind,
                        operation.campaign_ref,
                        member_ref=operation.member_ref,
                        captured_at=now,
                    )
                    if not provider_non_sending:
                        raise CampaignInputChanged(
                            "reconciled provider campaign is no longer non-sending"
                        )
                except CampaignInputChanged:
                    self._service.stop_after_provider_exposure(
                        operation.campaign_ref,
                        operation.member_ref,
                        provider_lead_id=provider_lead_id,
                        binding_fingerprint=binding,
                        captured_at=now,
                    )
                    self._store.set_operation_state(
                        operation.operation_ref,
                        ProviderOperationState.CONFIRMED,
                        now=now,
                        provider_identity=provider_lead_id,
                        provider_result_fingerprint=binding,
                        error_code="RECONCILED_PROVIDER_AUTHORIZATION_CHANGED",
                    )
                    return ProviderOperationState.CONFIRMED
                self._store.bind_provider_lead(
                    operation.member_ref,
                    provider_lead_id=provider_lead_id,
                    binding_fingerprint=binding,
                    now=now,
                )
                self._store.set_operation_state(
                    operation.operation_ref,
                    ProviderOperationState.CONFIRMED,
                    now=now,
                    provider_identity=provider_lead_id,
                    provider_result_fingerprint=binding,
                )
                return ProviderOperationState.CONFIRMED
            if not matches:
                self._store.set_operation_state(
                    operation.operation_ref,
                    ProviderOperationState.RETRYABLE_FAILED,
                    now=now,
                    error_code="RECONCILIATION_PROVED_ABSENCE",
                )
                return ProviderOperationState.RETRYABLE_FAILED
        elif operation.kind is ProviderOperationKind.ACTIVATE_CAMPAIGN:
            campaign, _, config = self._context(operation.campaign_ref)
            remote = self._provider.get_campaign(campaign["provider_campaign_id"])
            if str(remote.status).lower() in {
                "active",
                "1",
            } and provider_campaign_configs_match(remote.normalized_config, config):
                with self._engine.begin() as connection:
                    connection.execute(
                        sa.update(acquisition_campaign)
                        .where(
                            acquisition_campaign.c.campaign_ref == operation.campaign_ref
                        )
                        .values(lifecycle="ACTIVE", updated_at=now)
                    )
                self._store.set_operation_state(
                    operation.operation_ref,
                    ProviderOperationState.CONFIRMED,
                    now=now,
                    provider_identity=campaign["provider_campaign_id"],
                    provider_result_fingerprint=semantic_fingerprint(
                        {
                            "kind": "provider-activation-reconciliation-v1",
                            "status": remote.status,
                        }
                    ),
                )
                return ProviderOperationState.CONFIRMED
            if (
                str(remote.status).lower() in {"draft", "paused", "0", "2"}
                and provider_campaign_configs_match(remote.normalized_config, config)
            ):
                self._store.set_operation_state(
                    operation.operation_ref,
                    ProviderOperationState.RETRYABLE_FAILED,
                    now=now,
                    error_code="RECONCILIATION_PROVED_NOT_ACTIVATED",
                )
                return ProviderOperationState.RETRYABLE_FAILED
        elif operation.kind is ProviderOperationKind.PAUSE_CAMPAIGN:
            campaign = self._store.get_campaign(operation.campaign_ref)
            remote = self._provider.get_campaign(campaign["provider_campaign_id"])
            if str(remote.status).lower() in {"paused", "2"}:
                with self._engine.begin() as connection:
                    connection.execute(
                        sa.update(acquisition_campaign)
                        .where(
                            acquisition_campaign.c.campaign_ref
                            == operation.campaign_ref
                        )
                        .values(lifecycle="PAUSED", updated_at=now)
                    )
                self._store.set_operation_state(
                    operation.operation_ref,
                    ProviderOperationState.CONFIRMED,
                    now=now,
                    provider_identity=campaign["provider_campaign_id"],
                    provider_result_fingerprint=semantic_fingerprint(
                        {"kind": "provider-pause-reconciliation-v1", "status": remote.status}
                    ),
                )
                return ProviderOperationState.CONFIRMED
            if str(remote.status).lower() in {"active", "draft", "0", "1"}:
                self._store.set_operation_state(
                    operation.operation_ref,
                    ProviderOperationState.RETRYABLE_FAILED,
                    now=now,
                    error_code="RECONCILIATION_PROVED_NOT_PAUSED",
                )
                return ProviderOperationState.RETRYABLE_FAILED
        elif operation.kind is ProviderOperationKind.PAUSE_LEAD:
            if operation.member_ref is None:
                return ProviderOperationState.TERMINAL_FAILED
            _, member, _ = self._context(
                operation.campaign_ref, member_ref=operation.member_ref
            )
            remote = self._provider.get_lead(member["provider_lead_id"])
            status = remote.get("status") if isinstance(remote, dict) else None
            if status in {2, 3, -1, -2, -3}:
                self._store.set_operation_state(
                    operation.operation_ref,
                    ProviderOperationState.CONFIRMED,
                    now=now,
                    provider_identity=member["provider_lead_id"],
                    provider_result_fingerprint=semantic_fingerprint(
                        {"kind": "provider-lead-pause-reconciliation-v1", "status": status}
                    ),
                )
                return ProviderOperationState.CONFIRMED
            if status == 1:
                self._store.set_operation_state(
                    operation.operation_ref,
                    ProviderOperationState.RETRYABLE_FAILED,
                    now=now,
                    error_code="RECONCILIATION_PROVED_LEAD_SENDABLE",
                )
                return ProviderOperationState.RETRYABLE_FAILED
        self._store.set_operation_state(
            operation.operation_ref,
            ProviderOperationState.TERMINAL_FAILED,
            now=now,
            error_code="REMOTE_STATE_CONFLICT",
        )
        return ProviderOperationState.TERMINAL_FAILED

    def expire_authorization_windows(self, now: dt.datetime) -> tuple[int, int]:
        """Expire one-shot Step-1/Step-2 windows without rolling to another day."""
        with self._engine.begin() as connection:
            step_1_rows = connection.execute(
                sa.select(acquisition_campaign_member).where(
                    acquisition_campaign_member.c.execution_state == "QUEUED",
                    acquisition_campaign_member.c.sequence_state == "PENDING_STEP1",
                    acquisition_campaign_member.c.step_1_authorization_deadline <= now,
                )
            ).mappings().all()
            step_2_rows = connection.execute(
                sa.select(acquisition_campaign_member).where(
                    acquisition_campaign_member.c.execution_state == "SENT",
                    acquisition_campaign_member.c.sequence_state == "WAITING_STEP2",
                    acquisition_campaign_member.c.step_2_authorization_deadline <= now,
                )
            ).mappings().all()
            if step_1_rows:
                connection.execute(
                    sa.update(acquisition_campaign_member)
                    .where(
                        acquisition_campaign_member.c.member_ref.in_(
                            [row["member_ref"] for row in step_1_rows]
                        )
                    )
                    .values(
                        execution_state="FAILED",
                        sequence_state="FAILED",
                        reason_code="STEP1_WINDOW_EXPIRED",
                        updated_at=now,
                    )
                )
            if step_2_rows:
                connection.execute(
                    sa.update(acquisition_campaign_member)
                    .where(
                        acquisition_campaign_member.c.member_ref.in_(
                            [row["member_ref"] for row in step_2_rows]
                        )
                    )
                    .values(
                        sequence_state="FAILED",
                        reason_code="STEP2_WINDOW_EXPIRED",
                        updated_at=now,
                    )
                )
            affected_campaigns: set[str] = set()
            for row in step_1_rows:
                if row["provider_lead_id"]:
                    self._store.plan_operation_in_transaction(
                        connection,
                        ProviderOperationKind.PAUSE_LEAD,
                        campaign_ref=row["campaign_ref"],
                        member_ref=row["member_ref"],
                        desired_request_fingerprint=row["provider_binding_fingerprint"],
                        correlation_id=f"step1-window-expired:{row['member_ref']}",
                        now=now,
                    )
                affected_campaigns.add(row["campaign_ref"])
            affected_campaigns.update(row["campaign_ref"] for row in step_2_rows)
            for campaign_ref in affected_campaigns:
                desired_fingerprint = connection.scalar(
                    sa.select(acquisition_campaign.c.desired_provider_config_fingerprint).where(
                        acquisition_campaign.c.campaign_ref == campaign_ref
                    )
                )
                self._store.plan_operation_in_transaction(
                    connection,
                    ProviderOperationKind.PAUSE_CAMPAIGN,
                    campaign_ref=campaign_ref,
                    member_ref=None,
                    desired_request_fingerprint=desired_fingerprint,
                    correlation_id=f"sequence-window-expired:{campaign_ref}",
                    now=now,
                )
        return len(step_1_rows), len(step_2_rows)

    def _dependencies_confirmed(
        self, kind: ProviderOperationKind, campaign_ref: str
    ) -> bool:
        required: tuple[ProviderOperationKind, ...] = ()
        if kind is ProviderOperationKind.CONFIGURE_CAMPAIGN:
            required = (ProviderOperationKind.CREATE_CAMPAIGN,)
        elif kind is ProviderOperationKind.ADD_LEAD:
            required = (
                ProviderOperationKind.CREATE_CAMPAIGN,
                ProviderOperationKind.CONFIGURE_CAMPAIGN,
            )
        with self._engine.connect() as connection:
            for dependency in required:
                state = connection.scalar(
                    sa.select(acquisition_provider_operation.c.state).where(
                        acquisition_provider_operation.c.campaign_ref == campaign_ref,
                        acquisition_provider_operation.c.kind == dependency.value,
                    )
                )
                if state != ProviderOperationState.CONFIRMED.value:
                    return False
            if kind is ProviderOperationKind.ACTIVATE_CAMPAIGN:
                # Activation is deliberately planned in the same transaction
                # that seals/queues retained members.  Excluded members may
                # still have risk-reduction work in flight at that point; do
                # not claim activation until every such remote pause has a
                # durable confirmation.  A temporary dependency ordering must
                # never terminally poison the single deterministic ACTIVATE
                # operation.
                unconfirmed_risk_reduction = connection.scalar(
                    sa.select(sa.func.count())
                    .select_from(acquisition_provider_operation)
                    .where(
                        acquisition_provider_operation.c.campaign_ref
                        == campaign_ref,
                        acquisition_provider_operation.c.kind.in_(
                            (
                                ProviderOperationKind.PAUSE_LEAD.value,
                                ProviderOperationKind.PAUSE_CAMPAIGN.value,
                            )
                        ),
                        acquisition_provider_operation.c.state
                        != ProviderOperationState.CONFIRMED.value,
                    )
                )
                if int(unconfirmed_risk_reduction or 0) != 0:
                    return False
        return True

    def _context(self, campaign_ref: str, member_ref: str | None = None):
        with self._engine.connect() as connection:
            campaign = connection.execute(
                sa.select(acquisition_campaign).where(
                    acquisition_campaign.c.campaign_ref == campaign_ref
                )
            ).mappings().one()
            statement = sa.select(acquisition_campaign_member).where(
                acquisition_campaign_member.c.campaign_ref == campaign_ref
            )
            if member_ref is not None:
                statement = statement.where(
                    acquisition_campaign_member.c.member_ref == member_ref
                )
            member = connection.execute(statement).mappings().first()
            if member is None:
                raise RuntimeError("campaign has no reserved member")
        mailbox_refs = {
            row["mailbox_ref"]
            for row in connection_members(self._engine, campaign_ref)
        }
        if len(mailbox_refs) != 1:
            raise CampaignInputChanged("campaign mailbox binding is ambiguous")
        mailbox_ref = next(iter(mailbox_refs))
        mailbox = next(
            (
                entry
                for entry in self._deployment.mailbox_catalog.usable_entries
                if entry.mailbox_ref == mailbox_ref
            ),
            None,
        )
        if mailbox is None:
            raise CampaignInputChanged("campaign mailbox binding is unavailable")
        config = build_provider_campaign_config(
            step_1_execution_date=campaign["step_1_execution_date"],
            step_2_execution_date=campaign["step_2_execution_date"],
            timezone=campaign["timezone"],
            provider_account_id=mailbox.provider_account_id,
            daily_limit=min(3, mailbox.kivou_daily_cap),
        )
        if provider_campaign_config_fingerprint(campaign_ref, config) != campaign[
            "desired_provider_config_fingerprint"
        ]:
            raise CampaignInputChanged("provider campaign config fingerprint changed")
        return dict(campaign), dict(member), config

    def _lead_payload(
        self, member: dict[str, object], campaign: dict[str, object]
    ) -> dict[str, object]:
        with self._engine.connect() as connection:
            contact = connection.execute(
                sa.select(acquisition_contact.c.business_email).where(
                    acquisition_contact.c.contact_ref == member["contact_ref"]
                )
            ).one()
            artifact = connection.execute(
                sa.select(acquisition_personalization_artifact).where(
                    acquisition_personalization_artifact.c.personalization_artifact_id
                    == member["personalization_artifact_id"]
                )
            ).mappings().one()
        entries = tuple(
            entry
            for entry in self._deployment.footer_catalog.entries
            if entry.language == artifact["language"]
            and entry.sender_profile_ref == campaign["sender_profile_ref"]
        )
        if len(entries) != 1:
            raise CampaignInputChanged("exact campaign footer binding is unavailable")
        envelope = build_envelope(
            EnvelopeInput(
                language=artifact["language"],
                sender_profile_ref=campaign["sender_profile_ref"],
                subject=artifact["subject"],
                greeting=artifact["greeting"],
                body=artifact["body"],
                cta=artifact["cta"],
                attribution_url=self._service.attribution_url_for_member(
                    member, campaign
                ),
                catalog=self._deployment.footer_catalog,
            )
        )
        if envelope.envelope_fingerprint != member["envelope_fingerprint"]:
            raise CampaignInputChanged("provider envelope differs from authorized envelope")
        return {
            "email": contact.business_email,
            "custom_variables": {
                **envelope.custom_variables,
                "kivou_follow_up": envelope.follow_up_body,
                "kivou_member_ref": member["member_ref"],
            },
            "skip_if_in_workspace": True,
        }

    @staticmethod
    def _lead_binding_matches(
        value: object,
        *,
        provider_campaign_id: str,
        expected: dict[str, object],
    ) -> bool:
        if not isinstance(value, dict):
            return False
        campaign_id = value.get("campaign_id", value.get("campaign"))
        email = value.get("email")
        return bool(
            value.get("id")
            and campaign_id == provider_campaign_id
            and isinstance(email, str)
            and email.strip().casefold() == str(expected["email"]).strip().casefold()
            and value.get("custom_variables") == expected["custom_variables"]
        )

    @classmethod
    def _require_exact_lead_binding(
        cls,
        value: object,
        *,
        provider_campaign_id: str,
        expected: dict[str, object],
    ) -> None:
        if not cls._lead_binding_matches(
            value,
            provider_campaign_id=provider_campaign_id,
            expected=expected,
        ):
            raise CampaignInputChanged("provider lead binding does not match authorized copy")


def connection_members(engine: sa.Engine, campaign_ref: str) -> tuple[dict[str, object], ...]:
    """Load only safe member bindings needed to build provider campaign config."""
    with engine.connect() as connection:
        rows = connection.execute(
            sa.select(acquisition_campaign_member.c.mailbox_ref).where(
                acquisition_campaign_member.c.campaign_ref == campaign_ref
            )
        ).mappings().all()
    return tuple(dict(row) for row in rows)
