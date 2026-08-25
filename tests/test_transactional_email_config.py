from __future__ import annotations

import pytest

from signals.api.config import ApiConfig

EMAIL_ENVIRONMENT_NAMES = (
    "KIVOU_PUBLIC_APP_URL",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM_EMAIL",
    "SMTP_FROM_NAME",
    "SMTP_USE_TLS",
    "SMTP_TLS_MODE",
    "SMTP_TIMEOUT_SECONDS",
    "SMTP_REPLY_TO_EMAIL",
    "KIVOU_ALERT_LEASE_SECONDS",
    "KIVOU_ALERT_MAX_ATTEMPTS",
    "KIVOU_ALERT_RETRY_BASE_SECONDS",
)


@pytest.fixture(autouse=True)
def clean_email_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in EMAIL_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)


def configure_public_origin(
    monkeypatch: pytest.MonkeyPatch,
    *,
    public: str = "https://staging.kivou.test",
    allowed: str = "https://staging.kivou.test",
) -> None:
    monkeypatch.setenv("KIVOU_ALLOWED_ORIGIN", allowed)
    monkeypatch.setenv("KIVOU_PUBLIC_APP_URL", public)


def configure_complete_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_public_origin(monkeypatch)
    values = {
        "SMTP_HOST": "smtp.kivou.test",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "sender@kivou.eu",
        "SMTP_PASSWORD": "smtp-secret-never-render",
        "SMTP_FROM_EMAIL": "no-reply@kivou.eu",
        "SMTP_FROM_NAME": "Kivou",
        "SMTP_TLS_MODE": "starttls",
        "SMTP_TIMEOUT_SECONDS": "12",
        "SMTP_REPLY_TO_EMAIL": "support@kivou.eu",
        "KIVOU_ALERT_LEASE_SECONDS": "1800",
        "KIVOU_ALERT_MAX_ATTEMPTS": "5",
        "KIVOU_ALERT_RETRY_BASE_SECONDS": "900",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize(
    "value",
    [
        "http://staging.kivou.test",
        "https://user:secret@staging.kivou.test",
        "https://staging.kivou.test/app",
        "https://staging.kivou.test?next=https://evil.example",
        "https://staging.kivou.test#fragment",
    ],
)
def test_public_origin_rejects_unsafe_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    configure_public_origin(monkeypatch, public=value)

    with pytest.raises(ValueError, match="KIVOU_PUBLIC_APP_URL"):
        ApiConfig.from_environment()


def test_public_origin_must_match_the_allowed_deployment_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_public_origin(
        monkeypatch,
        public="https://staging.kivou.test",
        allowed="https://kivou.test",
    )

    with pytest.raises(ValueError, match="origine autorisée"):
        ApiConfig.from_environment()


def test_public_origin_is_normalized_without_a_trailing_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_public_origin(
        monkeypatch,
        public="https://staging.kivou.test/",
        allowed="https://staging.kivou.test",
    )

    config = ApiConfig.from_environment()

    assert config.public_app_url == "https://staging.kivou.test"
    assert config.public_site_url == "https://staging.kivou.test"


def transactional_links():
    try:
        from signals.transactional_email import links
    except ModuleNotFoundError:
        pytest.fail("la frontière de liens transactionnels n'existe pas encore")
    return links


def test_reset_link_stays_at_the_public_site_root() -> None:
    links = transactional_links()

    assert links.reset_url("https://staging.kivou.test", "a+b") == (
        "https://staging.kivou.test/reset-password?token=a%2Bb"
    )


def test_signal_link_adds_the_protected_application_route() -> None:
    links = transactional_links()

    assert links.signal_url("https://staging.kivou.test", "sig/opaque") == (
        "https://staging.kivou.test/app/signals/sig%2Fopaque"
    )


def test_preferences_link_adds_the_protected_application_route() -> None:
    links = transactional_links()

    assert links.preferences_url("https://staging.kivou.test") == (
        "https://staging.kivou.test/app/notifications"
    )


def test_password_reset_delivery_reuses_the_shared_link_builder() -> None:
    from signals.accounts.reset_delivery import reset_link
    from signals.transactional_email.links import reset_url

    assert reset_link is reset_url


def test_an_entirely_absent_smtp_configuration_remains_disabled() -> None:
    config = ApiConfig.from_environment()

    assert config.alerts_configured is False
    assert config.password_reset_email_configured is False


def test_complete_smtp_configuration_is_typed_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_complete_smtp(monkeypatch)

    config = ApiConfig.from_environment()

    assert config.alerts_configured is True
    assert config.smtp_tls_mode == "starttls"
    assert config.smtp_timeout_seconds == 12
    assert config.smtp_reply_to_email == "support@kivou.eu"
    assert config.alert_lease_ttl.total_seconds() == 1800
    assert config.alert_max_attempts == 5
    assert config.alert_retry_base.total_seconds() == 900
    assert "smtp-secret-never-render" not in repr(config)


def test_alert_job_lease_outlives_the_versioned_service_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_complete_smtp(monkeypatch)
    monkeypatch.setenv("KIVOU_ALERT_LEASE_SECONDS", "1799")

    with pytest.raises(ValueError, match="KIVOU_ALERT_LEASE_SECONDS"):
        ApiConfig.from_environment()


@pytest.mark.parametrize("missing", ["SMTP_HOST", "SMTP_FROM_EMAIL", "SMTP_TLS_MODE"])
def test_partial_smtp_configuration_disables_email_without_stopping_the_api(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """Une variable SMTP absente rend l'E-MAIL indisponible, jamais l'API.

    Ce test affirmait l'inverse — un échec fermé au démarrage. Il tombait juste
    tant qu'on ne regardait que l'e-mail ; mais `ApiConfig.from_environment()`
    est ce que construit `asgi.build_application()`, donc lever ici emportait
    le feed, la facturation et l'authentification avec le transport. Staging
    portait précisément une de ces configurations : le déploiement aurait été
    une panne totale, pas une dégradation.

    Le défaut fermé demeure là où il compte : `host` reste `None`, donc AUCUN
    envoi n'est tenté, et aucun mode de chiffrement n'est supposé.
    """
    configure_complete_smtp(monkeypatch)
    monkeypatch.delenv(missing)

    config = ApiConfig.from_environment()

    assert config.smtp_host is None, "aucun envoi ne doit être possible"
    assert config.smtp_unavailable_reason is not None
    assert missing in config.smtp_unavailable_reason


def test_username_and_password_are_required_as_a_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_complete_smtp(monkeypatch)
    monkeypatch.delenv("SMTP_PASSWORD")

    with pytest.raises(ValueError, match="ensemble"):
        ApiConfig.from_environment()


@pytest.mark.parametrize("mode", ["none", "tls", "false"])
def test_smtp_refuses_an_unencrypted_or_implicit_mode_name(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    configure_complete_smtp(monkeypatch)
    monkeypatch.setenv("SMTP_TLS_MODE", mode)

    with pytest.raises(ValueError, match="SMTP_TLS_MODE"):
        ApiConfig.from_environment()


def test_an_empty_tls_mode_is_treated_as_absent_not_as_a_bad_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une variable vide n'est pas un mode mal orthographié : elle est absente.

    La distinction compte : un nom DÉCLARÉ mais invalide reste une erreur
    bruyante — l'exploitant a exprimé une intention fausse. Une variable vide,
    elle, n'exprime rien, et ne doit pas emporter l'API avec elle.
    """
    configure_complete_smtp(monkeypatch)
    monkeypatch.setenv("SMTP_TLS_MODE", "")

    config = ApiConfig.from_environment()

    assert config.smtp_host is None
    assert config.smtp_tls_mode is None, "aucun mode n'est supposé"
    assert "SMTP_TLS_MODE" in (config.smtp_unavailable_reason or "")


def test_smtp_accepts_explicit_implicit_tls(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_complete_smtp(monkeypatch)
    monkeypatch.setenv("SMTP_TLS_MODE", "implicit_tls")

    assert ApiConfig.from_environment().smtp_tls_mode == "implicit_tls"


@pytest.mark.parametrize("timeout", ["0", "0.5", "61", "not-a-number"])
def test_smtp_timeout_is_bounded(
    monkeypatch: pytest.MonkeyPatch, timeout: str
) -> None:
    configure_complete_smtp(monkeypatch)
    monkeypatch.setenv("SMTP_TIMEOUT_SECONDS", timeout)

    with pytest.raises(ValueError, match="SMTP_TIMEOUT_SECONDS"):
        ApiConfig.from_environment()


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_smtp_port_is_bounded(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    configure_complete_smtp(monkeypatch)
    monkeypatch.setenv("SMTP_PORT", port)

    with pytest.raises(ValueError, match="SMTP_PORT"):
        ApiConfig.from_environment()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SMTP_FROM_EMAIL", "not-an-email"),
        ("SMTP_REPLY_TO_EMAIL", "not-an-email"),
    ],
)
def test_smtp_addresses_are_validated(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    configure_complete_smtp(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        ApiConfig.from_environment()
