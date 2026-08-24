"""Immutable, conflict-safe personalization artifact persistence."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Mapping
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from signals.persistence.conflicts import insert_if_absent
from signals.persistence.schema import acquisition_personalization_artifact
from signals.personalization.contracts import PersonalizationArtifactWrite


class PersonalizationArtifactIdempotencyConflict(RuntimeError):
    pass


def personalization_artifact_id(policy_evaluation_id: str) -> str:
    return hashlib.sha256(
        f"personalization-artifact-v1\0{policy_evaluation_id}".encode()
    ).hexdigest()


def _values(write: PersonalizationArtifactWrite) -> dict[str, object]:
    return {
        **write.model_dump(mode="python"),
        "claim_map": [entry.model_dump(mode="json") for entry in write.claim_map],
        "disposition": write.disposition.value,
        "created_at": write.created_at,
    }


def _semantic(value):
    """Normalize SQL/Pydantic representation differences before idempotency checks."""
    if isinstance(value, dt.datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)
        return aware.astimezone(dt.UTC).isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _semantic(nested) for key, nested in value.items()}
    if isinstance(value, (tuple, list)):
        return [_semantic(nested) for nested in value]
    return value


class PersonalizationStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_by_policy(self, policy_evaluation_id: str):
        with self._engine.connect() as connection:
            return self.get_by_policy_in_transaction(connection, policy_evaluation_id)

    @staticmethod
    def get_by_policy_in_transaction(connection: Connection, policy_evaluation_id: str):
        return (
            connection.execute(
                sa.select(acquisition_personalization_artifact).where(
                    acquisition_personalization_artifact.c.policy_evaluation_id
                    == policy_evaluation_id
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def append_in_transaction(connection: Connection, write: PersonalizationArtifactWrite):
        values = _values(write)
        if connection.dialect.name == "sqlite" or connection.dialect.name == "postgresql":
            pass
        else:
            raise RuntimeError("unsupported personalization persistence dialect")
        inserted = insert_if_absent(
            connection,
            acquisition_personalization_artifact,
            values,
        )
        row = PersonalizationStore.get_by_policy_in_transaction(
            connection, write.policy_evaluation_id
        )
        if row is None:
            raise PersonalizationArtifactIdempotencyConflict(write.policy_evaluation_id)
        if inserted:
            return row
        if any(_semantic(row[key]) != _semantic(value) for key, value in values.items()):
            raise PersonalizationArtifactIdempotencyConflict(write.policy_evaluation_id)
        return row
