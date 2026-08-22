"""Transactional sealed-batch and provider-operation persistence."""

from __future__ import annotations

import contextlib
import datetime as dt
from collections.abc import Iterator
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from signals.campaigns.contracts import (
    BATCH_SEAL_POLICY_VERSION,
    CAMPAIGN_FACTORY_VERSION,
    CAMPAIGN_SEQUENCE_POLICY_VERSION,
    PACING_POLICY_VERSION,
    PROVIDER_OPERATION_MAX_ATTEMPTS,
    PROVIDER_OPERATION_VERSION,
    SEND_WINDOW_POLICY_VERSION,
    SEQUENCE_WINDOW_POLICY_VERSION,
    TRACKING_POLICY_VERSION,
    CampaignFactoryInput,
    CampaignIdempotencyConflict,
    CampaignInputChanged,
    CampaignMemberReservation,
    CampaignPacingExceeded,
    CampaignReservationResult,
    ProviderOperationKind,
    ProviderOperationRecord,
    ProviderOperationState,
)
from signals.campaigns.factory import CampaignFactory
from signals.decision_engine.policy import semantic_fingerprint
from signals.persistence.schema import (
    acquisition_campaign,
    acquisition_campaign_member,
    acquisition_provider_operation,
)


class CampaignStore:
    # One bounded PostgreSQL transaction lock serializes the v1 global/country/
    # wedge/mailbox/company counters as well as empty-group batch creation.
    # Initial volume is five/day, so correctness is preferred to speculative
    # sharding; SPEC-029 may replace this with partitioned allocation.
    _POSTGRES_RESERVATION_LOCK = 0x4B49564F5526026

    def __init__(self, engine: sa.Engine) -> None:
        self.engine = engine

    def propose_plan(self, factory_input: CampaignFactoryInput, *, at: dt.datetime):
        """Return the lowest open generation without reserving a member slot."""
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("plan time must be timezone-aware")
        probe = CampaignFactory().build(factory_input, batch_generation=1)
        with self._serialized() as connection:
            generation = connection.scalar(
                sa.select(acquisition_campaign.c.batch_generation)
                .where(
                    acquisition_campaign.c.campaign_group_key == probe.campaign_group_key,
                    acquisition_campaign.c.lifecycle == "BUILDING",
                    acquisition_campaign.c.membership_closed_at.is_(None),
                    acquisition_campaign.c.reserved_member_count
                    < acquisition_campaign.c.member_capacity,
                    sa.or_(
                        acquisition_campaign.c.membership_close_at.is_(None),
                        acquisition_campaign.c.membership_close_at > at,
                    ),
                )
                .order_by(acquisition_campaign.c.batch_generation)
                .limit(1)
            )
            if generation is None:
                maximum = connection.scalar(
                    sa.select(sa.func.max(acquisition_campaign.c.batch_generation)).where(
                        acquisition_campaign.c.campaign_group_key == probe.campaign_group_key
                    )
                )
                generation = 1 if maximum is None else maximum + 1
        return CampaignFactory().build(factory_input, batch_generation=generation)

    @contextlib.contextmanager
    def _serialized(self) -> Iterator[sa.Connection]:
        connection = self.engine.connect()
        transaction: sa.Transaction | None = None
        try:
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                transaction = connection.begin()
                if connection.dialect.name == "postgresql":
                    connection.execute(
                        sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
                        {"lock_key": self._POSTGRES_RESERVATION_LOCK},
                    )
            yield connection
            if transaction is None:
                connection.commit()
            else:
                transaction.commit()
        except Exception:
            if transaction is None:
                connection.rollback()
            else:
                transaction.rollback()
            raise
        finally:
            connection.close()

    def reserve_member(
        self,
        factory_input: CampaignFactoryInput,
        member: CampaignMemberReservation,
        *,
        provider_workspace_ref: str,
        desired_provider_config_fingerprint: str,
        reserved_at: dt.datetime,
        expected_campaign_ref: str | None = None,
        operation_correlation_id: str | None = None,
        effective_mailbox_daily_cap: int | None = None,
    ) -> CampaignReservationResult:
        if reserved_at.tzinfo is None or reserved_at.utcoffset() is None:
            raise ValueError("reserved_at must be timezone-aware")
        member_ref = semantic_fingerprint(
            {
                "kind": "campaign-member-v1",
                "acquisition_opportunity_id": member.acquisition_opportunity_id,
            }
        )
        with self._serialized() as connection:
            existing = connection.execute(
                sa.select(acquisition_campaign_member).where(
                    acquisition_campaign_member.c.acquisition_opportunity_id
                    == member.acquisition_opportunity_id
                )
            ).mappings().one_or_none()
            if existing is not None:
                if (
                    existing["member_ref"] != member_ref
                    or existing["input_fingerprint"] != member.input_fingerprint
                    or existing["envelope_fingerprint"] != member.envelope_fingerprint
                    or existing["policy_action_fingerprint"]
                    != member.policy_action_fingerprint
                ):
                    raise CampaignIdempotencyConflict(
                        "opportunity already has different campaign semantics"
                    )
                campaign = connection.execute(
                    sa.select(acquisition_campaign.c.batch_generation).where(
                        acquisition_campaign.c.campaign_ref == existing["campaign_ref"]
                    )
                ).one()
                if operation_correlation_id is not None:
                    self._plan_initial_operations(
                        connection,
                        campaign_ref=existing["campaign_ref"],
                        member_ref=member_ref,
                        provider_config_fingerprint=desired_provider_config_fingerprint,
                        member_input_fingerprint=member.input_fingerprint,
                        correlation_id=operation_correlation_id,
                        now=reserved_at,
                    )
                return CampaignReservationResult(
                    campaign_ref=existing["campaign_ref"],
                    member_ref=member_ref,
                    batch_generation=campaign.batch_generation,
                    replayed=True,
                )

            if effective_mailbox_daily_cap is not None:
                self._require_pacing_capacity(
                    connection,
                    factory_input=factory_input,
                    member=member,
                    reserved_at=reserved_at,
                    effective_mailbox_daily_cap=effective_mailbox_daily_cap,
                )

            probe = CampaignFactory().build(factory_input, batch_generation=1)
            available = connection.execute(
                sa.select(acquisition_campaign)
                .where(
                    acquisition_campaign.c.campaign_group_key == probe.campaign_group_key,
                    acquisition_campaign.c.lifecycle == "BUILDING",
                    acquisition_campaign.c.membership_closed_at.is_(None),
                    acquisition_campaign.c.reserved_member_count
                    < acquisition_campaign.c.member_capacity,
                    sa.or_(
                        acquisition_campaign.c.membership_close_at.is_(None),
                        acquisition_campaign.c.membership_close_at > reserved_at,
                    ),
                )
                .order_by(acquisition_campaign.c.batch_generation)
                .with_for_update()
            ).mappings().first()
            if available is None:
                maximum = connection.scalar(
                    sa.select(sa.func.max(acquisition_campaign.c.batch_generation)).where(
                        acquisition_campaign.c.campaign_group_key == probe.campaign_group_key
                    )
                )
                plan = CampaignFactory().build(
                    factory_input, batch_generation=1 if maximum is None else maximum + 1
                )
                connection.execute(
                    sa.insert(acquisition_campaign).values(
                        campaign_ref=plan.campaign_ref,
                        campaign_group_key=plan.campaign_group_key,
                        batch_generation=plan.batch_generation,
                        factory_version=CAMPAIGN_FACTORY_VERSION,
                        plan_fingerprint=plan.plan_fingerprint,
                        country=factory_input.country,
                        jurisdiction=factory_input.jurisdiction,
                        language=factory_input.language,
                        wedge=factory_input.wedge,
                        wedge_version=factory_input.wedge_version,
                        selected_need_category=factory_input.selected_need_category,
                        selected_need_version=factory_input.selected_need_version,
                        personalization_catalog_version=(
                            factory_input.personalization_catalog_version
                        ),
                        personalization_template_version=(
                            factory_input.personalization_template_version
                        ),
                        language_policy_version=factory_input.language_policy_version,
                        envelope_catalog_version=factory_input.envelope_catalog_version,
                        sender_profile_ref=factory_input.sender_profile_ref,
                        mailbox_pool_version=factory_input.mailbox_pool_version,
                        compliance_ruleset_fingerprint=(
                            factory_input.compliance_ruleset_fingerprint
                        ),
                        sequence_policy_version=CAMPAIGN_SEQUENCE_POLICY_VERSION,
                        tracking_policy_version=TRACKING_POLICY_VERSION,
                        send_window_policy_version=SEND_WINDOW_POLICY_VERSION,
                        sequence_window_policy_version=SEQUENCE_WINDOW_POLICY_VERSION,
                        batch_policy_version=BATCH_SEAL_POLICY_VERSION,
                        pacing_policy_version=PACING_POLICY_VERSION,
                        provider_workspace_ref=provider_workspace_ref,
                        provider_campaign_name=plan.provider_campaign_name,
                        desired_provider_config_fingerprint=(
                            desired_provider_config_fingerprint
                        ),
                        timezone=plan.sequence_window.timezone,
                        step_1_execution_date=plan.sequence_window.step_1_execution_date,
                        step_1_authorization_deadline=(
                            plan.sequence_window.step_1_authorization_deadline.astimezone(
                                dt.UTC
                            )
                        ),
                        step_2_execution_date=plan.sequence_window.step_2_execution_date,
                        step_2_authorization_deadline=(
                            plan.sequence_window.step_2_authorization_deadline.astimezone(
                                dt.UTC
                            )
                        ),
                        lifecycle="BUILDING",
                        reserved_member_count=0,
                        member_capacity=10,
                        created_at=reserved_at,
                        updated_at=reserved_at,
                    )
                )
                campaign_values = {
                    "campaign_ref": plan.campaign_ref,
                    "batch_generation": plan.batch_generation,
                    "plan_fingerprint": plan.plan_fingerprint,
                    "step_1_execution_date": plan.sequence_window.step_1_execution_date,
                    "step_1_authorization_deadline": (
                        plan.sequence_window.step_1_authorization_deadline.astimezone(dt.UTC)
                    ),
                    "step_2_execution_date": plan.sequence_window.step_2_execution_date,
                    "step_2_authorization_deadline": (
                        plan.sequence_window.step_2_authorization_deadline.astimezone(dt.UTC)
                    ),
                }
            else:
                campaign_values = dict(available)

            campaign_ref = campaign_values["campaign_ref"]
            if expected_campaign_ref is not None and campaign_ref != expected_campaign_ref:
                from signals.campaigns.contracts import CampaignInputChanged

                raise CampaignInputChanged("campaign batch generation changed before reservation")
            connection.execute(
                sa.insert(acquisition_campaign_member).values(
                    member_ref=member_ref,
                    campaign_ref=campaign_ref,
                    acquisition_opportunity_id=member.acquisition_opportunity_id,
                    supplier_ref=member.supplier_ref,
                    contact_ref=member.contact_ref,
                    personalization_artifact_id=member.personalization_artifact_id,
                    personalization_artifact_fingerprint=(
                        member.personalization_artifact_fingerprint
                    ),
                    compliance_assessment_id=member.compliance_assessment_id,
                    compliance_assessment_fingerprint=(
                        member.compliance_assessment_fingerprint
                    ),
                    policy_evaluation_id=member.policy_evaluation_id,
                    policy_provenance=member.policy_provenance,
                    input_fingerprint=member.input_fingerprint,
                    contact_provider_identity_binding=(
                        member.contact_provider_identity_binding
                    ),
                    plan_fingerprint=campaign_values["plan_fingerprint"],
                    envelope_fingerprint=member.envelope_fingerprint,
                    policy_action_fingerprint=member.policy_action_fingerprint,
                    ruleset_fingerprint=member.ruleset_fingerprint,
                    sender_config_fingerprint=member.sender_config_fingerprint,
                    mailbox_ref=member.mailbox_ref,
                    mailbox_readiness_fingerprint=member.mailbox_readiness_fingerprint,
                    step_1_execution_date=campaign_values["step_1_execution_date"],
                    step_1_authorization_deadline=(
                        campaign_values["step_1_authorization_deadline"]
                    ),
                    step_2_execution_date=campaign_values["step_2_execution_date"],
                    step_2_authorization_deadline=(
                        campaign_values["step_2_authorization_deadline"]
                    ),
                    sequence_authorization_fingerprint=(
                        member.sequence_authorization_fingerprint
                    ),
                    execution_state="RESERVED",
                    sequence_state="PENDING_STEP1",
                    created_at=reserved_at,
                    updated_at=reserved_at,
                )
            )
            if operation_correlation_id is not None:
                self._plan_initial_operations(
                    connection,
                    campaign_ref=campaign_ref,
                    member_ref=member_ref,
                    provider_config_fingerprint=desired_provider_config_fingerprint,
                    member_input_fingerprint=member.input_fingerprint,
                    correlation_id=operation_correlation_id,
                    now=reserved_at,
                )
            current_count = int(
                connection.scalar(
                    sa.select(acquisition_campaign.c.reserved_member_count).where(
                        acquisition_campaign.c.campaign_ref == campaign_ref
                    )
                )
                or 0
            )
            next_count = current_count + 1
            campaign_updates: dict[str, object] = {
                "reserved_member_count": next_count,
                "updated_at": reserved_at,
            }
            if next_count == 1:
                campaign_updates.update(
                    {
                        "first_member_reserved_at": reserved_at,
                        "membership_close_at": reserved_at + dt.timedelta(minutes=15),
                    }
                )
            if next_count == 10:
                campaign_updates["membership_closed_at"] = reserved_at
            connection.execute(
                sa.update(acquisition_campaign)
                .where(acquisition_campaign.c.campaign_ref == campaign_ref)
                .values(**campaign_updates)
            )
            return CampaignReservationResult(
                campaign_ref=campaign_ref,
                member_ref=member_ref,
                batch_generation=campaign_values["batch_generation"],
            )

    @staticmethod
    def _require_pacing_capacity(
        connection: sa.Connection,
        *,
        factory_input: CampaignFactoryInput,
        member: CampaignMemberReservation,
        reserved_at: dt.datetime,
        effective_mailbox_daily_cap: int,
    ) -> None:
        timezone = ZoneInfo(
            "Europe/Zurich" if factory_input.jurisdiction == "CH" else "Europe/Paris"
        )
        local_date = reserved_at.astimezone(timezone).date()
        day_start = dt.datetime.combine(local_date, dt.time(), timezone).astimezone(dt.UTC)
        day_end = (day_start.astimezone(timezone) + dt.timedelta(days=1)).astimezone(
            dt.UTC
        )
        base = (
            sa.select(sa.func.count())
            .select_from(
                acquisition_campaign_member.join(
                    acquisition_campaign,
                    acquisition_campaign_member.c.campaign_ref
                    == acquisition_campaign.c.campaign_ref,
                )
            )
            .where(
                acquisition_campaign_member.c.created_at >= day_start,
                acquisition_campaign_member.c.created_at < day_end,
            )
        )
        checks = (
            ("global", 5, base),
            (
                "country",
                5,
                base.where(acquisition_campaign.c.country == factory_input.country),
            ),
            (
                "wedge",
                3,
                base.where(acquisition_campaign.c.wedge == factory_input.wedge),
            ),
            (
                "mailbox",
                min(3, effective_mailbox_daily_cap),
                base.where(
                    acquisition_campaign_member.c.mailbox_ref == member.mailbox_ref
                ),
            ),
        )
        for label, limit, statement in checks:
            if limit <= 0 or int(connection.scalar(statement) or 0) >= limit:
                raise CampaignPacingExceeded(f"{label} daily campaign cap reached")
        company_count = int(
            connection.scalar(
                sa.select(sa.func.count())
                .select_from(acquisition_campaign_member)
                .where(
                    acquisition_campaign_member.c.supplier_ref == member.supplier_ref,
                    acquisition_campaign_member.c.created_at
                    >= reserved_at - dt.timedelta(days=30),
                )
            )
            or 0
        )
        if company_count >= 1:
            raise CampaignPacingExceeded("company rolling 30-day contact cap reached")

    @staticmethod
    def _plan_initial_operations(
        connection: sa.Connection,
        *,
        campaign_ref: str,
        member_ref: str,
        provider_config_fingerprint: str,
        member_input_fingerprint: str,
        correlation_id: str,
        now: dt.datetime,
    ) -> None:
        for kind, bound_member, fingerprint in (
            (
                ProviderOperationKind.CREATE_CAMPAIGN,
                None,
                provider_config_fingerprint,
            ),
            (
                ProviderOperationKind.CONFIGURE_CAMPAIGN,
                None,
                provider_config_fingerprint,
            ),
            (ProviderOperationKind.ADD_LEAD, member_ref, member_input_fingerprint),
        ):
            operation_key = semantic_fingerprint(
                {
                    "kind": "provider-operation-key-v1",
                    "operation_kind": kind.value,
                    "campaign_ref": campaign_ref,
                    "member_ref": bound_member,
                    "desired_request_fingerprint": fingerprint,
                }
            )
            existing = connection.scalar(
                sa.select(acquisition_provider_operation.c.operation_ref).where(
                    acquisition_provider_operation.c.operation_key == operation_key
                )
            )
            if existing is None:
                connection.execute(
                    sa.insert(acquisition_provider_operation).values(
                        operation_ref=operation_key,
                        operation_key=operation_key,
                        operation_version=PROVIDER_OPERATION_VERSION,
                        kind=kind.value,
                        state=ProviderOperationState.PLANNED.value,
                        campaign_ref=campaign_ref,
                        member_ref=bound_member,
                        desired_request_fingerprint=fingerprint,
                        attempt=0,
                        correlation_id=correlation_id,
                        created_at=now,
                        updated_at=now,
                    )
                )

    def close_due_batches(self, now: dt.datetime) -> tuple[str, ...]:
        with self._serialized() as connection:
            rows = connection.execute(
                sa.select(acquisition_campaign.c.campaign_ref)
                .where(
                    acquisition_campaign.c.lifecycle == "BUILDING",
                    acquisition_campaign.c.membership_closed_at.is_(None),
                    acquisition_campaign.c.membership_close_at <= now,
                )
                .with_for_update()
            ).scalars().all()
            if rows:
                connection.execute(
                    sa.update(acquisition_campaign)
                    .where(acquisition_campaign.c.campaign_ref.in_(rows))
                    .values(
                        membership_closed_at=acquisition_campaign.c.membership_close_at,
                        updated_at=now,
                    )
                )
            return tuple(rows)

    def get_campaign(self, campaign_ref: str) -> dict[str, object]:
        with self.engine.connect() as connection:
            row = connection.execute(
                sa.select(acquisition_campaign).where(
                    acquisition_campaign.c.campaign_ref == campaign_ref
                )
            ).mappings().one()
            return dict(row)

    def plan_operation(
        self,
        kind: ProviderOperationKind,
        *,
        campaign_ref: str,
        member_ref: str | None,
        desired_request_fingerprint: str,
        correlation_id: str,
        now: dt.datetime,
    ) -> ProviderOperationRecord:
        with self._serialized() as connection:
            return self.plan_operation_in_transaction(
                connection,
                kind,
                campaign_ref=campaign_ref,
                member_ref=member_ref,
                desired_request_fingerprint=desired_request_fingerprint,
                correlation_id=correlation_id,
                now=now,
            )

    def plan_operation_in_transaction(
        self,
        connection: sa.Connection,
        kind: ProviderOperationKind,
        *,
        campaign_ref: str,
        member_ref: str | None,
        desired_request_fingerprint: str,
        correlation_id: str,
        now: dt.datetime,
    ) -> ProviderOperationRecord:
        operation_key = semantic_fingerprint(
            {
                "kind": "provider-operation-key-v1",
                "operation_kind": kind.value,
                "campaign_ref": campaign_ref,
                "member_ref": member_ref,
                "desired_request_fingerprint": desired_request_fingerprint,
            }
        )
        operation_ref = operation_key
        existing = connection.execute(
            sa.select(acquisition_provider_operation).where(
                acquisition_provider_operation.c.operation_key == operation_key
            )
        ).mappings().one_or_none()
        if existing is None and kind is ProviderOperationKind.ADD_LEAD:
            campaign = connection.execute(
                sa.select(
                    acquisition_campaign.c.lifecycle,
                    acquisition_campaign.c.membership_closed_at,
                ).where(acquisition_campaign.c.campaign_ref == campaign_ref)
            ).mappings().one()
            if (
                campaign["lifecycle"] != "BUILDING"
                or campaign["membership_closed_at"] is not None
            ):
                raise CampaignInputChanged("campaign membership is closed")
        if existing is None:
            connection.execute(
                sa.insert(acquisition_provider_operation).values(
                    operation_ref=operation_ref,
                    operation_key=operation_key,
                    operation_version=PROVIDER_OPERATION_VERSION,
                    kind=kind.value,
                    state=ProviderOperationState.PLANNED.value,
                    campaign_ref=campaign_ref,
                    member_ref=member_ref,
                    desired_request_fingerprint=desired_request_fingerprint,
                    attempt=0,
                    correlation_id=correlation_id,
                    created_at=now,
                    updated_at=now,
                )
            )
            existing = connection.execute(
                sa.select(acquisition_provider_operation).where(
                    acquisition_provider_operation.c.operation_ref == operation_ref
                )
            ).mappings().one()
        return self._operation_record(existing)

    def claim_operation(
        self,
        operation_ref: str,
        *,
        worker_ref: str,
        now: dt.datetime,
        lease_seconds: int,
    ) -> ProviderOperationRecord:
        with self._serialized() as connection:
            row = connection.execute(
                sa.select(acquisition_provider_operation)
                .where(acquisition_provider_operation.c.operation_ref == operation_ref)
                .with_for_update()
            ).mappings().one()
            if row["state"] == ProviderOperationState.IN_FLIGHT.value:
                lease = row["lease_expires_at"]
                if lease is not None and lease.replace(tzinfo=dt.UTC) <= now:
                    connection.execute(
                        sa.update(acquisition_provider_operation)
                        .where(acquisition_provider_operation.c.operation_ref == operation_ref)
                        .values(
                            state=ProviderOperationState.RECONCILE_REQUIRED.value,
                            error_code="LEASE_EXPIRED_REMOTE_OUTCOME_UNKNOWN",
                            updated_at=now,
                        )
                    )
                else:
                    return self._operation_record(row)
            elif row["state"] in {
                ProviderOperationState.PLANNED.value,
                ProviderOperationState.RETRYABLE_FAILED.value,
            }:
                if (
                    row["state"] == ProviderOperationState.RETRYABLE_FAILED.value
                    and int(row["attempt"]) >= PROVIDER_OPERATION_MAX_ATTEMPTS
                ):
                    connection.execute(
                        sa.update(acquisition_provider_operation)
                        .where(
                            acquisition_provider_operation.c.operation_ref
                            == operation_ref
                        )
                        .values(
                            state=ProviderOperationState.TERMINAL_FAILED.value,
                            lease_owner=None,
                            lease_expires_at=None,
                            retry_after=None,
                            error_code="RETRY_BUDGET_EXHAUSTED",
                            updated_at=now,
                        )
                    )
                    updated = connection.execute(
                        sa.select(acquisition_provider_operation).where(
                            acquisition_provider_operation.c.operation_ref
                            == operation_ref
                        )
                    ).mappings().one()
                    return self._operation_record(updated)
                retry_after = row["retry_after"]
                if retry_after is not None:
                    if retry_after.tzinfo is None:
                        retry_after = retry_after.replace(tzinfo=dt.UTC)
                    if retry_after > now:
                        return self._operation_record(row)
                connection.execute(
                    sa.update(acquisition_provider_operation)
                    .where(acquisition_provider_operation.c.operation_ref == operation_ref)
                    .values(
                        state=ProviderOperationState.IN_FLIGHT.value,
                        attempt=row["attempt"] + 1,
                        lease_owner=worker_ref,
                        lease_expires_at=now + dt.timedelta(seconds=lease_seconds),
                        started_at=now,
                        retry_after=None,
                        updated_at=now,
                    )
                )
            updated = connection.execute(
                sa.select(acquisition_provider_operation).where(
                    acquisition_provider_operation.c.operation_ref == operation_ref
                )
            ).mappings().one()
            return self._operation_record(updated)

    def get_operation(self, operation_ref: str) -> ProviderOperationRecord:
        with self.engine.connect() as connection:
            row = connection.execute(
                sa.select(acquisition_provider_operation).where(
                    acquisition_provider_operation.c.operation_ref == operation_ref
                )
            ).mappings().one()
            return self._operation_record(row)

    def set_operation_state(
        self,
        operation_ref: str,
        state: ProviderOperationState,
        *,
        now: dt.datetime,
        provider_identity: str | None = None,
        provider_result_fingerprint: str | None = None,
        error_code: str | None = None,
        retry_after: dt.datetime | None = None,
    ) -> ProviderOperationRecord:
        with self._serialized() as connection:
            values: dict[str, object] = {
                "state": state.value,
                "updated_at": now,
                "error_code": error_code,
                "retry_after": retry_after,
            }
            if state is ProviderOperationState.CONFIRMED:
                values["confirmed_at"] = now
            if state in {
                ProviderOperationState.RETRYABLE_FAILED,
                ProviderOperationState.TERMINAL_FAILED,
            }:
                values["failed_at"] = now
            if provider_identity is not None:
                values["provider_identity"] = provider_identity
            if provider_result_fingerprint is not None:
                values["provider_result_fingerprint"] = provider_result_fingerprint
            connection.execute(
                sa.update(acquisition_provider_operation)
                .where(acquisition_provider_operation.c.operation_ref == operation_ref)
                .values(**values)
            )
            row = connection.execute(
                sa.select(acquisition_provider_operation).where(
                    acquisition_provider_operation.c.operation_ref == operation_ref
                )
            ).mappings().one()
            return self._operation_record(row)

    def bind_provider_campaign(
        self,
        campaign_ref: str,
        *,
        provider_campaign_id: str,
        current_config_fingerprint: str | None,
        now: dt.datetime,
    ) -> None:
        with self._serialized() as connection:
            row = connection.execute(
                sa.select(acquisition_campaign).where(
                    acquisition_campaign.c.campaign_ref == campaign_ref
                )
            ).mappings().one()
            if row["provider_campaign_id"] not in (None, provider_campaign_id):
                from signals.campaigns.contracts import CampaignInputChanged

                raise CampaignInputChanged("provider campaign identity conflict")
            values: dict[str, object] = {
                "provider_campaign_id": provider_campaign_id,
                "updated_at": now,
            }
            if current_config_fingerprint is not None:
                values["current_provider_config_fingerprint"] = current_config_fingerprint
            connection.execute(
                sa.update(acquisition_campaign)
                .where(acquisition_campaign.c.campaign_ref == campaign_ref)
                .values(**values)
            )

    def bind_provider_lead(
        self,
        member_ref: str,
        *,
        provider_lead_id: str,
        binding_fingerprint: str,
        now: dt.datetime,
    ) -> None:
        with self._serialized() as connection:
            row = connection.execute(
                sa.select(acquisition_campaign_member).where(
                    acquisition_campaign_member.c.member_ref == member_ref
                )
            ).mappings().one()
            if row["execution_state"] not in {"RESERVED", "ENROLLED"}:
                from signals.campaigns.contracts import CampaignInputChanged

                raise CampaignInputChanged("member is no longer enrollable")
            if row["provider_lead_id"] not in (None, provider_lead_id):
                from signals.campaigns.contracts import CampaignInputChanged

                raise CampaignInputChanged("provider lead identity conflict")
            connection.execute(
                sa.update(acquisition_campaign_member)
                .where(acquisition_campaign_member.c.member_ref == member_ref)
                .values(
                    provider_lead_id=provider_lead_id,
                    provider_binding_fingerprint=binding_fingerprint,
                    execution_state="ENROLLED",
                    updated_at=now,
                )
            )

    @staticmethod
    def _operation_record(row: sa.RowMapping) -> ProviderOperationRecord:
        return ProviderOperationRecord(
            operation_ref=row["operation_ref"],
            operation_key=row["operation_key"],
            kind=row["kind"],
            state=row["state"],
            campaign_ref=row["campaign_ref"],
            member_ref=row["member_ref"],
            desired_request_fingerprint=row["desired_request_fingerprint"],
            attempt=row["attempt"],
            lease_owner=row["lease_owner"],
            lease_expires_at=(
                row["lease_expires_at"].replace(tzinfo=dt.UTC)
                if row["lease_expires_at"] is not None
                and row["lease_expires_at"].tzinfo is None
                else row["lease_expires_at"]
            ),
        )
