"""Immutable program-version registration using Kivou's conflict-safe inserts."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import asdict

import sqlalchemy as sa
from sqlalchemy.engine import Engine

from signals.acquisition_programs.contracts import AcquisitionProgramConfig
from signals.acquisition_programs.mail_provider import MailProviderEvidence
from signals.acquisition_programs.qualification import CapacityAssessment, FitAssessment
from signals.compliance.milomail_rules import MilomailPolicyDecision
from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import acquisition_program, acquisition_program_eligibility


class AcquisitionProgramStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def register(self, config: AcquisitionProgramConfig, *, at: dt.datetime) -> str:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("program registration time must be timezone-aware")
        snapshot = config.model_dump(mode="json")
        canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        program_id = hashlib.sha256(
            f"acquisition-program-v1\0{config.program_key}\0{fingerprint}".encode()
        ).hexdigest()
        values = {
            "program_id": program_id,
            "program_key": config.program_key,
            "schema_version": config.schema_version,
            "config_fingerprint": fingerprint,
            "config_snapshot": snapshot,
            "mode": config.campaign_mode,
            "enabled": config.enabled,
            "created_at": at,
            "updated_at": at,
        }
        with self._engine.begin() as connection:
            inserted = insert_if_absent(connection, acquisition_program, values)
            if not inserted:
                row = (
                    connection.execute(
                        sa.select(acquisition_program).where(
                            acquisition_program.c.program_id == program_id
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None or row["config_snapshot"] != snapshot:
                    raise ValueError("program version registration conflict")
        return program_id

    @staticmethod
    def record_eligibility_in_transaction(
        connection: sa.Connection,
        *,
        program_id: str,
        opportunity_id: str,
        supplier_ref: str | None,
        contact_ref: str | None,
        recipient_identity_hmac: str | None,
        recipient_identity_key_version: str | None,
        provider: MailProviderEvidence,
        capacity: CapacityAssessment,
        fit: FitAssessment,
        decision: MilomailPolicyDecision,
        wedge_key: str | None,
        collection_source_url: str | None,
        collected_at: dt.datetime | None,
        company_active_source_url: str | None,
        company_active_source_type: str | None,
        company_active_observed_at: dt.datetime | None,
        company_active_evidence_id: str | None,
    ) -> str:
        """Append a program assessment; same timestamp with changed facts conflicts."""
        seed = f"program-eligibility-v1\0{program_id}\0{opportunity_id}\0{decision.decided_at.isoformat()}"
        eligibility_id = hashlib.sha256(seed.encode()).hexdigest()
        provider_evidence = {
            **asdict(provider),
            "provider": provider.provider.value,
            "confidence": provider.confidence.value,
            "observed_at": provider.observed_at.isoformat(),
            "expires_at": provider.expires_at.isoformat(),
        }
        values = {
            "eligibility_id": eligibility_id,
            "program_id": program_id,
            "acquisition_opportunity_id": opportunity_id,
            "supplier_ref": supplier_ref,
            "contact_ref": contact_ref,
            "mail_provider": provider.provider.value,
            "wedge_key": wedge_key,
            "provider_confidence": provider.confidence.value,
            "provider_evidence": provider_evidence,
            "recipient_capacity": capacity.capacity.value,
            "professional_evidence": {
                **capacity.model_dump(mode="json"),
                "recipient_identity_hmac": recipient_identity_hmac,
                "recipient_identity_key_version": recipient_identity_key_version,
                "collection_source_url": collection_source_url,
                "collected_at": collected_at.isoformat() if collected_at else None,
                "company_active_source_url": company_active_source_url,
                "company_active_source_type": company_active_source_type,
                "company_active_observed_at": (
                    company_active_observed_at.isoformat() if company_active_observed_at else None
                ),
                "company_active_evidence_id": company_active_evidence_id,
            },
            "fit_score": fit.total,
            "fit_breakdown": fit.breakdown,
            "mail_pain_score": fit.mail_pain_score,
            "score_version": fit.score_version,
            "decision": decision.decision,
            "reason_codes": list(decision.reason_codes),
            "policy_country": decision.policy_country,
            "policy_version": decision.policy_version,
            "evidence_ids": list(decision.evidence_ids),
            "evaluated_at": decision.decided_at,
            "evidence_expires_at": min(
                (
                    expiry
                    for expiry in (provider.expires_at, capacity.evidence_expires_at)
                    if expiry is not None
                ),
                default=None,
            ),
        }
        inserted = insert_if_absent(
            connection,
            acquisition_program_eligibility,
            values,
            index_elements=[acquisition_program_eligibility.c.eligibility_id],
        )
        if not inserted:
            row = (
                connection.execute(
                    sa.select(acquisition_program_eligibility).where(
                        acquisition_program_eligibility.c.eligibility_id == eligibility_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None or any(
                _normalized(row[key]) != _normalized(value) for key, value in values.items()
            ):
                raise ValueError("program eligibility idempotency conflict")
        return eligibility_id


def _normalized(value):
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=value.tzinfo or dt.UTC).astimezone(dt.UTC).isoformat()
    if isinstance(value, (list, tuple)):
        return [_normalized(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalized(item) for key, item in value.items()}
    return value


__all__ = ["AcquisitionProgramStore"]
