from __future__ import annotations

import io
import json
import logging

from signals.acquisition_runtime.events import (
    LOGGER_NAME,
    configure_acquisition_runtime_logging,
    emit_acquisition_runtime_event,
)


def _isolated_stream() -> io.StringIO:
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    stream = io.StringIO()
    configure_acquisition_runtime_logging(stream=stream)
    return stream


def test_runtime_event_contains_only_machine_state_and_opaque_refs() -> None:
    stream = _isolated_stream()

    emit_acquisition_runtime_event(
        action="stage",
        status="succeeded",
        code="STAGE_COMPLETED",
        cycle_ref="a" * 64,
        stage="SUPPLIER_DISCOVERY",
        attempt=2,
    )

    assert json.loads(stream.getvalue()) == {
        "action": "stage",
        "attempt": 2,
        "code": "STAGE_COMPLETED",
        "cycle_ref": "a" * 64,
        "event": "acquisition_runtime",
        "stage": "SUPPLIER_DISCOVERY",
        "status": "succeeded",
    }


def test_runtime_event_rejects_pii_urls_and_arbitrary_codes() -> None:
    stream = _isolated_stream()

    emit_acquisition_runtime_event(
        action="stage",
        status="failed",
        code="secret=value",
        cycle_ref="person@example.test",
        stage="https://provider.example/private",
        attempt=-9,
    )

    payload = json.loads(stream.getvalue())
    assert payload == {
        "action": "stage",
        "attempt": 0,
        "code": "INVALID_RUNTIME_VALUE",
        "cycle_ref": "invalid_ref",
        "event": "acquisition_runtime",
        "stage": "INVALID_STAGE",
        "status": "failed",
    }
    assert "person@" not in stream.getvalue()
    assert "provider.example" not in stream.getvalue()
    assert "secret=value" not in stream.getvalue()


def test_direct_logger_call_cannot_bypass_the_closed_schema() -> None:
    stream = _isolated_stream()

    logging.getLogger(LOGGER_NAME).error(
        "private@example.test provider-secret",
        extra={"runtime_event": {"payload": "private@example.test"}},
    )

    assert json.loads(stream.getvalue()) == {
        "action": "runtime",
        "attempt": 0,
        "code": "INVALID_RUNTIME_EVENT",
        "event": "acquisition_runtime",
        "status": "failed",
    }
    assert "private@example.test" not in stream.getvalue()
    assert "provider-secret" not in stream.getvalue()


def test_logging_configuration_is_idempotent_and_does_not_propagate() -> None:
    stream = _isolated_stream()
    first = configure_acquisition_runtime_logging(stream=stream)
    second = configure_acquisition_runtime_logging(stream=stream)

    assert first is second
    assert len(first.handlers) == 1
    assert first.propagate is False
