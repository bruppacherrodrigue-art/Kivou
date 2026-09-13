"""Server-owned V11 field projection, independent of any layout switch.

Input directory values must already have passed the existing provenance and
suppression policy. This final boundary only removes rights and rejects
unusable fields; it cannot make a provider/model email publishable.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from signals.billing.catalogue import PlanEntitlements

_PREMIUM_FIELDS = frozenset(
    {
        "employees",
        "workforce",
        "directors",
        "directors_observed_at",
        "director_display_name",
        "director_display_title",
        "website_url",
        "website_source",
        "website_observed_at",
        "phone",
        "phone_source",
        "phone_observed_at",
        "published_email",
        "published_email_source_url",
        "published_email_observed_at",
        "contact_observed_at",
        "register_observed_at",
    }
)
_BANDS = {
    0: 0,
    2: 1,
    5: 3,
    9: 6,
    19: 10,
    49: 20,
    99: 50,
    199: 100,
    249: 200,
    499: 250,
    999: 500,
    1999: 1000,
    4999: 2000,
    9999: 5000,
}


def company_capabilities(
    entitlements: PlanEntitlements, *, lookup_available: bool
) -> dict[str, bool]:
    return {
        "can_view_company_data": entitlements.is_paid,
        "can_enrich_company": entitlements.is_paid,
        "can_lookup_contact": entitlements.is_paid and lookup_available,
        "can_manage_personal_contact": True,
        "can_take_notes": True,
        "can_follow_company": True,
    }


def usable_phone(value: object) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"[+\d\s().-]+", value):
        return None
    digits = re.sub(r"\D", "", value)
    return value.strip() if 9 <= len(digits) <= 15 else None


def project_directory(
    directory: Mapping[str, Any] | None, *, entitlements: PlanEntitlements
) -> dict[str, Any] | None:
    if directory is None:
        return None
    result = dict(directory)
    phone = usable_phone(result.get("phone"))
    if phone:
        result["phone"] = phone
    else:
        for key in ("phone", "phone_source", "phone_observed_at"):
            result.pop(key, None)
    employees = result.pop("employees", None)
    if isinstance(employees, int) and not isinstance(employees, bool) and employees >= 0:
        # The directory's SIRENE number stores the upper edge of a band.
        # Unknown historical values are labelled estimates, never exact headcount.
        result["workforce"] = (
            {"minimum": _BANDS[employees], "maximum": employees, "precision": "range"}
            if employees in _BANDS
            else {"minimum": None, "maximum": employees, "precision": "estimate"}
        )
    families = {
        "workforce": "workforce",
        "directors": "directors",
        "website": "website_url",
        "phone": "phone",
        "email": "published_email",
    }
    available = [family for family, field in families.items() if result.get(field)]
    if not entitlements.is_paid:
        result = {key: value for key, value in result.items() if key not in _PREMIUM_FIELDS}
    result["available_fields"] = available
    result["fields_locked"] = not entitlements.is_paid
    return result
