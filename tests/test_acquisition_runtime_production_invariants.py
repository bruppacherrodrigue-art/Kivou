"""Locks invariants 5 and 6 of the acquisition-production-shadow-phase1 spec.

Invariant 5 — a production cycle emits no commercial mutation: every provider
mutation counter is zero at the end of the cycle.

Invariant 6 — no secret, no email address, no raw provider object, no prompt
and no model response enters the journal.

Fix round 1 (review Critical): the first version of this file drove the real,
unstubbed domain (task 6/6B's `production_arguments` montage) and got a real
cycle that stopped at `SUPPLIER_DISCOVERY` — `SUPPRESSED`, before any provider
call. That proved a cycle *ran*, but not that it ever had the *opportunity to
mutate*: only `CAMPAIGN` (index 7) and `PROVIDER_HANDOFF` (index 8) touch
Instantly, and the production mutation guard itself lives at two places —
`runner.py`'s own pre-dispatch check and `registry.py:92-98` — both scoped to
`PROVIDER_HANDOFF`. A montage that never reaches that stage proves "zero
mutations" for the wrong reason (six stages short), exactly like an empty
journal proves "no secret" for the wrong reason.

The fix reuses `tests/test_acquisition_runtime_execution.py`'s
`test_fake_full_cycle_...` pattern: a `domain_builder` override with one fake
handler per stage, so the cycle deterministically walks `SIGNAL_SEED` through
`CAMPAIGN` (real store, real registry, real runner — only the *domain* is
faked) and reaches `PROVIDER_HANDOFF`, where — with the production default
`allow_qa_provider_mutations=False` — the guard fires *before* any handler for
that stage is ever dispatched. The `PROVIDER_HANDOFF` handler is a canary: if
it were ever reached, it calls the Instantly double the way the real domain's
`handoff_provider` would, so a regression that removed or narrowed the guard
would show up as a recorded mutating call, not a silent pass.

`production_arguments` / `seeded_french_opportunity` (task 6/6B) still supply
every other boundary — runtime config, connectivity, webhook, Hermes,
dependency probe, clock — for real; only `domain_builder` is overridden.
Journal capture follows the exact `_isolated_stream()` pattern from
`test_acquisition_runtime_events.py`.

Every assertion of absence is preceded by an assertion of presence: a cycle
that never ran, stopped short of the mutating stage, or a journal that stayed
empty or shallow, would make "zero mutations" or "no secret" pass vacuously.
"""

from __future__ import annotations

import io
import logging
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from test_acquisition_runtime_execution import ProbeInstantlyProvider
from test_acquisition_runtime_execution_production import (
    engine,
    production_arguments,
    seeded_french_opportunity,
)

from signals.acquisition_runtime.contracts import (
    AcquisitionRuntimeStage,
    RuntimeActionResult,
    RuntimeRunRequest,
    RuntimeRunStatus,
    RuntimeStageStatus,
)
from signals.acquisition_runtime.events import (
    LOGGER_NAME,
    configure_acquisition_runtime_logging,
)
from signals.acquisition_runtime.execution import build_runtime_execution_composition
from signals.persistence.schema import METADATA, acquisition_provider_operation

__all__ = ["engine", "production_arguments", "seeded_french_opportunity"]

_STAGES_BEFORE_PROVIDER_HANDOFF = tuple(AcquisitionRuntimeStage)[
    : tuple(AcquisitionRuntimeStage).index(AcquisitionRuntimeStage.PROVIDER_HANDOFF)
]


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


def _canary_domain_builder(
    *,
    instantly_double: MutationTrackingInstantlyProvider,
    executed_stages: list[AcquisitionRuntimeStage],
):
    """One fake handler per stage — the `test_fake_full_cycle_...` pattern.

    Every stage succeeds immediately except that `PROVIDER_HANDOFF`'s handler
    is a canary: if the runner or registry guard were ever bypassed and this
    handler actually dispatched, it attempts an Instantly mutation the way
    the real domain's `handoff_provider` would (`create_lead_or_batch`, one of
    `ADD_LEAD`'s real operations) — turning a bypassed guard into a recorded
    mutating call and a hard failure, not a quiet pass.
    """

    def handler(context) -> RuntimeActionResult:
        executed_stages.append(context.stage)
        if context.stage is AcquisitionRuntimeStage.PROVIDER_HANDOFF:
            instantly_double.create_lead_or_batch(
                provider_campaign_id="canary-campaign-ref", leads=()
            )
        return RuntimeActionResult(
            status=RuntimeStageStatus.SUCCEEDED,
            result_refs=(f"result:{context.stage.value.lower()}",),
            reason_codes=("STAGE_COMPLETE",),
        )

    def build(**_kwargs) -> SimpleNamespace:
        return SimpleNamespace(
            handlers={stage: handler for stage in AcquisitionRuntimeStage}
        )

    return build


@pytest.fixture
def production_engine(engine: sa.Engine) -> sa.Engine:
    """The shared production engine, extended with the full domain schema.

    `test_acquisition_runtime_execution_production._engine()` only creates the
    tables its own (composition-only) tests need — it never runs a cycle.
    Invariant 5 runs one for real (lease/cycle/stage bookkeeping is real; only
    the domain handlers are faked), which reaches live tables beyond that
    helper's list. `create_all` is idempotent, so this only adds what is
    missing.
    """

    METADATA.create_all(engine)
    return engine


@pytest.fixture
def instantly_double() -> MutationTrackingInstantlyProvider:
    return MutationTrackingInstantlyProvider()


@pytest.fixture
def executed_stages() -> list[AcquisitionRuntimeStage]:
    return []


@pytest.fixture
def production_composition(
    production_arguments: dict[str, object],
    production_engine: sa.Engine,
    instantly_double: MutationTrackingInstantlyProvider,
    executed_stages: list[AcquisitionRuntimeStage],
    seeded_french_opportunity: str,
):
    """Task 6/6B's real production montage, with a canary domain builder.

    Every argument except `domain_builder` and `instantly_provider` is the
    real production boundary: real runtime/connectivity config, real webhook
    configuration, real Hermes double, real dependency probe, real clock, and
    a real store bound to `production_engine`. Only the domain layer (the
    business stage handlers) is faked, deterministically, so the cycle can
    reach `PROVIDER_HANDOFF` without needing a live-credentialed Apollo.
    """

    arguments = dict(production_arguments)
    arguments["instantly_provider"] = instantly_double
    arguments["domain_builder"] = _canary_domain_builder(
        instantly_double=instantly_double, executed_stages=executed_stages
    )
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
    production_composition,
    production_engine,
    instantly_double,
    executed_stages,
) -> None:
    """Invariant 5: every provider mutation counter is zero at cycle end."""

    result = _run_once(production_composition)

    # Prove presence of the OPPORTUNITY to mutate — not merely presence of a
    # cycle. The cycle must genuinely reach PROVIDER_HANDOFF, the one stage
    # capable of a provider mutation, and be blocked there by the production
    # guard — not stopped several stages early, and not by a crash.
    assert result.stage is AcquisitionRuntimeStage.PROVIDER_HANDOFF, (
        f"the cycle never reached the mutating stage (stopped at "
        f"{result.stage!r}); a zero mutation count would prove nothing"
    )
    assert result.status is RuntimeRunStatus.WAITING
    assert result.reason_code == "QA_PROVIDER_MUTATION_NOT_AUTHORIZED", (
        "the cycle stopped at the mutating stage, but not for the production "
        "guard's own reason — that is a different finding"
    )
    # The seven stages before it, including CAMPAIGN, genuinely ran; the
    # canary handler for PROVIDER_HANDOFF itself was never dispatched.
    assert executed_stages == list(_STAGES_BEFORE_PROVIDER_HANDOFF)

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

    # Prove presence before proving absence — an empty journal, or one that
    # only covers the first stage or two, would make every forbidden-string
    # assertion below pass vacuously. The journal must cover the stages most
    # likely to carry contact data, prompts or provider payloads in the real
    # domain: contact discovery, personalization, campaign planning, and the
    # provider handoff itself.
    assert journal.strip() != "", "the journal captured nothing for a real cycle"
    for stage_name in (
        "CONTACT_DISCOVERY",
        "PERSONALIZATION",
        "CAMPAIGN",
        "PROVIDER_HANDOFF",
    ):
        assert stage_name in journal, f"the journal never reached {stage_name}"

    assert "@" not in journal
    forbidden = (
        "api_key",
        "bearer ",
        "password",
        "prompt",
        "completion",
        # Every secret configured anywhere in this montage — Apollo/Instantly
        # API keys, the webhook route secret, the attribution/suppression/
        # response fingerprint keys — shares this literal prefix by fixture
        # convention (see `_connectivity_config`/`_webhook_configuration` in
        # `test_acquisition_runtime_execution_production.py`).
        "synthetic-",
        # What contact discovery, personalization and campaign planning could
        # plausibly leak in the real domain: a source or provider URL, or a
        # decision-maker's LinkedIn profile.
        "http://",
        "https://",
        "linkedin",
    )
    for term in forbidden:
        assert term not in journal.lower(), f"forbidden term leaked: {term!r}"
