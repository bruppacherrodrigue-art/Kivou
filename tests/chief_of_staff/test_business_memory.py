from __future__ import annotations

from pathlib import Path

import pytest

from signals.chief_of_staff.business_memory import (
    BUSINESS_MEMORY_PATH,
    load_business_memory,
)


def test_versioned_business_memory_is_loaded_from_repository() -> None:
    memory = load_business_memory()
    assert memory.memory_version == "business-memory-v1"
    assert memory.updated_at.isoformat() == "2026-09-15"
    assert len(memory.decisions) >= 6
    assert {item.category for item in memory.decisions} >= {
        "POSITIONING",
        "PRICING",
        "ACQUISITION",
        "SECURITY",
        "AUTONOMY",
        "GOVERNANCE",
    }


def test_memory_sources_resolve_to_versioned_repository_files() -> None:
    root = Path(__file__).resolve().parents[2]
    for decision in load_business_memory().decisions:
        source = root / decision.source_ref.split("#", 1)[0]
        assert source.is_file(), decision.source_ref


def test_runtime_memory_is_immutable() -> None:
    memory = load_business_memory()
    with pytest.raises(TypeError):
        memory.decisions[0] = memory.decisions[0]  # type: ignore[index]


def test_memory_path_is_packaged_read_only_input() -> None:
    assert BUSINESS_MEMORY_PATH.name == "business_memory.v1.json"
    assert "chief_of_staff" in BUSINESS_MEMORY_PATH.parts
