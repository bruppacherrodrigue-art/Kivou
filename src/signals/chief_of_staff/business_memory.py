"""Load Kivou-owned, PR-versioned business memory as immutable data."""

from __future__ import annotations

from pathlib import Path

from signals.chief_of_staff.contracts import BusinessMemory

BUSINESS_MEMORY_PATH = Path(__file__).with_name("business_memory.v1.json")


def load_business_memory(path: Path = BUSINESS_MEMORY_PATH) -> BusinessMemory:
    return BusinessMemory.model_validate_json(path.read_text(encoding="utf-8"))


__all__ = ["BUSINESS_MEMORY_PATH", "load_business_memory"]
