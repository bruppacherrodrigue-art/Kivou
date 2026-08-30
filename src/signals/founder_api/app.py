"""Separate, read-only FastAPI application for control.kivou.eu."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from fastapi import FastAPI

from signals.founder_api.access import FounderIdentityDependency
from signals.founder_api.config import FounderApiConfig
from signals.founder_api.contracts import FounderSession


def create_founder_app(
    config: FounderApiConfig,
    *,
    now_override: Callable[[], dt.datetime] | None = None,
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

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/founder/session")
    def founder_session(identity: FounderIdentityDependency) -> FounderSession:
        now = now_override() if now_override is not None else dt.datetime.now(dt.UTC)
        return FounderSession(
            operator_email=identity.email,
            generated_at=now,
        )

    return app


__all__ = ["create_founder_app"]
