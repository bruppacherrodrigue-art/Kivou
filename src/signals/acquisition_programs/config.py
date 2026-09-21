"""Explicit, bounded program configuration; absent environment never activates."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from signals.acquisition_programs.contracts import AcquisitionProgramConfig, ProgramRuntimeFlags


def load_program_config(path: Path) -> AcquisitionProgramConfig:
    body = path.read_bytes()
    if len(body) > 65_536:
        raise ValueError("program configuration exceeds bound")
    raw = json.loads(body)
    if not isinstance(raw, dict):
        raise TypeError("program configuration must be an object")
    return AcquisitionProgramConfig.model_validate(raw)


def runtime_flags(source: Mapping[str, str]) -> ProgramRuntimeFlags:
    enabled = source.get("MILOMAIL_ACQUISITION_ENABLED", "false").casefold()
    if enabled not in {"true", "false"}:
        raise ValueError("MILOMAIL_ACQUISITION_ENABLED must be true or false")
    mode = source.get("MILOMAIL_CAMPAIGN_MODE", "SHADOW")
    if mode != "SHADOW":
        raise ValueError("Milo Mail runtime is locked to SHADOW")
    if enabled == "true" and "MILOMAIL_CAMPAIGN_MODE" not in source:
        raise ValueError("explicit SHADOW mode is required when enabling evaluation")
    return ProgramRuntimeFlags(
        enabled=enabled == "true",
        mode=mode,
        allowed_countries=tuple(
            item.strip() for item in source.get("MILOMAIL_ALLOWED_COUNTRIES", "FR").split(",")
        ),
        allowed_providers=tuple(
            item.strip()
            for item in source.get("MILOMAIL_ALLOWED_PROVIDERS", "GOOGLE_WORKSPACE").split(",")
        ),
        max_daily_contacts=int(source.get("MILOMAIL_MAX_DAILY_CONTACTS", "0")),
        max_monthly_contacts=int(source.get("MILOMAIL_MAX_MONTHLY_CONTACTS", "0")),
        max_cost_chf=source.get("MILOMAIL_MAX_COST_CHF", "0"),
    )


__all__ = ["load_program_config", "runtime_flags"]
