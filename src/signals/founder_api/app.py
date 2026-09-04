"""Separate, read-only FastAPI application for control.kivou.eu."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from signals.founder_api.access import FounderIdentityDependency
from signals.founder_api.config import FounderApiConfig
from signals.founder_api.contracts import FounderSession
from signals.founder_api.read_models import (
    FounderConsoleOverview,
    FounderProcedureDocumentReview,
    FounderReadService,
)


def create_founder_app(
    config: FounderApiConfig,
    *,
    now_override: Callable[[], dt.datetime] | None = None,
    read_service: FounderReadService | None = None,
) -> FastAPI:
    """Build the Founder API without mounting any customer or write route."""

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
    ) -> FounderConsoleOverview:
        del identity
        service: FounderReadService | None = app.state.read_service
        if service is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="les read models Founder ne sont pas configurés",
            )
        try:
            return service.overview(now=now(), week_offset=week_offset)
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

    return app


__all__ = ["create_founder_app"]
