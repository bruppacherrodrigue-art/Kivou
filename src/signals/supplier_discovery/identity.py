"""Stable Kivou-owned identities for suppliers and acquisition pairs."""

from __future__ import annotations

import hashlib


def _digest(namespace: str, *parts: str) -> str:
    payload = "\x1f".join((namespace, *parts)).encode()
    return hashlib.sha256(payload).hexdigest()


def supplier_ref_for(provider: str, provider_organization_id: str) -> str:
    if not provider.strip() or not provider_organization_id.strip():
        raise ValueError("provider identity fields are required")
    return "sup_" + _digest(
        "supplier-identity-v1",
        provider.strip().lower(),
        provider_organization_id.strip(),
    )[:60]


def acquisition_identity_for(signal_ref: str, supplier_ref: str) -> str:
    if not signal_ref.strip() or not supplier_ref.strip():
        raise ValueError("acquisition identity fields are required")
    return "acquisition-supplier-v1:" + _digest(
        "acquisition-supplier-v1", signal_ref.strip(), supplier_ref.strip()
    )


def domain_conflict_fingerprint(domain: str) -> str:
    return _digest("supplier-domain-conflict-v1", domain.strip().lower())
