from __future__ import annotations

import importlib
import io
import json
import logging

import pytest

from signals.api.config import ApiConfig

LOGGER_NAME = "signals.runtime_events"


@pytest.fixture(autouse=True)
def isolated_runtime_logger():
    logger = logging.getLogger(LOGGER_NAME)
    previous_handlers = logger.handlers[:]
    previous_level = logger.level
    previous_propagate = logger.propagate
    logger.handlers.clear()
    try:
        yield logger
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers[:] = previous_handlers
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


def _configured_environment(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    values = {
        "KIVOU_DATABASE_URL": f"sqlite+pysqlite:///{tmp_path / 'runtime-events.db'}",
        "KIVOU_ALLOWED_ORIGIN": "https://staging.kivou.test",
        "KIVOU_PUBLIC_APP_URL": "https://staging.kivou.test",
        "KIVOU_STRIPE_MODE": "test",
        "SMTP_HOST": "smtp.kivou.test",
        "SMTP_PORT": "587",
        "SMTP_FROM_EMAIL": "no-reply@kivou.eu",
        "SMTP_TLS_MODE": "starttls",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    for name in ("SMTP_USERNAME", "SMTP_PASSWORD", "STRIPE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)


def _runtime_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [
        handler
        for handler in logger.handlers
        if getattr(handler, "_kivou_runtime_events", False)
    ]


def test_runtime_handler_is_dedicated_and_idempotent(isolated_runtime_logger) -> None:
    from signals.runtime_events import configure_runtime_event_logging

    root = logging.getLogger()
    billing = logging.getLogger("signals.billing")
    root_handlers = root.handlers[:]
    billing_handlers = billing.handlers[:]
    stream = io.StringIO()

    first = configure_runtime_event_logging(stream=stream)
    second = configure_runtime_event_logging(stream=stream)

    assert first is second is isolated_runtime_logger
    assert len(_runtime_handlers(first)) == 1
    assert first.propagate is False
    assert root.handlers == root_handlers
    assert billing.handlers == billing_handlers


def test_asgi_build_really_wires_safe_reset_delivery_events(
    isolated_runtime_logger,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys,
) -> None:
    from signals.alerts.gateway import AlertDeliveryError

    _configured_environment(monkeypatch, tmp_path)
    module = importlib.import_module("signals.api.asgi")

    private_email = "private-recipient" + "@kivou.test"
    private_token = "private-reset-token"
    private_body = "private-message-body"
    private_url = "https://private.example/reset?token=private-reset-token"
    private_ip = "192.0.2.42"
    private_secret = "smtp-private-secret"

    class FailingGateway:
        def __init__(self, _configuration) -> None:
            pass

        def send(self, _message):
            raise AlertDeliveryError("smtp_unavailable", retryable=True) from RuntimeError(
                f"{private_email} {private_body} {private_url} {private_ip} {private_secret}"
            )

    monkeypatch.setattr(module, "SmtpAlertGateway", FailingGateway)

    app = module.build_application()
    app.state.password_reset_delivery.deliver(
        email=private_email,
        locale="fr",
        reset_token=private_token,
    )

    assert len(_runtime_handlers(isolated_runtime_logger)) == 1
    payload = json.loads(capsys.readouterr().err.strip())
    assert payload == {
        "attempt": 1,
        "channel": "password_reset",
        "code": "smtp_unavailable",
        "event": "delivery",
        "retryable": True,
        "status": "failed",
    }
    rendered = json.dumps(payload, sort_keys=True)
    for forbidden in (
        private_email,
        private_token,
        private_body,
        private_url,
        private_ip,
        private_secret,
        "RuntimeError",
        "Traceback",
    ):
        assert forbidden not in rendered


def test_cli_configures_the_same_channel_without_touching_other_loggers(
    isolated_runtime_logger,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from signals.alerts import cli

    _configured_environment(monkeypatch, tmp_path)
    root = logging.getLogger()
    billing = logging.getLogger("signals.billing")
    root_handlers = root.handlers[:]
    billing_handlers = billing.handlers[:]

    assert cli.main(["--dry-run"]) == 0
    assert cli.main(["--dry-run"]) == 0

    assert len(_runtime_handlers(isolated_runtime_logger)) == 1
    assert root.handlers == root_handlers
    assert billing.handlers == billing_handlers


def test_runtime_event_schema_has_no_arbitrary_data_escape_hatch() -> None:
    from signals.runtime_events import emit_delivery_event

    with pytest.raises(TypeError):
        emit_delivery_event(
            channel="alert",
            status="failed",
            code="smtp_450",
            retryable=True,
            attempt=1,
            exception=RuntimeError("private"),
        )


def test_reset_submission_is_described_as_submission_not_receipt(
    isolated_runtime_logger,
) -> None:
    from signals.accounts.reset_delivery import SmtpPasswordResetDelivery
    from signals.alerts.gateway import DeliveryResult
    from signals.runtime_events import configure_runtime_event_logging

    stream = io.StringIO()
    configure_runtime_event_logging(stream=stream)

    class AcceptedGateway:
        def send(self, message):
            return DeliveryResult(provider_message_id=message.message_id)

    delivery = SmtpPasswordResetDelivery(
        AcceptedGateway(),
        site_url=ApiConfig(public_app_url="https://staging.kivou.test").public_site_url
        or "",
        ttl=ApiConfig().password_reset_ttl,
    )
    delivery.deliver(
        email="synthetic-user@kivou.test",
        locale="fr",
        reset_token="synthetic-reset-token",
    )

    payload = json.loads(stream.getvalue())
    assert payload["status"] == "submitted"
    assert payload["code"] == "smtp_submission_accepted"
    assert "delivered" not in stream.getvalue()
    assert "received" not in stream.getvalue()
