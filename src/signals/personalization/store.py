"""Immutable, conflict-safe personalization artifact persistence."""

from __future__ import annotations

import hashlib

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

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
        if connection.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        elif connection.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            raise RuntimeError("unsupported personalization persistence dialect")
        result = connection.execute(
            insert(acquisition_personalization_artifact)
            .values(values)
            .on_conflict_do_nothing()
        )
        row = PersonalizationStore.get_by_policy_in_transaction(
            connection, write.policy_evaluation_id
        )
        if row is None:
            raise PersonalizationArtifactIdempotencyConflict(write.policy_evaluation_id)
        if result.rowcount == 1:
            return row
        if any(row[key] != value for key, value in values.items()):
            raise PersonalizationArtifactIdempotencyConflict(write.policy_evaluation_id)
        return row
