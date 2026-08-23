"""One authenticated, internal, read-only cockpit endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from signals.api.dependencies import current_session, request_now
from signals.api.errors import api_error
from signals.cockpit.contracts import WeeklyCommercialCockpit, completed_week

router = APIRouter()


@router.get("/internal/commercial-cockpit")
def commercial_cockpit(
    request: Request,
    week_offset: Annotated[int, Query(ge=0, le=51)] = 0,
) -> WeeklyCommercialCockpit:
    now = request_now(request)
    with request.app.state.engine.connect() as connection:
        session = current_session(request, connection, now)
        if session.account_id not in request.app.state.config.cockpit_operator_account_ids:
            raise api_error(403, "cockpit_forbidden", "accès interne refusé")
    week = completed_week(now, week_offset=week_offset)
    return request.app.state.cockpit_service.generate(week=week)


__all__ = ["router"]
