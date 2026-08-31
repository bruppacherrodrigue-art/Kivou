"""Locks invariants 5 and 6 of the acquisition-production-shadow-phase1 spec.

Invariant 5 — a production cycle emits no commercial mutation: every provider
mutation counter is zero at the end of the cycle.

Invariant 6 — no secret, no email address, no raw provider object, no prompt
and no model response enters the journal.

Both tests reuse the real production montage (`production_arguments` /
`seeded_french_opportunity` from `test_acquisition_runtime_execution_production`,
no stub domain builder) and the Instantly double (`ProbeInstantlyProvider`)
already used by the execution tests, per the task brief. Journal capture
follows the exact `_isolated_stream()` pattern from
`test_acquisition_runtime_events.py`.

Both assertions of absence are preceded by an assertion of presence: a cycle
that never ran, crashed on its first stage, or a journal that stayed empty,
would make "zero mutations" or "no secret" pass vacuously.
"""

from __future__ import annotations

import io
import logging

import pytest
import sqlalchemy as sa
from test_acquisition_runtime_execution import ProbeInstantlyProvider
from test_acquisition_runtime_execution_production import (
    engine,
    production_arguments,
    seeded_french_opportunity,
)

from signals.acquisition_runtime.contracts import RuntimeRunRequest
from signals.acquisition_runtime.events import (
    LOGGER_NAME,
    configure_acquisition_runtime_logging,
)
from signals.acquisition_runtime.execution import build_runtime_execution_composition
from signals.persistence.schema import METADATA, acquisition_provider_operation

__all__ = ["engine", "production_arguments", "seeded_french_opportunity"]


class MutationTrackingInstantlyProvider(ProbeInstantlyProvider):
    """Extends the execution tests' Instantly double with mutation tracking.

    Every Instantly operation capable of a real provider-side effect records
    its name before raising: a production cycle must never reach any of
    them, and if one ever is, both the recorded call and the raised error
    make the cycle fail loudly instead of silently mutating something.
    """

    def __init__(self, *, mailbox_ready: bool = True) -> None:
        super().__init__(mailbox_ready=mailbox_ready)
        self.mutating_calls: list[str] = []

    def _mutate(self, name: str) -> None:
        self.mutating_calls.append(name)
        raise AssertionError(f"forbidden production mutation attempted: {name}")

    def create_campaign(self, *, name: str, provider_config: dict[str, object]):
        self._mutate("create_campaign")

    def configure_campaign(
        self, provider_campaign_id: str, *, provider_config: dict[str, object]
    ):
        self._mutate("configure_campaign")

    def activate_campaign(self, provider_campaign_id: str):
        self._mutate("activate_campaign")

    def pause_campaign(self, provider_campaign_id: str):
        self._mutate("pause_campaign")

    def create_lead_or_batch(
        self, *, provider_campaign_id: str, leads: tuple[dict[str, object], ...]
    ):
        self._mutate("create_lead_or_batch")

    def pause_lead(self, provider_lead_id: str):
        self._mutate("pause_lead")


@pytest.fixture
def production_engine(engine: sa.Engine) -> sa.Engine:
    """The shared production engine, extended with the full domain schema.

    `test_acquisition_runtime_execution_production._engine()` only creates the
    tables its own (composition-only) tests need — it never runs a cycle.
    Invariant 5 runs one for real through the unstubbed domain builder, which
    reaches live tables (`acquisition_opportunity`, `acquisition_campaign`,
    `acquisition_provider_operation`, ...) that helper never had to touch.
    `create_all` is idempotent, so this only adds what is missing.
    """

    METADATA.create_all(engine)
    return engine


@pytest.fixture
def instantly_double() -> MutationTrackingInstantlyProvider:
    return MutationTrackingInstantlyProvider()


@pytest.fixture
def production_composition(
    production_arguments: dict[str, object],
    production_engine: sa.Engine,
    instantly_double: MutationTrackingInstantlyProvider,
    seeded_french_opportunity: str,
):
    """The real production montage (task 6/6B), Instantly swapped for the tracker."""

    arguments = dict(production_arguments)
    arguments["instantly_provider"] = instantly_double
    return build_runtime_execution_composition(**arguments)


@pytest.fixture
def captured_journal() -> io.StringIO:
    """Same capture method as `test_acquisition_runtime_events.py`'s `_isolated_stream`."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    stream = io.StringIO()
    configure_acquisition_runtime_logging(stream=stream)
    return stream


def _run_once(composition) -> object:
    return composition.runner.run_once(
        RuntimeRunRequest(owner_ref="runtime-owner:production-invariant-lock")
    )


def test_a_production_cycle_emits_no_commercial_mutation(
    production_composition, production_engine, instantly_double
) -> None:
    """Invariant 5: every provider mutation counter is zero at cycle end."""

    result = _run_once(production_composition)

    # Prove presence before proving absence — two separate ways a "zero
    # mutations" result could be true for the wrong reason:
    #   (a) the cycle never started at all (no lease, no cycle, no stage);
    #   (b) the cycle crashed on its first real stage (a swallowed exception,
    #       recorded as CURRENT_RUN_TECHNICAL_FAILURE) before reaching any
    #       real business decision.
    # This montage runs the real, unstubbed domain: SIGNAL_SEED genuinely
    # resolves the seeded event/award, and SUPPLIER_DISCOVERY genuinely
    # evaluates it — the deterministic outcome for this minimal fixture
    # (no CPV-derived need category) is SUPPRESSED/SUPPLIER_NEED_NOT_ACTIONABLE,
    # decided by the domain's own policy before any provider is ever called.
    assert result.stage is not None, (
        "no stage was ever attempted; a zero mutation count would be vacuous"
    )
    assert result.reason_code != "CURRENT_RUN_TECHNICAL_FAILURE", (
        f"the cycle crashed before reaching a real business decision "
        f"(reason={result.reason_code!r}); a zero mutation count would prove nothing"
    )

    assert instantly_double.mutating_calls == []
    with production_engine.connect() as connection:
        operations = connection.execute(
            sa.select(sa.func.count()).select_from(acquisition_provider_operation)
        ).scalar_one()
    assert operations == 0


def test_the_production_journal_never_carries_a_secret_or_an_address(
    production_composition, captured_journal
) -> None:
    """Invariant 6: no secret, address, provider object, prompt or completion."""

    _run_once(production_composition)
    journal = captured_journal.getvalue()

    # Prove presence before proving absence — an empty journal would make
    # every forbidden-string assertion below pass vacuously.
    assert journal.strip() != "", "the journal captured nothing for a real cycle"

    assert "@" not in journal
    for forbidden in ("api_key", "bearer ", "password", "prompt", "completion"):
        assert forbidden not in journal.lower()
