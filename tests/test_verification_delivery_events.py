"""Delivery receipts keep the security-mail channel, but no recipient or bearer."""
import logging

from test_email_verification import EMAIL, request_proof

from signals.runtime_events import LOGGER_NAME

pytest_plugins = ("test_email_verification",)


def test_verification_submission_has_a_safe_recognized_receipt(prepared_email):
    _, client, _, _, _ = prepared_email
    events = []

    class Capture(logging.Handler):
        def emit(self, record):
            events.append(record.runtime_event)

    logger = logging.getLogger(LOGGER_NAME)
    handler = Capture()
    level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        assert request_proof(client).status_code == 200
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)
    assert len(events) == 1
    assert events[0]["channel"] == "email_verification"
    assert events[0]["status"] == "submitted"
    assert events[0]["code"] == "smtp_submission_accepted"
    assert EMAIL not in str(events)
    assert "token" not in str(events)
