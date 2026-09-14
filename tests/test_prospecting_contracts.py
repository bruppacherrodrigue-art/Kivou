"""V11 field rights are independent of presentation flags and server projected."""

import json

from signals.billing.catalogue import entitlements_for
from signals.client_value.capabilities import company_capabilities, project_directory


def directory():
    return {
        "siren": "331364729",
        "name": "Exemple béton",
        "city": "Nice",
        "employees": 19,
        "directors": [{"name": "Alice Exemple"}],
        "website_url": "https://example.test/",
        "phone": "04 93 12 34 56",
        "published_email": "contact@example.test",
        "source": "registre",
        "published_email_source_url": "https://example.test/contact",
        "removal_path": "/contact",
    }


def test_discovery_projection_contains_no_protected_values():
    result = project_directory(directory(), entitlements=entitlements_for("discovery"))
    encoded = json.dumps(result)
    for private in ("Alice Exemple", "example.test", "04 93 12 34 56", '"employees": 19'):
        assert private not in encoded
    assert result["name"] == "Exemple béton"
    assert set(result["available_fields"]) == {
        "workforce",
        "directors",
        "website",
        "phone",
        "email",
    }
    assert result["fields_locked"] is True


def test_paid_projection_preserves_safe_sources_and_workforce_precision():
    for plan in ("essential", "pro"):
        result = project_directory(directory(), entitlements=entitlements_for(plan))
        assert result["published_email"] == "contact@example.test"
        assert result["phone"] == "04 93 12 34 56"
        assert "employees" not in result
        assert result["workforce"] == {"minimum": 10, "maximum": 19, "precision": "range"}
        assert result["fields_locked"] is False


def test_missing_or_invalid_data_is_not_promised_by_an_upsell():
    result = project_directory(
        {"siren": "331364729", "name": "Exemple", "phone": "04 93", "source": "registre"},
        entitlements=entitlements_for("discovery"),
    )
    assert result["available_fields"] == []
    assert "phone" not in result


def test_company_capabilities_use_entitlements_not_layout_or_plan_label():
    discovery = company_capabilities(entitlements_for("discovery"), lookup_available=False)
    paid = company_capabilities(entitlements_for("essential"), lookup_available=False)
    assert discovery["can_view_company_data"] is False
    assert paid["can_view_company_data"] is True
    assert paid["can_lookup_contact"] is False
    assert discovery["can_manage_personal_contact"] is True
