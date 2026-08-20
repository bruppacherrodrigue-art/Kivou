"""Frozen callable-free configuration for decision-policy-v1."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from signals.decision_engine.contracts import DecisionPolicyConfig


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")


def semantic_fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def decision_policy_config_fingerprint(config: DecisionPolicyConfig) -> str:
    values = config.model_dump(mode="json", exclude={"config_fingerprint"})
    return semantic_fingerprint(values)


_POLICY_VALUES = {
    "max_send_age_days": 60,
    "future_date_tolerance_days": 0,
    "award_publication_tolerance_days": 1,
    "domain_conflict_behavior": "REVIEW",
    "supplier_snapshot_mismatch_behavior": "REVIEW",
    "limited_research_behavior": "CONTINUE",
    "size_band_behavior": "CONTEXT_ONLY",
    "contact_role_tier_behavior": "CONTEXT_ONLY",
    "hold_enabled": False,
    "enrich_enabled": False,
}
_UNFINGERPRINTED = DecisionPolicyConfig(
    **_POLICY_VALUES,
    config_fingerprint="0" * 64,
)
DECISION_POLICY_V1 = _UNFINGERPRINTED.model_copy(
    update={"config_fingerprint": decision_policy_config_fingerprint(_UNFINGERPRINTED)}
)
