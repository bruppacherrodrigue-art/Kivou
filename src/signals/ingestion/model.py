from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Any, Literal

SourceName = Literal["simap", "boamp", "decp", "ted"]
RunStatus = Literal["running", "success", "failed", "rate_limited", "dry_run"]


@dataclasses.dataclass(frozen=True)
class IngestionCounters:
    records_fetched: int = 0
    records_accepted: int = 0
    records_rejected: int = 0
    records_persisted: int = 0
    representations_linked: int = 0
    opportunity_conflicts: int = 0
    signals_materialized: int = 0
    rate_limited_count: int = 0


@dataclasses.dataclass(frozen=True)
class Checkpoint:
    source: SourceName
    cursor: dict[str, Any] | None
    window_end: dt.datetime | None
    last_started_at: dt.datetime | None
    last_completed_at: dt.datetime | None
    status: str
    updated_at: dt.datetime


@dataclasses.dataclass(frozen=True)
class IngestionRun:
    run_id: str
    source: SourceName
    started_at: dt.datetime
    finished_at: dt.datetime | None
    status: str
    records_fetched: int
    records_accepted: int
    records_rejected: int
    records_persisted: int
    representations_linked: int
    opportunity_conflicts: int
    signals_materialized: int
    rate_limited_count: int
    error_category: str | None
    error_message: str | None
    checkpoint_before: dict[str, Any] | None
    checkpoint_after: dict[str, Any] | None
    dry_run: bool
