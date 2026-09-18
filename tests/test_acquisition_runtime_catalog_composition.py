from __future__ import annotations

import subprocess
import sys


def test_importing_catalog_composition_does_not_load_provider_or_model_stacks() -> None:
    script = """
import sys
import signals.acquisition_runtime.catalog_composition  # noqa: F401
blocked = (
    "signals.acquisition_connectivity",
    "signals.acquisition_runtime.composition",
    "signals.acquisition_runtime.execution",
    "signals.campaigns.instantly",
    "signals.company_research.apollo",
    "signals.company_research.binding",
    "signals.company_research.company_requests",
    "signals.company_research.enrichment",
    "signals.company_research.provider",
    "signals.company_research.providers",
    "signals.company_research.service",
    "signals.company_research.winner_queue",
    "signals.company_research.winner_worker",
    "signals.model_runtime",
)
print("\\n".join(sorted(name for name in sys.modules if name.startswith(blocked))))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout == "\n"
    assert completed.stderr == ""
