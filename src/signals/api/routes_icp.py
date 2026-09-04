"""Les profils de ciblage d'un compte.

La propriété n'est jamais fournie par le client : elle est lue sur la session.
Un `account_id` envoyé dans un corps de requête serait au mieux redondant, au
pire une élévation de privilège — il n'existe donc dans aucun schéma d'entrée.

Un profil appartenant à un autre compte se comporte comme un profil inexistant.
Distinguer « interdit » de « introuvable » permettrait de sonder l'existence des
ressources voisines, une adresse à la fois.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from signals.accounts import service
from signals.accounts.icp_input import TargetIcpInput
from signals.api.dependencies import current_session, enforce_origin, request_now
from signals.api.errors import api_error
from signals.billing import service as billing_service
from signals.ingestion.backfill import (
    materialize_landing_opportunity_in_transaction,
    rematerialize_target_in_transaction,
)

router = APIRouter()


class TargetIcpCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=256)
    customer_input: TargetIcpInput = TargetIcpInput()


class TargetIcpUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=256)
    customer_input: TargetIcpInput | None = None


class TargetIcpPlanLimitResponse(BaseModel):
    code: str
    limit: int
    territory_count: int


class TargetIcpResponse(BaseModel):
    """Ce qu'un client voit de son profil — son entrée, et où elle en est.

    Ni pondérations, ni règles de besoin, ni seuils internes : le profil moteur
    dérivé n'est pas exposé, seulement ce que le client a déclaré.
    """

    target_icp_id: str
    label: str
    status: str
    matching_revision: int
    plan_limit: TargetIcpPlanLimitResponse | None
    customer_input: TargetIcpInput
    missing_fields: tuple[str, ...]
    created_at: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def of(
        cls,
        stored: service.StoredTargetIcp,
        *,
        max_territories: int | None,
    ) -> TargetIcpResponse:
        plan_limit = None
        if stored.plan_limit_code is not None and max_territories is not None:
            plan_limit = TargetIcpPlanLimitResponse(
                code=stored.plan_limit_code,
                limit=max_territories,
                territory_count=len(set(stored.customer_input.territories)),
            )
        return cls(
            target_icp_id=stored.target_icp_id,
            label=stored.label,
            status=stored.status,
            matching_revision=stored.matching_revision,
            plan_limit=plan_limit,
            customer_input=stored.customer_input,
            missing_fields=stored.missing_fields,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
        )


@router.get("/target-icps")
def list_target_icps(request: Request) -> list[TargetIcpResponse]:
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        entitlements = billing_service.entitlements(connection, account_id=session.account_id)
        service.reconcile_territory_plan_limits(
            connection,
            account_id=session.account_id,
            max_territories=entitlements.max_territories_per_icp,
            now=now,
        )
        stored = service.list_target_icps(connection, account_id=session.account_id)
        if service.landing_signal(connection, account_id=session.account_id) is not None:
            service.mark_landing_step(
                connection,
                account_id=session.account_id,
                step="confirmation_started",
                now=now,
            )
    return [
        TargetIcpResponse.of(item, max_territories=entitlements.max_territories_per_icp)
        for item in stored
    ]


@router.post("/target-icps", status_code=201)
def create_target_icp(payload: TargetIcpCreate, request: Request) -> TargetIcpResponse:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        state = billing_service.billing_state(connection, account_id=session.account_id)
        try:
            service.enforce_territory_limit(
                payload.customer_input,
                max_territories=state.entitlements.max_territories_per_icp,
            )
        except service.TerritoryLimitExceeded as error:
            raise api_error(
                422,
                error.code,
                "ce profil dépasse la limite territoriale de l’offre",
                limit=error.limit,
                territory_count=error.territory_count,
                plan_code=state.plan_code,
            ) from error
        stored = service.create_target_icp(
            connection,
            account_id=session.account_id,
            label=payload.label,
            customer_input=payload.customer_input,
            now=now,
        )
        rematerialize_target_in_transaction(
            connection,
            target_icp_id=stored.target_icp_id,
            as_of=now.date(),
            materialized_at=now,
        )
        landing = service.landing_signal(connection, account_id=session.account_id)
        if landing is not None and landing.opportunity_key is not None:
            materialize_landing_opportunity_in_transaction(
                connection,
                target_icp_id=stored.target_icp_id,
                opportunity_key=landing.opportunity_key,
                as_of=now.date(),
                materialized_at=now,
            )
        request.app.state.conversion_milestone_service.observe_activation_in_transaction(
            connection, account_id=session.account_id, observed_at=now
        )
    return TargetIcpResponse.of(
        stored,
        max_territories=state.entitlements.max_territories_per_icp,
    )


@router.get("/target-icps/{target_icp_id}")
def get_target_icp(target_icp_id: str, request: Request) -> TargetIcpResponse:
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        entitlements = billing_service.entitlements(connection, account_id=session.account_id)
        service.reconcile_territory_plan_limits(
            connection,
            account_id=session.account_id,
            max_territories=entitlements.max_territories_per_icp,
            now=now,
        )
        try:
            stored = service.get_target_icp(
                connection, account_id=session.account_id, target_icp_id=target_icp_id
            )
        except service.TargetIcpNotFound as error:
            raise api_error(404, error.code, "profil de ciblage introuvable") from error
    return TargetIcpResponse.of(stored, max_territories=entitlements.max_territories_per_icp)


@router.patch("/target-icps/{target_icp_id}")
def update_target_icp(
    target_icp_id: str, payload: TargetIcpUpdate, request: Request
) -> TargetIcpResponse:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        state = billing_service.billing_state(connection, account_id=session.account_id)
        try:
            previous = service.get_target_icp(
                connection, account_id=session.account_id, target_icp_id=target_icp_id
            )
            if payload.customer_input is not None:
                service.enforce_territory_limit(
                    payload.customer_input,
                    max_territories=state.entitlements.max_territories_per_icp,
                )
            stored = service.update_target_icp(
                connection,
                account_id=session.account_id,
                target_icp_id=target_icp_id,
                label=payload.label,
                customer_input=payload.customer_input,
                now=now,
            )
            service.mark_landing_step(
                connection,
                account_id=session.account_id,
                step="profile_confirmed",
                now=now,
            )
        except service.TargetIcpNotFound as error:
            raise api_error(404, error.code, "profil de ciblage introuvable") from error
        except service.TerritoryLimitExceeded as error:
            raise api_error(
                422,
                error.code,
                "ce profil dépasse la limite territoriale de l’offre",
                limit=error.limit,
                territory_count=error.territory_count,
                plan_code=state.plan_code,
            ) from error
        service.reconcile_territory_plan_limits(
            connection,
            account_id=session.account_id,
            max_territories=state.entitlements.max_territories_per_icp,
            now=now,
        )
        stored = service.get_target_icp(
            connection, account_id=session.account_id, target_icp_id=target_icp_id
        )
        if stored.matching_revision != previous.matching_revision:
            rematerialize_target_in_transaction(
                connection,
                target_icp_id=stored.target_icp_id,
                as_of=now.date(),
                materialized_at=now,
            )
        landing = service.landing_signal(connection, account_id=session.account_id)
        if landing is not None and landing.opportunity_key is not None:
            materialize_landing_opportunity_in_transaction(
                connection,
                target_icp_id=stored.target_icp_id,
                opportunity_key=landing.opportunity_key,
                as_of=now.date(),
                materialized_at=now,
            )
        request.app.state.conversion_milestone_service.observe_activation_in_transaction(
            connection, account_id=session.account_id, observed_at=now
        )
    return TargetIcpResponse.of(
        stored,
        max_territories=state.entitlements.max_territories_per_icp,
    )
