"""Append-only assessment and suppression persistence for SPEC-025."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from signals.compliance.contracts import (
    ComplianceAssessmentWrite,
    SuppressionMatch,
    SuppressionMatchState,
    SuppressionReasonCode,
    SuppressionSource,
)
from signals.compliance.suppression import (
    SUPPRESSION_SCOPE,
    SuppressionIdentityKeyring,
    minimum_retention_until,
)
from signals.contact_discovery.store import ContactDiscoveryStore
from signals.persistence.schema import (
    acquisition_compliance_assessment,
    acquisition_contact_suppression,
)

_EVIDENCE_PREFIX = "suppression-evidence:"


class SuppressionIdempotencyConflict(RuntimeError):
    pass


class ComplianceAssessmentIdempotencyConflict(RuntimeError):
    pass


def _semantic(value):
    if isinstance(value, dt.datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
        return aware.astimezone(dt.UTC).isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _semantic(nested) for key, nested in value.items()}
    if isinstance(value, (tuple, list)):
        return [_semantic(nested) for nested in value]
    return value


def suppression_id(values: Mapping[str, object]) -> str:
    encoded = json.dumps(
        _semantic(dict(values)), allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(f"acquisition-suppression-v1\0{encoded}".encode()).hexdigest()


def compliance_assessment_id(policy_evaluation_id: str) -> str:
    return hashlib.sha256(f"compliance-assessment-v1\0{policy_evaluation_id}".encode()).hexdigest()


class SuppressionStore:
    def __init__(self, engine: Engine, keyring: SuppressionIdentityKeyring) -> None:
        self._engine = engine
        self._keyring = keyring

    def record_for_contact(
        self,
        contact_ref: str,
        *,
        source: SuppressionSource,
        reason_code: SuppressionReasonCode,
        evidence_ref: str,
        received_at: dt.datetime,
        effective_at: dt.datetime | None = None,
        key_version: str | None = None,
    ):
        if received_at.tzinfo is None or received_at.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")
        if effective_at is not None and (
            effective_at.tzinfo is None or effective_at.utcoffset() is None
        ):
            raise ValueError("effective_at must be timezone-aware")
        if not isinstance(reason_code, SuppressionReasonCode):
            raise TypeError("suppression reason_code must use the closed vocabulary")
        if not (
            isinstance(evidence_ref, str)
            and evidence_ref.startswith(_EVIDENCE_PREFIX)
            and len(evidence_ref) == len(_EVIDENCE_PREFIX) + 64
            and all(
                character in "0123456789abcdef"
                for character in evidence_ref[len(_EVIDENCE_PREFIX) :]
            )
        ):
            raise ValueError("suppression evidence_ref must be opaque")
        version = key_version or self._keyring.current_key_version
        self._keyring.require_versions_covered((version,))
        with self._engine.begin() as connection:
            contact = ContactDiscoveryStore.get_contact_in_transaction(
                connection, contact_ref, for_update=True
            )
            identities = self._keyring.identities_for_email(contact.business_email)
            self._lock_identities_in_transaction(connection, identities)
            values: dict[str, object] = {
                "identity_hmac": identities[version],
                "identity_key_version": version,
                "scope": SUPPRESSION_SCOPE,
                "source": source.value,
                "reason_code": reason_code.value,
                "evidence_ref": evidence_ref,
                "contact_ref": contact.contact_ref,
                "supplier_ref": contact.supplier_ref,
                "received_at": received_at,
                "effective_at": effective_at or received_at,
                "minimum_retention_until": minimum_retention_until(received_at),
                "supersedes_suppression_id": None,
                "created_at": received_at,
            }
            values["suppression_id"] = suppression_id(values)
            return self._append_in_transaction(connection, values)

    def match_contact(self, contact_ref: str, *, at: dt.datetime | None = None) -> SuppressionMatch:
        with self._engine.connect() as connection:
            return self.match_contact_in_transaction(connection, contact_ref, at=at)

    def match_contact_in_transaction(
        self, connection: Connection, contact_ref: str, *, at: dt.datetime | None = None
    ) -> SuppressionMatch:
        contact = ContactDiscoveryStore.get_contact_in_transaction(connection, contact_ref)
        identities = self._keyring.identities_for_email(contact.business_email)
        self._lock_identities_in_transaction(connection, identities)
        retained = tuple(
            connection.execute(
                sa.select(acquisition_contact_suppression.c.identity_key_version)
                .where(acquisition_contact_suppression.c.scope == SUPPRESSION_SCOPE)
                .distinct()
            ).scalars()
        )
        versions = tuple(sorted(self._keyring.keys))
        if set(retained).difference(self._keyring.keys):
            return SuppressionMatch(
                state=SuppressionMatchState.COVERAGE_UNSAFE,
                key_versions_considered=versions,
                suppression_refs=("suppression-keyring:coverage-unsafe",),
            )
        predicates = [
            sa.and_(
                acquisition_contact_suppression.c.identity_key_version == version,
                acquisition_contact_suppression.c.identity_hmac == identity,
            )
            for version, identity in identities.items()
        ]
        query = sa.select(acquisition_contact_suppression.c.suppression_id).where(
            acquisition_contact_suppression.c.scope == SUPPRESSION_SCOPE,
            sa.or_(*predicates),
        )
        if at is not None:
            if at.tzinfo is None or at.utcoffset() is None:
                raise ValueError("suppression assessment time must be timezone-aware")
            query = query.where(acquisition_contact_suppression.c.effective_at <= at)
        matches = tuple(
            connection.execute(
                query.order_by(acquisition_contact_suppression.c.suppression_id)
            ).scalars()
        )
        return SuppressionMatch(
            state=(SuppressionMatchState.MATCHED if matches else SuppressionMatchState.CLEAR),
            key_versions_considered=versions,
            suppression_refs=tuple(f"acquisition-suppression:{value}" for value in matches),
        )

    @staticmethod
    def _lock_identities_in_transaction(
        connection: Connection, identities: Mapping[str, str]
    ) -> None:
        """Serialize assessments and suppression writes on email-wide identities."""
        if connection.dialect.name == "sqlite":
            # SQLite has no advisory locks. A no-op write takes its database
            # write lock without creating or mutating suppression state.
            connection.execute(
                sa.update(acquisition_contact_suppression)
                .where(sa.false())
                .values(suppression_id=acquisition_contact_suppression.c.suppression_id)
            )
            return
        if connection.dialect.name == "postgresql":
            for identity in sorted(identities.values()):
                lock_key = int(identity[:16], 16)
                if lock_key >= 1 << 63:
                    lock_key -= 1 << 64
                connection.execute(
                    sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": lock_key},
                )
            return
        raise RuntimeError("unsupported suppression lock dialect")

    @staticmethod
    def _append_in_transaction(connection: Connection, values: dict[str, object]):
        if connection.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        elif connection.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            raise RuntimeError("unsupported suppression persistence dialect")
        result = connection.execute(
            insert(acquisition_contact_suppression)
            .values(values)
            .on_conflict_do_nothing(
                index_elements=[acquisition_contact_suppression.c.suppression_id]
            )
        )
        row = (
            connection.execute(
                sa.select(acquisition_contact_suppression).where(
                    acquisition_contact_suppression.c.suppression_id == values["suppression_id"]
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise SuppressionIdempotencyConflict(str(values["suppression_id"]))
        if result.rowcount == 0 and any(
            _semantic(row[key]) != _semantic(value) for key, value in values.items()
        ):
            raise SuppressionIdempotencyConflict(str(values["suppression_id"]))
        return row


class ComplianceAssessmentStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_by_policy(self, policy_evaluation_id: str):
        with self._engine.connect() as connection:
            return self.get_by_policy_in_transaction(connection, policy_evaluation_id)

    @staticmethod
    def get_by_policy_in_transaction(connection: Connection, policy_evaluation_id: str):
        return (
            connection.execute(
                sa.select(acquisition_compliance_assessment).where(
                    acquisition_compliance_assessment.c.policy_evaluation_id == policy_evaluation_id
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def append_in_transaction(connection: Connection, write: ComplianceAssessmentWrite):
        values = write.model_dump(mode="python")
        values.update(
            {
                "jurisdiction": write.jurisdiction.value,
                "state": write.state.value,
                "reason_codes": list(write.reason_codes),
                "evidence_refs": list(write.evidence_refs),
                "disposition": write.disposition.value,
            }
        )
        if connection.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        elif connection.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            raise RuntimeError("unsupported compliance persistence dialect")
        result = connection.execute(
            insert(acquisition_compliance_assessment)
            .values(values)
            .on_conflict_do_nothing(
                index_elements=[acquisition_compliance_assessment.c.policy_evaluation_id]
            )
        )
        row = ComplianceAssessmentStore.get_by_policy_in_transaction(
            connection, write.policy_evaluation_id
        )
        if row is None:
            raise ComplianceAssessmentIdempotencyConflict(write.policy_evaluation_id)
        if result.rowcount == 0 and any(
            _semantic(row[key]) != _semantic(value) for key, value in values.items()
        ):
            raise ComplianceAssessmentIdempotencyConflict(write.policy_evaluation_id)
        return row


__all__ = [
    "ComplianceAssessmentIdempotencyConflict",
    "ComplianceAssessmentStore",
    "SuppressionIdempotencyConflict",
    "SuppressionStore",
    "compliance_assessment_id",
    "suppression_id",
]
