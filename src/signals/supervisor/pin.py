"""Immutable official Hermes release selected for the Kivou adapter."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True)
class HermesPin:
    repository: str
    tag: str
    commit: str
    version: str
    python: str


def load_hermes_pin() -> HermesPin:
    resource = files("signals.supervisor").joinpath("hermes.lock.toml")
    parsed = tomllib.loads(resource.read_text(encoding="utf-8"))["hermes"]
    return HermesPin(**parsed)
