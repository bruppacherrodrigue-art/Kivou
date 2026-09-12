"""Separate, read-only FastAPI application for control.kivou.eu."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from signals.founder_api.access import FounderIdentityDependency
from signals.founder_api.commercial_tunnel import FounderTunnelPeriod
from signals.founder_api.config import FounderApiConfig
from signals.founder_api.contracts import FounderSession
from signals.founder_api.prospection import FounderDirectoryStatus, FounderProspection
from signals.founder_api.prospection_actions import build_prospection_actions_router
from signals.founder_api.read_models import (
    FounderConsoleOverview,
    FounderProcedureDocumentReview,
    FounderReadService,
    FounderSystemPage,
)
from signals.prospection_actions.service import ProspectionActions


def create_founder_app(
    config: FounderApiConfig,
    *,
    now_override: Callable[[], dt.datetime] | None = None,
    read_service: FounderReadService | None = None,
    prospection_actions: ProspectionActions | None = None,
) -> FastAPI:
    """Build the isolated Founder API with an optional least-privilege action service."""

    app = FastAPI(
        title="Kivou Founder Control",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = config
    app.state.now_override = now_override
    app.state.read_service = read_service
    app.state.prospection_actions = prospection_actions
    if prospection_actions is not None:
        app.include_router(build_prospection_actions_router(prospection_actions))

        @app.exception_handler(RequestValidationError)
        async def _action_validation_error(
            request: Request, error: RequestValidationError
        ) -> JSONResponse:
            if not request.url.path.startswith("/api/founder/actions/prospection/"):
                return await request_validation_exception_handler(request, error)
            rejection_reason = request.url.path.endswith("/reject") and any(
                tuple(item.get("loc", ())) == ("body", "reason")
                for item in error.errors()
            )
            code = "INVALID_REJECTION_REASON" if rejection_reason else "INVALID_ACTION_PAYLOAD"
            return JSONResponse(
                status_code=422,
                content={
                    "detail": {
                        "code": code,
                        "message": "requête d'action invalide",
                        "target_ids": [],
                    }
                },
            )

    def now() -> dt.datetime:
        return now_override() if now_override is not None else dt.datetime.now(dt.UTC)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/founder/session")
    def founder_session(identity: FounderIdentityDependency) -> FounderSession:
        return FounderSession(
            operator_email=identity.email,
            generated_at=now(),
        )

    @app.get("/api/founder/overview")
    def founder_overview(
        identity: FounderIdentityDependency,
        week_offset: Annotated[int, Query(ge=0, le=51)] = 0,
        period: FounderTunnelPeriod = FounderTunnelPeriod.LAST_7_DAYS,
    ) -> FounderConsoleOverview:
        del identity
        service: FounderReadService | None = app.state.read_service
        if service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="les read models Founder ne sont pas configurés",
            )
        try:
            return service.overview(
                now=now(),
                week_offset=week_offset,
                period=period,
            )
        except (SQLAlchemyError, RuntimeError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="les read models Founder sont indisponibles",
            ) from error

    @app.get("/api/founder/procedure-document-reviews")
    def founder_procedure_document_reviews(
        identity: FounderIdentityDependency,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> tuple[FounderProcedureDocumentReview, ...]:
        del identity
        service: FounderReadService | None = app.state.read_service
        if service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="les read models Founder ne sont pas configurés",
            )
        try:
            return service.procedure_document_reviews(limit=limit)
        except SQLAlchemyError as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="les dossiers à revoir sont indisponibles",
            ) from error

    @app.get("/api/founder/prospection")
    def founder_prospection(
        identity: FounderIdentityDependency,
        page: Annotated[int, Query(ge=1, le=10_000)] = 1,
        page_size: Annotated[int, Query(ge=1, le=25)] = 25,
        q: Annotated[str | None, Query(max_length=100)] = None,
        family: Annotated[str | None, Query(max_length=100)] = None,
        department: Annotated[str | None, Query(max_length=3)] = None,
        directory_status: Annotated[
            FounderDirectoryStatus | None,
            Query(alias="status"),
        ] = None,
        reverification_reason: Annotated[
            str | None,
            Query(alias="reason", max_length=128),
        ] = None,
    ) -> FounderProspection:
        del identity
        service: FounderReadService | None = app.state.read_service
        if service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="les données de prospection ne sont pas configurées",
            )
        try:
            return service.prospection(
                now=now(),
                page=page,
                page_size=page_size,
                q=q,
                family=family,
                department=department,
                directory_status=directory_status,
                reverification_reason=reverification_reason,
            )
        except (SQLAlchemyError, RuntimeError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="les données de prospection sont indisponibles",
            ) from error

    @app.get("/api/founder/system")
    def founder_system(identity: FounderIdentityDependency) -> FounderSystemPage:
        del identity
        service: FounderReadService | None = app.state.read_service
        if service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="les données système ne sont pas configurées",
            )
        try:
            return service.system(now=now())
        except (SQLAlchemyError, RuntimeError) as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="les données système sont indisponibles",
            ) from error

    return app


__all__ = ["create_founder_app"]
