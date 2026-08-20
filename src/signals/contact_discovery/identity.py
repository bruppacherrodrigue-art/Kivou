"""Stable Kivou contact identity independent of mutable email metadata."""

import hashlib
import json


def contact_ref_for(provider: str, provider_person_id: str, supplier_ref: str) -> str:
    values = (provider.strip(), provider_person_id.strip(), supplier_ref.strip())
    if any(not value for value in values):
        raise ValueError("contact identity fields must be non-empty")
    payload = {
        "identity_version": "contact-identity-v1",
        "provider": values[0],
        "provider_person_id": values[1],
        "supplier_ref": values[2],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
