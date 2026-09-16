"""Explicit versioned Chief of Staff profile loader."""

from __future__ import annotations

from importlib.resources import files

CHIEF_OF_STAFF_PROFILE_VERSION = "1.1.0"


def load_chief_of_staff_profile() -> str:
    resource = files("signals.supervisor").joinpath(
        "profiles", "kivou-chief-of-staff", "SKILL.md"
    )
    return resource.read_text(encoding="utf-8")


__all__ = ["CHIEF_OF_STAFF_PROFILE_VERSION", "load_chief_of_staff_profile"]
