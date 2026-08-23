"""Authenticated internal read-only acquisition operations endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from signals.api.dependencies import current_session, request_now
from signals.api.errors import api_error

router = APIRouter()


def _authorize(request: Request) -> None:
    now = request_now(request)
    with request.app.state.engine.connect() as connection:
        session = current_session(request, connection, now)
        if session.account_id not in request.app.state.config.cockpit_operator_account_ids:
            raise api_error(403, "acquisition_ops_forbidden", "accès interne refusé")


@router.get("/internal/acquisition-ops/health")
def operational_health(request: Request):
    _authorize(request)
    return request.app.state.operations_service.health(observed_at=request_now(request))


@router.get("/internal/acquisition-ops/readiness")
def autonomous_readiness(request: Request):
    _authorize(request)
    return request.app.state.operations_service.readiness(evaluated_at=request_now(request))


@router.get("/internal/acquisition-ops/incidents")
def operational_incidents(
    request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 100
):
    _authorize(request)
    return {"items": request.app.state.operations_service.incidents(limit=limit)}


@router.get("/internal/acquisition-ops/dead-letters")
def operational_dead_letters(
    request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 100
):
    _authorize(request)
    return {"items": request.app.state.operations_service.dead_letters(limit=limit)}


__all__ = ["router"]
