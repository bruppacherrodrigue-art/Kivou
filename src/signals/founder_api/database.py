"""Read-only production database boundary for the Founder Console."""

from __future__ import annotations

import os

import sqlalchemy as sa

FOUNDER_DATABASE_URL_ENV = "KIVOU_FOUNDER_DATABASE_URL"
FOUNDER_STATEMENT_TIMEOUT_MS = 10_000


def resolve_founder_database_url(url: str | None = None) -> str:
    """Resolve only the explicitly configured Founder database."""

    if url:
        return url
    configured = os.environ.get(FOUNDER_DATABASE_URL_ENV)
    if not configured:
        raise RuntimeError(
            f"{FOUNDER_DATABASE_URL_ENV} n'est pas défini : le Founder Console "
            "ne devine jamais quelle base lire"
        )
    return configured


def create_founder_database_engine(url: str | None = None) -> sa.Engine:
    """Create a PostgreSQL engine whose sessions are forced read-only.

    The deployment must still use a dedicated role with SELECT-only grants.
    Session read-only is an additional safety boundary, not a replacement for
    PostgreSQL privileges.
    """

    resolved = resolve_founder_database_url(url)
    parsed = sa.engine.make_url(resolved)
    if parsed.get_backend_name() != "postgresql":
        raise RuntimeError(
            "la Founder API de production exige PostgreSQL ; "
            "aucune base locale ou SQLite n'est acceptée"
        )
    engine = sa.create_engine(
        resolved,
        future=True,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
        pool_timeout=5,
        connect_args={
            "connect_timeout": 5,
            "options": (
                "-c default_transaction_read_only=on "
                "-c application_name=kivou-founder-control "
                f"-c statement_timeout={FOUNDER_STATEMENT_TIMEOUT_MS}"
            ),
        },
    )

    @sa.event.listens_for(engine, "engine_connect")
    def _verify_read_only(connection: sa.Connection) -> None:
        state = connection.exec_driver_sql("SHOW transaction_read_only").scalar_one()
        if state != "on":
            raise RuntimeError(
                "la connexion Founder PostgreSQL n'est pas en lecture seule"
            )

    return engine


__all__ = [
    "FOUNDER_DATABASE_URL_ENV",
    "FOUNDER_STATEMENT_TIMEOUT_MS",
    "create_founder_database_engine",
    "resolve_founder_database_url",
]
