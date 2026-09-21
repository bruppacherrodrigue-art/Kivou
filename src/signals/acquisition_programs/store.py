"""Immutable program-version registration using Kivou's conflict-safe inserts."""

from __future__ import annotations

import datetime as dt
import hashlib
import json

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition_programs.contracts import AcquisitionProgramConfig
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import acquisition_program


class AcquisitionProgramStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def register(self, config: AcquisitionProgramConfig, *, at: dt.datetime) -> str:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("program registration time must be timezone-aware")
        snapshot = config.model_dump(mode="json")
        canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        program_id = hashlib.sha256(
            f"acquisition-program-v1\0{config.program_key}\0{fingerprint}".encode()
        ).hexdigest()
        values = {
            "program_id": program_id,
            "program_key": config.program_key,
            "schema_version": config.schema_version,
            "config_fingerprint": fingerprint,
            "config_snapshot": snapshot,
            "mode": config.campaign_mode,
            "enabled": config.enabled,
            "created_at": at,
            "updated_at": at,
        }
        with self._engine.begin() as connection:
            inserted = insert_if_absent(connection, acquisition_program, values)
            if not inserted:
                row = connection.execute(
                    sa.select(acquisition_program).where(acquisition_program.c.program_id == program_id)
                ).mappings().one_or_none()
                if row is None or row["config_snapshot"] != snapshot:
                    raise ValueError("program version registration conflict")
        return program_id


__all__ = ["AcquisitionProgramStore"]
