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
from signals.ingestion.backfill import materialize_existing_opportunities_for_target

router = APIRouter()


class TargetIcpCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=256)
    customer_input: TargetIcpInput = TargetIcpInput()


class TargetIcpUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=256)
    customer_input: TargetIcpInput | None = None


class TargetIcpResponse(BaseModel):
    """Ce qu'un client voit de son profil — son entrée, et où elle en est.

    Ni pondérations, ni règles de besoin, ni seuils internes : le profil moteur
    dérivé n'est pas exposé, seulement ce que le client a déclaré.
    """

    target_icp_id: str
    label: str
    status: str
    customer_input: TargetIcpInput
    missing_fields: tuple[str, ...]
    created_at: dt.datetime
    updated_at: dt.datetime

    @classmethod
    def of(cls, stored: service.StoredTargetIcp) -> TargetIcpResponse:
        return cls(
            target_icp_id=stored.target_icp_id,
            label=stored.label,
            status=stored.status,
            customer_input=stored.customer_input,
            missing_fields=stored.missing_fields,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
        )


@router.get("/target-icps")
def list_target_icps(request: Request) -> list[TargetIcpResponse]:
    now = request_now(request)
    with request.app.state.engine.connect() as connection:
        session = current_session(request, connection, now)
        stored = service.list_target_icps(connection, account_id=session.account_id)
    return [TargetIcpResponse.of(item) for item in stored]


@router.post("/target-icps", status_code=201)
def create_target_icp(payload: TargetIcpCreate, request: Request) -> TargetIcpResponse:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        stored = service.create_target_icp(
            connection,
            account_id=session.account_id,
            label=payload.label,
            customer_input=payload.customer_input,
            now=now,
        )
    if stored.status == "active":
        materialize_existing_opportunities_for_target(
            request.app.state.engine,
            target_icp_id=stored.target_icp_id,
            as_of=now.date(),
            materialized_at=now,
        )
    return TargetIcpResponse.of(stored)


@router.get("/target-icps/{target_icp_id}")
def get_target_icp(target_icp_id: str, request: Request) -> TargetIcpResponse:
    now = request_now(request)
    with request.app.state.engine.connect() as connection:
        session = current_session(request, connection, now)
        try:
            stored = service.get_target_icp(
                connection, account_id=session.account_id, target_icp_id=target_icp_id
            )
        except service.TargetIcpNotFound as error:
            raise api_error(404, error.code, "profil de ciblage introuvable") from error
    return TargetIcpResponse.of(stored)


@router.patch("/target-icps/{target_icp_id}")
def update_target_icp(
    target_icp_id: str, payload: TargetIcpUpdate, request: Request
) -> TargetIcpResponse:
    enforce_origin(request, request.app.state.config)
    now = request_now(request)
    with request.app.state.engine.begin() as connection:
        session = current_session(request, connection, now)
        try:
            stored = service.update_target_icp(
                connection,
                account_id=session.account_id,
                target_icp_id=target_icp_id,
                label=payload.label,
                customer_input=payload.customer_input,
                now=now,
            )
        except service.TargetIcpNotFound as error:
            raise api_error(404, error.code, "profil de ciblage introuvable") from error
    if stored.status == "active":
        materialize_existing_opportunities_for_target(
            request.app.state.engine,
            target_icp_id=stored.target_icp_id,
            as_of=now.date(),
            materialized_at=now,
        )
    return TargetIcpResponse.of(stored)
