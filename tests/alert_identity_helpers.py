"""Explicit verified identity fixtures for ALERT tests; no production gate bypass."""

import sqlalchemy as sa
from engagement_helpers import NOW, account_of, signed_up

from signals.accounts.schema import auth_user


def verify_recipient(engine, client, *, email: str | None = None) -> None:
    from signals.accounts.email_verification import email_identity as table

    account_id = account_of(client)
    with engine.begin() as connection:
        user = connection.execute(
            sa.select(auth_user).where(auth_user.c.account_id == account_id)
        ).one()
        address = email if email is not None else user.email_normalized
        if email is not None:
            connection.execute(
                sa.update(auth_user)
                .where(auth_user.c.user_id == user.user_id)
                .values(email_normalized=address, updated_at=NOW)
            )
        connection.execute(sa.delete(table).where(table.c.user_id == user.user_id))
        connection.execute(
            sa.insert(table).values(
                user_id=user.user_id,
                verified_email=address,
                verified_at=NOW,
                pending_email=None,
                token_hash=None,
                expires_at=None,
                requested_at=NOW,
            )
        )


def verified_signed_up(app, engine, email="alice@negoce-romand.ch", locale="fr"):
    client = signed_up(app, email, locale=locale)
    verify_recipient(engine, client)
    return client
