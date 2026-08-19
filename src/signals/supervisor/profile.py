"""Versioned Kivou acquisition-supervisor instructions."""

from __future__ import annotations

from importlib.resources import files

PROFILE_VERSION = "1.0.0"


def load_supervisor_profile() -> str:
    resource = files("signals.supervisor").joinpath(
        "profiles", "kivou-acquisition-supervisor", "SKILL.md"
    )
    return resource.read_text(encoding="utf-8")
