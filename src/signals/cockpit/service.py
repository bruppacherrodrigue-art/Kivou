"""Deterministic façade for the weekly commercial cockpit."""

from __future__ import annotations

import sqlalchemy as sa

from signals.cockpit.contracts import REPORT_VERSION, CockpitWeek, WeeklyCommercialCockpit
from signals.cockpit.metrics import RepositoryCockpitMetrics
from signals.decision_engine.policy import semantic_fingerprint


class WeeklyCommercialCockpitService:
    def __init__(
        self,
        engine: sa.Engine,
        *,
        metrics: RepositoryCockpitMetrics | None = None,
    ) -> None:
        self.engine = engine
        self.metrics = metrics or RepositoryCockpitMetrics(engine)

    def generate(self, *, week: CockpitWeek) -> WeeklyCommercialCockpit:
        metrics = self.metrics.capture(week=week)
        semantic = {
            "kind": REPORT_VERSION,
            "week_start": week.week_start,
            "week_end": week.week_end,
            "timezone": week.timezone,
            "funnel": metrics.funnel,
            "analytical_rows": metrics.analytical_rows,
            "wedge_m2_efficiency": metrics.wedge_m2_efficiency,
            "data_quality": metrics.data_quality,
        }
        return WeeklyCommercialCockpit(
            report_ref=semantic_fingerprint(semantic),
            week_start=week.week_start,
            week_end=week.week_end,
            captured_at=week.week_end,
            funnel=metrics.funnel,
            analytical_rows=metrics.analytical_rows,
            wedge_m2_efficiency=metrics.wedge_m2_efficiency,
            data_quality=metrics.data_quality,
        )


__all__ = ["WeeklyCommercialCockpitService"]
