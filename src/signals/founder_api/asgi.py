"""Versioned ASGI entry point for the separate Founder Console API."""

from __future__ import annotations

from fastapi import FastAPI

from signals.founder_api.app import create_founder_app
from signals.founder_api.config import FounderApiConfig


def build_application() -> FastAPI:
    return create_founder_app(FounderApiConfig.from_environment())


def __getattr__(name: str) -> FastAPI:
    if name == "app":
        return build_application()
    raise AttributeError(f"module {__name__!r} n'a pas d'attribut {name!r}")


__all__ = ["build_application"]
