"""Versioned ASGI entry point for the separate Founder Console API."""

from __future__ import annotations

from fastapi import FastAPI

from signals.founder_api.app import create_founder_app
from signals.founder_api.config import FounderApiConfig
from signals.founder_api.database import create_founder_database_engine
from signals.founder_api.read_models import FounderReadService
from signals.operations.service import OperationsReadService


def build_application() -> FastAPI:
    config = FounderApiConfig.from_environment()
    engine = create_founder_database_engine()
    operations = OperationsReadService(
        engine,
        environment_identity=config.environment,
    )
    return create_founder_app(
        config,
        read_service=FounderReadService(engine, operations=operations),
    )


def __getattr__(name: str) -> FastAPI:
    if name == "app":
        return build_application()
    raise AttributeError(f"module {__name__!r} n'a pas d'attribut {name!r}")


__all__ = ["build_application"]
