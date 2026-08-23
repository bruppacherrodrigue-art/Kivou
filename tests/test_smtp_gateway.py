from __future__ import annotations

import email
import smtplib
import socket
import ssl
import types
from typing import ClassVar

import pytest
import trustme
from aiosmtpd.controller import Controller

from signals.alerts.gateway import (
    AlertDeliveryError,
    AlertMessage,
    SmtpAlertGateway,
    SmtpConfiguration,
    UncertainDelivery,
)


class CapturingHandler:
    def __init__(self) -> None:
        self.messages: list[bytes] = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(envelope.content)
        return "250 accepted"


@pytest.fixture
def starttls_server():
    ca = trustme.CA()
    certificate = ca.issue_cert("127.0.0.1")
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    certificate.configure_cert(server_context)
    client_context = ssl.create_default_context()
    ca.configure_trust(client_context)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    handler = CapturingHandler()
    controller = Controller(
        handler,
        hostname="127.0.0.1",
        port=port,
        tls_context=server_context,
        require_starttls=True,
    )
    controller.start()
    try:
        yield types.SimpleNamespace(
            port=port,
            messages=handler.messages,
            client_context=client_context,
        )
    finally:
        controller.stop()


def sample_message() -> AlertMessage:
    return AlertMessage(
        to_email="recipient@kivou.eu",
        subject="Test transactionnel",
        text_body="Message synthétique",
        message_id="<test-transactional@kivou.eu>",
        language="fr",
    )


def configuration(**overrides) -> SmtpConfiguration:
    values = {
        "host": "smtp.kivou.test",
        "port": 587,
        "from_email": "no-reply@kivou.eu",
        "tls_mode": "starttls",
        "timeout_seconds": 3,
    }
    values.update(overrides)
    return SmtpConfiguration(**values)


class RecordingSmtp:
    calls: ClassVar[list[tuple[str, int, int]]] = []
    logins: ClassVar[list[tuple[str, str]]] = []
    started_tls = 0
    send_failure: Exception | None = None
    tls_failure: Exception | None = None

    @classmethod
    def reset(cls) -> None:
        cls.calls = []
        cls.logins = []
        cls.started_tls = 0
        cls.send_failure = None
        cls.tls_failure = None

    def __init__(self, host, port, *, timeout):
        self.calls.append((host, port, timeout))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self, *, context):
        type(self).started_tls += 1
        if self.tls_failure is not None:
            raise self.tls_failure
        return 220, b"ready"

    def login(self, username, password):
        self.logins.append((username, password))

    def send_message(self, message):
        if self.send_failure is not None:
            raise self.send_failure
        return {}


class RecordingSmtpSsl(RecordingSmtp):
    contexts: ClassVar[list[ssl.SSLContext]] = []

    @classmethod
    def reset(cls) -> None:
        super().reset()
        cls.contexts = []

    def __init__(self, host, port, *, timeout, context):
        super().__init__(host, port, timeout=timeout)
        self.contexts.append(context)


@pytest.fixture(autouse=True)
def reset_recorders() -> None:
    RecordingSmtp.reset()
    RecordingSmtpSsl.reset()


def test_starttls_delivers_once_to_the_loopback_server(starttls_server) -> None:
    gateway = SmtpAlertGateway(
        configuration(
            host="127.0.0.1",
            port=starttls_server.port,
            reply_to_email="support@kivou.eu",
        ),
        ssl_context=starttls_server.client_context,
    )

    gateway.send(sample_message())

    assert len(starttls_server.messages) == 1
    parsed = email.message_from_bytes(starttls_server.messages[0])
    assert parsed["Reply-To"] == "support@kivou.eu"
    assert parsed["Message-ID"] == sample_message().message_id
    assert parsed["Auto-Submitted"] == "auto-generated"


def test_implicit_tls_uses_smtp_ssl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP_SSL", RecordingSmtpSsl)
    context = ssl.create_default_context()

    SmtpAlertGateway(
        configuration(port=465, tls_mode="implicit_tls"), ssl_context=context
    ).send(sample_message())

    assert RecordingSmtpSsl.calls == [("smtp.kivou.test", 465, 3)]
    assert RecordingSmtpSsl.contexts == [context]
    assert RecordingSmtpSsl.started_tls == 0


def test_starttls_uses_the_configured_timeout_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smtplib, "SMTP", RecordingSmtp)
    context = ssl.create_default_context()

    SmtpAlertGateway(configuration(timeout_seconds=7), ssl_context=context).send(
        sample_message()
    )

    assert RecordingSmtp.calls == [("smtp.kivou.test", 587, 7)]
    assert RecordingSmtp.started_tls == 1


def test_authentication_uses_the_configured_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", RecordingSmtp)

    SmtpAlertGateway(
        configuration(username="sender@kivou.eu", password="smtp-secret")
    ).send(sample_message())

    assert RecordingSmtp.logins == [("sender@kivou.eu", "smtp-secret")]


@pytest.mark.parametrize(("code", "retryable"), [(451, True), (550, False)])
def test_smtp_response_classification(
    monkeypatch: pytest.MonkeyPatch, code: int, retryable: bool
) -> None:
    RecordingSmtp.send_failure = smtplib.SMTPDataError(code, b"private response")
    monkeypatch.setattr(smtplib, "SMTP", RecordingSmtp)

    with pytest.raises(AlertDeliveryError) as raised:
        SmtpAlertGateway(configuration()).send(sample_message())

    assert raised.value.retryable is retryable
    assert raised.value.code == f"smtp_{code}"
    assert "private" not in str(raised.value)


def test_disconnect_during_message_submission_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordingSmtp.send_failure = smtplib.SMTPServerDisconnected("private response")
    monkeypatch.setattr(smtplib, "SMTP", RecordingSmtp)

    with pytest.raises(UncertainDelivery) as raised:
        SmtpAlertGateway(configuration()).send(sample_message())

    assert raised.value.code == "unknown_delivery_state"
    assert "private" not in str(raised.value)


def test_timeout_during_message_submission_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    RecordingSmtp.send_failure = TimeoutError("private endpoint")
    monkeypatch.setattr(smtplib, "SMTP", RecordingSmtp)

    with pytest.raises(UncertainDelivery) as raised:
        SmtpAlertGateway(configuration()).send(sample_message())

    assert raised.value.code == "unknown_delivery_state"
    assert "private" not in str(raised.value)


def test_connection_refusal_before_submission_is_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refused(*args, **kwargs):
        raise ConnectionRefusedError("private endpoint")

    monkeypatch.setattr(smtplib, "SMTP", refused)

    with pytest.raises(AlertDeliveryError) as raised:
        SmtpAlertGateway(configuration()).send(sample_message())

    assert raised.value.code == "smtp_unavailable"
    assert raised.value.retryable is True
    assert "private" not in str(raised.value)


def test_tls_failure_is_terminal_and_secret_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    RecordingSmtp.tls_failure = ssl.SSLError("private certificate detail")
    monkeypatch.setattr(smtplib, "SMTP", RecordingSmtp)

    with pytest.raises(AlertDeliveryError) as raised:
        SmtpAlertGateway(configuration()).send(sample_message())

    assert raised.value.code == "smtp_tls_failed"
    assert raised.value.retryable is False
    assert "private" not in str(raised.value)


def test_smtp_configuration_repr_never_contains_the_password() -> None:
    configured = configuration(password="smtp-secret-never-render")

    assert "smtp-secret-never-render" not in repr(configured)
