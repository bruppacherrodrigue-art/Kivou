"""Public MX evidence never becomes a positive claim on DNS uncertainty."""

import datetime as dt

import pytest

from signals.acquisition_programs.mail_provider import (
    MailProvider,
    MailProviderDetector,
    normalize_domain,
)

NOW = dt.datetime(2026, 9, 21, 10, tzinfo=dt.UTC)


class FakeResolver:
    def __init__(self, answers: list[tuple[str, ...] | Exception]) -> None:
        self.answers = iter(answers)
        self.calls = 0

    def mx(self, domain: str, *, timeout: float) -> tuple[str, ...]:
        self.calls += 1
        answer = next(self.answers)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.mark.parametrize("value", ["https://example.fr", "1.2.3.4", "bad..fr", "localhost", "a@b.fr", "example.fr/path", "-bad.fr"])
def test_invalid_domain_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_domain(value)


def test_domain_normalization_and_gmail_consumer() -> None:
    assert normalize_domain(" Example.FR. ") == "example.fr"
    resolver = FakeResolver([])
    result = MailProviderDetector(resolver).detect_email("founder@gmail.com", observed_at=NOW)
    assert result.provider is MailProvider.GMAIL_CONSUMER
    assert result.confidence == "CONFIRMED"
    assert resolver.calls == 0


@pytest.mark.parametrize("mx", [("smtp.google.com.",), ("aspmx.l.google.com.", "alt1.aspmx.l.google.com."), ("alt4.aspmx.l.google.com",)])
def test_google_workspace_new_and_legacy_mx(mx: tuple[str, ...]) -> None:
    result = MailProviderDetector(FakeResolver([mx])).detect_domain("agency.fr", observed_at=NOW)
    assert result.provider is MailProvider.GOOGLE_WORKSPACE
    assert result.confidence == "CONFIRMED"
    assert result.mx_records == tuple(sorted(item.rstrip(".") for item in mx))


def test_microsoft_other_mixed_and_absent() -> None:
    answers = [
        (("agency-fr.mail.protection.outlook.com",), MailProvider.MICROSOFT_365),
        (("mx.otherhost.fr",), MailProvider.OTHER),
        (("smtp.google.com", "mx.otherhost.fr"), MailProvider.UNKNOWN),
        ((), MailProvider.UNKNOWN),
    ]
    for mx, expected in answers:
        result = MailProviderDetector(FakeResolver([mx])).detect_domain("agency.fr", observed_at=NOW)
        assert result.provider is expected


def test_timeout_never_positive_and_expired_cache_requeries() -> None:
    resolver = FakeResolver([TimeoutError(), ("smtp.google.com",)])
    detector = MailProviderDetector(resolver, ttl_seconds=60, attempts=1)
    first = detector.detect_domain("agency.fr", observed_at=NOW)
    assert first.provider is MailProvider.UNKNOWN
    assert detector.detect_domain("agency.fr", observed_at=NOW + dt.timedelta(seconds=59)) == first
    assert resolver.calls == 1
    second = detector.detect_domain("agency.fr", observed_at=NOW + dt.timedelta(seconds=60))
    assert second.provider is MailProvider.GOOGLE_WORKSPACE
    assert resolver.calls == 2


def test_cache_never_serves_an_observation_from_the_future() -> None:
    resolver = FakeResolver([("smtp.google.com",), ("mx.otherhost.fr",)])
    detector = MailProviderDetector(resolver)
    detector.detect_domain("agency.fr", observed_at=NOW + dt.timedelta(hours=1))
    earlier = detector.detect_domain("agency.fr", observed_at=NOW)
    assert earlier.provider is MailProvider.OTHER
    assert earlier.observed_at == NOW
    assert resolver.calls == 2
