"""Versioned ASGI entry point for the separate Founder Console API."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from signals.founder_api.actions_composition import build_prospection_actions
from signals.founder_api.app import create_founder_app
from signals.founder_api.config import FounderApiConfig
from signals.founder_api.database import (
    create_founder_database_engine,
    create_founder_write_database_engine,
)
from signals.founder_api.read_models import FounderReadService
from signals.operations.service import OperationsReadService


def build_application() -> FastAPI:
    config = FounderApiConfig.from_environment()
    engine = create_founder_database_engine()
    write_engine = create_founder_write_database_engine()
    with write_engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1").scalar_one()
    provider_client = httpx.Client(timeout=10.0, follow_redirects=False)
    operations = OperationsReadService(
        engine,
        environment_identity=config.environment,
    )
    application = create_founder_app(
        config,
        read_service=FounderReadService(engine, operations=operations),
        prospection_actions=build_prospection_actions(write_engine, client=provider_client),
    )
    application.state.founder_read_engine = engine
    application.state.founder_write_engine = write_engine
    application.state.founder_provider_client = provider_client

    @application.on_event("shutdown")
    def _close_resources() -> None:
        provider_client.close()
        write_engine.dispose()
        engine.dispose()

    return application


def __getattr__(name: str) -> FastAPI:
    if name == "app":
        return build_application()
    raise AttributeError(f"module {__name__!r} n'a pas d'attribut {name!r}")


__all__ = ["build_application"]
