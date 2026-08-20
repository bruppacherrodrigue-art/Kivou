from pathlib import Path


def test_contact_discovery_has_no_customer_private_or_outbound_dependency() -> None:
    package = Path("src/signals/contact_discovery")
    source = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))

    assert "target_icp" not in source.casefold()
    assert "materialized_signal" not in source
    assert "signal_feedback" not in source
    assert "billing" not in source.casefold()
    assert "instantly" not in source.casefold()
    assert "smtp" not in source.casefold()
    assert 'reveal_phone_number", "true' not in source
    assert 'reveal_personal_emails", "true' not in source
